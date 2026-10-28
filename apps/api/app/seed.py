"""Reproducible synthetic records. Development opt-in only; no authentication bypass."""
import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from app import storage
from app.auth import ROLE_PERMISSIONS
from app.core.config import get_settings
from app.db import session_factory
from app.documents import chunks, extract, verify_file
from app.models import (
    Agent,
    AgentTool,
    AgentVersion,
    Department,
    Document,
    DocumentChunk,
    DocumentVersion,
    Membership,
    Permission,
    Role,
    RolePermission,
    User,
    utcnow,
)

DEPARTMENTS = {"finance": "Finance", "hr": "Human Resources", "legal": "Legal", "operations": "Operations"}
NAMES = {"finance.employee": "Avery Linden", "finance.manager": "Morgan Vale", "hr.employee": "Jordan Elm", "hr.manager": "Riley Finch", "legal.employee": "Casey Brook", "legal.manager": "Taylor Ash", "operations.employee": "Skyler Reed", "operations.manager": "Quinn Birch", "platform.admin": "Drew Cedar", "audit.viewer": "Alex Willow"}


def identifier(name):
    return str(uuid5(NAMESPACE_URL, "enterpriseflow:" + name))


def data_root():
    candidates = [Path("/srv/demo-data"), Path(__file__).resolve().parents[3] / "demo-data"]
    return next(p for p in candidates if (p / "manifest.json").exists())


def seed(db):
    s = get_settings()
    if s.is_production or not s.enable_dev_users:
        raise RuntimeError("Synthetic seed requires APP_ENV=development and ENABLE_DEV_USERS=true")
    departments, users = {}, {}
    for role, permissions in ROLE_PERMISSIONS.items():
        if not db.get(Role, role):
            db.add(Role(name=role))
        for permission in permissions:
            if not db.get(Permission, permission):
                db.add(Permission(name=permission))
                db.flush()
        db.flush()
        for permission in permissions:
            if not db.get(RolePermission, (role, permission)):
                db.add(RolePermission(role=role, permission=permission))
    for slug, name in DEPARTMENTS.items():
        row = db.scalar(select(Department).where(Department.slug == slug))
        if not row:
            row = Department(id=identifier("department:" + slug), slug=slug, name=name)
            db.add(row)
        departments[slug] = row
    db.flush()
    for username, name in NAMES.items():
        subject = identifier(username)
        user = db.scalar(select(User).where(User.subject == subject))
        if not user:
            user = User(id=subject, subject=subject, email=username + "@example.test", name=name, roles=["platform_admin"] if username == "platform.admin" else [])
            db.add(user)
        users[username] = user
        db.flush()
        prefix, role = username.split(".")
        slug = "finance" if username == "audit.viewer" else prefix
        if slug in departments:
            role = "auditor" if username == "audit.viewer" else role
            if not db.get(Membership, (user.id, departments[slug].id)):
                db.add(Membership(user_id=user.id, department_id=departments[slug].id, role=role))
    for slug, dept in departments.items():
        aid = identifier("agent:" + slug)
        if not db.get(Agent, aid):
            agent = Agent(id=aid, department_id=dept.id, name=dept.name + " Assistant", description={"finance": "Review invoice evidence and finance policy. Payments are never executed.", "hr": "Find policy evidence and guide onboarding with protected employee records.", "legal": "Analyze agreement evidence for professional review. No contract signing.", "operations": "Review fictional property records, field provenance and listing exceptions."}[slug], provider=s.default_llm_provider, model=s.openai_model if s.default_llm_provider == "openai" else s.anthropic_model, system_prompt=f"Support authorized {dept.name} employees. Use sources, acknowledge missing evidence, and refer consequential decisions to an authorized human.", tools=["search_documents"])
            db.add(agent)
            db.flush()
            db.add(AgentTool(agent_id=aid, name="search_documents"))
            db.add(AgentVersion(agent_id=aid, version=1, config={"provider": agent.provider, "model": agent.model, "tools": agent.tools, "system_prompt": agent.system_prompt}))
    db.commit()
    root = data_root()
    manifest = json.loads((root / "manifest.json").read_text())
    for category, slug in [("invoices", "finance"), ("hr_documents", "hr"), ("legal_documents", "legal")]:
        for item in manifest[category]:
            path = root / item["path"]
            did = identifier("document:" + item["path"])
            if db.get(Document, did):
                continue
            data = path.read_bytes()
            mime = verify_file(path.name, None, data)
            pages = extract(data, mime)
            key = f"{departments[slug].id}/{did}/1/demo"
            storage.put(key, data, mime)
            digest = hashlib.sha256(data).hexdigest()
            document = Document(id=did, department_id=departments[slug].id, owner_id=users[slug + ".employee"].id, name="DEMO · " + path.name, mime_type=mime, size=len(data), content_hash=digest, storage_key=key, visibility="department", status="ready", scan_status="synthetic_fixture_structural_checks", version=1, extracted_text="\n\n".join(f"[{loc}]\n{text}" for loc, text in pages), embedding_status="not_configured", processed_at=utcnow())
            db.add(document)
            db.flush()
            db.add(DocumentVersion(document_id=did, department_id=departments[slug].id, version=1, storage_key=key, content_hash=digest))
            for ordinal, (location, text) in enumerate(chunks(pages)):
                db.add(DocumentChunk(document_id=did, department_id=departments[slug].id, content=text, location=location, ordinal=ordinal, version=1))
    db.commit()
    from app.business import seed_business
    seed_business(db, departments, users)
    db.commit()
    return {"users": len(users), "departments": len(departments), "agents": 4, "fixture_documents": 40, "data_kind": "synthetic demonstration"}


if __name__ == "__main__":
    with session_factory()() as db:
        print(json.dumps(seed(db)))
