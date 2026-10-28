"""Role bootstrap tests stub the database boundary and never connect to a server."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "bootstrap_database", Path(__file__).parents[1] / "docker" / "bootstrap_database.py",
)
bootstrap_database = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap_database)


@pytest.mark.parametrize("role_exists", [False, True])
@pytest.mark.parametrize("function_exists", [False, True])
def test_runtime_role_gets_only_existing_deletion_function(monkeypatch, capsys, role_exists, function_exists):
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+psycopg://migration:test-admin-password@database/enterpriseflow?sslmode=require",
    )
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://runtime%22rotated:test-runtime-password@database/enterpriseflow?sslmode=require",
    )
    statements = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def execute(self, statement, parameters=None):
            query = statement if isinstance(statement, str) else statement.as_string()
            statements.append(query)
            if "FROM pg_roles" in query:
                assert parameters == ('runtime"rotated',)
                row = (1,) if role_exists else None
            elif "to_regprocedure" in query:
                assert query == "SELECT to_regprocedure('public.finalize_document_deletion(text)')"
                row = ("finalize_document_deletion(text)" if function_exists else None,)
            elif "to_regclass" in query:
                row = ("audit_events",)
            else:
                row = None
            return SimpleNamespace(fetchone=lambda: row)

    monkeypatch.setattr(bootstrap_database.psycopg, "connect", lambda **_: Connection())
    bootstrap_database.bootstrap()

    function_grants = [statement for statement in statements if "GRANT EXECUTE" in statement]
    expected = ['GRANT EXECUTE ON FUNCTION public.finalize_document_deletion(text) TO "runtime""rotated"']
    assert function_grants == (expected if function_exists else [])
    assert not any("ALL FUNCTIONS" in statement for statement in statements)
    assert not any("DEFAULT PRIVILEGES" in statement and "FUNCTION" in statement for statement in statements)
    role_statement = next(statement for statement in statements if "ROLE \"runtime" in statement)
    assert role_statement.startswith("ALTER ROLE" if role_exists else "CREATE ROLE")
    assert "NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE" in role_statement
    assert 'REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM "runtime""rotated"' in statements
    output = capsys.readouterr().out
    assert "test-admin-password" not in output
    assert "test-runtime-password" not in output
