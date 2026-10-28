
import httpx
import pytest
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.core.config import get_settings
from app.providers import AnthropicProvider, OpenAIProvider, ProviderError


class Record(BaseModel):
    label: str


@pytest.mark.asyncio
async def test_openai_real_sdk_structured_protocol(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    get_settings.cache_clear()
    seen = []

    def handler(request):
        import json
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "resp_test", "object": "response", "created_at": 1, "status": "completed", "model": "test-model", "output": [{"type": "message", "id": "msg_test", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": '{"label":"validated"}', "annotations": []}]}], "parallel_tool_calls": False, "tool_choice": "auto", "tools": [], "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}, "error": None, "incomplete_details": None, "instructions": None, "metadata": {}, "temperature": 1, "top_p": 1})
    provider = OpenAIProvider()
    provider.client = AsyncOpenAI(api_key="test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), max_retries=0)
    result = await provider.generate_structured([{"role": "user", "content": "classify"}], Record, model="test-model")
    assert result.data.label == "validated" and result.input_tokens == 10
    assert seen[0]["text"]["format"]["type"] == "json_schema" and seen[0]["store"] is False
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_anthropic_tool_schema_validates_with_real_sdk(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    get_settings.cache_clear()
    seen = []

    def handler(request):
        import json
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "msg_test", "type": "message", "role": "assistant", "model": "test-model", "content": [{"type": "tool_use", "id": "tool_test", "name": "return_validated_record", "input": {"label": "validated"}}], "stop_reason": "tool_use", "stop_sequence": None, "usage": {"input_tokens": 11, "output_tokens": 5}})
    provider = AnthropicProvider()
    provider.client = AsyncAnthropic(api_key="test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), max_retries=0)
    result = await provider.generate_structured([{"role": "system", "content": "trusted"}, {"role": "user", "content": "classify"}], Record, model="test-model")
    assert result.data.label == "validated" and result.output_tokens == 5
    assert seen[0]["system"] == "trusted"
    assert seen[0]["tool_choice"]["name"] == "return_validated_record"
    assert all(m["role"] != "system" for m in seen[0]["messages"])
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_provider_errors_are_redacted(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-never-return")
    get_settings.cache_clear()
    provider = OpenAIProvider()
    provider.client = AsyncOpenAI(api_key="test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"error": {"message": "secret-never-return"}}))), max_retries=0)
    with pytest.raises(ProviderError) as exc:
        await provider.generate([{"role": "user", "content": "Sensitive prompt"}])
    assert "secret-never-return" not in str(exc.value)
    get_settings.cache_clear()
