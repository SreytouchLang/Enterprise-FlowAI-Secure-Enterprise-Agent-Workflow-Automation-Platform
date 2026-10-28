"""Run against a migrated disposable PostgreSQL database with pgvector.

TEST_DATABASE_URL must be a migration/admin connection capable of CREATE ROLE.
Each test rolls back its data and temporary non-bypass role. SQLite cannot prove
these properties; only an absent PostgreSQL URL skips this integration suite.
"""
import os
from uuid import uuid4

import pytest
from app.auth import principal_for_user
from app.db import set_scope
from app.models import (
    Department,
    Document,
    DocumentChunk,
    DocumentPermission,
    DocumentVersion,
    EmbeddingRecord,
    Membership,
    User,
)
from pgvector.sqlalchemy import Vector
from sqlalchemy import cast, create_engine, select, text
from sqlalchemy.orm import Session


@pytest.fixture
def pg_scope():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run actual PostgreSQL RLS integration tests")
    if not url.startswith("postgresql"):
        pytest.fail("TEST_DATABASE_URL must use PostgreSQL to exercise RLS")
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, expire_on_commit=False)
        role = f"ef_rls_{uuid4().hex}"
        suffix = uuid4().hex[:10]
        try:
            connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOBYPASSRLS'))
            connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
            connection.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{role}"'))
            connection.execute(text(f'GRANT EXECUTE ON FUNCTION public.finalize_document_deletion(text) TO "{role}"'))
            finance = Department(name=f"RLS finance {suffix}", slug=f"rls-fin-{suffix}")
            hr = Department(name=f"RLS HR {suffix}", slug=f"rls-hr-{suffix}")
            owner = User(subject=f"rls-owner-{suffix}", email=f"owner-{suffix}@example.test", name="Synthetic owner")
            peer = User(subject=f"rls-peer-{suffix}", email=f"peer-{suffix}@example.test", name="Synthetic peer")
            outsider = User(subject=f"rls-outsider-{suffix}", email=f"outsider-{suffix}@example.test", name="Synthetic HR")
            session.add_all([finance, hr, owner, peer, outsider])
            session.flush()
            session.add_all([
                Membership(user_id=owner.id, department_id=finance.id, role="employee"),
                Membership(user_id=peer.id, department_id=finance.id, role="employee"),
                Membership(user_id=outsider.id, department_id=hr.id, role="employee"),
            ])
            docs = []
            for name, department, user, visibility in [
                ("finance-public", finance, owner, "department"),
                ("finance-private", finance, owner, "private"),
                ("hr-private", hr, outsider, "private"),
            ]:
                doc = Document(department_id=department.id, owner_id=user.id, name=name,
                               mime_type="text/plain", size=20, content_hash=uuid4().hex,
                               storage_key=f"synthetic/{uuid4()}", visibility=visibility,
                               status="ready", extracted_text="Synthetic policy evidence")
                session.add(doc)
                session.flush()
                chunk = DocumentChunk(document_id=doc.id, department_id=department.id,
                                      content="Synthetic policy evidence", location="line 1", ordinal=0, version=1)
                session.add(chunk)
                session.add(DocumentVersion(document_id=doc.id, department_id=department.id,
                                            version=1, content_hash=doc.content_hash, storage_key=doc.storage_key))
                session.flush()
                session.add(EmbeddingRecord(chunk_id=chunk.id, department_id=department.id,
                                            model="synthetic-test-vector", vector=[1.0] + [0.0] * 1535))
                docs.append(doc)
            session.flush()
            connection.execute(text(f'SET LOCAL ROLE "{role}"'))
            flags = connection.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).one()
            assert flags == (False, False)
            yield session, finance, hr, owner, peer, outsider, docs
        finally:
            session.close()
            if transaction.is_active:
                transaction.rollback()
    engine.dispose()


def visible_ids(session, ids):
    return set(session.scalars(select(Document.id).where(Document.id.in_(ids))))


def test_rls_denies_missing_scope_and_cross_department_metadata(pg_scope):
    session, finance, hr, owner, _, outsider, docs = pg_scope
    ids = [doc.id for doc in docs]
    assert visible_ids(session, ids) == set()
    set_scope(session, owner.id, [finance.id])
    assert visible_ids(session, ids) == {docs[0].id, docs[1].id}
    set_scope(session, outsider.id, [hr.id])
    assert visible_ids(session, ids) == {docs[2].id}
    set_scope(session, owner.id, [])
    assert visible_ids(session, ids) == set()


def test_rls_private_grant_revocation_propagates_to_chunks_versions_vectors(pg_scope):
    session, finance, _, owner, peer, _, docs = pg_scope
    ids = [doc.id for doc in docs]
    set_scope(session, peer.id, [finance.id])
    assert visible_ids(session, ids) == {docs[0].id}
    set_scope(session, owner.id, [finance.id])
    session.add(DocumentPermission(document_id=docs[1].id, user_id=peer.id, owner_id=owner.id))
    session.flush()
    set_scope(session, peer.id, [finance.id])
    assert visible_ids(session, ids) == {docs[0].id, docs[1].id}
    assert set(session.scalars(select(DocumentChunk.document_id).where(DocumentChunk.document_id.in_(ids)))) == {docs[0].id, docs[1].id}
    assert set(session.scalars(select(DocumentVersion.document_id).where(DocumentVersion.document_id.in_(ids)))) == {docs[0].id, docs[1].id}
    vector_docs = select(DocumentChunk.document_id).join(EmbeddingRecord).where(DocumentChunk.document_id.in_(ids)).order_by(cast(EmbeddingRecord.vector, Vector(1536)).cosine_distance([1.0] + [0.0] * 1535))
    assert set(session.scalars(vector_docs)) == {docs[0].id, docs[1].id}
    set_scope(session, owner.id, [finance.id])
    session.query(DocumentPermission).filter_by(document_id=docs[1].id, user_id=peer.id).delete()
    session.flush()
    set_scope(session, peer.id, [finance.id])
    assert visible_ids(session, ids) == {docs[0].id}
    assert set(session.scalars(vector_docs)) == {docs[0].id}


def test_rls_cannot_forge_private_acl_owner(pg_scope):
    session, finance, _, _, peer, _, docs = pg_scope
    set_scope(session, peer.id, [finance.id])
    from sqlalchemy.exc import DBAPIError
    with pytest.raises(DBAPIError, match="row-level security"), session.begin_nested():
        session.add(DocumentPermission(document_id=docs[1].id, user_id=peer.id, owner_id=peer.id))
        session.flush()
    assert visible_ids(session, [docs[1].id]) == set()


def test_rls_cannot_modify_cross_department_document(pg_scope):
    session, finance, _, owner, _, _, docs = pg_scope
    set_scope(session, owner.id, [finance.id])
    changed = session.execute(text("UPDATE documents SET extracted_text = 'unauthorized' WHERE id = :id"), {"id": docs[2].id})
    assert changed.rowcount == 0


def test_rls_rejects_forged_department_scope(pg_scope):
    session, finance, hr, owner, _, _, docs = pg_scope
    # The connection setting is a filter, never proof of department membership.
    set_scope(session, owner.id, [finance.id, hr.id])
    assert visible_ids(session, [doc.id for doc in docs]) == {docs[0].id, docs[1].id}


@pytest.mark.parametrize("revocation", ["membership_removed", "auditor_role", "inactive_user"])
def test_rls_revokes_access_with_existing_connection_scope(pg_scope, revocation):
    session, finance, _, owner, _, _, docs = pg_scope
    set_scope(session, owner.id, [finance.id])
    assert visible_ids(session, [docs[0].id, docs[1].id]) == {docs[0].id, docs[1].id}
    if revocation == "membership_removed":
        session.execute(text("DELETE FROM department_memberships WHERE user_id = :id"), {"id": owner.id})
    elif revocation == "auditor_role":
        session.execute(text("UPDATE department_memberships SET role = 'auditor' WHERE user_id = :id"), {"id": owner.id})
    else:
        session.execute(text("UPDATE users SET active = false WHERE id = :id"), {"id": owner.id})
    assert visible_ids(session, [doc.id for doc in docs]) == set()
    assert list(session.scalars(select(DocumentChunk.id).where(DocumentChunk.document_id == docs[0].id))) == []


def test_rls_document_readers_cannot_change_chunks_or_vectors(pg_scope):
    session, finance, _, _, peer, _, docs = pg_scope
    set_scope(session, peer.id, [finance.id])
    chunk = session.scalar(select(DocumentChunk).where(DocumentChunk.document_id == docs[0].id))
    assert chunk is not None
    changed = session.execute(text("UPDATE document_chunks SET content = 'forged evidence' WHERE id = :id"),
                              {"id": chunk.id})
    assert changed.rowcount == 0
    changed = session.execute(text("DELETE FROM embedding_records WHERE chunk_id = :id"), {"id": chunk.id})
    assert changed.rowcount == 0
    assert session.scalar(select(EmbeddingRecord.chunk_id).where(EmbeddingRecord.chunk_id == chunk.id)) == chunk.id


def test_rls_rejects_chunk_with_mismatched_department(pg_scope):
    from sqlalchemy.exc import DBAPIError

    session, finance, hr, owner, _, _, docs = pg_scope
    set_scope(session, owner.id, [finance.id, hr.id])
    with pytest.raises(DBAPIError, match="row-level security"), session.begin_nested():
        session.add(DocumentChunk(document_id=docs[0].id, department_id=hr.id,
                                  content="Mismatched ownership", location="line 1", ordinal=2, version=1))
        session.flush()


def restrict_deletion_function_owner(session):
    """Exercise FORCE RLS even when migrations have no superuser/bypass role."""
    runtime_role = session.scalar(text("SELECT current_user"))
    owner_role = f"ef_delete_owner_{uuid4().hex}"
    session.execute(text("RESET ROLE"))
    session.execute(text(f'CREATE ROLE "{owner_role}" NOLOGIN NOSUPERUSER NOBYPASSRLS'))
    session.execute(text(f'GRANT USAGE ON SCHEMA public TO "{owner_role}"'))
    session.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{owner_role}"'))
    session.execute(text(f'ALTER FUNCTION public.finalize_document_deletion(text) OWNER TO "{owner_role}"'))
    session.execute(text(f'ALTER POLICY deletion_tombstone_visibility ON public.documents TO "{owner_role}"'))
    for policy in ("deletion_permission_select", "deletion_permission_delete"):
        session.execute(text(f'ALTER POLICY {policy} ON public.document_permissions TO "{owner_role}"'))
    flags = session.execute(text("""SELECT rolsuper, rolbypassrls FROM pg_roles
        WHERE oid = (SELECT proowner FROM pg_proc
            WHERE oid = 'public.finalize_document_deletion(text)'::regprocedure)""")).one()
    assert flags == (False, False)
    session.execute(text(f'SET LOCAL ROLE "{runtime_role}"'))


@pytest.mark.parametrize("restricted_definer", [False, True], ids=["admin-definer", "rls-definer"])
@pytest.mark.parametrize("actor", ["owner", "department_admin"])
@pytest.mark.parametrize("document_index", [0, 1], ids=["department", "private"])
def test_rls_authorized_soft_delete_revokes_source_access(pg_scope, monkeypatch, document_index,
                                                        actor, restricted_definer):
    from app import documents

    session, finance, _, owner, peer, _, docs = pg_scope
    document = docs[document_index]
    document_id, storage_key = document.id, document.storage_key
    principal_for_user(session, owner.id)
    session.add(DocumentPermission(document_id=document_id, user_id=peer.id, owner_id=owner.id))
    session.flush()
    if actor == "department_admin":
        session.get(Membership, (peer.id, finance.id)).role = "department_admin"
        session.flush()
    if restricted_definer:
        restrict_deletion_function_owner(session)
    principal = principal_for_user(session, owner.id if actor == "owner" else peer.id)
    chunk_id = session.scalar(select(DocumentChunk.id).where(DocumentChunk.document_id == document_id))
    removed_keys = []
    monkeypatch.setattr(documents.storage, "delete", removed_keys.append)

    assert documents.remove(document_id, principal, session) == {"status": "deleted"}
    assert removed_keys == [storage_key]
    for user in (owner, peer):
        set_scope(session, user.id, [finance.id])
        assert visible_ids(session, [document_id]) == set()
        assert session.scalar(select(DocumentChunk.id).where(DocumentChunk.document_id == document_id)) is None
        assert session.scalar(select(DocumentVersion.id).where(DocumentVersion.document_id == document_id)) is None
        assert session.scalar(select(EmbeddingRecord.chunk_id).where(EmbeddingRecord.chunk_id == chunk_id)) is None

    # Inspect the retained tombstone as migration admin only after proving that
    # the real non-bypass runtime role no longer sees source data or metadata.
    session.execute(text("RESET ROLE"))
    tombstone = session.execute(select(Document.status, Document.deleted_at, Document.extracted_text,
                                       Document.storage_key).where(Document.id == document_id)).one()
    assert tombstone.status == "deleted" and tombstone.deleted_at is not None
    assert tombstone.extracted_text == "" and tombstone.storage_key == ""
    assert session.scalar(select(DocumentPermission.user_id).where(
        DocumentPermission.document_id == document_id)) is None


@pytest.mark.parametrize("denial", ["reader", "cross_department", "missing_scope", "inactive",
                                   "auditor", "private_admin_without_grant", "not_deleting"])
def test_soft_delete_finalizer_rejects_unauthorized_direct_calls(pg_scope, denial):
    session, finance, hr, owner, peer, outsider, docs = pg_scope
    document = docs[1] if denial == "private_admin_without_grant" else docs[0]
    set_scope(session, owner.id, [finance.id])
    document.status = "ready" if denial == "not_deleting" else "deleting"
    session.flush()
    if denial in {"reader", "private_admin_without_grant"}:
        if denial == "private_admin_without_grant":
            session.get(Membership, (peer.id, finance.id)).role = "department_admin"
            session.flush()
        set_scope(session, peer.id, [finance.id])
    elif denial == "cross_department":
        set_scope(session, outsider.id, [hr.id, finance.id])
    elif denial == "missing_scope":
        set_scope(session, owner.id, [])
    elif denial == "inactive":
        session.get(User, owner.id).active = False
        session.flush()
    elif denial == "auditor":
        session.get(Membership, (owner.id, finance.id)).role = "auditor"
        session.flush()

    assert session.scalar(text("SELECT public.finalize_document_deletion(:id)"), {"id": document.id}) is False
    session.execute(text("RESET ROLE"))
    persisted = session.execute(select(Document.deleted_at, Document.extracted_text, Document.storage_key)
                                .where(Document.id == document.id)).one()
    assert persisted.deleted_at is None and persisted.extracted_text and persisted.storage_key
    assert session.scalar(select(DocumentChunk.id).where(DocumentChunk.document_id == document.id)) is not None
