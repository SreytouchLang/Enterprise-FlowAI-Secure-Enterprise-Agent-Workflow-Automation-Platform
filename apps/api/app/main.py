import json
import logging
import re
import time
import uuid

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sqlalchemy.exc import IntegrityError

from app import agents, auth, documents, evaluations, platform, rag
from app.api.health import router as health_router
from app.audit import request_id
from app.core.config import get_settings
from app.providers import ProviderError

log = logging.getLogger("enterpriseflow")
REQUESTS = Counter("enterpriseflow_http_requests_total", "HTTP responses", ["method", "route", "status"])
LATENCY = Histogram("enterpriseflow_http_duration_seconds", "HTTP request latency", ["route"])


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins.split(","), allow_credentials=True, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID", "Idempotency-Key"], expose_headers=["X-Request-ID"])

    @app.middleware("http")
    async def request_middleware(request: Request, call_next):
        started = time.monotonic()
        incoming = request.headers.get("x-request-id", "")
        correlation = incoming if re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", incoming) else str(uuid.uuid4())
        token = request_id.set(correlation)
        request.state.request_id = correlation
        try:
            response = await call_next(request)
        except Exception:
            # Never include exception messages, URL query strings, prompts or token data in logs.
            log.error(json.dumps({"event": "unhandled_error", "request_id": correlation}))
            response = JSONResponse({"error": {"code": "internal_error", "message": "The request could not be completed", "request_id": correlation}}, status_code=500)
        route = getattr(request.scope.get("route"), "path", "unmatched")
        REQUESTS.labels(request.method, route, str(response.status_code)).inc()
        LATENCY.labels(route).observe(time.monotonic() - started)
        log.info(json.dumps({"event": "http_request", "request_id": correlation, "method": request.method, "route": route, "status": response.status_code, "duration_ms": round((time.monotonic() - started) * 1000)}))
        response.headers["x-request-id"] = correlation
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["referrer-policy"] = "no-referrer"
        response.headers["cache-control"] = "no-store"
        if settings.is_production:
            response.headers["strict-transport-security"] = "max-age=31536000; includeSubDomains"
        request_id.reset(token)
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse({"error": {"code": f"http_{exc.status_code}", "message": exc.detail, "request_id": getattr(request.state, "request_id", "")}}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        fields = [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse({"error": {"code": "validation_error", "message": "Request validation failed", "fields": fields, "request_id": request.state.request_id}}, status_code=422)

    @app.exception_handler(ProviderError)
    async def provider_error(request, exc):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message, "request_id": request.state.request_id}}, status_code=503 if "configured" in exc.code or "provider" in exc.code else 422)

    @app.exception_handler(IntegrityError)
    async def conflict(request, exc):
        return JSONResponse({"error": {"code": "conflict", "message": "This record conflicts with existing data", "request_id": request.state.request_id}}, status_code=409)

    app.include_router(health_router)
    for router in (auth.router, documents.router, rag.router, agents.router, platform.router, evaluations.router):
        app.include_router(router, prefix="/api/v1")
    from app import business, jobs, workflows
    app.include_router(business.router, prefix="/api/v1")
    app.include_router(jobs.router, prefix="/api/v1")
    app.include_router(workflows.router, prefix="/api/v1")

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    if settings.otel_exporter_otlp_endpoint:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        provider = TracerProvider()
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/traces")))
        trace.set_tracer_provider(provider)
        # Auth callback carries the authorization code in the URL and is excluded entirely.
        def redact_request_url(span, scope):
            if span and span.is_recording():
                path = scope.get("path", "/")
                span.set_attribute("http.url", path)
                span.set_attribute("url.full", path)
                span.set_attribute("url.query", "")
                span.set_attribute("http.target", path)
        FastAPIInstrumentor.instrument_app(app, excluded_urls=".*auth.*", server_request_hook=redact_request_url, http_capture_headers_server_request=[], http_capture_headers_server_response=[])
    return app


app = create_app()
