import hashlib
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import cipher
from app.db import get_db
from app.main import create_app
from app.models import LoginState, SessionRecord, User, utcnow


def session_client(db):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    raw = "opaque-session-id-for-test-only"
    db.add(SessionRecord(id=hashlib.sha256(raw.encode()).hexdigest(), user_id="fin", csrf_token="csrf-test", access_token=cipher().encrypt(b"test-access-token").decode(), refresh_token=cipher().encrypt(b"test-refresh-token").decode(), id_token=cipher().encrypt(b"test-id-token").decode(), token_expires_at=utcnow() + timedelta(minutes=5), expires_at=utcnow() + timedelta(hours=1)))
    db.commit()
    client.cookies.set("ef_session", raw)
    return client


def test_server_session_csrf_and_origin_checks(db):
    client = session_client(db)
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["csrf_token"] == "csrf-test"
    assert "test-access-token" not in me.text
    payload = {"agent_id": "finance-agent"}
    assert client.post("/api/v1/conversations", json=payload).status_code == 403
    assert client.post("/api/v1/conversations", json=payload, headers={"x-csrf-token": "csrf-test", "origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/v1/conversations", json=payload, headers={"x-csrf-token": "csrf-test", "origin": "http://localhost:3000"}).status_code == 201
    db.get(User, "fin").active = False
    db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_has_pkce_browser_binding_and_one_time_state(db):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    response = client.get("/api/v1/auth/login", follow_redirects=False)
    assert response.status_code == 307
    args = parse_qs(urlparse(response.headers["location"]).query)
    assert args["code_challenge_method"] == ["S256"]
    state = db.get(LoginState, args["state"][0])
    assert state and len(state.verifier) >= 43
    assert args["nonce"] == [state.nonce]
    assert "HttpOnly" in response.headers["set-cookie"]
    client.cookies.clear()
    assert client.get("/api/v1/auth/callback", params={"state": state.id, "code": "bad"}).status_code == 400


def test_logout_deletes_session_and_expires_cookie(db):
    client = session_client(db)
    result = client.post("/api/v1/auth/logout", headers={"x-csrf-token": "csrf-test"})
    assert result.status_code == 200
    assert "/protocol/openid-connect/logout?" in result.json()["logout_url"]
    assert db.scalar(select(SessionRecord)) is None
    assert client.get("/api/v1/auth/me").status_code == 401


def test_expiring_session_rotates_tokens_once_and_keeps_identity(db, monkeypatch):
    client = session_client(db)
    session = db.scalar(select(SessionRecord))
    session.token_expires_at = utcnow() + timedelta(seconds=5)
    db.commit()
    calls = []

    def refresh(url, data, timeout):
        calls.append(data["grant_type"])
        assert data["refresh_token"] == "test-refresh-token"
        return httpx.Response(200, json={"access_token": "rotated-access", "refresh_token": "rotated-refresh"},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr("app.auth.httpx.post", refresh)
    monkeypatch.setattr("app.auth.validate_token", lambda token: {"sub": "fin", "exp": (utcnow() + timedelta(minutes=5)).timestamp()})
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200
    assert calls == ["refresh_token"]
    assert cipher().decrypt(session.refresh_token.encode()) == b"rotated-refresh"


def test_refresh_subject_change_revokes_local_session(db, monkeypatch):
    client = session_client(db)
    db.scalar(select(SessionRecord)).token_expires_at = utcnow()
    db.commit()
    monkeypatch.setattr("app.auth.httpx.post", lambda url, **kwargs: httpx.Response(
        200, json={"access_token": "wrong-subject"}, request=httpx.Request("POST", url)))
    monkeypatch.setattr("app.auth.validate_token", lambda token: {"sub": "hr", "exp": (utcnow() + timedelta(minutes=5)).timestamp()})
    assert client.get("/api/v1/auth/me").status_code == 401
    assert db.scalar(select(SessionRecord)) is None


@pytest.mark.parametrize("invalid_claim", [None, "nonce", "audience", "missing_audience"])
def test_oidc_callback_validates_signed_tokens_and_consumes_state(db, monkeypatch, caplog, invalid_claim):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    login = client.get("/api/v1/auth/login", follow_redirects=False)
    state_id = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    state = db.get(LoginState, state_id)
    nonce, verifier = state.nonce, state.verifier
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr("app.auth.jwks_client", lambda: SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key=key.public_key())))
    common = {"sub": "fin", "iss": "http://localhost:8080/realms/enterpriseflow",
              "iat": utcnow(), "exp": utcnow() + timedelta(minutes=5)}
    identity = jwt.encode({**common, "aud": "enterpriseflow-web",
                           "nonce": "wrong-nonce" if invalid_claim == "nonce" else nonce}, key, algorithm="RS256")
    access_claims = {**common, "aud": "unrelated-api" if invalid_claim == "audience" else "enterpriseflow-api"}
    if invalid_claim == "missing_audience":
        access_claims.pop("aud")
    access = jwt.encode(access_claims, key, algorithm="RS256")

    def exchange(url, data, timeout):
        assert data["code_verifier"] == verifier
        assert data["code"] == "private-authorization-code"
        return httpx.Response(200, json={"id_token": identity, "access_token": access,
                                        "refresh_token": "private-refresh-token"}, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.auth.httpx.post", exchange)
    response = client.get("/api/v1/auth/callback", params={"state": state_id, "code": "private-authorization-code"},
                          follow_redirects=False)
    assert response.status_code == (401 if invalid_claim else 303)
    assert (db.scalar(select(SessionRecord)) is None) == bool(invalid_claim)
    assert db.get(LoginState, state_id) is None
    assert client.get("/api/v1/auth/callback", params={"state": state_id, "code": "replay"}).status_code == 400
    if invalid_claim:
        assert "oidc_sign_in_failed" in caplog.text
    for secret in (identity, access, "private-authorization-code", "private-refresh-token", verifier):
        assert secret not in caplog.text
