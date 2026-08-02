"""
PAAC FastAPI application.
Steps 39-50: health, metrics, rate limiting, API key auth, request validation.
Steps 76-85: Prometheus metrics, structured logging.
"""
from __future__ import annotations

import multiprocessing as _mp

# A-04 fix: use spawn so Z3 subprocesses do not inherit open file descriptors
# or partially-initialised thread state from the parent (fork-under-threads).
if _mp.get_start_method(allow_none=True) != "spawn":
    _mp.set_start_method("spawn", force=True)

import os
import secrets
import sys
import time
import traceback
from collections import defaultdict
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from loguru import logger
from pydantic import BaseModel, field_validator

from .monitor.code_monitor import CodeModification, CodeMonitor
from .monitor.watchdog import Watchdog

# ---------------------------------------------------------------------------
# Structured JSON logging (Step 76)
# ---------------------------------------------------------------------------

logger.remove()
logger.add(
    sys.stdout,
    level="INFO",
    format=(
        '{{"time":"{time:YYYY-MM-DDTHH:mm:ss.SSSZ}",'
        '"level":"{level}",'
        '"message":"{message}"}}'
    ),
    serialize=False,
)
logger.add("paac_core.log", rotation="10 MB", level="DEBUG", serialize=True)

# ---------------------------------------------------------------------------
# Prometheus metrics (Steps 77-81)
# ---------------------------------------------------------------------------

try:
    from prometheus_client import (
        Counter,
        Gauge,
        Histogram,
        generate_latest,
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        REGISTRY,
    )
    _PROM_AVAILABLE = True
    _verifications_total = Counter(
        "verifications_total", "Total verification requests", ["outcome"]
    )
    _verification_errors_total = Counter(
        "verification_errors_total", "Total verification errors"
    )
    _circuit_breaker_state = Counter(
        "circuit_breaker_state_changes_total", "Circuit breaker state changes", ["state"]
    )
    _verification_latency = Histogram(
        "verification_latency_seconds",
        "Verification latency in seconds",
        buckets=[0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0],
    )
    _active_verifications = Gauge(
        "active_verifications", "Currently active verification requests"
    )
except ImportError:
    _PROM_AVAILABLE = False

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

try:
    with open("config/default.yaml") as f:
        config: dict[str, Any] = yaml.safe_load(f) or {}
except FileNotFoundError:
    config = {}

# ---------------------------------------------------------------------------
# API key auth (Step 40)
# ---------------------------------------------------------------------------

_API_KEY = os.environ.get("PAAC_API_KEY", "")

# ---------------------------------------------------------------------------
# Rate limiting (Steps 39, 87): 100 req/min per IP
# ---------------------------------------------------------------------------

_RATE_LIMIT = int(os.environ.get("PAAC_RATE_LIMIT", "100"))
_RATE_WINDOW_S = 60
_rate_counters: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(ip: str) -> bool:
    now = time.monotonic()
    window = _rate_counters[ip]
    # Evict old entries
    _rate_counters[ip] = [t for t in window if now - t < _RATE_WINDOW_S]
    if len(_rate_counters[ip]) >= _RATE_LIMIT:
        return False
    _rate_counters[ip].append(now)
    return True


# ---------------------------------------------------------------------------
# Input sanitization (Step 88): reject non-SIL characters
# ---------------------------------------------------------------------------

import re as _re

_SIL_SAFE_RE = _re.compile(r'^[\x20-\x7E\n\r\t]*$')


def _sanitize_sil(code: str) -> str:
    if not _SIL_SAFE_RE.match(code):
        raise ValueError("SIL code contains non-printable or non-ASCII characters.")
    return code


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="PAAC API",
    description="Provably Aligned Core Verification API v4.1",
    version="4.1.0",
)

monitor = CodeMonitor(config)
watchdog = Watchdog(config)
watchdog.start()


# ---------------------------------------------------------------------------
# Middleware: rate limiting + API key (Steps 39-40)
# ---------------------------------------------------------------------------

@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # Skip auth/rate for health and metrics
    if request.url.path in ("/health", "/metrics"):
        return await call_next(request)

    # API key check (A-03 fix: constant-time comparison via secrets.compare_digest)
    if _API_KEY:
        key = request.headers.get("X-API-Key", "")
        if not secrets.compare_digest(key, _API_KEY):
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid or missing API key."},
            )

    # Rate limiting
    ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(ip):
        return JSONResponse(
            status_code=429,
            content={"error": "Rate limit exceeded. Max 100 requests/minute."},
        )

    return await call_next(request)


# ---------------------------------------------------------------------------
# Request model with validation (Step 41)
# ---------------------------------------------------------------------------

class ModificationRequest(BaseModel):
    func_name: str
    old_code: str
    new_code: str
    pre_cond: str
    post_cond: str
    source_citation: str = ""

    @field_validator("func_name")
    @classmethod
    def func_name_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("func_name must not be empty.")
        return v

    @field_validator("new_code")
    @classmethod
    def new_code_sanitized(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("new_code must not be empty.")
        _sanitize_sil(v)
        return v


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/verify")
async def verify_modification(req: ModificationRequest, request: Request):
    """Verify and apply a proposed code modification."""
    watchdog.heartbeat()
    start = time.monotonic()

    if _PROM_AVAILABLE:
        _active_verifications.inc()

    try:
        mod = CodeModification(**req.model_dump())
        result = monitor.intercept_modification(mod)
        elapsed = time.monotonic() - start

        if _PROM_AVAILABLE:
            outcome = result.get("status", "error")
            _verifications_total.labels(outcome=outcome).inc()
            _verification_latency.observe(elapsed)
            if outcome == "error":
                _verification_errors_total.inc()

        return result
    except Exception as exc:  # noqa: BLE001
        elapsed = time.monotonic() - start
        logger.error(f"Unhandled exception in /verify: {exc}\n{traceback.format_exc()}")
        if _PROM_AVAILABLE:
            _verification_errors_total.inc()
            _verifications_total.labels(outcome="error").inc()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        if _PROM_AVAILABLE:
            _active_verifications.dec()


@app.get("/health")
async def health():
    """Step 42: Health endpoint — returns healthy/degraded/unhealthy."""
    from .core.failsafe import CircuitBreaker
    cb_state = CodeMonitor._circuit_breaker.state

    if cb_state == "OPEN":
        status = "unhealthy"
        http_code = 503
    elif cb_state == "HALF_OPEN":
        status = "degraded"
        http_code = 200
    else:
        status = "healthy"
        http_code = 200

    return JSONResponse(
        status_code=http_code,
        content={
            "status": status,
            "circuit_breaker": cb_state,
            "axioms_loaded": len(monitor.axioms),
            "registry_size": len(CodeMonitor._live_registry),
        },
    )


@app.get("/metrics")
async def metrics():
    """Step 77/85: Prometheus metrics endpoint."""
    if not _PROM_AVAILABLE:
        return PlainTextResponse(
            "# prometheus_client not installed\n", media_type="text/plain"
        )
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@app.exception_handler(Exception)
async def panic_hook(request: Request, exc: Exception):
    """Step 63: Panic hook — log unhandled exceptions with ERROR level."""
    logger.error(
        f"PANIC: unhandled exception on {request.url.path}: "
        f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    )
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error. Incident logged."},
    )


@app.on_event("shutdown")
def shutdown_event():
    watchdog.stop()
    monitor.stop_watchdog()
