"""Provision the restricted runtime login from migration-task secrets.

No values are logged. The application role never owns schema objects. Run this
only in the separate migration task, whose secret contains both database URLs.
"""
import os

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url


def bootstrap() -> None:
    admin = make_url(os.environ["MIGRATION_DATABASE_URL"])
    application = make_url(os.environ["DATABASE_URL"])
    if application.username == admin.username or not application.username or not application.password:
        raise RuntimeError("Distinct migration and runtime roles with passwords are required")
    options = dict(admin.query)
    with psycopg.connect(host=admin.host, port=admin.port or 5432, dbname=admin.database,
                          user=admin.username, password=admin.password, **options) as connection:
        exists = connection.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (application.username,)).fetchone()
        statement = "ALTER ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE" if exists else "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE"
        connection.execute(sql.SQL(statement).format(sql.Identifier(application.username), sql.Literal(application.password)))
        for statement in [
            "GRANT USAGE ON SCHEMA public TO {}",
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}",
            "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}",
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}",
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {}",
        ]:
            connection.execute(sql.SQL(statement).format(sql.Identifier(application.username)))
        # Repeated deployments must not regrant mutation rights on immutable audit history.
        if connection.execute("SELECT to_regclass('public.audit_events')").fetchone()[0]:
            connection.execute(sql.SQL("REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM {}").format(sql.Identifier(application.username)))
        # A replacement runtime role may be provisioned after migration 0005.
        # Grant only the reviewed deletion entry point, never all functions.
        if connection.execute("SELECT to_regprocedure('public.finalize_document_deletion(text)')").fetchone()[0]:
            connection.execute(sql.SQL(
                "GRANT EXECUTE ON FUNCTION public.finalize_document_deletion(text) TO {}",
            ).format(sql.Identifier(application.username)))
    print("Restricted runtime database role provisioned.")


if __name__ == "__main__":
    bootstrap()
