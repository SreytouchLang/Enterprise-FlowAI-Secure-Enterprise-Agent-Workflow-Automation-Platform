from decimal import Decimal

import pytest
from sqlalchemy import select, update

from app.models import AgentExecution, Document, DocumentChunk, Membership, Message, User
from app.providers import ProviderResult


class TestOnlyProvider:
    __test__ = False
    def __init__(self, text):
        self.text = text

    async def stream(self, messages, model=None, max_tokens=2048):
        yield {"type": "delta", "content": self.text}
        yield {"type": "usage", "result": ProviderResult(self.text, "test_only", model, 10, 10, Decimal("0.0001"))}


def setup_source(db):
    doc = Document(id="policy", department_id="hr", owner_id="hr", name="Vacation policy", mime_type="text/plain", size=30, content_hash="b"*64, storage_key="unused", visibility="department", status="ready", version=1, extracted_text="Vacation allowance is twenty days annually.")
    db.add(doc)
    db.flush()
    db.add(DocumentChunk(id="policy-chunk", document_id=doc.id, department_id="hr", content=doc.extracted_text, location="paragraph 1", ordinal=0, version=1))
    db.commit()


def test_real_graph_stream_persists_checkpoint_and_citations(client, db, monkeypatch):
    setup_source(db)
    monkeypatch.setattr("app.agents.get_provider", lambda name: TestOnlyProvider("Twenty days of vacation per year [1]."))
    c = client.post("/api/v1/conversations", headers={"x-test-user": "hr"}, json={"agent_id": "hr-agent"}).json()
    response = client.post(f"/api/v1/conversations/{c['id']}/messages", headers={"x-test-user": "hr"}, json={"content": "What is vacation allowance?"})
    assert "event: done" in response.text, response.text
    assert '"chunk_id": "policy-chunk"' in response.text
    execution = db.scalar(select(AgentExecution))
    assert execution.status == "completed" and len(execution.trace) == 2
    history = client.get(f"/api/v1/conversations/{c['id']}", headers={"x-test-user": "hr"}).json()
    assert history["messages"][-1]["citations"][0]["document_id"] == "policy"
    # Previously generated answers must not survive a loss of source permissions.
    doc = db.get(Document, "policy")
    doc.owner_id, doc.visibility = "hrmanager", "private"
    db.commit()
    history = client.get(f"/api/v1/conversations/{c['id']}", headers={"x-test-user": "hr"}).json()
    assert "Twenty days" not in history["messages"][-1]["content"]


def test_invalid_citation_fails_without_saving_success(client, db, monkeypatch):
    setup_source(db)
    monkeypatch.setattr("app.agents.get_provider", lambda name: TestOnlyProvider("Twenty days [999]."))
    c = client.post("/api/v1/conversations", headers={"x-test-user": "hr"}, json={"agent_id": "hr-agent"}).json()
    response = client.post(f"/api/v1/conversations/{c['id']}/messages", headers={"x-test-user": "hr"}, json={"content": "vacation"})
    assert "invalid_citation" in response.text and "event: done" not in response.text
    assert db.scalar(select(AgentExecution)).status == "failed"


@pytest.mark.parametrize("change", ["source_acl", "account_deactivated", "role_revoked"])
def test_stream_rechecks_access_before_emitting_provider_content(client, db, monkeypatch, change):
    setup_source(db)

    class RevokingProvider(TestOnlyProvider):
        async def stream(self, messages, model=None, max_tokens=2048):
            if change == "source_acl":
                mutation = update(Document).where(Document.id == "policy").values(
                    owner_id="hrmanager", visibility="private")
            elif change == "account_deactivated":
                mutation = update(User).where(User.id == "hr").values(active=False)
            else:
                mutation = update(Membership).where(Membership.user_id == "hr").values(role="auditor")
            # Bypass session synchronization to reproduce another transaction
            # changing records already cached by this request's identity map.
            db.execute(mutation.execution_options(synchronize_session=False))
            db.commit()
            async for chunk in super().stream(messages, model, max_tokens):
                yield chunk

    monkeypatch.setattr("app.agents.get_provider", lambda name: RevokingProvider("Secret answer after revocation [1]."))
    conversation = client.post("/api/v1/conversations", headers={"x-test-user": "hr"},
                               json={"agent_id": "hr-agent"}).json()
    response = client.post(f"/api/v1/conversations/{conversation['id']}/messages",
                           headers={"x-test-user": "hr"}, json={"content": "vacation"})
    assert "access_revoked" in response.text
    assert "Secret answer" not in response.text
    assert "event: done" not in response.text
    assert db.scalar(select(Message).where(Message.role == "assistant")) is None
    assert db.scalar(select(AgentExecution)).status == "failed"


def test_source_revoked_after_retrieval_never_reaches_the_provider(client, db, monkeypatch):
    from app import agents

    setup_source(db)
    original_search = agents.search

    async def revoke_after_search(*args, **kwargs):
        results = await original_search(*args, **kwargs)
        db.execute(update(Document).where(Document.id == "policy").values(
            owner_id="hrmanager", visibility="private"))
        db.commit()
        return results

    class UnexpectedProvider:
        async def stream(self, *args, **kwargs):
            pytest.fail("Revoked evidence must never be sent to an external provider")
            yield  # Keep the provider interface an async iterator.

    monkeypatch.setattr(agents, "search", revoke_after_search)
    monkeypatch.setattr(agents, "get_provider", lambda name: UnexpectedProvider())
    conversation = client.post("/api/v1/conversations", headers={"x-test-user": "hr"},
                               json={"agent_id": "hr-agent"}).json()
    response = client.post(f"/api/v1/conversations/{conversation['id']}/messages",
                           headers={"x-test-user": "hr"}, json={"content": "vacation"})
    assert "access_revoked" in response.text
    assert "event: done" not in response.text


def test_retrieval_rechecks_cached_candidates_before_returning_content(client, db, monkeypatch):
    from app import rag

    setup_source(db)
    original_score = rag.lexical_score
    revoked = False

    def score_and_revoke(query, content):
        nonlocal revoked
        if not revoked:
            db.execute(update(Document).where(Document.id == "policy").values(
                owner_id="hrmanager", visibility="private").execution_options(synchronize_session=False))
            db.commit()
            revoked = True
        return original_score(query, content)

    monkeypatch.setattr(rag, "lexical_score", score_and_revoke)
    response = client.post("/api/v1/search", headers={"x-test-user": "hr"},
                           json={"query": "vacation", "department_id": "hr"})
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert "twenty days" not in response.text


def test_search_reports_lexical_when_no_vector_search_was_executed(client, db, monkeypatch):
    from app.core.config import get_settings

    setup_source(db)
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-not-a-real-key")
    get_settings.cache_clear()
    response = client.post("/api/v1/search", headers={"x-test-user": "hr"},
                           json={"query": "vacation", "department_id": "hr"})
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert response.json()["mode"] == "lexical"
