"""Core persistence. Authorization never trusts department or role claims from clients."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Entity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Department(Entity, Base):
    __tablename__ = "departments"
    name: Mapped[str] = mapped_column(String(100), unique=True)
    slug: Mapped[str] = mapped_column(String(30), unique=True)


class User(Entity, Base):
    __tablename__ = "users"
    subject: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Global roles are deliberately distinct from department memberships.
    roles: Mapped[list] = mapped_column(JSON, default=list)


class Membership(Base):
    __tablename__ = "department_memberships"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(40), default="employee")


class Role(Base):
    __tablename__ = "roles"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)


class Permission(Base):
    __tablename__ = "permissions"
    name: Mapped[str] = mapped_column(String(80), primary_key=True)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role: Mapped[str] = mapped_column(ForeignKey("roles.name"), primary_key=True)
    permission: Mapped[str] = mapped_column(ForeignKey("permissions.name"), primary_key=True)


class LoginState(Base):
    __tablename__ = "login_states"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    verifier: Mapped[str] = mapped_column(String(150))
    nonce: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SessionRecord(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(100))
    access_token: Mapped[str] = mapped_column(Text)  # encrypted at application boundary
    refresh_token: Mapped[str] = mapped_column(Text, default="")
    id_token: Mapped[str] = mapped_column(Text, default="")
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Agent(Entity, Base):
    __tablename__ = "agents"
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="Answer from authorized sources. Cite evidence.")
    provider: Mapped[str] = mapped_column(String(30), default="openai")
    model: Mapped[str] = mapped_column(String(100), default="gpt-4.1-mini")
    tools: Mapped[list] = mapped_column(JSON, default=lambda: ["search_documents"])
    status: Mapped[str] = mapped_column(String(20), default="active")
    max_tokens: Mapped[int] = mapped_column(Integer, default=2048)
    max_iterations: Mapped[int] = mapped_column(Integer, default=4)
    budget_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0.25"))
    prompt_version: Mapped[int] = mapped_column(Integer, default=1)


class AgentVersion(Entity, Base):
    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version"),)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    version: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict] = mapped_column(JSON)


class AgentTool(Base):
    __tablename__ = "agent_tools"
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), primary_key=True)


class Document(Entity, Base):
    __tablename__ = "documents"
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(150))
    size: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    storage_key: Mapped[str] = mapped_column(String(300))
    visibility: Mapped[str] = mapped_column(String(20), default="department")
    status: Mapped[str] = mapped_column(String(30), default="queued")
    scan_status: Mapped[str] = mapped_column(String(40), default="pending")
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    error_code: Mapped[str | None] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(Integer, default=1)
    embedding_status: Mapped[str] = mapped_column(String(40), default="not_configured")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentVersion(Entity, Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version"),)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"))
    version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(300))


class DocumentPermission(Base):
    __tablename__ = "document_permissions"
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)


class DocumentChunk(Entity, Base):
    __tablename__ = "document_chunks"
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), index=True)
    content: Mapped[str] = mapped_column(Text)
    location: Mapped[str] = mapped_column(String(100))
    ordinal: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer)


class EmbeddingRecord(Base):
    __tablename__ = "embedding_records"
    chunk_id: Mapped[str] = mapped_column(ForeignKey("document_chunks.id", ondelete="CASCADE"), primary_key=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), index=True)
    model: Mapped[str] = mapped_column(String(100))
    vector: Mapped[list] = mapped_column(JSON().with_variant(Vector(1536), "postgresql"))


class Conversation(Entity, Base):
    __tablename__ = "conversations"
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    title: Mapped[str] = mapped_column(String(160), default="New conversation")


class Message(Entity, Base):
    __tablename__ = "messages"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSON, default=list)


class AgentExecution(Entity, Base):
    __tablename__ = "agent_executions"
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"))
    status: Mapped[str] = mapped_column(String(30), default="running")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[int] = mapped_column(Integer, default=1)
    trace: Mapped[list] = mapped_column(JSON, default=list)  # event metadata only
    seeded_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class ModelUsage(Entity, Base):
    __tablename__ = "model_usage"
    execution_id: Mapped[str | None] = mapped_column(ForeignKey("agent_executions.id"))
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(14, 8), default=0)
    reserved_usd: Mapped[Decimal] = mapped_column(Numeric(14, 8), default=0)
    status: Mapped[str] = mapped_column(String(20), default="reserved")


class AuditEvent(Entity, Base):
    __tablename__ = "audit_events"
    actor_id: Mapped[str | None] = mapped_column(String(36), index=True)
    department_id: Mapped[str | None] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(60))
    resource_id: Mapped[str | None] = mapped_column(String(100))
    result: Mapped[str] = mapped_column(String(30), default="success")
    request_id: Mapped[str] = mapped_column(String(80), default="")


class Notification(Entity, Base):
    __tablename__ = "notifications"
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(Text, default="")
    resource_type: Mapped[str | None] = mapped_column(String(60))
    resource_id: Mapped[str | None] = mapped_column(String(100))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Job(Entity, Base):
    __tablename__ = "jobs"
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str] = mapped_column(String(36))
    idempotency_key: Mapped[str] = mapped_column(String(150), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_ids: Mapped[list] = mapped_column(JSON, default=list)
    claim_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
