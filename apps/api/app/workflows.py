"""A bounded DAG interpreter with SQL checkpoints and transactional approvals.

Only allowlisted, typed nodes execute. A checkpoint and its side effects commit
together. A lease prevents concurrent resumes; interrupted runs can be resumed
after lease expiry without repeating completed nodes or approval decisions.
"""

import asyncio
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import record
from app.auth import Principal, authorize_department, get_principal, principal_for_user
from app.db import get_db, set_scope
from app.domain_models import (
    ApprovalDecision,
    ApprovalRequest,
    Invoice,
    LegalReview,
    OnboardingCase,
    Workflow,
    WorkflowRun,
    WorkflowStep,
    WorkflowVersion,
    uid,
    utcnow,
)
from app.domain_schemas import (
    DecisionInput,
    WorkflowCreate,
    WorkflowDefinition,
    WorkflowStart,
    WorkflowUpdate,
)
from app.models import Job, Membership, Notification, User

router = APIRouter(tags=["Workflows and approvals"])


def row_dict(row, exclude=()):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns
            if column.name not in exclude}


def check_documents(db, principal, document_ids):
    from app.documents import get_document

    for document_id in document_ids or []:
        get_document(db, principal, document_id)


def visible_page(db, principal, model, permission, department_id=None, limit=50, offset=0,
                 document_getter=None):
    departments = principal.department_ids
    if department_id:
        authorize_department(principal, department_id, permission)
        departments = [department_id]
    # Department permission is checked for each record: permissions may differ by membership.
    rows = db.scalars(select(model).where(model.department_id.in_(departments))
                      .order_by(model.created_at.desc())).all()
    visible = []
    for item in rows:
        try:
            authorize_department(principal, item.department_id, permission)
            if document_getter:
                check_documents(db, principal, document_getter(item))
        except HTTPException as exc:
            if exc.status_code in {403, 404}:
                continue
            raise
        visible.append(item)
    return visible[offset:offset + limit], len(visible)


def workflow_documents(workflow):
    return [node["config"]["document_id"] for node in workflow.definition["nodes"]
            if node["type"] == "document_input" and node.get("config", {}).get("document_id")]


def get_workflow(db, principal, workflow_id, permission="workflows:read"):
    query = select(Workflow).where(Workflow.id == workflow_id)
    if permission == "workflows:manage":
        query = query.with_for_update().execution_options(populate_existing=True)
    workflow = db.scalar(query)
    if not workflow:
        raise HTTPException(404, "Workflow not found")
    authorize_department(principal, workflow.department_id, permission)
    check_documents(db, principal, workflow_documents(workflow))
    return workflow


def get_run(db, principal, run_id, permission="workflows:read"):
    run = db.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(404, "Workflow run not found")
    authorize_department(principal, run.department_id, permission)
    check_documents(db, principal, run.document_ids)
    return run


def run_dict(db, run, detail=True):
    result = row_dict(run, exclude=("claim_token", "lease_until"))
    if detail:
        result["output"] = result["state"]
        result["steps"] = [row_dict(step) for step in db.scalars(
            select(WorkflowStep).where(WorkflowStep.run_id == run.id)
            .order_by(WorkflowStep.started_at))]
    else:
        result.pop("input", None)
        result.pop("state", None)
    return result


def validate_assignee(db, department_id, user_id):
    if not user_id:
        return
    membership = db.get(Membership, (user_id, department_id))
    user = db.get(User, user_id)
    if not membership or not user or not user.active:
        raise HTTPException(422, "Assignee must be an active member of this department")


def create_approval(db, principal, department_id, resource_type, resource_id, title,
                    payload=None, document_ids=None, checkpoint="review",
                    expires_hours=48, assigned_to=None):
    existing = db.scalar(select(ApprovalRequest).where(
        ApprovalRequest.resource_type == resource_type,
        ApprovalRequest.resource_id == resource_id,
        ApprovalRequest.checkpoint == checkpoint))
    if existing:
        return existing
    validate_assignee(db, department_id, assigned_to)
    approval = ApprovalRequest(
        department_id=department_id, resource_type=resource_type, resource_id=resource_id,
        title=title, requested_by=principal.id, assigned_to=assigned_to,
        payload=payload or {}, document_ids=document_ids or [], checkpoint=checkpoint,
        expires_at=utcnow() + timedelta(hours=expires_hours),
    )
    db.add(approval)
    db.flush()
    from app.auth import principal_for_user

    candidates = [assigned_to] if assigned_to else list(db.scalars(
        select(User.id).join(Membership, Membership.user_id == User.id).where(
            Membership.department_id == department_id, User.active.is_(True))))
    try:
        for candidate_id in candidates:
            try:
                reviewer = principal_for_user(db, candidate_id)
                authorize_department(reviewer, department_id, "approvals:decide")
                check_documents(db, reviewer, document_ids or [])
            except HTTPException:
                if assigned_to:
                    raise HTTPException(422, "Assigned reviewer must have approval permission and source access") from None
                continue
            # Notifications are delivered only to authorized recipients. Their text
            # never includes source content or confidential metadata.
            db.add(Notification(department_id=department_id, user_id=candidate_id,
                                title="Approval requested", message="An authorized review is required.",
                                resource_type="approval", resource_id=approval.id))
    finally:
        set_scope(db, principal.id, principal.department_ids)
    record(db, principal, "approval.requested", "approval", approval.id, department_id)
    return approval


@router.get("/workflows")
def list_workflows(department_id: str | None = None, limit: int = Query(50, ge=1, le=100),
                   offset: int = Query(0, ge=0), db: Session = Depends(get_db),
                   principal: Principal = Depends(get_principal)):
    rows, total = visible_page(db, principal, Workflow, "workflows:read", department_id,
                               limit, offset, workflow_documents)
    return {"items": [row_dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.post("/workflows", status_code=201)
def create_workflow(body: WorkflowCreate, db: Session = Depends(get_db),
                    principal: Principal = Depends(get_principal)):
    authorize_department(principal, body.department_id, "workflows:manage")
    workflow = Workflow(department_id=body.department_id, name=body.name,
                        description=body.description, definition=body.definition.model_dump(),
                        created_by=principal.id)
    check_documents(db, principal, workflow_documents(workflow))
    db.add(workflow)
    db.flush()
    record(db, principal, "workflow.created", "workflow", workflow.id, workflow.department_id)
    db.commit()
    return row_dict(workflow)


@router.get("/workflows/{workflow_id}")
def read_workflow(workflow_id: str, db: Session = Depends(get_db),
                  principal: Principal = Depends(get_principal)):
    workflow = get_workflow(db, principal, workflow_id)
    result = row_dict(workflow)
    result["versions"] = [row_dict(version) for version in db.scalars(
        select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow.id)
        .order_by(WorkflowVersion.version.desc()))]
    # Older versions can reference documents that are no longer in the draft.
    for version in result["versions"]:
        ids = [node["config"]["document_id"] for node in version["definition"]["nodes"]
               if node["type"] == "document_input" and node.get("config", {}).get("document_id")]
        check_documents(db, principal, ids)
    return result


@router.patch("/workflows/{workflow_id}")
def edit_workflow(workflow_id: str, body: WorkflowUpdate, db: Session = Depends(get_db),
                  principal: Principal = Depends(get_principal)):
    workflow = get_workflow(db, principal, workflow_id, "workflows:manage")
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(workflow, key, value)
    check_documents(db, principal, workflow_documents(workflow))
    workflow.status = "draft"
    record(db, principal, "workflow.updated", "workflow", workflow.id, workflow.department_id)
    db.commit()
    return row_dict(workflow)


@router.post("/workflows/{workflow_id}/publish")
def publish_workflow(workflow_id: str, db: Session = Depends(get_db),
                     principal: Principal = Depends(get_principal)):
    workflow = get_workflow(db, principal, workflow_id, "workflows:manage")
    WorkflowDefinition.model_validate(workflow.definition)
    workflow.published_version += 1
    workflow.status = "published"
    db.add(WorkflowVersion(workflow_id=workflow.id, version=workflow.published_version,
                           definition=workflow.definition))
    record(db, principal, "workflow.published", "workflow", workflow.id, workflow.department_id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Workflow was published concurrently; reload and retry") from None
    return row_dict(workflow)


def condition_matches(config, state):
    value = state
    for part in config["field"].split("."):
        value = value.get(part) if isinstance(value, dict) else None
    operator, expected = config["operator"], config.get("value")
    if operator == "exists":
        return value is not None
    if operator == "eq":
        return value == expected
    if operator == "ne":
        return value != expected
    try:
        left, right = Decimal(str(value)), Decimal(str(expected))
        if not left.is_finite() or not right.is_finite():
            return False
        return {"gt": left > right, "gte": left >= right, "lt": left < right}[operator]
    except (InvalidOperation, ValueError, KeyError):
        return False


async def execute_node(db, principal, run, node, state):
    """Returns (state changes, branch, pause). Nodes have no arbitrary I/O escape hatch."""
    kind, config = node["type"], node.get("config", {})
    authorize_department(principal, run.department_id, "workflows:run")
    if kind in {"start", "end"}:
        return {}, None, False
    if kind == "transform":
        return config["assign"], None, False
    if kind == "condition":
        return {}, "true" if condition_matches(config, state) else "false", False
    if kind == "document_input":
        from app.documents import get_document

        document_id = config.get("document_id") or state.get(config.get("input_field", "document_id"))
        if not isinstance(document_id, str):
            raise HTTPException(422, "Document input requires a document ID")
        document = get_document(db, principal, document_id)
        if document.department_id != run.department_id:
            raise HTTPException(403, "Workflow documents must belong to the workflow department")
        run.document_ids = list(dict.fromkeys([*run.document_ids, document.id]))
        return {"document_id": document.id}, None, False
    if kind == "text_extraction":
        from app.documents import get_document

        document = get_document(db, principal, state.get("document_id", ""))
        if document.department_id != run.department_id or document.id not in run.document_ids:
            raise HTTPException(403, "Use a document input node before text extraction")
        if document.status != "ready":
            raise HTTPException(409, "Document ingestion must finish before workflow extraction")
        return {"text": document.extracted_text[:60000]}, None, False
    if kind == "classification":
        text = str(state.get("text", "")).casefold()
        matches = [label for label, words in config["categories"].items()
                   if any(word.casefold() in text for word in words)]
        return {"classification": matches[0] if len(matches) == 1 else config["fallback"],
                "classification_matches": matches}, None, False
    if kind == "rag_search":
        from app.rag import search

        query = config.get("query") or state.get(config.get("input_field", "query"))
        if not isinstance(query, str) or not query.strip():
            raise HTTPException(422, "RAG search requires a query")
        citations = await search(db, principal, query, run.department_id, limit=config.get("limit", 5))
        ids = [item["document_id"] for item in citations]
        run.document_ids = list(dict.fromkeys([*run.document_ids, *ids]))
        return {"citations": citations}, None, False
    if kind == "llm_extraction":
        from app.business import extract_structured
        from app.domain_schemas import InvoiceData, LegalAnalysis

        if not state.get("text") or not run.document_ids:
            raise HTTPException(422, "LLM extraction requires an authorized extracted document")
        schema = InvoiceData if config["schema"] == "invoice" else LegalAnalysis
        result = await extract_structured(
            db, principal, run.department_id, run.document_ids, schema,
            config["provider"], config.get("model"),
        )
        return {"extracted": result, **({"total": result["total"]} if "total" in result else {})}, None, False
    if kind == "validation":
        if config["schema"] == "invoice":
            from app.business import validate_invoice
            from app.domain_schemas import InvoiceData

            data = InvoiceData.model_validate(state.get("extracted", {}))
            errors = validate_invoice(data)
        else:
            errors = [f"Missing required field: {field}" for field in config["fields"]
                      if state.get(field) in (None, "", [])]
        return {"validation_errors": errors, "valid": not errors}, None, False
    if kind == "notification":
        db.add(Notification(department_id=run.department_id, user_id=run.started_by,
                            title=config["title"], message=config["message"],
                            resource_type="workflow_run", resource_id=run.id))
        return {"notification_created": True}, None, False
    if kind == "approval":
        approval = create_approval(
            db, principal, run.department_id, "workflow_run", run.id, config["title"],
            payload={"node_id": node["id"], "workflow_id": run.workflow_id},
            document_ids=run.document_ids, checkpoint=node["id"],
            assigned_to=config.get("assigned_to"), expires_hours=config["expires_hours"],
        )
        if approval.status == "approved":
            return {"approval_id": approval.id, "approval_status": "approved"}, None, False
        if approval.status != "pending":
            raise HTTPException(409, "Workflow approval was rejected or expired")
        return {"approval_id": approval.id}, None, True
    raise HTTPException(422, "Unsupported node type")


class LeaseLost(Exception):
    """A newer worker owns this run; this process must discard its pending writes."""


def owns_claim(db, run_id, token):
    # Suppress autoflush: pending node output must not be written before fencing.
    # PostgreSQL holds this row lock until the checkpoint transaction commits.
    with db.no_autoflush:
        current = db.scalar(select(WorkflowRun.claim_token).where(WorkflowRun.id == run_id).with_for_update())
    return current == token


async def resume_workflow(db, principal, run_id):
    run = get_run(db, principal, run_id, "workflows:run")
    if run.status in {"completed", "rejected", "expired", "cancelled"}:
        return run
    token, now = uid(), utcnow()
    claimed = db.execute(update(WorkflowRun).where(
        WorkflowRun.id == run.id,
        or_(WorkflowRun.claim_token.is_(None), WorkflowRun.lease_until < now),
    ).values(claim_token=token, lease_until=now + timedelta(minutes=5), status="running")
        .execution_options(synchronize_session="fetch"))
    db.commit()
    if not claimed.rowcount:
        raise HTTPException(409, "Workflow is already running; its lease must expire before recovery")
    db.refresh(run)
    lease_lost = False
    try:
        version = db.scalar(select(WorkflowVersion).where(
            WorkflowVersion.workflow_id == run.workflow_id,
            WorkflowVersion.version == run.workflow_version))
        if version is None:
            raise HTTPException(409, "Published workflow version is unavailable")
        definition = WorkflowDefinition.model_validate(version.definition).model_dump()
        nodes = {node["id"]: node for node in definition["nodes"]}
        for _ in range(64):
            principal = principal_for_user(db, principal.id)
            authorize_department(principal, run.department_id, "workflows:run")
            check_documents(db, principal, run.document_ids)
            if not owns_claim(db, run.id, token):
                raise LeaseLost()
            node = nodes[run.next_node_id]
            step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.run_id == run.id, WorkflowStep.node_id == node["id"]))
            if step is None:
                step = WorkflowStep(run_id=run.id, node_id=node["id"], node_type=node["type"])
                db.add(step)
                db.flush()
            if step.attempts >= 3:
                raise HTTPException(409, "Node retry budget exhausted")
            step.attempts += 1
            step.status = "running"
            db.commit()
            async with asyncio.timeout(120):
                changes, branch, pause = await execute_node(db, principal, run, node, dict(run.state))
            if not owns_claim(db, run.id, token):
                raise LeaseLost()
            # Remote nodes can outlive a membership change or source-share
            # revocation. Validate again before publishing their checkpoint.
            principal = principal_for_user(db, principal.id)
            authorize_department(principal, run.department_id, "workflows:run")
            check_documents(db, principal, run.document_ids)
            run.state = {**run.state, **changes}
            step.output = {"changed_fields": sorted(changes), "branch": branch}
            step.status = "waiting_approval" if pause else "completed"
            if pause:
                step.attempts -= 1  # Waiting for a human is not a failed execution attempt.
                run.status = "waiting_approval"
                break
            step.completed_at = utcnow()
            targets = [edge["target"] for edge in definition["edges"]
                       if edge["source"] == node["id"] and edge.get("branch") == branch]
            run.next_node_id = targets[0] if targets else None
            run.error = None
            if run.next_node_id is None:
                run.status, run.completed_at = "completed", utcnow()
                db.add(Notification(department_id=run.department_id, user_id=run.started_by,
                                    title="Workflow completed", resource_type="workflow_run",
                                    resource_id=run.id))
            run.lease_until = utcnow() + timedelta(minutes=5)
            record(db, principal, "workflow.step_completed", "workflow_run", run.id, run.department_id)
            db.commit()
            if run.status == "completed":
                break
        else:
            raise HTTPException(409, "Workflow step budget exhausted")
    except LeaseLost:
        db.rollback()
        db.refresh(run)
        lease_lost = True
    except Exception as exc:
        db.rollback()
        db.refresh(run)
        if not owns_claim(db, run.id, token):
            lease_lost = True
        else:
            run.status = "failed"
            # Only classification is persisted; sensitive payloads never enter errors.
            run.error = getattr(exc, "code", None) or (
                f"node_http_{exc.status_code}" if isinstance(exc, HTTPException) else "node_execution_failed")
            record(db, principal, "workflow.failed", "workflow_run", run.id, run.department_id, result="failure")
            db.add(Notification(department_id=run.department_id, user_id=run.started_by,
                                title="Workflow requires attention", resource_type="workflow_run", resource_id=run.id))
    finally:
        if lease_lost:
            db.rollback()
        else:
            db.execute(update(WorkflowRun).where(WorkflowRun.id == run.id, WorkflowRun.claim_token == token)
                       .values(claim_token=None, lease_until=None).execution_options(synchronize_session="fetch"))
            db.commit()
    return run


async def continue_workflow(db, principal, run):
    """Queue graphs with remote I/O; execute small deterministic graphs immediately.

    The committed Job is the durable outbox. A broker outage leaves it available
    to the worker recovery sweep. Each approval checkpoint has a distinct job key.
    """
    if run.status in {"completed", "rejected", "expired", "cancelled"}:
        return run
    version = db.scalar(select(WorkflowVersion).where(
        WorkflowVersion.workflow_id == run.workflow_id,
        WorkflowVersion.version == run.workflow_version))
    if version is None:
        raise HTTPException(409, "Published workflow version is unavailable")
    if not any(node["type"] in {"llm_extraction", "rag_search"} for node in version.definition["nodes"]):
        return await resume_workflow(db, principal, run.id)
    approval = db.scalar(select(ApprovalRequest).where(
        ApprovalRequest.resource_type == "workflow_run", ApprovalRequest.resource_id == run.id,
        ApprovalRequest.checkpoint == run.next_node_id))
    if approval and approval.status == "pending":
        return run
    checkpoint = f"{run.next_node_id}:{approval.status if approval else 'start'}"
    key = f"workflow:{run.id}:{sha256(checkpoint.encode()).hexdigest()[:24]}"
    job = db.scalar(select(Job).where(Job.idempotency_key == key))
    if job is None:
        job = Job(kind="workflow", department_id=run.department_id, user_id=run.started_by,
                  resource_id=run.id, idempotency_key=key)
        db.add(job)
        run.status = "queued"
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            db.refresh(run)
            return run
        from app.worker import dispatch_job

        dispatch_job(job.id)
    return run


@router.post("/workflows/{workflow_id}/run", status_code=201)
async def start_workflow(workflow_id: str, body: WorkflowStart, db: Session = Depends(get_db),
                         principal: Principal = Depends(get_principal)):
    workflow = get_workflow(db, principal, workflow_id, "workflows:run")
    if not workflow.published_version:
        raise HTTPException(409, "Publish a workflow before running it")
    version = db.scalar(select(WorkflowVersion).where(
        WorkflowVersion.workflow_id == workflow.id,
        WorkflowVersion.version == workflow.published_version))
    if version is None:
        raise HTTPException(409, "Published workflow version is unavailable")
    definition = WorkflowDefinition.model_validate(version.definition)
    document_ids = [node.config["document_id"] for node in definition.nodes
                    if node.type == "document_input" and node.config.get("document_id")]
    check_documents(db, principal, document_ids)
    key = body.idempotency_key or uid()
    existing = db.scalar(select(WorkflowRun).where(WorkflowRun.workflow_id == workflow_id,
                         WorkflowRun.started_by == principal.id, WorkflowRun.idempotency_key == key))
    if existing:
        check_documents(db, principal, existing.document_ids)
        if existing.input != body.input:
            raise HTTPException(409, "Idempotency key already used for different input")
        return run_dict(db, existing)
    run = WorkflowRun(department_id=workflow.department_id, workflow_id=workflow.id,
                      workflow_version=workflow.published_version, started_by=principal.id,
                      idempotency_key=key, input=body.input, state=body.input,
                      document_ids=document_ids,
                      next_node_id=next(node.id for node in definition.nodes if node.type == "start"))
    db.add(run)
    try:
        db.flush()
        record(db, principal, "workflow.started", "workflow_run", run.id, run.department_id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Duplicate workflow submission; retry with the same idempotency key") from None
    await continue_workflow(db, principal, run)
    return run_dict(db, run)


@router.get("/workflow-runs")
def list_runs(department_id: str | None = None, limit: int = Query(50, ge=1, le=100),
              offset: int = Query(0, ge=0), db: Session = Depends(get_db),
              principal: Principal = Depends(get_principal)):
    rows, total = visible_page(db, principal, WorkflowRun, "workflows:read", department_id,
                               limit, offset, lambda row: row.document_ids)
    return {"items": [run_dict(db, row, False) for row in rows], "total": total,
            "limit": limit, "offset": offset}


@router.get("/workflow-runs/{run_id}")
def read_run(run_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    return run_dict(db, get_run(db, principal, run_id))


@router.post("/workflow-runs/{run_id}/resume")
async def recover_run(run_id: str, db: Session = Depends(get_db),
                      principal: Principal = Depends(get_principal)):
    run = get_run(db, principal, run_id, "workflows:run")
    if run.started_by != principal.id:
        raise HTTPException(403, "Only the workflow initiator can request recovery")
    from app.auth import principal_for_user

    try:
        initiator = principal_for_user(db, run.started_by)
        authorize_department(initiator, run.department_id, "workflows:run")
        check_documents(db, initiator, run.document_ids)
        await continue_workflow(db, initiator, run)
    finally:
        set_scope(db, principal.id, principal.department_ids)
    # A resumed node can introduce additional private source references.
    check_documents(db, principal, run.document_ids)
    return run_dict(db, run)


def apply_approval_result(db, approval, status):
    if approval.resource_type == "invoice":
        item = db.get(Invoice, approval.resource_id)
        item.approval_status = status
    elif approval.resource_type == "onboarding":
        item = db.get(OnboardingCase, approval.resource_id)
        item.status = "completed" if status == "approved" else status
        if status == "approved":
            item.completed_at = utcnow()
    elif approval.resource_type == "legal_review":
        item = db.get(LegalReview, approval.resource_id)
        item.status = "reviewed" if status == "approved" else status
    elif approval.resource_type == "workflow_run" and status in {"rejected", "expired"}:
        item = db.get(WorkflowRun, approval.resource_id)
        item.status, item.completed_at = status, utcnow()


def expire_approvals(db):
    now = utcnow()
    pending = db.scalars(select(ApprovalRequest).where(
        ApprovalRequest.status == "pending", ApprovalRequest.expires_at <= now)).all()
    for approval in pending:
        changed = db.execute(update(ApprovalRequest).where(
            ApprovalRequest.id == approval.id, ApprovalRequest.status == "pending"
        ).values(status="expired", decided_at=now).execution_options(synchronize_session="fetch"))
        if changed.rowcount:
            apply_approval_result(db, approval, "expired")
            record(db, None, "approval.expired", "approval", approval.id, approval.department_id)
    db.commit()
    return len(pending)


def get_approval(db, principal, approval_id, permission="approvals:read"):
    approval = db.get(ApprovalRequest, approval_id)
    if not approval:
        raise HTTPException(404, "Approval not found")
    authorize_department(principal, approval.department_id, permission)
    check_documents(db, principal, approval.document_ids)
    return approval


def approval_dict(db, approval):
    result = row_dict(approval)
    result["decisions"] = [row_dict(decision) for decision in db.scalars(
        select(ApprovalDecision).where(ApprovalDecision.approval_id == approval.id))]
    return result


@router.get("/approvals")
def list_approvals(department_id: str | None = None, limit: int = Query(50, ge=1, le=100),
                   offset: int = Query(0, ge=0), db: Session = Depends(get_db),
                   principal: Principal = Depends(get_principal)):
    expire_approvals(db)
    rows, total = visible_page(db, principal, ApprovalRequest, "approvals:read", department_id,
                               limit, offset, lambda row: row.document_ids)
    return {"items": [approval_dict(db, row) for row in rows], "total": total,
            "limit": limit, "offset": offset}


@router.get("/approvals/{approval_id}")
def read_approval(approval_id: str, db: Session = Depends(get_db),
                   principal: Principal = Depends(get_principal)):
    approval = get_approval(db, principal, approval_id)
    expire_approvals(db)
    db.refresh(approval)
    return approval_dict(db, approval)


async def decide_approval(db, principal, approval_id, decision, comment):
    approval = get_approval(db, principal, approval_id, "approvals:decide")
    if approval.assigned_to and approval.assigned_to != principal.id:
        raise HTTPException(403, "This approval is assigned to another reviewer")
    expire_approvals(db)
    db.refresh(approval)
    if approval.status == "expired":
        raise HTTPException(409, "Approval has expired")
    if approval.status != "pending" and approval.status != decision:
        raise HTTPException(409, "Approval already has a different decision")
    initiator = None
    if decision == "approved" and approval.resource_type == "workflow_run":
        from app.auth import principal_for_user

        run = db.get(WorkflowRun, approval.resource_id)
        try:
            initiator = principal_for_user(db, run.started_by)
            authorize_department(initiator, run.department_id, "workflows:run")
            check_documents(db, initiator, run.document_ids)
        finally:
            set_scope(db, principal.id, principal.department_ids)
    if approval.status == "pending":
        now = utcnow()
        changed = db.execute(update(ApprovalRequest).where(
            ApprovalRequest.id == approval.id, ApprovalRequest.status == "pending",
            ApprovalRequest.expires_at > now,
        ).values(status=decision, decided_at=now).execution_options(synchronize_session="fetch"))
        if not changed.rowcount:
            db.rollback()
            raise HTTPException(409, "Approval changed concurrently; reload before retrying")
        db.add(ApprovalDecision(approval_id=approval.id, decided_by=principal.id,
                                decision=decision, comment=comment))
        apply_approval_result(db, approval, decision)
        record(db, principal, f"approval.{decision}", "approval", approval.id, approval.department_id)
        db.commit()
        db.refresh(approval)
    # Repeated identical decisions can recover an interrupted continuation, but cannot
    # create another decision or repeat completed steps.
    if initiator is not None:
        try:
            set_scope(db, initiator.id, initiator.department_ids)
            await continue_workflow(db, initiator, db.get(WorkflowRun, approval.resource_id))
        finally:
            set_scope(db, principal.id, principal.department_ids)
    check_documents(db, principal, approval.document_ids)
    return approval_dict(db, approval)


@router.post("/approvals/{approval_id}/approve")
async def approve(approval_id: str, body: DecisionInput, db: Session = Depends(get_db),
                  principal: Principal = Depends(get_principal)):
    return await decide_approval(db, principal, approval_id, "approved", body.comment)


@router.post("/approvals/{approval_id}/reject")
async def reject(approval_id: str, body: DecisionInput, db: Session = Depends(get_db),
                 principal: Principal = Depends(get_principal)):
    return await decide_approval(db, principal, approval_id, "rejected", body.comment)
