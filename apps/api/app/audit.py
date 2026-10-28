from contextvars import ContextVar

from app.models import AuditEvent

request_id: ContextVar[str] = ContextVar("request_id", default="")


def record(db, principal, action, resource_type, resource_id=None, department_id=None, result="success"):
    event = AuditEvent(actor_id=principal.id if principal else None, department_id=department_id, action=action, resource_type=resource_type, resource_id=resource_id, result=result, request_id=request_id.get())
    db.add(event)
    return event
