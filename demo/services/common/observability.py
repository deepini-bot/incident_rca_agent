"""Logging (JSON), metrics (Prometheus), tracing (OpenTelemetry) and fault hooks."""
import asyncio
import json
import logging
import os
import random
import sys
import time
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from . import faults

SERVICE = os.getenv("SERVICE_NAME", "unknown")
log = logging.getLogger("app")

REQS = Counter("http_requests_total", "HTTP requests", ["service", "method", "path", "status"])
LAT = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["service", "method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
SKIP_PREFIXES = ("/metrics", "/health", "/admin")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        d = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "service": SERVICE,
            "msg": record.getMessage(),
        }
        ctx = trace.get_current_span().get_span_context()
        if ctx.is_valid:
            d["trace_id"] = format(ctx.trace_id, "032x")
        d.update(getattr(record, "fields", {}))
        if record.exc_info:
            d["exc"] = self.formatException(record.exc_info)
        return json.dumps(d)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    logging.getLogger("httpx").setLevel(logging.WARNING)


def setup_tracing(app: FastAPI) -> None:
    resource = Resource.create({"service.name": SERVICE, "service.version": faults.DEFAULT_VERSION})
    provider = TracerProvider(resource=resource)
    endpoint = os.getenv("OTLP_ENDPOINT", "http://tempo:4318/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    HTTPXClientInstrumentor().instrument()
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,metrics,admin")


async def request_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith(SKIP_PREFIXES):
        return await call_next(request)
    start = time.perf_counter()
    st = faults.state
    try:
        if st.latency_ms > 0:
            await asyncio.sleep(st.latency_ms / 1000)
        if st.error_rate > 0 and random.random() < st.error_rate:
            raise RuntimeError(
                f"unhandled exception in {request.method} {path}: KeyError 'discount_code' "
                f"(version {st.version})"
            )
        response = await call_next(request)
    except Exception:
        log.exception("unhandled exception while handling request")
        response = JSONResponse({"detail": "internal error"}, status_code=500)
    status = response.status_code
    dur = time.perf_counter() - start
    route = request.scope.get("route")
    tmpl = route.path if route else path
    REQS.labels(SERVICE, request.method, tmpl, str(status)).inc()
    LAT.labels(SERVICE, request.method, tmpl).observe(dur)
    level = logging.ERROR if status >= 500 else logging.WARNING if status >= 400 else logging.INFO
    log.log(level, f"{request.method} {tmpl} -> {status}", extra={"fields": {
        "event": "request", "method": request.method, "path": tmpl,
        "status": status, "duration_ms": round(dur * 1000, 1),
    }})
    return response


def setup_service(app: FastAPI) -> None:
    setup_logging()
    app.include_router(faults.router)
    faults.publish_version()

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": SERVICE, "version": faults.state.version}

    @app.get("/metrics")
    async def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # Our middleware first, tracing last, so the OTel span wraps everything (outermost).
    app.middleware("http")(request_middleware)
    setup_tracing(app)
    app.add_event_handler("startup", faults.start_background)
