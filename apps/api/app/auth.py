"""OIDC Authorization Code + PKCE, server-side encrypted tokens and database RBAC."""
import base64
import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from urllib.parse import urlencode

import httpx
import jwt
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import request_id
from app.core.config import get_settings
from app.db import get_db, set_scope
from app.models import Department, LoginState, Membership, SessionRecord, User, utcnow

router = APIRouter(prefix="/auth", tags=["authentication"])
log = logging.getLogger("enterpriseflow.auth")
EMPLOYEE = {"documents:read", "documents:upload", "workflows:read", "workflows:run", "agents:read", "agents:execute", "conversations:write", "analytics:read", "approvals:read"}
ROLE_PERMISSIONS = {
    "employee": EMPLOYEE,
    "manager": EMPLOYEE | {"approvals:decide", "workflows:manage", "audit:read"},
    "department_admin": EMPLOYEE | {"approvals:decide", "workflows:manage", "audit:read", "agents:manage", "members:manage", "documents:delete"},
    "platform_admin": {"platform:admin", "agents:manage", "agents:read", "members:manage", "settings:manage"},
    "auditor": {"audit:read"},
}


@dataclass
class Principal:
    id: str
    email: str = ""
    name: str = ""
    roles: list[str] = field(default_factory=list)
    department_ids: list[str] = field(default_factory=list)
    permissions: set[str] = field(default_factory=set)
    csrf_token: str = ""
    department_permissions: dict[str, set[str]] | None = None


def require_permission(principal: Principal, permission: str):
    if permission not in principal.permissions:
        raise HTTPException(403, "Permission denied")


def authorize_department(principal: Principal, department_id: str, permission: str | None = None):
    if department_id not in principal.department_ids:
        raise HTTPException(403, "Department access denied")
    if permission:
        require_permission(principal, permission)
        if principal.department_permissions is not None and permission not in principal.department_permissions.get(department_id, set()):
            raise HTTPException(403, "Department permission denied")


def principal_for_user(db: Session, user_id: str) -> Principal:
    # Long-running workers and streams reuse sessions. Refresh identity and role
    # rows so the identity map cannot preserve permissions revoked elsewhere.
    user = db.scalar(select(User).where(User.id == user_id).execution_options(populate_existing=True))
    if not user or not user.active:
        raise HTTPException(401, "Account inactive or not onboarded")
    memberships = list(db.scalars(select(Membership).where(Membership.user_id == user.id)
                                  .execution_options(populate_existing=True)))
    scopes = {m.department_id: set(ROLE_PERMISSIONS.get(m.role, set())) for m in memberships}
    roles = list(set(user.roles + [m.role for m in memberships]))
    permissions = set().union(*(ROLE_PERMISSIONS.get(r, set()) for r in user.roles), *scopes.values())
    principal = Principal(user.id, user.email, user.name, roles, list(scopes), permissions, department_permissions=scopes)
    set_scope(db, user.id, principal.department_ids)
    return principal


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def cipher() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(get_settings().session_cookie_secret.encode()).digest()))


@lru_cache
def jwks_client() -> jwt.PyJWKClient:
    s = get_settings()
    return jwt.PyJWKClient(s.oidc_jwks_url or f"{s.oidc_issuer}/protocol/openid-connect/certs", cache_keys=True, lifespan=300, timeout=10)


def validate_token(token: str, audience: str | None = None) -> dict:
    s = get_settings()
    try:
        key = jwks_client().get_signing_key_from_jwt(token)
        return jwt.decode(token, key.key, algorithms=["RS256"], audience=audience or s.oidc_audience, issuer=s.oidc_issuer, options={"require": ["exp", "iat", "sub", "iss", "aud"]}, leeway=10)
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(401, "Invalid or expired identity token") from exc


def token_endpoint() -> str:
    s = get_settings()
    return s.oidc_token_url or f"{s.oidc_issuer}/protocol/openid-connect/token"


def get_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    token = request.headers.get("authorization", "")
    if token.startswith("Bearer "):
        claims = validate_token(token[7:])
        user = db.scalar(select(User).where(User.subject == claims["sub"]))
        if not user:
            raise HTTPException(401, "Account has not been onboarded")
        p = principal_for_user(db, user.id)
    else:
        raw = request.cookies.get("ef_session")
        session = db.get(SessionRecord, hashlib.sha256(raw.encode()).hexdigest()) if raw else None
        if not session or aware(session.expires_at) <= utcnow():
            raise HTTPException(401, "Sign in to continue")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), session.csrf_token):
                raise HTTPException(403, "Invalid CSRF token")
            origin = request.headers.get("origin")
            if origin and origin not in get_settings().allowed_origins.split(","):
                raise HTTPException(403, "Origin not allowed")
        if aware(session.token_expires_at) <= utcnow() + timedelta(seconds=20):
            # Concurrent page requests must not rotate the same refresh token twice.
            # Reload after taking the row lock because another request may have refreshed it.
            session = db.scalar(select(SessionRecord).where(SessionRecord.id == session.id)
                                .with_for_update().execution_options(populate_existing=True))
            if not session or aware(session.expires_at) <= utcnow():
                raise HTTPException(401, "Session expired. Sign in again.")
            if aware(session.token_expires_at) <= utcnow() + timedelta(seconds=20):
                try:
                    data = {"grant_type": "refresh_token", "client_id": get_settings().oidc_client_id, "refresh_token": cipher().decrypt(session.refresh_token.encode()).decode()}
                    if get_settings().oidc_client_secret:
                        data["client_secret"] = get_settings().oidc_client_secret
                    response = httpx.post(token_endpoint(), data=data, timeout=10)
                    response.raise_for_status()
                    tokens = response.json()
                    claims = validate_token(tokens["access_token"])
                    session_user = db.get(User, session.user_id)
                    if not session_user or claims["sub"] != session_user.subject:
                        raise ValueError("Subject changed")
                    session.access_token = cipher().encrypt(tokens["access_token"].encode()).decode()
                    if tokens.get("refresh_token"):
                        session.refresh_token = cipher().encrypt(tokens["refresh_token"].encode()).decode()
                    session.token_expires_at = datetime.fromtimestamp(claims["exp"], timezone.utc)
                    db.commit()
                except Exception as exc:
                    db.delete(session)
                    db.commit()
                    raise HTTPException(401, "Session expired. Sign in again.") from exc
            else:
                db.commit()  # Release the lock without repeating a completed refresh.
        p = principal_for_user(db, session.user_id)
        p.csrf_token = session.csrf_token
    request.state.principal = p
    return p


@router.get("/login")
def login(db: Session = Depends(get_db)):
    s = get_settings()
    state, verifier, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(64), secrets.token_urlsafe(32)
    db.add(LoginState(id=state, verifier=verifier, nonce=nonce, expires_at=utcnow() + timedelta(minutes=5)))
    db.commit()
    params = {"response_type": "code", "client_id": s.oidc_client_id, "redirect_uri": f"{s.api_public_url}/api/v1/auth/callback", "scope": "openid profile email", "state": state, "nonce": nonce, "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode(), "code_challenge_method": "S256"}
    response = RedirectResponse((s.oidc_authorize_url or f"{s.oidc_issuer}/protocol/openid-connect/auth") + "?" + urlencode(params))
    response.set_cookie("ef_login", state, httponly=True, secure=s.is_production, samesite="lax", max_age=300, path="/api/v1/auth")
    return response


@router.get("/callback")
def callback(request: Request, state: str, code: str, db: Session = Depends(get_db)):
    s = get_settings()
    row = db.scalar(select(LoginState).where(LoginState.id == state).with_for_update())
    if not row or aware(row.expires_at) < utcnow() or not hmac.compare_digest(state, request.cookies.get("ef_login", "")):
        raise HTTPException(400, "Invalid or expired login state")
    verifier, nonce = row.verifier, row.nonce
    db.delete(row)
    db.commit()
    payload = {"grant_type": "authorization_code", "code": code, "redirect_uri": f"{s.api_public_url}/api/v1/auth/callback", "client_id": s.oidc_client_id, "code_verifier": verifier}
    if s.oidc_client_secret:
        payload["client_secret"] = s.oidc_client_secret
    try:
        result = httpx.post(token_endpoint(), data=payload, timeout=15)
        result.raise_for_status()
        tokens = result.json()
        identity = validate_token(tokens["id_token"], s.oidc_client_id)
        claims = validate_token(tokens["access_token"])
        if identity.get("nonce") != nonce or identity["sub"] != claims["sub"]:
            raise ValueError("Identity verification failed")
    except Exception as exc:
        # Exception messages can contain authorization codes or token URLs.
        # Log only exception class names and the existing request correlation.
        cause = exc.__cause__ or exc
        log.warning("oidc_sign_in_failed request_id=%s exception_type=%s cause_type=%s",
                    request_id.get(), type(exc).__name__, type(cause).__name__)
        raise HTTPException(401, "Identity provider sign-in failed") from exc
    user = db.scalar(select(User).where(User.subject == claims["sub"], User.active.is_(True)))
    if not user:
        raise HTTPException(403, "Ask an administrator to onboard your identity")
    cookie = secrets.token_urlsafe(48)
    db.add(SessionRecord(id=hashlib.sha256(cookie.encode()).hexdigest(), user_id=user.id, csrf_token=secrets.token_urlsafe(32), access_token=cipher().encrypt(tokens["access_token"].encode()).decode(), refresh_token=cipher().encrypt(tokens.get("refresh_token", "").encode()).decode(), id_token=cipher().encrypt(tokens["id_token"].encode()).decode(), token_expires_at=datetime.fromtimestamp(claims["exp"], timezone.utc), expires_at=utcnow() + timedelta(seconds=s.session_ttl_seconds)))
    db.commit()
    response = RedirectResponse(s.frontend_url, status_code=303)
    response.delete_cookie("ef_login", path="/api/v1/auth")
    response.set_cookie("ef_session", cookie, httponly=True, secure=s.is_production, samesite="lax", max_age=s.session_ttl_seconds, path="/")
    return response


@router.get("/me")
def me(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    departments = db.scalars(select(Department).where(Department.id.in_(p.department_ids))).all()
    return {"id": p.id, "email": p.email, "name": p.name, "roles": p.roles, "department_ids": p.department_ids, "permissions": sorted(p.permissions), "department_permissions": {k: sorted(v) for k, v in (p.department_permissions or {}).items()}, "departments": [{"id": d.id, "name": d.name, "slug": d.slug} for d in departments], "csrf_token": p.csrf_token}


@router.post("/logout")
def logout(request: Request, response: Response, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    raw = request.cookies.get("ef_session", "")
    session = db.get(SessionRecord, hashlib.sha256(raw.encode()).hexdigest())
    logout_url = None
    if session:
        s = get_settings()
        params = {"id_token_hint": cipher().decrypt(session.id_token.encode()).decode(), "post_logout_redirect_uri": s.frontend_url, "client_id": s.oidc_client_id}
        logout_url = (s.oidc_logout_url or f"{s.oidc_issuer}/protocol/openid-connect/logout") + "?" + urlencode(params)
        db.delete(session)
        db.commit()
    response.delete_cookie("ef_session", path="/")
    return {"status": "signed_out", "logout_url": logout_url}
