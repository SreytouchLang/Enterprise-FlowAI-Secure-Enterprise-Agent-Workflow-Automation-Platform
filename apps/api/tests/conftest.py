import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import get_principal, principal_for_user
from app.core.config import get_settings
from app.db import get_db
from app.main import create_app
from app.models import Agent, Base, Department, Membership, User


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        for slug in ["finance", "hr", "legal", "operations"]:
            session.add(Department(id=slug, name=slug.title(), slug=slug))
        session.flush()
        for name, dept, role in [("fin", "finance", "employee"), ("manager", "finance", "manager"), ("hr", "hr", "employee"), ("hrmanager", "hr", "manager"), ("legal", "legal", "employee"), ("ops", "operations", "employee"), ("auditor", "finance", "auditor"), ("admin", None, "platform_admin")]:
            session.add(User(id=name, subject=name, name=name, email=name + "@example.test", roles=[role] if role == "platform_admin" else []))
            session.flush()
            if dept:
                session.add(Membership(user_id=name, department_id=dept, role=role))
        for dept in ["finance", "hr", "legal", "operations"]:
            session.add(Agent(id=dept + "-agent", name=dept.title(), department_id=dept, tools=["search_documents"], provider="openai", model="gpt-4.1-mini"))
        session.commit()
        yield session
    engine.dispose()


@pytest.fixture
def client(db, monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/unused-app.sqlite")
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "uploads"))
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db

    def principal(request: Request):
        user_id = request.headers.get("x-test-user")
        if not user_id:
            raise HTTPException(401, "Test requires explicit identity")
        return principal_for_user(db, user_id)
    app.dependency_overrides[get_principal] = principal
    monkeypatch.setattr("app.worker.dispatch_job", lambda job_id: None)
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()
