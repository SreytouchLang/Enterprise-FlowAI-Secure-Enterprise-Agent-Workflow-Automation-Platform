"""Owner-scoped durable business operations, with transactional result publication."""
import asyncio
import hashlib
import json
import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import business
from app.audit import record
from app.auth import Principal, authorize_department, get_principal, principal_for_user
from app.db import get_db
from app.domain_schemas import (
    DocumentAction,
    InvoiceData,
    InvoiceExtract,
    LegalAnalysis,
    LegalInput,
    PropertyInput,
    SummaryData,
)
from app.models import Job, utcnow
from app.workflows import check_documents

router = APIRouter(prefix="/jobs", tags=["Background jobs"])
BUSINESS_KINDS = {"invoice", "legal", "hr_summary", "property"}
SCHEMAS: dict[str, type[DocumentAction | PropertyInput]] = {
    "invoice": InvoiceExtract, "legal": LegalInput, "hr_summary": DocumentAction,
    "property": PropertyInput,
}
ERROR_MESSAGES = {
    "provider_not_configured": "The selected model provider is not configured.",
    "provider_error": "The model provider could not complete this operation.",
    "spending_limit": "The configured model spending limit was reached.",
    "access_denied": "Access to the department or source documents is no longer available.",
    "invalid_input": "The input is invalid or conflicts with an existing record.",
    "invalid_evidence": "Model evidence could not be verified against the source documents.",
    "timeout": "Processing exceeded the allowed time.",
    "worker_interrupted": "The worker stopped before completing this operation.",
    "processing_failed": "Processing failed. Review the input before retrying.",
}


def job_dict(job):
    return {"id": job.id, "job_id": job.id, "kind": job.kind, "department_id": job.department_id,
            "resource_id": job.resource_id, "status": job.status, "attempts": job.attempts,
            "error_code": job.error_code,
            "error_message": ERROR_MESSAGES.get(job.error_code, "Processing failed.") if job.error_code else None,
            "result": job.result if job.status == "completed" else None,
            "created_at": job.created_at, "updated_at": job.updated_at,
            "available_at": job.available_at}


def authorize_job(db, principal, job, permission="workflows:read"):
    # Never return even metadata to another member of the same department.
    if not job or job.user_id != principal.id or job.kind not in BUSINESS_KINDS:
        raise HTTPException(404, "Job not found")
    authorize_department(principal, job.department_id, permission)
    check_documents(db, principal, job.document_ids)


def get_job(db, principal, job_id, permission="workflows:read", lock=False):
    query = select(Job).where(Job.id == job_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    job = db.scalar(query)
    authorize_job(db, principal, job, permission)
    return job


def validate_input(db, principal, kind, body):
    document_ids = []
    if kind == "hr_summary":
        doc = business.ready_document(db, principal, body.document_id)
        department_id = doc.department_id
        domain = "hr"
    else:
        department_id = body.department_id
        domain = {"invoice": "finance", "legal": "legal", "property": "operations"}[kind]
    business.domain_access(db, principal, department_id, domain)
    if kind != "property":
        document_ids = [body.document_id]
        if kind == "legal" and body.comparison_document_id:
            document_ids.append(body.comparison_document_id)
        for document_id in document_ids:
            business.ready_document(db, principal, document_id, department_id)
    else:
        try:
            business.normalize_property(body.sources)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
    return department_id, document_ids


def enqueue_business_job(db, principal, kind, body, idempotency_key=None):
    department_id, document_ids = validate_input(db, principal, kind, body)
    payload = body.model_dump(mode="json")
    input_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    key = idempotency_key or str(uuid4())
    if not key.strip() or len(key) > 120:
        raise HTTPException(422, "Idempotency-Key must contain 1 to 120 characters")
    key = "business:" + hashlib.sha256(f"{principal.id}:{kind}:{key}".encode()).hexdigest()
    existing = db.scalar(select(Job).where(Job.idempotency_key == key))
    if existing:
        authorize_job(db, principal, existing, "workflows:run")
        if existing.input_hash != input_hash:
            raise HTTPException(409, "Idempotency-Key was already used with different input")
        return job_dict(existing)
    job_id = str(uuid4())
    job = Job(id=job_id, department_id=department_id, user_id=principal.id, kind=kind,
              resource_id=job_id, idempotency_key=key, payload=payload, input_hash=input_hash,
              document_ids=document_ids)
    db.add(job)
    try:
        db.flush()
        record(db, principal, "job.queued", "job", job.id, department_id)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(Job).where(Job.idempotency_key == key))
        if not existing:
            raise
        authorize_job(db, principal, existing, "workflows:run")
        if existing.input_hash != input_hash:
            raise HTTPException(409, "Idempotency-Key was already used with different input") from None
        return job_dict(existing)
    from app.worker import dispatch_job
    dispatch_job(job.id)
    return job_dict(job)


@router.get("")
def list_jobs(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
              db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    rows = db.scalars(select(Job).where(Job.user_id == principal.id, Job.kind.in_(BUSINESS_KINDS))
                      .order_by(Job.created_at.desc())).all()
    visible = []
    for job in rows:
        try:
            authorize_job(db, principal, job)
        except HTTPException as exc:
            if exc.status_code in {403, 404}:
                continue
            raise
        visible.append(job)
    return {"items": [job_dict(job) for job in visible[offset:offset + limit]],
            "total": len(visible), "limit": limit, "offset": offset}


@router.get("/{job_id}")
def read_job(job_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    return job_dict(get_job(db, principal, job_id))


@router.post("/{job_id}/retry", status_code=202)
def retry_job(job_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    job = get_job(db, principal, job_id, "workflows:run", lock=True)
    if job.status != "dead_letter" or job.attempts >= 6:
        raise HTTPException(409, "Only failed jobs below the six-attempt lifetime limit can be retried")
    validate_input(db, principal, job.kind, SCHEMAS[job.kind].model_validate(job.payload))
    job.status, job.error_code, job.claim_token = "queued", None, None
    job.available_at = job.updated_at = utcnow()
    record(db, principal, "job.retry_requested", "job", job.id, job.department_id)
    db.commit()
    from app.worker import dispatch_job
    dispatch_job(job.id)
    return job_dict(job)


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    job = get_job(db, principal, job_id, "workflows:run", lock=True)
    if job.status == "cancelled":
        return job_dict(job)
    if job.status not in {"queued", "running", "retrying", "dead_letter"}:
        raise HTTPException(409, "Completed jobs cannot be cancelled")
    # Fencing prevents an already-running model request from publishing a result.
    # The provider may still charge for work that had already started.
    job.status, job.claim_token, job.updated_at = "cancelled", None, utcnow()
    record(db, principal, "job.cancelled", "job", job.id, job.department_id)
    db.commit()
    return job_dict(job)


async def execute_business_job(db, job_id, claim_token):
    job = db.get(Job, job_id)
    principal = principal_for_user(db, job.user_id)
    authorize_job(db, principal, job, "workflows:run")
    body = SCHEMAS[job.kind].model_validate(job.payload)
    validate_input(db, principal, job.kind, body)
    started = time.monotonic()
    output = None
    if isinstance(body, DocumentAction):
        schema = {"invoice": InvoiceData, "legal": LegalAnalysis, "hr_summary": SummaryData}[job.kind]
        output = await asyncio.wait_for(business.extract_structured(
            db, principal, job.department_id, job.document_ids, schema,
            provider=body.provider, model=body.model), timeout=240)
    # Provider usage accounting commits independently. No business result exists
    # until the claim is locked and revalidated after that potentially long call.
    db.rollback()
    db.expire_all()
    job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if not job or job.status != "running" or job.claim_token != claim_token:
        db.rollback()
        return False
    principal = principal_for_user(db, job.user_id)
    authorize_job(db, principal, job, "workflows:run")
    validate_input(db, principal, job.kind, body)
    if isinstance(body, InvoiceExtract):
        invoice = business.save_invoice(db, principal, job.department_id, InvoiceData.model_validate(output),
                                        body.document_id, body.expected_vendor,
                                        int((time.monotonic() - started) * 1000), commit=False)
        result = business.invoice_dict(invoice)
    elif isinstance(body, LegalInput):
        result = business.save_legal_review(db, principal, body, output, commit=False)
    elif isinstance(body, PropertyInput):
        result = business.save_property(db, principal, body, commit=False)
    else:
        result = output
        record(db, principal, "hr.document_summarized", "document", body.document_id, job.department_id)
    job.result = jsonable_encoder(result)
    job.resource_id = result.get("id", job.resource_id)
    job.status, job.error_code, job.claim_token = "completed", None, None
    job.updated_at = utcnow()
    record(db, principal, "job.completed", "job", job.id, job.department_id)
    # New invoice/review, approval, audit entry and job result publish atomically.
    db.commit()
    return True
