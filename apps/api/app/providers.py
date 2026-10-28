"""Provider-specific structured and streaming APIs, bounded calls and persisted spend reservations."""
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from pydantic import BaseModel
from sqlalchemy import func, select

from app.auth import authorize_department
from app.core.config import get_settings
from app.models import ModelUsage, User, utcnow


class ProviderError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


@dataclass
class ProviderResult:
    content: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    data: Any = None


class LLMProvider(Protocol):
    async def generate(self, messages, model=None, max_tokens=2048) -> ProviderResult: ...
    async def generate_structured(self, messages, schema, model=None, max_tokens=2048) -> ProviderResult: ...
    def stream(self, messages, model=None, max_tokens=2048): ...


def price(input_tokens: int, output_tokens: int) -> Decimal:
    s = get_settings()
    return (Decimal(input_tokens) * s.input_cost_per_million + Decimal(output_tokens) * s.output_cost_per_million) / Decimal(1000000)


class OpenAIProvider:
    def __init__(self):
        s = get_settings()
        if not s.openai_api_key:
            raise ProviderError("provider_not_configured", "OpenAI is not configured. Add a backend API key.")
        self.client = AsyncOpenAI(api_key=s.openai_api_key, timeout=s.model_timeout_seconds, max_retries=2)

    async def generate(self, messages, model=None, max_tokens=2048):
        try:
            response = await self.client.responses.create(model=model or get_settings().openai_model, input=messages, max_output_tokens=max_tokens, store=False)
            if response.status != "completed" or not response.output_text or response.usage is None:
                raise ValueError("No completed output")
            return ProviderResult(response.output_text, "openai", response.model, response.usage.input_tokens, response.usage.output_tokens, price(response.usage.input_tokens, response.usage.output_tokens))
        except Exception as exc:
            raise ProviderError("provider_error", "OpenAI could not complete this request. No successful result was saved.") from exc

    async def generate_structured(self, messages, schema, model=None, max_tokens=2048):
        try:
            response = await self.client.responses.parse(model=model or get_settings().openai_model, input=messages, text_format=schema, max_output_tokens=max_tokens, store=False)
            if response.status != "completed" or response.output_parsed is None or response.usage is None:
                raise ValueError("Missing validated output")
            parsed = schema.model_validate(response.output_parsed)
            return ProviderResult(parsed.model_dump_json(), "openai", response.model, response.usage.input_tokens, response.usage.output_tokens, price(response.usage.input_tokens, response.usage.output_tokens), parsed)
        except Exception as exc:
            raise ProviderError("structured_output_failed", "OpenAI returned no valid structured result.") from exc

    async def stream(self, messages, model=None, max_tokens=2048):
        completed = False
        try:
            stream = await self.client.responses.create(model=model or get_settings().openai_model, input=messages, max_output_tokens=max_tokens, stream=True, store=False)
            async with stream:
                async for event in stream:
                    if event.type == "response.output_text.delta":
                        yield {"type": "delta", "content": event.delta}
                    elif event.type == "response.completed":
                        r = event.response
                        if r.usage is None:
                            raise ValueError("Missing stream usage")
                        completed = True
                        yield {"type": "usage", "result": ProviderResult(r.output_text, "openai", r.model, r.usage.input_tokens, r.usage.output_tokens, price(r.usage.input_tokens, r.usage.output_tokens))}
            if not completed:
                raise ValueError("Incomplete stream")
        except Exception as exc:
            raise ProviderError("provider_error", "OpenAI stream ended without a completed response.") from exc


class AnthropicProvider:
    def __init__(self):
        s = get_settings()
        if not s.anthropic_api_key:
            raise ProviderError("provider_not_configured", "Anthropic is not configured. Add a backend API key.")
        self.client = AsyncAnthropic(api_key=s.anthropic_api_key, timeout=s.model_timeout_seconds, max_retries=2)

    def params(self, messages, model, max_tokens):
        return {"model": model or get_settings().anthropic_model, "max_tokens": max_tokens, "system": "\n".join(m["content"] for m in messages if m["role"] == "system"), "messages": [m for m in messages if m["role"] in {"user", "assistant"}]}

    async def generate(self, messages, model=None, max_tokens=2048):
        try:
            r = await self.client.messages.create(**self.params(messages, model, max_tokens))
            if r.stop_reason != "end_turn":
                raise ValueError("Incomplete response")
            content = "".join(block.text for block in r.content if block.type == "text")
            return ProviderResult(content, "anthropic", r.model, r.usage.input_tokens, r.usage.output_tokens, price(r.usage.input_tokens, r.usage.output_tokens))
        except Exception as exc:
            raise ProviderError("provider_error", "Anthropic could not complete this request.") from exc

    async def generate_structured(self, messages, schema, model=None, max_tokens=2048):
        try:
            r = await self.client.messages.create(**self.params(messages, model, max_tokens), tools=[{"name": "return_validated_record", "description": "Return the extracted structured record only; this tool performs no action.", "input_schema": schema.model_json_schema()}], tool_choice={"type": "tool", "name": "return_validated_record"})
            blocks = [b for b in r.content if b.type == "tool_use" and b.name == "return_validated_record"]
            if len(blocks) != 1 or r.stop_reason != "tool_use":
                raise ValueError("Invalid structured output")
            parsed = schema.model_validate(blocks[0].input)
            return ProviderResult(parsed.model_dump_json(), "anthropic", r.model, r.usage.input_tokens, r.usage.output_tokens, price(r.usage.input_tokens, r.usage.output_tokens), parsed)
        except Exception as exc:
            raise ProviderError("structured_output_failed", "Anthropic returned no valid structured result.") from exc

    async def stream(self, messages, model=None, max_tokens=2048):
        try:
            async with self.client.messages.stream(**self.params(messages, model, max_tokens)) as stream:
                async for delta in stream.text_stream:
                    yield {"type": "delta", "content": delta}
                r = await stream.get_final_message()
                if r.stop_reason != "end_turn":
                    raise ValueError("Incomplete stream")
                content = "".join(b.text for b in r.content if b.type == "text")
                yield {"type": "usage", "result": ProviderResult(content, "anthropic", r.model, r.usage.input_tokens, r.usage.output_tokens, price(r.usage.input_tokens, r.usage.output_tokens))}
        except Exception as exc:
            raise ProviderError("provider_error", "Anthropic stream ended without a completed response.") from exc


def get_provider(name=None) -> LLMProvider:
    name = name or get_settings().default_llm_provider
    if name == "openai":
        return OpenAIProvider()
    if name == "anthropic":
        return AnthropicProvider()
    raise ProviderError("unsupported_provider", "Only configured OpenAI and Anthropic providers are available.")


def reserve_usage(db, p, department_id, messages, provider, model, max_tokens=2048, budget_usd=None, execution_id=None):
    authorize_department(p, department_id)
    if not 1 <= max_tokens <= 8192:
        raise ProviderError("token_limit", "Output token budget must be between 1 and 8192")
    size = sum(len(m["content"].encode("utf-8")) for m in messages)
    if size > 64000:
        raise ProviderError("context_limit", "Request exceeds the bounded context size")
    # Bytes form a conservative upper bound on text tokens; no float currency arithmetic.
    reserved = price(size + 1024, max_tokens)
    limit = min(Decimal(str(budget_usd or get_settings().execution_budget_usd)), get_settings().execution_budget_usd)
    if reserved > limit:
        raise ProviderError("spending_limit", "Request exceeds the configured execution spending limit")
    db.scalar(select(User).where(User.id == p.id).with_for_update())
    today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    spent = db.scalar(select(func.coalesce(func.sum(ModelUsage.cost_usd + ModelUsage.reserved_usd), 0)).where(ModelUsage.user_id == p.id, ModelUsage.created_at >= today))
    if Decimal(str(spent)) + reserved > get_settings().daily_budget_usd:
        raise ProviderError("spending_limit", "Daily model spending limit reached")
    usage = ModelUsage(execution_id=execution_id, department_id=department_id, user_id=p.id, provider=provider, model=model, reserved_usd=reserved, status="reserved")
    db.add(usage)
    db.commit()
    return usage


def finalize_usage(db, usage, result: ProviderResult | None):
    if result:
        usage.input_tokens, usage.output_tokens = result.input_tokens, result.output_tokens
        usage.cost_usd, usage.reserved_usd, usage.status = result.cost_usd, Decimal(0), "completed"
    else:
        # Failed calls may be billable. Keep their conservative reservation until reconciliation.
        usage.status = "failed_reserved"
    db.commit()


async def structured_call(db, p, department_id, messages, schema: type[BaseModel], provider=None, model=None, max_tokens=2048, budget_usd=None):
    name = provider or get_settings().default_llm_provider
    adapter = get_provider(name)
    model = model or (get_settings().openai_model if name == "openai" else get_settings().anthropic_model)
    budget_messages = messages + [{"role": "system", "content": json.dumps(schema.model_json_schema())}]
    usage = reserve_usage(db, p, department_id, budget_messages, name, model, max_tokens, budget_usd)
    try:
        result = await adapter.generate_structured(messages, schema, model=model, max_tokens=max_tokens)
    except Exception:
        finalize_usage(db, usage, None)
        raise
    finalize_usage(db, usage, result)
    return result
