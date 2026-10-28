from fastapi import APIRouter, Response
from redis import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.db import get_engine

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(response: Response) -> dict[str, object]:
    s = get_settings()
    checks = {}
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"
    try:
        with Redis.from_url(s.redis_url, socket_connect_timeout=2, socket_timeout=2) as redis:
            redis.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"
    checks["llm_provider"] = "configured" if s.llm_provider_configured else "not_configured"
    healthy = checks["database"] == "ok" and checks["redis"] == "ok" and (s.llm_provider_configured or not s.is_production)
    if not healthy:
        response.status_code = 503
    return {"status": "ready" if healthy else "not_ready", "mode": s.app_env, "checks": checks}
