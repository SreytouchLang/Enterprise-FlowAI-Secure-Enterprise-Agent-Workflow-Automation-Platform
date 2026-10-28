import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app import storage, worker
from app.auth import principal_for_user
from app.core.config import get_settings
from app.models import Document, DocumentChunk, DocumentPermission, Job, Membership, User, utcnow
from app.worker import ingest


@pytest.mark.asyncio
async def test_worker_extracts_and_reindex_does_not_duplicate_chunks(client, db):
    data = b"Vacation policy. Every synthetic employee receives twenty days annually."
    key = "hr/test/1"
    storage.put(key, data, "text/plain")
    doc = Document(id="worker-doc", department_id="hr", owner_id="hr", name="policy.txt", mime_type="text/plain", size=len(data), content_hash=hashlib.sha256(data).hexdigest(), storage_key=key, visibility="private", status="queued", version=1)
    job = Job(id="worker-job", department_id="hr", user_id="hr", kind="ingest", resource_id=doc.id, idempotency_key="worker-test", status="running")
    db.add_all([doc, job])
    db.commit()
    p = principal_for_user(db, "hr")
    await ingest(db, job, p)
    assert doc.status == "ready" and doc.embedding_status == "not_configured"
    count = db.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    await ingest(db, job, p)
    assert count == db.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    assert count > 0 and "twenty days" in doc.extracted_text


@pytest.mark.asyncio
async def test_scan_requirement_fails_closed(client, db, monkeypatch):
    from app.documents import scan
    monkeypatch.setenv("REQUIRE_VIRUS_SCAN", "true")
    monkeypatch.setenv("CLAMAV_HOST", "")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="scanner_unavailable"):
        scan(b"A clean-looking file still needs the required antivirus scan")
    get_settings.cache_clear()


def test_active_ingestion_cannot_be_requeued_or_replaced(client):
    headers = {"x-test-user": "hr"}
    uploaded = client.post("/api/v1/documents/upload", headers=headers,
                           data={"department_id": "hr"}, files={"file": ("policy.txt", b"Current policy version", "text/plain")})
    assert uploaded.status_code == 202
    document_id = uploaded.json()["id"]
    assert client.post(f"/api/v1/documents/{document_id}/reindex", headers=headers).status_code == 409
    replaced = client.post("/api/v1/documents/upload", headers=headers,
                           data={"department_id": "hr", "document_id": document_id},
                           files={"file": ("policy.txt", b"Different policy version", "text/plain")})
    assert replaced.status_code == 409
    assert client.get(f"/api/v1/documents/{document_id}/status", headers=headers).json()["version"] == 1


@pytest.mark.parametrize("visibility", ["department", "private"])
def test_admin_reindex_executes_after_original_uploader_deactivated(client, db, monkeypatch, visibility):
    uploaded = client.post(
        "/api/v1/documents/upload", headers={"x-test-user": "hr"},
        data={"department_id": "hr", "visibility": visibility},
        files={"file": ("policy.txt", b"Synthetic policy retained after employee departure.", "text/plain")},
    )
    assert uploaded.status_code == 202
    document = db.get(Document, uploaded.json()["id"])
    job = db.scalar(select(Job).where(Job.resource_id == document.id))
    document.status, job.status = "failed", "dead_letter"
    job.attempts, job.error_code = 3, "processing_failed"
    job.available_at = utcnow() + timedelta(minutes=10)
    db.get(Membership, ("hrmanager", "hr")).role = "department_admin"
    if visibility == "private":
        db.add(DocumentPermission(document_id=document.id, user_id="hrmanager", owner_id="hr"))
    db.get(User, "hr").active = False
    db.commit()

    response = client.post(f"/api/v1/documents/{document.id}/reindex",
                           headers={"x-test-user": "hrmanager"})
    assert response.status_code == 202, response.text
    assert job.user_id == "hrmanager"
    monkeypatch.setattr(worker, "session_factory", lambda: lambda: db)
    worker.process_job.run(job.id)

    document = db.get(Document, document.id)
    job = db.get(Job, job.id)
    assert job.status == "completed" and job.attempts == 1
    assert document.status == "ready"
    assert "employee departure" in document.extracted_text
    assert document.owner_id == "hr" and document.visibility == visibility
    assert db.scalar(select(func.count()).select_from(DocumentChunk)
                     .where(DocumentChunk.document_id == document.id)) > 0
    if visibility == "private":
        assert db.get(DocumentPermission, (document.id, "hrmanager")) is not None


def test_admin_reindex_cannot_access_unshared_private_document(client, db):
    uploaded = client.post(
        "/api/v1/documents/upload", headers={"x-test-user": "hr"},
        data={"department_id": "hr", "visibility": "private"},
        files={"file": ("private.txt", b"Private source remains private after owner departure.", "text/plain")},
    )
    assert uploaded.status_code == 202
    document = db.get(Document, uploaded.json()["id"])
    job = db.scalar(select(Job).where(Job.resource_id == document.id))
    document.status, job.status = "ready", "completed"
    db.get(Membership, ("hrmanager", "hr")).role = "department_admin"
    db.get(User, "hr").active = False
    db.commit()

    response = client.post(f"/api/v1/documents/{document.id}/reindex",
                           headers={"x-test-user": "hrmanager"})
    assert response.status_code == 404
    assert document.status == "ready" and document.owner_id == "hr"
    assert job.status == "completed" and job.user_id == "hr"


@pytest.mark.parametrize("job_status", ["queued", "running", "retrying"])
def test_reindex_does_not_replace_an_active_job_when_document_status_is_failed(client, db, job_status):
    headers = {"x-test-user": "hr"}
    uploaded = client.post(
        "/api/v1/documents/upload", headers=headers, data={"department_id": "hr"},
        files={"file": ("policy.txt", b"Synthetic policy awaiting automatic ingestion recovery.", "text/plain")},
    )
    assert uploaded.status_code == 202
    document = db.get(Document, uploaded.json()["id"])
    job = db.scalar(select(Job).where(Job.resource_id == document.id))
    document.status, job.status, job.attempts = "failed", job_status, 1
    db.commit()

    response = client.post(f"/api/v1/documents/{document.id}/reindex", headers=headers)
    assert response.status_code == 409
    assert job.status == job_status and job.attempts == 1
