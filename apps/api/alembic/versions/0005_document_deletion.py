"""Finalize deletion atomically without exposing tombstones through runtime RLS."""

from sqlalchemy import text

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return
    quote = connection.dialect.identifier_preparer.quote
    owner = quote(connection.scalar(text("SELECT current_user")))
    # PostgreSQL checks SELECT policies against an UPDATE's new row. Permit
    # only the migration/function owner to see scrubbed tombstones, including
    # when that owner is subject to FORCE RLS and has no bypass privileges.
    op.execute(f"""CREATE POLICY deletion_tombstone_visibility ON public.documents
        FOR SELECT TO {owner} USING (
            deleted_at IS NOT NULL AND status = 'deleted'
            AND extracted_text = '' AND storage_key = '')""")
    cleanup = """EXISTS (
        SELECT 1 FROM public.documents d
        JOIN public.department_memberships m ON m.department_id = d.department_id
        JOIN public.users u ON u.id = m.user_id
        WHERE d.id = document_permissions.document_id
          AND d.status IN ('deleting', 'deleted')
          AND u.id = current_setting('app.user_id', true) AND u.active
          AND d.department_id = ANY(string_to_array(current_setting('app.department_ids', true), ','))
          AND m.role IN ('employee', 'manager', 'department_admin')
          AND (d.owner_id = u.id OR m.role = 'department_admin'))"""
    # A permission SELECT policy must not query documents: documents_read
    # already queries permissions, so doing so would create recursive RLS.
    op.execute(f"""CREATE POLICY deletion_permission_select ON public.document_permissions
        FOR SELECT TO {owner} USING (true)""")
    op.execute(f"""CREATE POLICY deletion_permission_delete ON public.document_permissions
        FOR DELETE TO {owner} USING ({cleanup})""")
    op.execute("""CREATE FUNCTION public.finalize_document_deletion(target_id text)
        RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog AS $$
        DECLARE target public.documents%ROWTYPE;
        BEGIN
            SELECT d.* INTO target FROM public.documents d
            JOIN public.department_memberships m ON m.department_id = d.department_id
            JOIN public.users u ON u.id = m.user_id
            WHERE d.id = target_id AND d.deleted_at IS NULL AND d.status = 'deleting'
              AND u.id = current_setting('app.user_id', true) AND u.active
              AND d.department_id = ANY(string_to_array(current_setting('app.department_ids', true), ','))
              AND m.role IN ('employee', 'manager', 'department_admin')
              AND (d.owner_id = u.id OR m.role = 'department_admin')
              AND (d.visibility = 'department' OR d.owner_id = u.id OR EXISTS (
                  SELECT 1 FROM public.document_permissions p
                  WHERE p.document_id = d.id AND p.user_id = u.id))
            FOR UPDATE OF d;
            IF NOT FOUND THEN RETURN false; END IF;

            DELETE FROM public.embedding_records WHERE chunk_id IN (
                SELECT id FROM public.document_chunks WHERE document_id = target_id);
            DELETE FROM public.document_chunks WHERE document_id = target_id;
            DELETE FROM public.document_versions WHERE document_id = target_id;
            -- Keep private grants until the UPDATE has passed its source ACL
            -- check. Permission cleanup is part of this same transaction.
            UPDATE public.documents SET deleted_at = clock_timestamp(),
                extracted_text = '', storage_key = '', status = 'deleted'
                WHERE id = target_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Document deletion authorization changed' USING ERRCODE = '42501';
            END IF;
            DELETE FROM public.document_permissions WHERE document_id = target_id;
            RETURN true;
        END $$""")
    op.execute("REVOKE ALL ON FUNCTION public.finalize_document_deletion(text) FROM PUBLIC")
    # Runtime roles are provisioned before migration. Match existing document
    # mutation privileges rather than assuming a particular deployment username.
    roles = connection.scalars(text("""SELECT rolname FROM pg_roles
        WHERE NOT rolsuper AND NOT rolbypassrls
          AND has_table_privilege(oid, 'public.documents', 'UPDATE')
          AND has_table_privilege(oid, 'public.documents', 'DELETE')"""))
    for role in roles:
        op.execute(f"GRANT EXECUTE ON FUNCTION public.finalize_document_deletion(text) TO {quote(role)}")


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP FUNCTION public.finalize_document_deletion(text)")
    op.execute("DROP POLICY deletion_permission_select ON public.document_permissions")
    op.execute("DROP POLICY deletion_permission_delete ON public.document_permissions")
    op.execute("DROP POLICY deletion_tombstone_visibility ON public.documents")
