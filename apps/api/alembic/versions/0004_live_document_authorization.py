"""Check live membership in RLS and separate readable source data from writable data."""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

USER = "current_setting('app.user_id', true)"
SCOPE = "department_id = ANY(string_to_array(current_setting('app.department_ids', true), ','))"
ACTIVE_MEMBERSHIP = f"""EXISTS (
    SELECT 1 FROM department_memberships m JOIN users u ON u.id = m.user_id
    WHERE m.user_id = {USER} AND m.department_id = documents.department_id
      AND m.role IN ('employee', 'manager', 'department_admin') AND u.active)"""
OWNER = f"""(owner_id = {USER} OR EXISTS (
    SELECT 1 FROM department_memberships m WHERE m.user_id = {USER}
    AND m.department_id = documents.department_id AND m.role = 'department_admin'))"""


def document_policies(live_membership: bool):
    scope = f"({SCOPE} AND {ACTIVE_MEMBERSHIP})" if live_membership else SCOPE
    for name in ("documents_read", "documents_insert", "documents_update", "documents_delete"):
        op.execute(f"DROP POLICY {name} ON documents")
    op.execute(f"""CREATE POLICY documents_read ON documents FOR SELECT USING (
        {scope} AND deleted_at IS NULL AND
        (visibility = 'department' OR owner_id = {USER} OR EXISTS (
          SELECT 1 FROM document_permissions p WHERE p.document_id = documents.id AND p.user_id = {USER})))""")
    op.execute(f"CREATE POLICY documents_insert ON documents FOR INSERT WITH CHECK ({scope} AND owner_id = {USER})")
    ownership = f"({scope} AND {OWNER})"
    op.execute(f"CREATE POLICY documents_update ON documents FOR UPDATE USING {ownership} WITH CHECK {ownership}")
    op.execute(f"CREATE POLICY documents_delete ON documents FOR DELETE USING {ownership}")


def source_policies(table, read_access, write_access):
    op.execute(f"CREATE POLICY source_read ON {table} FOR SELECT USING ({read_access})")
    op.execute(f"CREATE POLICY source_insert ON {table} FOR INSERT WITH CHECK ({write_access})")
    op.execute(f"CREATE POLICY source_update ON {table} FOR UPDATE USING ({write_access}) WITH CHECK ({write_access})")
    op.execute(f"CREATE POLICY source_delete ON {table} FOR DELETE USING ({write_access})")


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    document_policies(True)
    writer = f"""(d.owner_id = {USER} OR EXISTS (
        SELECT 1 FROM department_memberships m WHERE m.user_id = {USER}
        AND m.department_id = d.department_id AND m.role = 'department_admin'))"""
    for table in ("document_chunks", "document_versions"):
        op.execute(f"DROP POLICY document_access ON {table}")
        parent = f"SELECT 1 FROM documents d WHERE d.id = {table}.document_id AND d.department_id = {table}.department_id"
        source_policies(table, f"EXISTS ({parent})", f"EXISTS ({parent} AND {writer})")
    op.execute("DROP POLICY embedding_access ON embedding_records")
    parent = """SELECT 1 FROM document_chunks c JOIN documents d ON d.id = c.document_id
                WHERE c.id = embedding_records.chunk_id AND d.department_id = embedding_records.department_id"""
    source_policies("embedding_records", f"EXISTS ({parent})", f"EXISTS ({parent} AND {writer})")


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    document_policies(False)
    for table in ("document_chunks", "document_versions", "embedding_records"):
        for name in ("source_read", "source_insert", "source_update", "source_delete"):
            op.execute(f"DROP POLICY {name} ON {table}")
        if table == "embedding_records":
            op.execute("CREATE POLICY embedding_access ON embedding_records USING (EXISTS (SELECT 1 FROM document_chunks c WHERE c.id = embedding_records.chunk_id))")
        else:
            op.execute(f"CREATE POLICY document_access ON {table} USING (EXISTS (SELECT 1 FROM documents d WHERE d.id = {table}.document_id))")
