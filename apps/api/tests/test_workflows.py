import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from test_business import add_document, invoice_payload
from test_business import domain_env as _domain_fixture

from app.auth import principal_for_user
from app.domain_models import ApprovalDecision, ApprovalRequest, WorkflowRun, WorkflowStep, utcnow
from app.domain_schemas import InvoiceData, WorkflowDefinition
from app.models import DocumentPermission, Job, Membership, Notification, User
from app.workflows import condition_matches, resume_workflow


@pytest.fixture
def domain_env(monkeypatch, tmp_path):
    yield from _domain_fixture.__wrapped__(monkeypatch, tmp_path)


def definition(approval=True):
    nodes = [{"id": "start", "type": "start"}, {"id": "end", "type": "end"}]
    edges = [{"source": "start", "target": "end"}]
    if approval:
        nodes.insert(1, {"id": "review", "type": "approval", "config": {"title": "Review", "expires_hours": 24}})
        edges = [{"source": "start", "target": "review"}, {"source": "review", "target": "end"}]
    return {"nodes": nodes, "edges": edges}


def create_and_publish(env, graph=None):
    env.identity["current"] = "fin_manager"
    response = env.client.post("/api/v1/workflows", json={"department_id": "finance", "name": "Synthetic review", "definition": graph or definition()})
    assert response.status_code == 201, response.text
    workflow = response.json()
    assert env.client.post(f"/api/v1/workflows/{workflow['id']}/publish").status_code == 200
    return workflow


def test_workflow_dag_rejects_unsafe_types_cycles_and_orphans():
    graph = definition()
    graph["nodes"][1]["type"] = "http_request"
    with pytest.raises(ValidationError, match="Unsupported"):
        WorkflowDefinition.model_validate(graph)
    graph = definition()
    graph["edges"][1]["target"] = "review"
    with pytest.raises(ValidationError, match="cycles"):
        WorkflowDefinition.model_validate(graph)
    graph = definition(False)
    graph["nodes"].append({"id": "orphan", "type": "end"})
    with pytest.raises(ValidationError, match="reachable"):
        WorkflowDefinition.model_validate(graph)


def test_condition_edges_and_decimal_thresholds():
    assert condition_matches({"field": "invoice.total", "operator": "gt", "value": "1000"}, {"invoice": {"total": "1000.01"}})
    assert not condition_matches({"field": "invoice.total", "operator": "gt", "value": "1000"}, {"invoice": {"total": "NaN"}})
    graph = definition()
    graph["nodes"][1] = {"id": "review", "type": "condition", "config": {"field": "total", "operator": "gt", "value": "1000"}}
    with pytest.raises(ValidationError, match="true and false"):
        WorkflowDefinition.model_validate(graph)


def test_workflow_pauses_resumes_after_restart_and_duplicate_approval_is_idempotent(domain_env):
    env = domain_env
    workflow = create_and_publish(env)
    env.identity["current"] = "fin_employee"
    response = env.client.post(f"/api/v1/workflows/{workflow['id']}/run", json={"input": {"amount": "1200"}, "idempotency_key": "test-run"})
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["status"] == "waiting_approval"
    assert [step["status"] for step in run["steps"]] == ["completed", "waiting_approval"]
    approval_id = env.client.get("/api/v1/approvals").json()["items"][0]["id"]
    env.db.expunge_all()  # Simulates a fresh process/session loading only persisted checkpoints.
    env.identity["current"] = "fin_manager"
    first = env.client.post(f"/api/v1/approvals/{approval_id}/approve", json={"comment": "Reviewed"})
    assert first.status_code == 200, first.text
    assert env.client.get(f"/api/v1/workflow-runs/{run['id']}").json()["status"] == "completed"
    second = env.client.post(f"/api/v1/approvals/{approval_id}/approve", json={"comment": "Duplicate retry"})
    assert second.status_code == 200
    assert len(env.db.scalars(select(ApprovalDecision)).all()) == 1
    assert len(env.db.scalars(select(WorkflowStep)).all()) == 3
    assert len(env.db.scalars(select(Notification).where(Notification.title == "Workflow completed")).all()) == 1
    assert env.client.post(f"/api/v1/approvals/{approval_id}/reject", json={}).status_code == 409


def test_workflow_run_idempotency_and_definition_versions(domain_env):
    env = domain_env
    workflow = create_and_publish(env, definition(False))
    body = {"input": {"value": 1}, "idempotency_key": "same-key"}
    first = env.client.post(f"/api/v1/workflows/{workflow['id']}/run", json=body).json()
    second = env.client.post(f"/api/v1/workflows/{workflow['id']}/run", json=body).json()
    assert first["id"] == second["id"]
    body["input"]["value"] = 2
    assert env.client.post(f"/api/v1/workflows/{workflow['id']}/run", json=body).status_code == 409
    env.client.patch(f"/api/v1/workflows/{workflow['id']}", json={"definition": definition()})
    published = env.client.post(f"/api/v1/workflows/{workflow['id']}/publish").json()
    assert published["published_version"] == 2
    assert env.client.get(f"/api/v1/workflow-runs/{first['id']}").json()["workflow_version"] == 1


def test_approval_expiry_rejection_and_revoked_initiator_authorization(domain_env):
    env = domain_env
    workflow = create_and_publish(env)
    env.identity["current"] = "fin_employee"
    run = env.client.post(f"/api/v1/workflows/{workflow['id']}/run", json={}).json()
    approval = env.db.scalar(select(ApprovalRequest))
    approval.expires_at = utcnow() - timedelta(minutes=1)
    env.db.commit()
    env.identity["current"] = "fin_manager"
    result = env.client.post(f"/api/v1/approvals/{approval.id}/approve", json={})
    assert result.status_code == 409
    assert env.client.get(f"/api/v1/workflow-runs/{run['id']}").json()["status"] == "expired"
    env.identity["current"] = "fin_employee"
    second = env.client.post(f"/api/v1/workflows/{workflow['id']}/run", json={}).json()
    pending = env.db.scalar(select(ApprovalRequest).where(ApprovalRequest.resource_id == second["id"]))
    env.db.delete(env.db.get(Membership, ("fin_employee", "finance")))
    env.db.commit()
    env.identity["current"] = "fin_manager"
    assert env.client.post(f"/api/v1/approvals/{pending.id}/approve", json={}).status_code == 403
    env.db.refresh(pending)
    assert pending.status == "pending"


def test_workflow_authorization_and_private_source_isolation(domain_env):
    env = domain_env
    document = add_document(env, "finance", "fin_manager", "private", "Secret synthetic invoice.")
    graph = {"nodes": [{"id": "start", "type": "start"},
                       {"id": "document", "type": "document_input", "config": {"document_id": document.id}},
                       {"id": "extract", "type": "text_extraction"},
                       {"id": "review", "type": "approval"}, {"id": "end", "type": "end"}],
             "edges": [{"source": "start", "target": "document"}, {"source": "document", "target": "extract"},
                       {"source": "extract", "target": "review"}, {"source": "review", "target": "end"}]}
    workflow = create_and_publish(env, graph)
    run = env.client.post(f"/api/v1/workflows/{workflow['id']}/run", json={}).json()
    assert run["state"]["text"] == "Secret synthetic invoice."
    env.identity["current"] = "fin_employee"
    assert env.client.get("/api/v1/workflows").json()["total"] == 0
    assert env.client.get("/api/v1/workflow-runs").json()["total"] == 0
    assert env.client.get(f"/api/v1/workflow-runs/{run['id']}").status_code == 404
    env.identity["current"] = "hr_employee"
    assert env.client.post(f"/api/v1/workflows/{workflow['id']}/run", json={}).status_code == 403


def test_workflow_conditional_branch_executes_only_selected_path(domain_env):
    env = domain_env
    graph = {"nodes": [{"id": "start", "type": "start"},
                       {"id": "condition", "type": "condition", "config": {"field": "amount", "operator": "gt", "value": 1000}},
                       {"id": "review", "type": "approval"}, {"id": "end", "type": "end"}],
             "edges": [{"source": "start", "target": "condition"},
                       {"source": "condition", "target": "review", "branch": "true"},
                       {"source": "condition", "target": "end", "branch": "false"},
                       {"source": "review", "target": "end"}]}
    workflow = create_and_publish(env, graph)
    small = env.client.post(f"/api/v1/workflows/{workflow['id']}/run", json={"input": {"amount": "999"}}).json()
    large = env.client.post(f"/api/v1/workflows/{workflow['id']}/run", json={"input": {"amount": "1001"}}).json()
    assert small["status"] == "completed"
    assert large["status"] == "waiting_approval"
    assert len(env.db.scalars(select(ApprovalRequest)).all()) == 1


def test_active_run_lease_prevents_duplicate_execution(domain_env):
    env = domain_env
    workflow = create_and_publish(env)
    run = env.client.post(f"/api/v1/workflows/{workflow['id']}/run", json={}).json()
    stored = env.db.get(WorkflowRun, run["id"])
    stored.claim_token, stored.lease_until = "other-process", utcnow() + timedelta(minutes=3)
    env.db.commit()
    assert env.client.post(f"/api/v1/workflow-runs/{run['id']}/resume").status_code == 409


def test_recovery_cannot_return_new_private_sources_to_another_caller(domain_env):
    env = domain_env
    document = add_document(env, "finance", "fin_employee", "private", "Private source introduced after approval.")
    graph = {"nodes": [{"id": "start", "type": "start"},
                       {"id": "review", "type": "approval"},
                       {"id": "document", "type": "document_input"},
                       {"id": "extract", "type": "text_extraction"}, {"id": "end", "type": "end"}],
             "edges": [{"source": "start", "target": "review"}, {"source": "review", "target": "document"},
                       {"source": "document", "target": "extract"}, {"source": "extract", "target": "end"}]}
    workflow = create_and_publish(env, graph)
    env.identity["current"] = "fin_employee"
    run = env.client.post(f"/api/v1/workflows/{workflow['id']}/run", json={"input": {"document_id": document.id}}).json()
    approval = env.db.scalar(select(ApprovalRequest))
    env.identity["current"] = "fin_manager"
    assert env.client.post(f"/api/v1/workflow-runs/{run['id']}/resume").status_code == 403
    approved = env.client.post(f"/api/v1/approvals/{approval.id}/approve", json={})
    assert approved.status_code == 200, approved.text
    assert "Private source introduced" not in approved.text
    assert env.db.info["principal_scope"][0] == "fin_manager"
    assert env.client.get(f"/api/v1/workflow-runs/{run['id']}").status_code == 404
    env.identity["current"] = "fin_employee"
    assert env.client.get(f"/api/v1/workflow-runs/{run['id']}").json()["state"]["text"] == document.extracted_text


def test_remote_workflow_is_queued_durably_before_dispatch(domain_env, monkeypatch):
    from app import rag, worker

    env = domain_env
    dispatch = Mock()
    monkeypatch.setattr(worker, "dispatch_job", dispatch)
    retrieval = AsyncMock(return_value=[])
    monkeypatch.setattr(rag, "search", retrieval)
    graph = {"nodes": [{"id": "start", "type": "start"},
                       {"id": "retrieve", "type": "rag_search", "config": {"query": "Policy"}},
                       {"id": "end", "type": "end"}],
             "edges": [{"source": "start", "target": "retrieve"}, {"source": "retrieve", "target": "end"}]}
    workflow = create_and_publish(env, graph)
    response = env.client.post(f"/api/v1/workflows/{workflow['id']}/run", json={})
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["status"] == "queued"
    assert retrieval.await_count == 0
    job = env.db.scalar(select(Job).where(Job.resource_id == run["id"]))
    assert job.kind == "workflow"
    dispatch.assert_called_once_with(job.id)
    env.db.expunge_all()
    # The worker can execute from persisted records without the original HTTP request.
    completed = asyncio.run(resume_workflow(env.db, principal_for_user(env.db, "fin_manager"), run["id"]))
    assert completed.status == "completed"
    assert retrieval.await_count == 1


def test_stale_worker_cannot_commit_output_or_release_a_new_workers_lease(domain_env, monkeypatch):
    from app import workflows

    env = domain_env
    workflow = create_and_publish(env, definition(False))

    async def replaced_claim(db, principal, run, node, state):
        # Simulate another process taking over while an asynchronous node was running.
        db.execute(update(WorkflowRun).where(WorkflowRun.id == run.id).values(claim_token="new-worker"))
        db.commit()
        return {"stale_output": "must never commit"}, None, False

    monkeypatch.setattr(workflows, "execute_node", replaced_claim)
    response = env.client.post(f"/api/v1/workflows/{workflow['id']}/run", json={})
    assert response.status_code == 201, response.text
    run = env.db.get(WorkflowRun, response.json()["id"])
    assert run.claim_token == "new-worker"
    assert "stale_output" not in run.state
    assert run.status == "running"


@pytest.mark.parametrize("revocation, expected_error", [
    ("membership", "node_http_403"),
    ("account", "node_http_401"),
    ("source_share", "node_http_404"),
])
def test_remote_workflow_discards_output_when_authorization_is_revoked(domain_env, revocation, expected_error):
    env = domain_env
    document = add_document(env, "finance", "fin_employee", "private", "Synthetic invoice INV-1001")
    env.db.add(DocumentPermission(document_id=document.id, user_id="fin_manager", owner_id="fin_employee"))
    env.db.commit()
    graph = {
        "nodes": [{"id": "start", "type": "start"},
                  {"id": "document", "type": "document_input", "config": {"document_id": document.id}},
                  {"id": "text", "type": "text_extraction"},
                  {"id": "analyze", "type": "llm_extraction"},
                  {"id": "end", "type": "end"}],
        "edges": [{"source": "start", "target": "document"},
                  {"source": "document", "target": "text"},
                  {"source": "text", "target": "analyze"},
                  {"source": "analyze", "target": "end"}],
    }
    workflow = create_and_publish(env, graph)
    response = env.client.post(f"/api/v1/workflows/{workflow['id']}/run", json={})
    assert response.status_code == 201 and response.json()["status"] == "queued"
    run_id = response.json()["id"]

    async def revoke_during_model_call(*args, **kwargs):
        # A separate administrator transaction commits while the remote model
        # request is in flight; the worker still holds its original Principal.
        with Session(env.engine) as admin:
            if revocation == "membership":
                admin.get(Membership, ("fin_manager", "finance")).role = "auditor"
            elif revocation == "account":
                admin.get(User, "fin_manager").active = False
            else:
                admin.delete(admin.get(DocumentPermission, (document.id, "fin_manager")))
            admin.commit()
        return SimpleNamespace(data=InvoiceData.model_validate(invoice_payload()))

    env.model.side_effect = revoke_during_model_call
    run = asyncio.run(resume_workflow(env.db, principal_for_user(env.db, "fin_manager"), run_id))

    env.model.assert_awaited_once()
    assert run.status == "failed" and run.error == expected_error
    assert "extracted" not in run.state and "total" not in run.state
    assert run.claim_token is None
    assert env.db.scalar(select(Notification).where(
        Notification.resource_id == run.id, Notification.title == "Workflow completed")) is None
    assert env.db.scalar(select(WorkflowStep).where(
        WorkflowStep.run_id == run.id, WorkflowStep.node_id == "end")) is None
