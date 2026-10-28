"""Durable database jobs + Celery transport, redelivery and a recovery sweep."""
import asyncio
from datetime import timedelta
from uuid import uuid4

from celery import Celery
from fastapi import HTTPException
from sqlalchemy import delete, select, update

from app import storage
from app.audit import record
from app.auth import principal_for_user
from app.core.config import get_settings
from app.db import session_factory
from app.documents import chunks, extract, get_document, scan, verify_file
from app.models import Document, DocumentChunk, EmbeddingRecord, Job, Notification, utcnow
from app.providers import ProviderError
from app.rag import embeddings

s = get_settings()
celery_app = Celery("enterpriseflow", broker=s.redis_url, backend=s.redis_url, include=["app.evaluations"])
celery_app.conf.update(task_acks_late=True, task_reject_on_worker_lost=True, worker_prefetch_multiplier=1, broker_connection_retry_on_startup=True, task_serializer="json", accept_content=["json"], result_serializer="json", task_track_started=True, task_soft_time_limit=540, task_time_limit=600, beat_schedule={"recover-queued-jobs": {"task": "app.worker.recover_jobs", "schedule": 60.0}, "daily-fixture-evaluation": {"task": "app.evaluations.run_scheduled_evaluation", "schedule": 86400.0}})


def dispatch_job(job_id):
    if get_settings().jobs_eager and not get_settings().is_production:
        # Do not enter asyncio.run in the web server's running event loop.
        from threading import Thread
        thread = Thread(target=process_job.run, args=(job_id,), daemon=True)
        thread.start()
    else:
        try:
            process_job.apply_async(args=[job_id], retry=False)
        except Exception:
            # Committed DB job survives a broker outage; beat retries dispatch.
            pass


async def ingest(db, job, p, claim_token=None):
    doc = get_document(db, p, job.resource_id)
    if doc.status == "ready" and job.status == "completed":
        return
    doc = db.scalar(select(Document).where(Document.id == doc.id).with_for_update()
                    .execution_options(populate_existing=True))
    get_document(db, p, doc.id)
    if doc.deleted_at or doc.status == "deleting":
        raise HTTPException(404, "Document not found")
    document_id, version, storage_key = doc.id, doc.version, doc.storage_key
    name, mime_type, department_id = doc.name, doc.mime_type, doc.department_id
    job_id, user_id = job.id, job.user_id
    doc.status = "processing"
    db.commit()
    data = storage.get(storage_key)
    verify_file(name, mime_type, data)
    scan_status = scan(data)
    pages = extract(data, mime_type)
    prepared = list(chunks(pages))
    vectors = []
    embedding_status = "not_configured"
    if get_settings().openai_api_key:
        for offset in range(0, len(prepared), 16):
            vectors.extend(await embeddings(db, p, department_id, [content for _, content in prepared[offset:offset + 16]]))
        embedding_status = "ready"
    # Embedding usage commits must never expose half-indexed documents. Recheck
    # the immutable input and current authorization before the one index commit.
    db.rollback()
    db.expire_all()
    if claim_token:
        job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if not job or job.status != "running" or job.claim_token != claim_token:
            db.rollback()
            return
    p = principal_for_user(db, user_id)
    doc = db.scalar(select(Document).where(Document.id == document_id).with_for_update())
    get_document(db, p, document_id)
    if doc.version != version or doc.storage_key != storage_key or doc.status == "deleting" or doc.deleted_at:
        raise HTTPException(409, "Document changed during ingestion")
    ids = select(DocumentChunk.id).where(DocumentChunk.document_id == doc.id)
    db.execute(delete(EmbeddingRecord).where(EmbeddingRecord.chunk_id.in_(ids)))
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    for i, (location, content) in enumerate(prepared):
        row = DocumentChunk(document_id=doc.id, department_id=doc.department_id, content=content, location=location, ordinal=i, version=doc.version)
        db.add(row)
        db.flush()
        if vectors:
            db.add(EmbeddingRecord(chunk_id=row.id, department_id=doc.department_id, model=get_settings().embedding_model, vector=vectors[i]))
    doc.extracted_text = "\n\n".join(f"[{location}]\n{text}" for location, text in pages)
    doc.embedding_status, doc.scan_status = embedding_status, scan_status
    doc.status, doc.error_code, doc.processed_at = "ready", None, utcnow()
    if claim_token:
        job.status, job.error_code, job.claim_token, job.updated_at = "completed", None, None, utcnow()
    db.add(Notification(user_id=doc.owner_id, department_id=doc.department_id, title="Document ready", message="An uploaded document finished processing.", resource_type="document", resource_id=doc.id))
    record(db, p, "document.ingested", "document", doc.id, doc.department_id)
    db.commit()


@celery_app.task(bind=True, name="app.worker.process_job", max_retries=3)
def process_job(self, job_id):
    with session_factory()() as db:
        # Atomic status transition prevents two deliveries from running the same active job.
        claim_token = str(uuid4())
        claimed = db.execute(update(Job).where(Job.id == job_id, Job.status.in_(["queued", "retrying"]),
                                             Job.available_at <= utcnow(), Job.attempts < 6)
                             .values(status="running", claim_token=claim_token, updated_at=utcnow(), attempts=Job.attempts + 1)).rowcount
        db.commit()
        if not claimed:
            return
        job = db.get(Job, job_id)
        try:
            p = principal_for_user(db, job.user_id)
            if job.kind == "ingest":
                asyncio.run(ingest(db, job, p, claim_token))
                return
            elif job.kind == "workflow":
                from app.workflows import resume_workflow
                run = asyncio.run(resume_workflow(db, p, job.resource_id))
                if run.status == "failed":
                    raise ValueError("workflow_step_failed")
            else:
                from app.jobs import BUSINESS_KINDS, execute_business_job
                if job.kind not in BUSINESS_KINDS:
                    raise ValueError("unsupported_job")
                asyncio.run(execute_business_job(db, job_id, claim_token))
                return
            db.execute(update(Job).where(Job.id == job_id, Job.status == "running", Job.claim_token == claim_token)
                       .values(status="completed", claim_token=None, error_code=None, updated_at=utcnow()))
            db.commit()
        except Exception as exc:
            db.rollback()
            db.expire_all()
            job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
            if not job or job.status != "running" or job.claim_token != claim_token:
                db.rollback()
                return
            code, retryable = classify_failure(exc)
            job.status = "dead_letter" if job.attempts % 3 == 0 or not retryable else "retrying"
            job.error_code, job.updated_at, job.claim_token = code, utcnow(), None
            delay = 2 ** min(job.attempts, 3) * 10
            job.available_at = utcnow() + timedelta(seconds=delay)
            # Never resurrect a deleted document or overwrite the status of a
            # newer ingestion after the worker has lost source access.
            if job.kind == "ingest":
                doc = db.scalar(select(Document).where(Document.id == job.resource_id).with_for_update())
                if doc and not doc.deleted_at and doc.status == "processing":
                    doc.status, doc.error_code = "failed", job.error_code
            db.add(Notification(user_id=job.user_id, department_id=job.department_id, title="Background processing failed", message="Review the processing status before retrying.", resource_type="document" if job.kind == "ingest" else "workflow_run" if job.kind == "workflow" else "job", resource_id=job.resource_id if job.kind in {"ingest", "workflow"} else job.id))
            db.commit()
            if job.status == "retrying" and not get_settings().jobs_eager:
                raise self.retry(exc=RuntimeError(job.error_code), countdown=delay)


def classify_failure(exc):
    if isinstance(exc, ProviderError):
        known = {"provider_not_configured", "provider_error", "spending_limit"}
        return exc.code if exc.code in known else "processing_failed", exc.code in {"provider_error", "embedding_failed"}
    if isinstance(exc, HTTPException):
        if exc.status_code in {401, 403, 404}:
            return "access_denied", False
        if exc.status_code == 502:
            return "invalid_evidence", False
        return "invalid_input", False
    if isinstance(exc, TimeoutError):
        return "timeout", True
    return "processing_failed", True


@celery_app.task(name="app.worker.recover_jobs")
def recover_jobs():
    with session_factory()() as db:
        stale = list(db.scalars(select(Job).where(Job.status == "running", Job.updated_at < utcnow() - timedelta(minutes=15))
                               .with_for_update(skip_locked=True)))
        for job in stale:
            job.status = "dead_letter" if job.attempts % 3 == 0 or job.attempts >= 6 else "queued"
            job.claim_token, job.error_code = None, "worker_interrupted"
            job.updated_at = job.available_at = utcnow()
        db.commit()
        ids = list(db.scalars(select(Job.id).where(Job.status.in_(["queued", "retrying"]), Job.attempts < 6,
                                                 Job.available_at <= utcnow()).limit(100)))
        for job_id in ids:
            dispatch_job(job_id)
        try:
            from app.workflows import expire_approvals
            expire_approvals(db)
        except ImportError:
            pass
    return {"dispatched": len(ids)}
