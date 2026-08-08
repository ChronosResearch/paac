"""
PAAC FastAPI application — v5.0.0
Steps 39-50: health, metrics, rate limiting, API key auth, request validation.
Steps 76-85: Prometheus metrics, structured logging.
v5.0.0: bootstrap self-verification, cryptographic attestation, multi-agent.
"""

from __future__ import annotations

import multiprocessing as _mp

# A-04 fix: use spawn so Z3 subprocesses do not inherit open file descriptors
# or partially-initialised thread state from the parent (fork-under-threads).
if _mp.get_start_method(allow_none=True) != "spawn":
    _mp.set_start_method("spawn", force=True)

import os
import re as _re
import secrets
import sys
import time
import traceback
from collections import defaultdict
from typing import Any

import yaml
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from loguru import logger
from pydantic import BaseModel, field_validator

from .core.attestation import get_engine as get_attest_engine
from .core.self_verify import get_self_verifier
from .monitor.code_monitor import CodeModification, CodeMonitor
from .monitor.watchdog import Watchdog

# ---------------------------------------------------------------------------
# Structured JSON logging
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
# Prometheus metrics
# ---------------------------------------------------------------------------

try:
    from prometheus_client import (
        Counter,
        Gauge,
        Histogram,
    )

    _PROM_AVAILABLE = True
    _verifications_total = Counter(
        "verifications_total", "Total verification requests", ["outcome"]
    )
    _verification_errors_total = Counter(
        "verification_errors_total", "Total verification errors"
    )
    _circuit_breaker_state = Counter(
        "circuit_breaker_state_changes_total",
        "Circuit breaker state changes",
        ["state"],
    )
    _verification_latency = Histogram(
        "verification_latency_seconds",
        "Verification latency in seconds",
        buckets=[0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0],
    )
    _active_verifications = Gauge(
        "active_verifications", "Currently active verification requests"
    )
    _attestations_total = Counter("attestations_total", "Total attestations generated")
    _attestation_latency = Histogram(
        "attestation_latency_seconds",
        "Attestation generation latency in seconds",
        buckets=[0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5],
    )
    _self_verify_total = Counter(
        "self_verify_total", "Total self-verification runs", ["result"]
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
# API key auth
# ---------------------------------------------------------------------------

_API_KEY = os.environ.get("PAAC_API_KEY", "")

# ---------------------------------------------------------------------------
# Rate limiting: 100 req/min per IP
# ---------------------------------------------------------------------------

_RATE_LIMIT = int(os.environ.get("PAAC_RATE_LIMIT", "100"))
_RATE_WINDOW_S = 60
_rate_counters: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(ip: str) -> bool:
    now = time.monotonic()
    _rate_counters[ip] = [t for t in _rate_counters[ip] if now - t < _RATE_WINDOW_S]
    if len(_rate_counters[ip]) >= _RATE_LIMIT:
        return False
    _rate_counters[ip].append(now)
    return True


# ---------------------------------------------------------------------------
# Input sanitization: reject non-SIL characters
# ---------------------------------------------------------------------------

_SIL_SAFE_RE = _re.compile(r"^[\x20-\x7E\n\r\t]*$")


def _sanitize_sil(code: str) -> str:
    if not _SIL_SAFE_RE.match(code):
        raise ValueError("SIL code contains non-printable or non-ASCII characters.")
    return code


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

monitor = CodeMonitor(config)
watchdog = Watchdog(config)
watchdog.start()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Startup / shutdown lifecycle (replaces deprecated @app.on_event)."""
    # startup: bootstrap self-verification if configured
    _bootstrap_cfg = config.get("bootstrap_verification", {})
    if _bootstrap_cfg.get("run_on_startup", False):
        try:
            sv = get_self_verifier()
            _sv_result = sv.run()
            if not _sv_result.passed:
                logger.error(f"Startup self-verification FAILED: {_sv_result.message}")
            else:
                logger.info(f"Startup self-verification PASSED: {_sv_result.message}")
        except Exception as _sv_exc:  # noqa: BLE001
            logger.warning(f"Startup self-verification error (non-fatal): {_sv_exc}")
    yield
    # shutdown
    watchdog.stop()
    monitor.stop_watchdog()


app = FastAPI(
    title="PAAC API",
    description="Provably Aligned Core Verification API v5.0.0",
    version="5.0.0",
    lifespan=_lifespan,
)


# ---------------------------------------------------------------------------
# Middleware: rate limiting + API key
# ---------------------------------------------------------------------------


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # Skip auth/rate for health and metrics
    if request.url.path in ("/health", "/metrics"):
        return await call_next(request)

    # API key check (A-03: constant-time comparison)
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
# Request models
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
# Core endpoints
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

        # Generate attestation if enabled and accepted
        attest_cfg = config.get("attestation", {})
        if attest_cfg.get("enabled", True) and result.get("status") == "accepted":
            try:
                import hashlib

                engine = get_attest_engine()
                prog_hash = hashlib.sha256(req.new_code.encode()).hexdigest()
                axiom_hash = engine.hash_axioms([a.condition for a in monitor.axioms])
                mod_id = f"{req.func_name}:{int(time.time())}"
                t_attest = time.monotonic()
                record = engine.attest(mod_id, prog_hash, axiom_hash, True, None)
                attest_elapsed = time.monotonic() - t_attest
                result["attestation_id"] = mod_id
                result["attestation_commitment"] = record.commitment[:16] + "..."
                if _PROM_AVAILABLE:
                    _attestations_total.inc()
                    _attestation_latency.observe(attest_elapsed)
            except Exception as _ae:  # noqa: BLE001
                logger.warning(f"Attestation generation failed (non-fatal): {_ae}")

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
    """Health endpoint — returns healthy/degraded/unhealthy."""
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

    # Include self-verification status if available
    sv = get_self_verifier()
    sv_result = sv.last_result
    sv_status = (
        "passed"
        if sv_result and sv_result.passed
        else "failed" if sv_result and not sv_result.passed else "not_run"
    )

    attest_metrics = get_attest_engine().metrics()

    return JSONResponse(
        status_code=http_code,
        content={
            "status": status,
            "version": "5.0.0",
            "circuit_breaker": cb_state,
            "axioms_loaded": len(monitor.axioms),
            "registry_size": len(CodeMonitor._live_registry),
            "self_verification": sv_status,
            "attestation": attest_metrics,
        },
    )


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    if not _PROM_AVAILABLE:
        return PlainTextResponse(
            "# prometheus_client not installed\n", media_type="text/plain"
        )
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------------------
# Bootstrap self-verification endpoint
# ---------------------------------------------------------------------------


@app.post("/self-verify")
async def self_verify_endpoint():
    """
    Run bootstrap self-verification of the PAAC TCB.

    Translates TCB function contracts to SIL stubs and verifies them
    against PAAC's own structural invariants.
    """
    sv = get_self_verifier()
    result = sv.run()

    if _PROM_AVAILABLE:
        _self_verify_total.labels(result="passed" if result.passed else "failed").inc()

    return {
        "passed": result.passed,
        "stage": result.stage,
        "elapsed_ms": round(result.elapsed_ms, 1),
        "stubs_verified": len(result.stub_results),
        "stubs_failed": sum(1 for v in result.stub_results.values() if not v),
        "message": result.message,
        "counterexamples": result.counterexamples,
    }


# ---------------------------------------------------------------------------
# Attestation endpoints
# ---------------------------------------------------------------------------


@app.get("/attest/{modification_id}")
async def get_attestation(modification_id: str):
    """
    Retrieve the attestation record for a given modification ID.
    Returns the full HMAC-SHA256 commitment and metadata.
    """
    engine = get_attest_engine()
    record = engine.get(modification_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"No attestation found for modification_id={modification_id!r}.",
        )
    return record.to_dict()


@app.post("/attest/verify")
async def verify_attestation_endpoint(record_data: dict):
    """
    Verify an attestation record submitted by a third party.
    Returns {valid: true/false}.
    """
    from .core.attestation import AttestationRecord, verify_attestation

    try:
        record = AttestationRecord.from_dict(record_data)
        valid = verify_attestation(record)
        return {"valid": valid}
    except (KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid attestation record: {exc}"
        )


# ---------------------------------------------------------------------------
# Multi-agent endpoints
# ---------------------------------------------------------------------------


@app.get("/agents")
async def list_agents():
    """List all registered agents and their status."""
    # Use a module-level verifier instance
    verifier = _get_compositional_verifier()
    statuses = verifier.agent_statuses()
    metrics = verifier.metrics()
    return {
        "agents": [
            {
                "agent_id": s.agent_id,
                "active_func": s.active_func,
                "queued_count": s.queued_count,
                "last_seen": s.last_seen,
            }
            for s in statuses
        ],
        "metrics": metrics,
    }


# Module-level compositional verifier singleton
_compositional_verifier = None
_cv_lock = __import__("threading").Lock()


def _get_compositional_verifier():
    global _compositional_verifier
    with _cv_lock:
        if _compositional_verifier is None:
            from .core.compositional import CompositionalVerifier

            _compositional_verifier = CompositionalVerifier(
                timeout_ms=config.get("verification_timeout_ms", 5000)
            )
    return _compositional_verifier


# ---------------------------------------------------------------------------
# Exception handler and shutdown
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def panic_hook(request: Request, exc: Exception):
    """Panic hook — log unhandled exceptions with ERROR level."""
    logger.error(
        f"PANIC: unhandled exception on {request.url.path}: "
        f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    )
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error. Incident logged."},
    )


# Shutdown is handled by the _lifespan context manager above.
