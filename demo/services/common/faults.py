"""Fault state + admin endpoints, shared by every service.

Faults are toggled with POST /admin/fault. Injection is deliberately NOT logged and
NOT exposed as a metric: the agent must infer causes from symptoms, not read the answer.
The only exception is a version change, which logs a `deploy` event (that is a legit
signal an on-call engineer would see in a change log).
"""
import asyncio
import logging
import os
from dataclasses import dataclass, asdict

from fastapi import APIRouter
from prometheus_client import Gauge
from pydantic import BaseModel, Field

SERVICE = os.getenv("SERVICE_NAME", "unknown")
DEFAULT_VERSION = os.getenv("SERVICE_VERSION", "v1.0.0")
log = logging.getLogger("app")

APP_INFO = Gauge("app_version_info", "Running version of the service", ["service", "version"])


@dataclass
class FaultState:
    slow_db_ms: int = 0          # extra time each DB connection is held (SELECT SLEEP)
    latency_ms: int = 0          # extra latency on every request (bad deploy / downstream hang)
    error_rate: float = 0.0      # fraction of requests that raise (bad deploy)
    leak_mb_per_s: float = 0.0   # memory leak rate
    version: str = DEFAULT_VERSION


state = FaultState()
_leak_store: list = []


def publish_version() -> None:
    APP_INFO.clear()
    APP_INFO.labels(SERVICE, state.version).set(1)


def _deploy(new_version: str) -> None:
    old = state.version
    state.version = new_version
    publish_version()
    log.info(f"deployed {SERVICE} {old} -> {new_version}",
             extra={"fields": {"event": "deploy", "from_version": old, "to_version": new_version}})


async def leak_loop() -> None:
    while True:
        await asyncio.sleep(1)
        if state.leak_mb_per_s > 0:
            _leak_store.append(b"x" * int(state.leak_mb_per_s * 1024 * 1024))


def start_background() -> None:
    asyncio.get_event_loop().create_task(leak_loop())


class FaultUpdate(BaseModel):
    slow_db_ms: int | None = Field(None, ge=0)
    latency_ms: int | None = Field(None, ge=0)
    error_rate: float | None = Field(None, ge=0, le=1)
    leak_mb_per_s: float | None = Field(None, ge=0)
    version: str | None = None


router = APIRouter(prefix="/admin")


@router.get("/fault")
async def get_fault():
    return asdict(state)


@router.post("/fault")
async def set_fault(update: FaultUpdate):
    data = update.model_dump(exclude_none=True)
    new_version = data.pop("version", None)
    for k, v in data.items():
        setattr(state, k, v)
    if data.get("leak_mb_per_s") == 0:
        _leak_store.clear()
    if new_version and new_version != state.version:
        _deploy(new_version)
    return asdict(state)


@router.delete("/fault")
async def reset_fault():
    """Silent reset (used between eval runs)."""
    state.slow_db_ms = 0
    state.latency_ms = 0
    state.error_rate = 0.0
    state.leak_mb_per_s = 0.0
    state.version = DEFAULT_VERSION
    _leak_store.clear()
    publish_version()
    return asdict(state)
