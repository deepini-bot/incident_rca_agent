"""Outbound service-to-service calls with metrics and consistent error mapping."""
import logging
import os
import time

import httpx
from fastapi import HTTPException
from prometheus_client import Histogram

SERVICE = os.getenv("SERVICE_NAME", "unknown")
TIMEOUT_S = float(os.getenv("DOWNSTREAM_TIMEOUT_S", "2"))
log = logging.getLogger("app")

DOWNSTREAM = Histogram(
    "downstream_request_duration_seconds", "Outbound call latency", ["service", "target", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT_S))


async def call_json(client: httpx.AsyncClient, target: str, method: str, path: str, **kw):
    """Call http://<target>:8000<path>. Raises HTTPException with a sensible status on failure."""
    url = f"http://{target}:8000{path}"
    start = time.perf_counter()
    status = "error"
    try:
        r = await client.request(method, url, **kw)
        status = str(r.status_code)
    except httpx.TimeoutException:
        status = "timeout"
        log.error(f"call to {target} {method} {path} timed out after {TIMEOUT_S}s",
                  extra={"fields": {"event": "downstream_timeout", "target": target}})
        raise HTTPException(504, f"{target} timed out")
    except httpx.HTTPError as e:
        log.error(f"call to {target} {method} {path} failed: {e!r}",
                  extra={"fields": {"event": "downstream_error", "target": target}})
        raise HTTPException(502, f"{target} unavailable")
    finally:
        DOWNSTREAM.labels(SERVICE, target, status).observe(time.perf_counter() - start)

    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", "error")
        except Exception:
            detail = "error"
        log.warning(f"{target} {method} {path} returned {r.status_code}: {detail}",
                    extra={"fields": {"event": "downstream_status", "target": target,
                                      "status": r.status_code}})
        raise HTTPException(r.status_code if r.status_code < 500 else 502, f"{target}: {detail}")
    return r.json()
