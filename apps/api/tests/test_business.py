"""Business journeys use a real SQLite database; model doubles are test-only."""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app import business, jobs, worker, workflows
from app.auth import get_principal, principal_for_user
from app.db import get_db
from app.domain_models import ApprovalRequest, Invoice, LegalReview, PropertyRecord, WorkflowRun
from app.domain_schemas import InvoiceData, LegalAnalysis, PropertySourceInput, SummaryData
from app.models import Base, Department, Document, Job, Membership, Notification, User, utcnow
from app.providers import ProviderError


@pytest.fixture
def domain_env(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'business.sqlite'}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    dispatch = Mock()
    monkeypatch.setattr(worker, "dispatch_job", dispatch)
    monkeypatch.setattr(worker, "session_factory", lambda: sessions)
    monkeypatch.setattr(worker, "get_settings", lambda: SimpleNamespace(jobs_eager=True))
    # Every model call must be explicitly configured by its test. No broker,
    # production database or real provider is used by these worker journeys.
    model = AsyncMock(side_effect=AssertionError("Unexpected model request"))
    monkeypatch.setattr(business, "structured_call", model)
    with Session(engine, expire_on_commit=False) as db:
        for slug in ("finance", "hr", "legal", "operations"):
            db.add(Department(id=slug, name=slug.title(), slug=slug))
        for identity, role, department in [
            ("fin_employee", "employee", "finance"), ("fin_manager", "manager", "finance"),
            ("hr_employee", "employee", "hr"), ("hr_manager", "manager", "hr"),
            ("legal_employee", "employee", "legal"), ("legal_manager", "manager", "legal"),
            ("ops_employee", "employee", "operations"), ("ops_manager", "manager", "operations"),
        ]:
            db.add(User(id=identity, subject=identity, email=f"{identity}@example.test", name=identity))
            db.flush()
            db.add(Membership(user_id=identity, department_id=department, role=role))
        db.commit()
        app = FastAPI()
        app.include_router(business.router, prefix="/api/v1")
        app.include_router(workflows.router, prefix="/api/v1")
        app.include_router(jobs.router, prefix="/api/v1")
        identity = {"current": "fin_employee"}

        def session_dependency():
            yield db

        def principal_dependency():
            return principal_for_user(db, identity["current"])

        app.dependency_overrides[get_db] = session_dependency
        app.dependency_overrides[get_principal] = principal_dependency
        with TestClient(app) as client:
            yield SimpleNamespace(client=client, db=db, identity=identity, engine=engine,
                                  dispatch=dispatch, model=model)
    engine.dispose()


def invoice_payload(total="1350.00", number="INV-1001"):
    total_value = Decimal(total)
    return {
        "vendor_name": "Fictional Property Services", "invoice_number": number,
        "invoice_date": (date.today() - timedelta(days=2)).isoformat(),
        "due_date": (date.today() + timedelta(days=28)).isoformat(), "currency": "USD",
        "subtotal": str(total_value - Decimal("100")), "tax": "100.00", "total": total,
        "line_items": [{"description": "Property inspection", "quantity": "1",
                        "unit_price": str(total_value - Decimal("100")),
                        "amount": str(total_value - Decimal("100"))}],
    }


def add_document(env, department, owner, visibility="department", text="Synthetic source text."):
    document = Document(department_id=department, owner_id=owner, name="Synthetic evidence.txt",
                        mime_type="text/plain", size=len(text), content_hash="a" * 64,
                        storage_key="test-only", visibility=visibility, status="ready", extracted_text=text)
    env.db.add(document)
    env.db.commit()
    return document


def run_job(env, response):
    assert response.status_code == 202, response.text
    queued = response.json()
    assert queued["status"] == "queued"
    assert queued["attempts"] == 0
    assert queued["result"] is None
    env.dispatch.assert_called_with(queued["id"])
    # The real worker claims and publishes in its own transaction. Expire the
    # API session so polling observes persisted state rather than cached rows.
    env.db.rollback()
    worker.process_job.run(queued["id"])
    env.db.expire_all()
    result = env.client.get(f"/api/v1/jobs/{queued['id']}")
    assert result.status_code == 200, result.text
    return result.json()


def test_decimal_invoice_calculations_detect_all_exceptions():
    raw = invoice_payload()
    raw.update(currency="XYZ", due_date="2020-01-01", subtotal="1200.00", total="999999.00")
    raw["line_items"][0]["quantity"] = "2"
    data = InvoiceData.model_validate(raw)
    errors = business.validate_invoice(data, duplicate=True, expected_vendor="Another Vendor")
    assert set(errors) == {"duplicate_invoice_number", "due_date_before_invoice_date", "unsupported_currency",
                           "suspiciously_large_amount", "vendor_mismatch", "line_1_calculation_mismatch",
                           "subtotal_mismatch", "total_mismatch"}


def test_invoice_rejects_float_currency_and_negative_amount():
    raw = invoice_payload()
    raw["total"] = 1350.0
    with pytest.raises(ValidationError, match="decimal strings"):
        InvoiceData.model_validate(raw)
    raw["total"] = "-5.00"
    with pytest.raises(ValidationError):
        InvoiceData.model_validate(raw)


def test_finance_manual_invoice_manager_approval_and_duplicates(domain_env):
    env = domain_env
    response = env.client.post("/api/v1/finance/invoices/manual", json={"department_id": "finance", "data": invoice_payload()})
    assert response.status_code == 201, response.text
    invoice = response.json()
    assert invoice["validation_errors"] == []
    result = env.client.post(f"/api/v1/finance/invoices/{invoice['id']}/submit")
    assert result.json()["approval_status"] == "pending_approval"
    approval_id = env.client.get("/api/v1/approvals").json()["items"][0]["id"]
    assert env.client.post(f"/api/v1/approvals/{approval_id}/approve", json={}).status_code == 403
    env.identity["current"] = "fin_manager"
    assert env.client.post(f"/api/v1/approvals/{approval_id}/approve", json={"comment": "Verified."}).status_code == 200
    assert env.client.get(f"/api/v1/finance/invoices/{invoice['id']}").json()["approval_status"] == "approved"
    duplicate = env.client.post("/api/v1/finance/invoices/manual", json={"department_id": "finance", "data": invoice_payload()})
    assert "duplicate_invoice_number" in duplicate.json()["validation_errors"]
    assert env.client.post(f"/api/v1/finance/invoices/{duplicate.json()['id']}/submit").status_code == 409


def test_approval_alerts_go_only_to_authorized_reviewers_with_document_access(domain_env):
    env = domain_env
    document = add_document(env, "finance", "fin_employee", "department")
    invoice = env.client.post("/api/v1/finance/invoices/manual", json={
        "department_id": "finance", "document_id": document.id, "data": invoice_payload()}).json()
    result = env.client.post(f"/api/v1/finance/invoices/{invoice['id']}/submit")
    assert result.status_code == 200
    alerts = env.db.scalars(select(Notification).where(Notification.title == "Approval requested")).all()
    assert [alert.user_id for alert in alerts] == ["fin_manager"]
    assert env.db.info["principal_scope"][0] == "fin_employee"
    private_document = add_document(env, "finance", "fin_employee", "private")
    private_invoice = env.client.post("/api/v1/finance/invoices/manual", json={
        "department_id": "finance", "document_id": private_document.id,
        "data": invoice_payload(number="PRIVATE-INV")}).json()
    env.client.post(f"/api/v1/finance/invoices/{private_invoice['id']}/submit")
    # No same-department recipient may discover the inaccessible private invoice.
    assert len(env.db.scalars(select(Notification).where(Notification.title == "Approval requested")).all()) == 1


def test_private_finance_documents_remain_private_in_invoice_and_approval_views(domain_env):
    env = domain_env
    document = add_document(env, "finance", "fin_employee", "private")
    invoice = env.client.post("/api/v1/finance/invoices/manual", json={
        "department_id": "finance", "document_id": document.id, "data": invoice_payload()}).json()
    env.client.post(f"/api/v1/finance/invoices/{invoice['id']}/submit")
    approval = env.db.scalar(select(ApprovalRequest))
    env.identity["current"] = "fin_manager"
    assert env.client.get("/api/v1/finance/invoices").json()["total"] == 0
    assert env.client.get("/api/v1/approvals").json()["total"] == 0
    assert env.client.get(f"/api/v1/approvals/{approval.id}").status_code == 404
    assert env.client.post(f"/api/v1/approvals/{approval.id}/approve", json={}).status_code == 404


def test_cross_department_business_inputs_and_access_are_denied(domain_env):
    env = domain_env
    assert env.client.post("/api/v1/hr/onboardings", json={"department_id": "hr", "employee_name": "Fictional Person",
                           "employee_email": "person@example.test", "start_date": "2026-10-15"}).status_code == 403
    document = add_document(env, "hr", "hr_employee", "private")
    assert env.client.post("/api/v1/finance/invoices", json={"department_id": "finance", "document_id": document.id}).status_code == 404
    assert env.client.get("/api/v1/operations/properties?department_id=operations").status_code == 403


def test_invoice_corrections_are_validated_and_submitted_records_immutable(domain_env):
    env = domain_env
    payload = invoice_payload()
    payload["total"] = "1500.00"
    invoice = env.client.post("/api/v1/finance/invoices/manual", json={"department_id": "finance", "data": payload}).json()
    assert invoice["processing_status"] == "needs_review"
    result = env.client.patch(f"/api/v1/finance/invoices/{invoice['id']}", json=invoice_payload())
    assert result.json()["processing_status"] == "processed"
    env.client.post(f"/api/v1/finance/invoices/{invoice['id']}/submit")
    assert env.client.patch(f"/api/v1/finance/invoices/{invoice['id']}", json=invoice_payload()).status_code == 409


def test_invoice_provider_failure_never_creates_success_record(domain_env, monkeypatch):
    env = domain_env
    document = add_document(env, "finance", "fin_employee")
    monkeypatch.setattr(business, "structured_call", AsyncMock(side_effect=ProviderError("provider_not_configured", "Provider not configured")))
    result = env.client.post("/api/v1/finance/invoices", json={"department_id": "finance", "document_id": document.id})
    job = run_job(env, result)
    assert job["status"] == "dead_letter"
    assert job["error_code"] == "provider_not_configured"
    assert job["attempts"] == 1
    assert job["result"] is None
    assert env.db.scalar(select(Invoice)) is None
    alert = env.db.scalar(select(Notification).where(Notification.resource_id == job["id"]))
    assert alert.title == "Background processing failed"
    assert alert.user_id == "fin_employee"


def test_invoice_structured_extraction_uses_authorized_document(domain_env, monkeypatch):
    env = domain_env
    document = add_document(env, "finance", "fin_employee", text="Synthetic invoice INV-1001")
    model = AsyncMock(return_value=SimpleNamespace(data=InvoiceData.model_validate(invoice_payload())))
    monkeypatch.setattr(business, "structured_call", model)
    result = env.client.post("/api/v1/finance/invoices", json={"department_id": "finance", "document_id": document.id})
    assert env.db.scalar(select(Invoice)) is None
    job = run_job(env, result)
    assert job["status"] == "completed"
    assert job["attempts"] == 1
    assert job["result"]["extracted"]["total"] == "1350.00"
    invoice = env.db.get(Invoice, job["resource_id"])
    assert invoice.document_id == document.id
    assert job["result"]["id"] == invoice.id
    model.assert_awaited_once()
    assert "Synthetic invoice INV-1001" in str(model.call_args)


def test_business_job_idempotency_and_redelivery_publish_one_result(domain_env):
    env = domain_env
    document = add_document(env, "finance", "fin_employee")
    env.model.side_effect = None
    env.model.return_value = SimpleNamespace(data=InvoiceData.model_validate(invoice_payload()))
    payload = {"department_id": "finance", "document_id": document.id}
    headers = {"Idempotency-Key": "invoice-request-1"}
    queued = env.client.post("/api/v1/finance/invoices", json=payload, headers=headers)
    repeated = env.client.post("/api/v1/finance/invoices", json=payload, headers=headers)
    assert repeated.status_code == 202
    assert repeated.json()["id"] == queued.json()["id"]
    assert env.client.post("/api/v1/finance/invoices", json={
        **payload, "expected_vendor": "Different vendor"}, headers=headers).status_code == 409
    env.dispatch.assert_called_once()
    completed = run_job(env, queued)
    assert completed["status"] == "completed"
    env.db.rollback()
    worker.process_job.run(completed["id"])
    env.db.expire_all()
    replay = env.client.post("/api/v1/finance/invoices", json=payload, headers=headers)
    assert replay.json() == completed
    env.model.assert_awaited_once()
    assert len(env.db.scalars(select(Invoice)).all()) == 1
    assert env.db.get(Job, completed["id"]).attempts == 1


@pytest.mark.parametrize("other_user", ["fin_manager", "hr_employee"])
def test_business_jobs_are_visible_and_mutable_only_by_owner(domain_env, other_user):
    env = domain_env
    document = add_document(env, "finance", "fin_employee")
    queued = env.client.post("/api/v1/finance/invoices", json={
        "department_id": "finance", "document_id": document.id})
    assert queued.status_code == 202
    job_id = queued.json()["id"]
    assert env.client.get("/api/v1/jobs").json()["total"] == 1
    env.identity["current"] = other_user
    assert env.client.get("/api/v1/jobs").json()["total"] == 0
    assert env.client.get(f"/api/v1/jobs/{job_id}").status_code == 404
    assert env.client.post(f"/api/v1/jobs/{job_id}/cancel").status_code == 404
    assert env.client.post(f"/api/v1/jobs/{job_id}/retry").status_code == 404
    assert env.db.get(Job, job_id).status == "queued"


@pytest.mark.parametrize("cancel_during_provider", [False, True])
def test_business_job_cancellation_prevents_result_publication(domain_env, cancel_during_provider):
    env = domain_env
    document = add_document(env, "finance", "fin_employee")
    queued = env.client.post("/api/v1/finance/invoices", json={
        "department_id": "finance", "document_id": document.id})
    assert queued.status_code == 202
    job_id = queued.json()["id"]

    async def model_response(*args, **kwargs):
        response = env.client.post(f"/api/v1/jobs/{job_id}/cancel")
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
        return SimpleNamespace(data=InvoiceData.model_validate(invoice_payload()))

    if cancel_during_provider:
        env.model.side_effect = model_response
    else:
        assert env.client.post(f"/api/v1/jobs/{job_id}/cancel").status_code == 200
    env.db.rollback()
    worker.process_job.run(job_id)
    env.db.expire_all()
    job = env.client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["status"] == "cancelled"
    assert job["result"] is None
    assert env.db.scalar(select(Invoice)) is None
    assert env.model.await_count == int(cancel_during_provider)
    assert env.client.post(f"/api/v1/jobs/{job_id}/retry").status_code == 409


def test_business_job_rechecks_source_access_after_provider_returns(domain_env):
    env = domain_env
    document = add_document(env, "finance", "fin_employee")
    document_id = document.id
    queued = env.client.post("/api/v1/finance/invoices", json={
        "department_id": "finance", "document_id": document_id})
    assert queued.status_code == 202

    async def revoke_access(*args, **kwargs):
        with Session(env.engine) as db:
            source = db.get(Document, document_id)
            source.owner_id, source.visibility = "fin_manager", "private"
            db.commit()
        return SimpleNamespace(data=InvoiceData.model_validate(invoice_payload()))

    env.model.side_effect = revoke_access
    env.db.rollback()
    worker.process_job.run(queued.json()["id"])
    env.db.expire_all()
    job = env.db.get(Job, queued.json()["id"])
    assert job.status == "dead_letter"
    assert job.error_code == "access_denied"
    assert job.result is None
    assert env.db.scalar(select(Invoice)) is None
    assert env.client.get(f"/api/v1/jobs/{job.id}").status_code == 404
    assert env.client.get("/api/v1/jobs").json()["total"] == 0


def test_business_job_transient_failure_can_retry_without_duplicate_result(domain_env):
    env = domain_env
    document = add_document(env, "finance", "fin_employee")
    env.model.side_effect = ProviderError("provider_error", "Provider temporarily unavailable")
    queued = env.client.post("/api/v1/finance/invoices", json={
        "department_id": "finance", "document_id": document.id})
    job = run_job(env, queued)
    assert job["status"] == "retrying"
    assert job["error_code"] == "provider_error"
    assert env.client.post(f"/api/v1/jobs/{job['id']}/retry").status_code == 409
    for attempt in (2, 3):
        row = env.db.get(Job, job["id"])
        row.available_at = utcnow() - timedelta(seconds=1)
        env.db.commit()
        worker.process_job.run(job["id"])
        env.db.expire_all()
        assert env.db.get(Job, job["id"]).attempts == attempt
    assert env.db.get(Job, job["id"]).status == "dead_letter"
    assert env.db.scalar(select(Invoice)) is None
    env.model.side_effect = None
    env.model.return_value = SimpleNamespace(data=InvoiceData.model_validate(invoice_payload()))
    retry = env.client.post(f"/api/v1/jobs/{job['id']}/retry")
    assert retry.status_code == 202
    assert retry.json()["status"] == "queued"
    assert retry.json()["error_code"] is None
    env.db.rollback()
    worker.process_job.run(job["id"])
    env.db.expire_all()
    completed = env.client.get(f"/api/v1/jobs/{job['id']}").json()
    assert completed["status"] == "completed"
    assert completed["attempts"] == 4
    assert len(env.db.scalars(select(Invoice)).all()) == 1
    assert env.client.post(f"/api/v1/jobs/{job['id']}/cancel").status_code == 409


def test_hr_summary_job_persists_verified_evidence(domain_env):
    env = domain_env
    env.identity["current"] = "hr_employee"
    source = "Employees receive twenty days of annual leave."
    document = add_document(env, "hr", "hr_employee", text=source)
    summary = SummaryData(summary="Annual leave is twenty days.",
                          evidence=[{"document_id": document.id, "quote": source}])
    env.model.side_effect = None
    env.model.return_value = SimpleNamespace(data=summary)
    job = run_job(env, env.client.post("/api/v1/hr/summarize", json={"document_id": document.id}))
    assert job["status"] == "completed"
    assert job["kind"] == "hr_summary"
    assert job["result"] == summary.model_dump(mode="json")
    assert env.db.get(Job, job["id"]).result == job["result"]


def test_hr_onboarding_requires_completion_then_manager_review(domain_env):
    env = domain_env
    env.identity["current"] = "hr_employee"
    result = env.client.post("/api/v1/hr/onboardings", json={"department_id": "hr", "employee_name": "Fictional Aster Reed",
                            "employee_email": "aster@example.test", "start_date": "2026-10-15"})
    assert result.status_code == 201, result.text
    case = result.json()
    assert len(case["tasks"]) == 4
    assert env.client.post(f"/api/v1/hr/onboardings/{case['id']}/submit").status_code == 409
    for task in case["tasks"]:
        assert env.client.patch(f"/api/v1/hr/tasks/{task['id']}", json={"completed": True}).status_code == 200
    assert env.client.post(f"/api/v1/hr/onboardings/{case['id']}/submit").json()["status"] == "pending_review"
    assert env.client.patch(f"/api/v1/hr/tasks/{case['tasks'][0]['id']}", json={"completed": False}).status_code == 409
    env.identity["current"] = "hr_manager"
    approval = env.client.get("/api/v1/approvals").json()["items"][0]
    assert env.client.post(f"/api/v1/approvals/{approval['id']}/approve", json={}).status_code == 200
    assert env.client.get("/api/v1/hr/onboardings").json()["items"][0]["status"] == "completed"


def legal_analysis(document_id, quote):
    return LegalAnalysis(document_type="service_agreement", parties=["Fictional A", "Fictional B"],
                          effective_date="2026-10-01", renewal_type="manual", summary="Synthetic agreement summary.",
                          obligations=["Provide inspection services"], termination_clauses=[],
                          review_flags=[], evidence=[{"document_id": document_id, "quote": quote}])


def test_legal_analysis_requires_real_source_evidence_and_human_review(domain_env, monkeypatch):
    env = domain_env
    env.identity["current"] = "legal_employee"
    text = "Fictional A shall provide inspection services for Fictional B."
    document = add_document(env, "legal", "legal_employee", text=text)
    monkeypatch.setattr(business, "structured_call", AsyncMock(return_value=SimpleNamespace(data=legal_analysis(document.id, text))))
    result = env.client.post("/api/v1/legal/reviews", json={"department_id": "legal", "document_id": document.id})
    job = run_job(env, result)
    assert job["status"] == "completed"
    review = job["result"]
    assert review["analysis"]["requires_human_review"] is True
    assert "Termination clauses are missing" in review["analysis"]["review_flags"]
    assert review["status"] == "pending_review"
    approval = env.db.scalar(select(ApprovalRequest).where(ApprovalRequest.resource_id == review["id"]))
    assert approval.status == "pending"
    monkeypatch.setattr(business, "structured_call", AsyncMock(return_value=SimpleNamespace(data=legal_analysis(document.id, "Fabricated supporting quotation"))))
    rejected = run_job(env, env.client.post("/api/v1/legal/reviews", json={
        "department_id": "legal", "document_id": document.id}))
    assert rejected["status"] == "dead_letter"
    assert rejected["error_code"] == "invalid_evidence"
    assert rejected["result"] is None
    assert len(env.db.scalars(select(LegalReview)).all()) == 1
    assert len(env.db.scalars(select(ApprovalRequest)).all()) == 1


def test_property_conflicts_preserve_every_source_without_choosing_a_value():
    sources = [PropertySourceInput(name="A", fields={"city": "phoenix", "bedrooms": "3", "bathrooms": 2}),
               PropertySourceInput(name="B", fields={"city": " Phoenix ", "bedrooms": 4, "bathrooms": "2.0"}),
               PropertySourceInput(name="C", fields={"status": "bank owned"})]
    normalized, provenance, conflicts, missing = business.normalize_property(sources)
    assert normalized["city"] == "Phoenix"
    assert normalized["bedrooms"] is None
    assert normalized["bathrooms"] == "2"
    assert normalized["status"] == "REO"
    assert conflicts == [{"field": "bedrooms", "values": [3, 4]}]
    assert len(provenance["bedrooms"]) == 2
    assert missing == ["address"]


def test_property_import_review_provenance_and_description(domain_env):
    env = domain_env
    env.identity["current"] = "ops_employee"
    sources = [{"name": "A", "fields": {"address": "123 Fictional Lane", "city": "Phoenix", "bedrooms": 3,
                                        "bathrooms": 2, "status": "REO"}},
               {"name": "B", "fields": {"bedrooms": 4}}]
    result = env.client.post("/api/v1/operations/properties", json={"department_id": "operations", "property_id": "P-TEST", "sources": sources})
    job = run_job(env, result)
    assert job["status"] == "completed"
    item = job["result"]
    assert len(item["sources"]) == 2
    assert len(item["conflicts"]) == 1
    assert env.db.get(PropertyRecord, job["resource_id"]).property_id == "P-TEST"
    assert item["normalized"]["bedrooms"] is None
    assert env.client.post(f"/api/v1/operations/properties/{item['id']}/description").status_code == 409
    decision = {"resolved_fields": {"bedrooms": 4}, "comment": "Verified against fictional inspection."}
    assert env.client.post(f"/api/v1/operations/properties/{item['id']}/review", json=decision).status_code == 403
    env.identity["current"] = "ops_manager"
    result = env.client.post(f"/api/v1/operations/properties/{item['id']}/review", json=decision)
    assert result.status_code == 200, result.text
    assert result.json()["conflicts"][0]["resolved_value"] == {"value": 4}
    assert result.json()["provenance"]["bedrooms"][-1]["source"] == "human_review"
    assert "4 bedrooms" in env.client.post(f"/api/v1/operations/properties/{item['id']}/description").json()["description"]


@pytest.mark.parametrize("value", ["NaN", "Infinity", -1, "3.5"])
def test_property_rejects_invalid_bedroom_values(value):
    with pytest.raises(ValueError):
        business.normalize_property_value("bedrooms", value)


def test_seed_business_is_reproducible_and_demo_history_labeled(domain_env):
    db = domain_env.db
    departments, users = db.scalars(select(Department)).all(), db.scalars(select(User)).all()
    business.seed_business(db, departments, users)
    db.commit()
    business.seed_business(db, departments, users)
    db.commit()
    assert len(db.scalars(select(Invoice)).all()) == 20
    assert len(db.scalars(select(PropertyRecord)).all()) == 30
    runs = db.scalars(select(WorkflowRun)).all()
    assert len(runs) == 15
    assert all(run.is_demo for run in runs)
