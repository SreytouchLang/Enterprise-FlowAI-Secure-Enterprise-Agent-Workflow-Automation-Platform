"""Defense in depth for documents, vectors and immutable audit rows; LangGraph persistence."""
from sqlalchemy import text

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

CHILDREN = {
    "document_chunks": "document_id",
    "document_versions": "document_id",
}
SCOPE = "department_id = ANY(string_to_array(current_setting('app.department_ids', true), ','))"
USER = "current_setting('app.user_id', true)"


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    # The API role must be NOSUPERUSER NOBYPASSRLS. Migration credentials are separate.
    op.execute("ALTER TABLE documents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE documents FORCE ROW LEVEL SECURITY")
    op.execute(f"""CREATE POLICY documents_read ON documents FOR SELECT USING (
        {SCOPE} AND deleted_at IS NULL AND
        (visibility = 'department' OR owner_id = {USER} OR EXISTS (
          SELECT 1 FROM document_permissions p WHERE p.document_id = documents.id AND p.user_id = {USER})))""")
    ownership = f"({SCOPE} AND (owner_id = {USER} OR EXISTS (SELECT 1 FROM department_memberships m WHERE m.user_id = {USER} AND m.department_id = documents.department_id AND m.role = 'department_admin')))"
    op.execute(f"CREATE POLICY documents_insert ON documents FOR INSERT WITH CHECK ({SCOPE} AND owner_id = {USER})")
    op.execute(f"CREATE POLICY documents_update ON documents FOR UPDATE USING {ownership} WITH CHECK {ownership}")
    op.execute(f"CREATE POLICY documents_delete ON documents FOR DELETE USING {ownership}")
    op.execute("ALTER TABLE document_permissions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_permissions FORCE ROW LEVEL SECURITY")
    # No documents subquery here: avoids recursive policies on documents_read.
    op.execute(f"CREATE POLICY permission_visibility ON document_permissions FOR SELECT USING (user_id = {USER} OR owner_id = {USER})")
    op.execute(f"CREATE POLICY permission_insert ON document_permissions FOR INSERT WITH CHECK (owner_id = {USER} AND EXISTS (SELECT 1 FROM documents d WHERE d.id = document_permissions.document_id AND d.owner_id = {USER}))")
    op.execute(f"CREATE POLICY permission_delete ON document_permissions FOR DELETE USING (owner_id = {USER})")
    for table, column in CHILDREN.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY document_access ON {table} USING (EXISTS (SELECT 1 FROM documents d WHERE d.id = {table}.{column}))")
    op.execute("ALTER TABLE embedding_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE embedding_records FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY embedding_access ON embedding_records USING (EXISTS (SELECT 1 FROM document_chunks c WHERE c.id = embedding_records.chunk_id))")
    op.execute("CREATE INDEX ix_document_chunks_fts ON document_chunks USING gin(to_tsvector('english', content))")
    op.execute("CREATE INDEX ix_embedding_vector ON embedding_records USING hnsw(vector vector_cosine_ops)")
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'enterpriseflow') THEN REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM enterpriseflow; END IF; END $$")
    # Official LangGraph PostgreSQL saver migrations need autocommit for concurrent indexes.
    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver
    url = op.get_bind().engine.url.render_as_string(hide_password=False).replace("postgresql+psycopg://", "postgresql://")
    with op.get_context().autocommit_block():
        with psycopg.connect(url, autocommit=True) as connection:
            PostgresSaver(connection).setup()


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_fts")
    op.execute("DROP INDEX IF EXISTS ix_embedding_vector")
    for table in ["embedding_records", "document_versions", "document_chunks", "document_permissions", "documents"]:
        names = op.get_bind().execute(text("SELECT policyname FROM pg_policies WHERE schemaname = current_schema() AND tablename = :t"), {"t": table}).scalars().all()
        for name in names:
            op.execute(f'DROP POLICY "{name}" ON {table}')
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    for table in ["checkpoint_writes", "checkpoint_blobs", "checkpoints", "checkpoint_migrations"]:
        op.execute(f"DROP TABLE IF EXISTS {table}")
