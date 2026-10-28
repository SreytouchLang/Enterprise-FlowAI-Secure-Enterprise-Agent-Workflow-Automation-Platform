"""Keep ephemeral identity credentials out of uploaded CI diagnostics."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "diagnostics", Path(__file__).parents[1] / "collect_compose_diagnostics.py",
)
diagnostics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostics)


def test_redacts_configured_credentials_and_runtime_identity_tokens():
    content = """Connecting postgresql+psycopg://app:database-password@postgres/db
auth password=database-password
GET /api/auth/callback?code=one-time-code&state=secret-state&session_state=session-value
Response {"access_token": "opaque-access", "refresh_token": "opaque-refresh"}
Request {'csrf_token': 'opaque-csrf', 'verifier': 'opaque-pkce'}
Authorization: Bearer opaque-bearer
Cookie: ef_session=opaque-cookie; preference=also-private
Set-Cookie: ef_session=issued-cookie; HttpOnly
Token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.c2lnbmF0dXJl
OPENAI_API_KEY=provider-secret
worker: Task document.ingest completed"""
    result = diagnostics.redact(content, "POSTGRES_PASSWORD=database-password\nOPENAI_API_KEY=provider-secret\n")
    for secret in [
        "database-password", "one-time-code", "secret-state", "session-value", "opaque-access",
        "opaque-refresh", "opaque-csrf", "opaque-pkce", "opaque-bearer", "opaque-cookie",
        "issued-cookie", "eyJhbGciOiJIUzI1NiJ9", "provider-secret",
    ]:
        assert secret not in result
    assert "worker: Task document.ingest completed" in result


def test_redacts_connection_passwords_not_present_in_dotenv():
    result = diagnostics.redact("postgresql://runtime:temporary-password@database:5432/app", "")
    assert result == "postgresql://[REDACTED]@database:5432/app"


def test_redacts_quoted_cookie_headers_and_secret_values_containing_spaces():
    content = """Headers: {'cookie': 'ef_session=private-session; theme=dark'}
Response: {"set-cookie": "ef_session=new-private-session; HttpOnly"}
Credentials: {"password": "a secret with spaces", 'secret': 'another private phrase'}"""
    result = diagnostics.redact(content, "")
    for secret in ("private-session", "new-private-session", "secret with spaces", "another private phrase"):
        assert secret not in result
