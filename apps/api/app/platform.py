"""Metadata, real activity analytics, explicit membership administration and safe settings."""
from datetime import timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.audit import record
from app.auth import ROLE_PERMISSIONS, Principal, authorize_department, get_principal, require_permission
from app.core.config import get_settings
from app.db import get_db
from app.documents import document_filter, get_document
from app.models import (
    Agent,
    AgentExecution,
    AuditEvent,
    Department,
    Document,
    Membership,
    ModelUsage,
    Notification,
    SessionRecord,
    User,
    utcnow,
)

router = APIRouter(tags=["platform"])


def scoped_departments(p, permission):
    return [d for d in p.department_ids if p.department_permissions is None or permission in p.department_permissions.get(d, set())]


@router.get("/departments")
def departments(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    query = select(Department)
    if "platform:admin" not in p.permissions:
        query = query.where(Department.id.in_(p.department_ids))
    rows = list(db.scalars(query.order_by(Department.name)))
    return {"items": [{"id": d.id, "name": d.name, "slug": d.slug} for d in rows], "total": len(rows), "limit": 100, "offset": 0}


@router.get("/analytics/overview")
def overview(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    from app.domain_models import ApprovalRequest, WorkflowRun
    require_permission(p, "analytics:read")
    ids = scoped_departments(p, "analytics:read")
    executions = list(db.scalars(select(AgentExecution).where(AgentExecution.department_id.in_(ids), AgentExecution.seeded_demo.is_(False))))
    # Workflow counters expose only runs started by this user, avoiding private input metadata leaks.
    runs = list(db.scalars(select(WorkflowRun).where(WorkflowRun.department_id.in_(ids), WorkflowRun.started_by == p.id, WorkflowRun.is_demo.is_(False))))
    completed = sum(r.status == "completed" for r in runs)
    documents = db.scalar(select(func.count()).select_from(Document).where(document_filter(p), Document.status == "ready"))
    approvals = list(db.scalars(select(ApprovalRequest).where(ApprovalRequest.department_id.in_(ids), ApprovalRequest.status == "pending")))
    pending = 0
    for approval in approvals:
        if approval.assigned_to and approval.assigned_to != p.id and approval.requested_by != p.id:
            continue
        try:
            for document_id in approval.document_ids:
                get_document(db, p, document_id)
        except HTTPException:
            continue
        pending += 1
    activity = []
    for i in range(13, -1, -1):
        day = (utcnow() - timedelta(days=i)).date()
        activity.append({"date": day.isoformat(), "completed": sum(e.created_at.date() == day and e.status == "completed" for e in executions) + sum(r.created_at.date() == day and r.status == "completed" for r in runs), "failed": sum(e.created_at.date() == day and e.status == "failed" for e in executions) + sum(r.created_at.date() == day and r.status == "failed" for r in runs)})
    depts = list(db.scalars(select(Department).where(Department.id.in_(ids))))
    return {"active_agents": db.scalar(select(func.count()).select_from(Agent).where(Agent.department_id.in_(ids), Agent.status == "active")), "workflows_completed": completed, "pending_approvals": pending, "documents_processed": documents, "failed_executions": sum(e.status == "failed" for e in executions) + sum(r.status == "failed" for r in runs), "estimated_minutes_saved": completed * 5, "estimate_method": "Illustrative estimate: 5 minutes per completed, non-demo workflow started by you. Not a measured business outcome.", "activity": activity, "departments": [{"name": d.name, "executions": sum(e.department_id == d.id for e in executions)} for d in depts], "provider_configured": get_settings().llm_provider_configured, "seeded_history_excluded": True}


@router.get("/analytics/agents")
def agent_analytics(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    require_permission(p, "analytics:read")
    agents = db.scalars(select(Agent).where(Agent.department_id.in_(scoped_departments(p, "analytics:read")))).all()
    items = []
    for agent in agents:
        runs = db.scalars(select(AgentExecution).where(AgentExecution.agent_id == agent.id, AgentExecution.seeded_demo.is_(False))).all()
        items.append({"id": agent.id, "name": agent.name, "executions": len(runs), "completed": sum(r.status == "completed" for r in runs), "failed": sum(r.status == "failed" for r in runs), "average_duration_ms": round(sum(r.duration_ms for r in runs) / len(runs)) if runs else 0})
    return {"items": items, "total": len(items)}


@router.get("/analytics/workflows")
def workflow_analytics(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    from app.domain_models import Workflow, WorkflowRun
    require_permission(p, "analytics:read")
    items = []
    for workflow in db.scalars(select(Workflow).where(Workflow.department_id.in_(scoped_departments(p, "analytics:read")))):
        runs = db.scalars(select(WorkflowRun).where(WorkflowRun.workflow_id == workflow.id, WorkflowRun.started_by == p.id, WorkflowRun.is_demo.is_(False))).all()
        completed = sum(r.status == "completed" for r in runs)
        items.append({"id": workflow.id, "name": workflow.name, "runs": len(runs), "completed": completed, "failed": sum(r.status == "failed" for r in runs), "success_rate": round(completed / len(runs), 4) if runs else None})
    return {"items": items, "total": len(items)}


@router.get("/analytics/costs")
def costs(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    require_permission(p, "analytics:read")
    rows = list(db.scalars(select(ModelUsage).where(ModelUsage.department_id.in_(scoped_departments(p, "analytics:read")))))
    models = sorted(set(r.model for r in rows))
    items = [{"model": model, "input_tokens": sum(r.input_tokens for r in rows if r.model == model), "output_tokens": sum(r.output_tokens for r in rows if r.model == model), "cost_usd": str(sum((r.cost_usd for r in rows if r.model == model), Decimal(0))), "reserved_usd": str(sum((r.reserved_usd for r in rows if r.model == model), Decimal(0)))} for model in models]
    return {"items": items, "total": len(items), "cost_usd": str(sum((r.cost_usd for r in rows), Decimal(0))), "input_tokens": sum(r.input_tokens for r in rows), "output_tokens": sum(r.output_tokens for r in rows), "method": "Estimates use configured per-million-token rates. Reconcile with provider billing; failed calls retain spend reservations."}


@router.get("/audit-events")
def audit_events(p: Principal = Depends(get_principal), db: Session = Depends(get_db), limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0), action: str = "", department_id: str | None = None):
    require_permission(p, "audit:read")
    q = select(AuditEvent).where(AuditEvent.department_id.in_(scoped_departments(p, "audit:read")))
    if department_id:
        authorize_department(p, department_id, "audit:read")
        q = q.where(AuditEvent.department_id == department_id)
    if action:
        q = q.where(AuditEvent.action.ilike(f"%{action[:80]}%"))
    rows = db.scalars(q.order_by(AuditEvent.created_at.desc()).limit(limit).offset(offset)).all()
    return {"items": [{k: getattr(r, k) for k in ("id", "created_at", "actor_id", "department_id", "action", "resource_type", "resource_id", "result", "request_id")} for r in rows], "total": db.scalar(select(func.count()).select_from(q.subquery())), "limit": limit, "offset": offset}


@router.get("/notifications")
def notifications(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(Notification).where(Notification.user_id == p.id, Notification.department_id.in_(p.department_ids)).order_by(Notification.created_at.desc()).limit(100)))
    return {"items": [{k: getattr(r, k) for k in ("id", "title", "message", "resource_type", "resource_id", "read_at", "created_at")} for r in rows], "total": len(rows), "limit": 100, "offset": 0}


@router.post("/notifications/{notification_id}/read")
def read_notification(notification_id: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    row = db.scalar(select(Notification).where(Notification.id == notification_id, Notification.user_id == p.id, Notification.department_id.in_(p.department_ids)))
    if not row:
        raise HTTPException(404, "Notification not found")
    row.read_at = utcnow()
    db.commit()
    return {"status": "read"}


@router.get("/settings")
def settings(p: Principal = Depends(get_principal)):
    s = get_settings()
    return {"environment": s.app_env, "providers": [{"name": "openai", "configured": bool(s.openai_api_key)}, {"name": "anthropic", "configured": bool(s.anthropic_api_key)}], "default_provider": s.default_llm_provider, "models": {"openai": s.openai_model, "anthropic": s.anthropic_model}, "spending_limits": {"execution_usd": str(s.execution_budget_usd), "daily_per_user_usd": str(s.daily_budget_usd)}, "security": {"authentication": "OIDC authorization code + PKCE", "department_isolation": True, "private_documents": True, "human_approvals": True, "virus_scanning_required": s.require_virus_scan or s.is_production}, "configuration_method": "Providers and global security limits are configured by backend environment/Secrets Manager. Agent model and budget limits are editable on Agents."}


class MemberInput(BaseModel):
    department_id: str
    role: Literal["employee", "manager", "department_admin", "auditor"]


class UserInput(BaseModel):
    subject: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=255)
    name: str = Field(min_length=1, max_length=150)


@router.get("/users")
def users(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    require_permission(p, "members:manage")
    q = select(User)
    if "platform:admin" not in p.permissions:
        q = q.join(Membership).where(Membership.department_id.in_(scoped_departments(p, "members:manage"))).distinct()
    rows = list(db.scalars(q.limit(100)))
    return {"items": [{"id": u.id, "name": u.name, "email": u.email, "active": u.active, "roles": u.roles, "memberships": [{"department_id": m.department_id, "role": m.role} for m in db.scalars(select(Membership).where(Membership.user_id == u.id)) if "platform:admin" in p.permissions or m.department_id in scoped_departments(p, "members:manage")]} for u in rows], "total": len(rows)}


@router.post("/users", status_code=201)
def onboard(body: UserInput, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    require_permission(p, "platform:admin")
    if db.scalar(select(User).where((User.subject == body.subject) | (User.email == body.email))):
        raise HTTPException(409, "Identity is already onboarded")
    row = User(**body.model_dump(), roles=[])
    db.add(row)
    db.flush()
    record(db, p, "user.onboard", "user", row.id)
    db.commit()
    return {"id": row.id, "status": "onboarded"}


@router.put("/users/{user_id}/membership")
def membership(user_id: str, body: MemberInput, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    require_permission(p, "members:manage")
    if "platform:admin" not in p.permissions:
        authorize_department(p, body.department_id, "members:manage")
        if body.role == "department_admin":
            raise HTTPException(403, "Only a platform administrator can appoint department administrators")
    if not db.get(User, user_id) or not db.get(Department, body.department_id):
        raise HTTPException(404, "User or department not found")
    row = db.get(Membership, (user_id, body.department_id))
    if row:
        row.role = body.role
    else:
        db.add(Membership(user_id=user_id, department_id=body.department_id, role=body.role))
    record(db, p, "membership.assign", "user", user_id, body.department_id)
    db.commit()
    return {"status": "assigned"}


@router.delete("/users/{user_id}/membership/{department_id}")
def remove_membership(user_id: str, department_id: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    require_permission(p, "members:manage")
    if "platform:admin" not in p.permissions:
        authorize_department(p, department_id, "members:manage")
    db.execute(delete(Membership).where(Membership.user_id == user_id, Membership.department_id == department_id))
    record(db, p, "membership.remove", "user", user_id, department_id)
    db.commit()
    return {"status": "removed"}


class ActiveInput(BaseModel):
    active: bool


@router.patch("/users/{user_id}")
def deactivate(user_id: str, body: ActiveInput, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    require_permission(p, "platform:admin")
    if user_id == p.id and not body.active:
        raise HTTPException(409, "Administrators cannot deactivate their own session")
    row = db.get(User, user_id)
    if not row:
        raise HTTPException(404, "User not found")
    row.active = body.active
    if not body.active:
        db.execute(delete(SessionRecord).where(SessionRecord.user_id == user_id))
    record(db, p, "user.activate" if body.active else "user.deactivate", "user", user_id)
    db.commit()
    return {"id": row.id, "active": row.active, "sessions_revoked": not row.active}


@router.get("/roles")
def roles(p: Principal = Depends(get_principal)):
    require_permission(p, "members:manage")
    return {"items": [{"name": role, "permissions": sorted(permissions)} for role, permissions in ROLE_PERMISSIONS.items()]}
