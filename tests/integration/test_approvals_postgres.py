"""Real PostgreSQL transaction races in an isolated, disposable test schema.

Set TEST_DATABASE_URL to a PostgreSQL migration/admin connection. These tests
create a uniquely named schema and remove only that schema after completion.
They never reset, migrate, or edit the application's seeded tables.
"""

import asyncio
import os
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app import business, workflows
from app.auth import principal_for_user
from app.domain_models import (
    ApprovalDecision,
    ApprovalRequest,
    Invoice,
    WorkflowRun,
    WorkflowStep,
)
from app.domain_schemas import InvoiceData, ManualInvoice, WorkflowCreate, WorkflowStart
from app.models import Base, Department, Membership, Notification, User
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session


@pytest.fixture
def postgres_domain():
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to exercise PostgreSQL transaction concurrency")
    if not database_url.startswith("postgresql"):
        pytest.fail("TEST_DATABASE_URL must use PostgreSQL; SQLite cannot verify row locking")
    admin = create_engine(database_url, pool_pre_ping=True)
    schema = f"ef_concurrency_{uuid4().hex}"
    with admin.begin() as connection:
        assert connection.dialect.name == "postgresql"
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = admin.execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(engine)
        with Session(engine, expire_on_commit=False) as db:
            department = Department(name=f"Concurrency Finance {schema}", slug="finance")
            db.add(department)
            identities = {}
            for role in ("employee", "manager_one", "manager_two"):
                user = User(subject=f"{schema}:{role}", email=f"{role}.{schema}@example.test", name=role)
                db.add(user)
                db.flush()
                db.add(Membership(user_id=user.id, department_id=department.id,
                                  role="employee" if role == "employee" else "manager"))
                identities[role] = user.id
            db.commit()
            department_id = department.id
        yield SimpleNamespace(engine=engine, department_id=department_id, users=identities)
    finally:
        # All test sessions are closed before dropping this uniquely owned schema.
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def invoice_data(total="1350.00"):
    subtotal = Decimal(total) - Decimal(100)
    return InvoiceData(
        vendor_name="Fictional concurrent vendor", invoice_number="CONCURRENCY-INV-001",
        invoice_date=date.today() - timedelta(days=1), due_date=date.today() + timedelta(days=30),
        currency="USD", subtotal=subtotal, tax=Decimal(100), total=Decimal(total),
        line_items=[{"description": "Synthetic inspection", "quantity": "1",
                     "unit_price": str(subtotal), "amount": str(subtotal)}],
    )


def test_simultaneous_approvals_commit_one_decision_and_one_workflow_action(postgres_domain):
    env = postgres_domain
    graph = {
        "nodes": [{"id": "start", "type": "start"}, {"id": "review", "type": "approval"},
                  {"id": "notify", "type": "notification", "config": {"title": "Approved action"}},
                  {"id": "end", "type": "end"}],
        "edges": [{"source": "start", "target": "review"}, {"source": "review", "target": "notify"},
                  {"source": "notify", "target": "end"}],
    }
    with Session(env.engine, expire_on_commit=False) as db:
        manager = principal_for_user(db, env.users["manager_one"])
        workflow = workflows.create_workflow(WorkflowCreate(
            name="Concurrent review", department_id=env.department_id, definition=graph), db, manager)
        workflows.publish_workflow(workflow["id"], db, manager)
        employee = principal_for_user(db, env.users["employee"])
        run = asyncio.run(workflows.start_workflow(workflow["id"], WorkflowStart(), db, employee))
        assert run["status"] == "waiting_approval"
        run_id = run["id"]
        approval_id = db.scalar(select(ApprovalRequest.id).where(ApprovalRequest.resource_id == run_id))

    update_barrier = threading.Barrier(2, timeout=10)

    def synchronize_decision_updates(connection, cursor, statement, parameters, context, executemany):
        values = parameters.values() if isinstance(parameters, dict) else parameters
        if "approval_requests SET" in statement and approval_id in values:
            # Both transactions have read pending and now compete for the actual
            # UPDATE row lock; this is not merely sequential duplicate delivery.
            update_barrier.wait()

    def submit(manager_id):
        with Session(env.engine, expire_on_commit=False) as db:
            principal = principal_for_user(db, manager_id)
            try:
                asyncio.run(workflows.decide_approval(db, principal, approval_id, "approved", "Verified"))
                return 200
            except HTTPException as exc:
                return exc.status_code

    event.listen(env.engine, "before_cursor_execute", synchronize_decision_updates)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(submit, env.users[role]) for role in ("manager_one", "manager_two")]
            statuses = [future.result(timeout=20) for future in futures]
    finally:
        event.remove(env.engine, "before_cursor_execute", synchronize_decision_updates)
    assert sorted(statuses) == [200, 409]

    # The transaction that lost the compare-and-swap can safely retry after reload.
    assert submit(env.users["manager_two"]) == 200
    with Session(env.engine) as db:
        assert db.scalar(select(func.count()).select_from(ApprovalDecision)
                         .where(ApprovalDecision.approval_id == approval_id)) == 1
        assert db.get(WorkflowRun, run_id).status == "completed"
        steps = db.scalars(select(WorkflowStep).where(WorkflowStep.run_id == run_id)).all()
        assert len(steps) == 4
        assert all(step.status == "completed" and step.attempts == 1 for step in steps)
        assert db.scalar(select(func.count()).select_from(Notification).where(
            Notification.resource_id == run_id, Notification.title == "Approved action")) == 1
        assert db.scalar(select(func.count()).select_from(Notification).where(
            Notification.resource_id == run_id, Notification.title == "Workflow completed")) == 1


@pytest.mark.parametrize("first_operation", ["edit", "submit"])
def test_invoice_correction_and_submission_are_serialized(postgres_domain, monkeypatch, first_operation):
    env = postgres_domain
    with Session(env.engine, expire_on_commit=False) as db:
        employee = principal_for_user(db, env.users["employee"])
        invoice = business.manual_invoice(ManualInvoice(department_id=env.department_id, data=invoice_data()),
                                          db, employee)
        invoice_id = invoice["id"]

    first_locked, second_started, release_first = threading.Event(), threading.Event(), threading.Event()
    operation = threading.local()
    original_get_invoice = business.get_invoice

    def synchronized_get_invoice(db, principal, target_id, permission="workflows:read"):
        if operation.name != first_operation:
            second_started.set()
        row = original_get_invoice(db, principal, target_id, permission)
        if operation.name == first_operation:
            first_locked.set()
            assert release_first.wait(timeout=10), "Timed out waiting to release the first transaction"
        return row

    monkeypatch.setattr(business, "get_invoice", synchronized_get_invoice)

    def execute(name):
        operation.name = name
        with Session(env.engine, expire_on_commit=False) as db:
            employee = principal_for_user(db, env.users["employee"])
            try:
                if name == "edit":
                    result = business.correct_invoice(invoice_id, invoice_data("2450.00"), db, employee)
                else:
                    result = business.submit_invoice(invoice_id, db, employee)
                return 200, result
            except HTTPException as exc:
                return exc.status_code, None

    second_operation = "submit" if first_operation == "edit" else "edit"
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(execute, first_operation)
        assert first_locked.wait(timeout=10)
        second = pool.submit(execute, second_operation)
        try:
            assert second_started.wait(timeout=10)
            # Without FOR UPDATE, the competing handler completes here and this
            # assertion fails. Holding the first lock makes both orderings stable.
            with pytest.raises(TimeoutError):
                second.result(timeout=0.2)
        finally:
            release_first.set()
        first_status, _ = first.result(timeout=10)
        second_status, _ = second.result(timeout=10)
    assert first_status == 200
    assert second_status == (200 if first_operation == "edit" else 409)

    expected_total = "2450.00" if first_operation == "edit" else "1350.00"
    with Session(env.engine) as db:
        invoice = db.get(Invoice, invoice_id)
        approval = db.scalar(select(ApprovalRequest).where(ApprovalRequest.resource_type == "invoice",
                                                           ApprovalRequest.resource_id == invoice_id))
        assert invoice.approval_status == "pending_approval"
        assert invoice.total == Decimal(expected_total)
        assert approval.payload["invoice"]["total"] == expected_total
