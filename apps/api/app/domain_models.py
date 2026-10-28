"""Department-owned business records and durable workflow checkpoints."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


def uid() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Workflow(Record, Base):
    __tablename__ = "workflows"
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    definition: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    published_version: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (UniqueConstraint("workflow_id", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkflowRun(Record, Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (UniqueConstraint("workflow_id", "started_by", "idempotency_key"),)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"), index=True)
    workflow_version: Mapped[int] = mapped_column(Integer)
    started_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    next_node_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    document_ids: Mapped[list] = mapped_column(JSON, default=list)
    claim_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    is_demo: Mapped[bool] = mapped_column(default=False)


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"
    __table_args__ = (UniqueConstraint("run_id", "node_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    node_id: Mapped[str] = mapped_column(String(80))
    node_type: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), default="running")
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApprovalRequest(Record, Base):
    __tablename__ = "approval_requests"
    __table_args__ = (UniqueConstraint("resource_type", "resource_id", "checkpoint"),)
    title: Mapped[str] = mapped_column(String(200))
    resource_type: Mapped[str] = mapped_column(String(40), index=True)
    resource_id: Mapped[str] = mapped_column(String(36), index=True)
    checkpoint: Mapped[str] = mapped_column(String(80), default="review")
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    assigned_to: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    document_ids: Mapped[list] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    approval_id: Mapped[str] = mapped_column(ForeignKey("approval_requests.id"), unique=True)
    decided_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(30))
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Invoice(Record, Base):
    __tablename__ = "invoices"
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    vendor_name: Mapped[str] = mapped_column(String(200))
    invoice_number: Mapped[str] = mapped_column(String(100), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    extracted: Mapped[dict] = mapped_column(JSON)
    validation_errors: Mapped[list] = mapped_column(JSON, default=list)
    processing_status: Mapped[str] = mapped_column(String(30), default="processed")
    approval_status: Mapped[str] = mapped_column(String(30), default="not_submitted")
    processing_ms: Mapped[int] = mapped_column(Integer, default=0)
    is_demo: Mapped[bool] = mapped_column(default=False)


class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id"), index=True)
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class OnboardingTemplate(Record, Base):
    __tablename__ = "onboarding_templates"
    name: Mapped[str] = mapped_column(String(120))
    tasks: Mapped[list] = mapped_column(JSON)


class OnboardingCase(Record, Base):
    __tablename__ = "onboarding_cases"
    employee_name: Mapped[str] = mapped_column(String(160))
    employee_email: Mapped[str] = mapped_column(String(250))
    start_date: Mapped[str] = mapped_column(String(10))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(30), default="active")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OnboardingTask(Base):
    __tablename__ = "onboarding_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    onboarding_id: Mapped[str] = mapped_column(ForeignKey("onboarding_cases.id"), index=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    required_document: Mapped[str | None] = mapped_column(String(200), nullable=True)
    assigned_to: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    completed: Mapped[bool] = mapped_column(default=False)
    completed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LegalReview(Record, Base):
    __tablename__ = "legal_reviews"
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    comparison_document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    analysis: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="pending_review")


class PropertyRecord(Record, Base):
    __tablename__ = "property_records"
    __table_args__ = (UniqueConstraint("department_id", "property_id"),)
    property_id: Mapped[str] = mapped_column(String(80))
    normalized: Mapped[dict] = mapped_column(JSON)
    provenance: Mapped[dict] = mapped_column(JSON)
    missing_fields: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="needs_review")
    review_comment: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_demo: Mapped[bool] = mapped_column(default=False)


class PropertySource(Base):
    __tablename__ = "property_sources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    property_record_id: Mapped[str] = mapped_column(ForeignKey("property_records.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    fields: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PropertyConflict(Base):
    __tablename__ = "property_conflicts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    property_record_id: Mapped[str] = mapped_column(ForeignKey("property_records.id"), index=True)
    field: Mapped[str] = mapped_column(String(80))
    values: Mapped[list] = mapped_column(JSON)
    resolved_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
