"""
src/core/failsafe.py
--------------------
Fail-safe mechanisms for PAAC v4.1:
  - CircuitBreaker: opens after 5 consecutive verification failures; half-open
    probe after 60 s cooldown; closes on first successful probe.
  - WALCheckpointStore: write-ahead log on disk; replays on startup so
    checkpoints survive process restarts when Redis is unavailable.
  - RegistryPersistence: persists _live_registry to a JSON file after every
    accepted modification; loads it on startup.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

_CB_FAILURE_THRESHOLD = 5   # consecutive failures before opening
_CB_COOLDOWN_S = 60.0       # seconds to wait before half-open probe


class CircuitOpenError(Exception):
    """Raised when a request arrives while the circuit is open."""


class CircuitBreaker:
    """
    Tracks consecutive Z3 verification failures.

    States:
      CLOSED    — normal operation
      OPEN      — all requests rejected with CircuitOpenError
      HALF_OPEN — one probe allowed; success → CLOSED, failure → OPEN
    """

    def __init__(
        self,
        failure_threshold: int = _CB_FAILURE_THRESHOLD,
        cooldown_s: float = _CB_COOLDOWN_S,
    ) -> None:
        self._threshold = failure_threshold
        self._cooldown = cooldown_s
        self._consecutive_failures = 0
        self._state = "CLOSED"
        self._opened_at: float = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        return self._state

    def allow_request(self) -> None:
        """Raise CircuitOpenError if the circuit is open and not yet cooled."""
        with self._lock:
            if self._state == "CLOSED":
                return
            if self._state == "OPEN":
                if time.monotonic() - self._opened_at >= self._cooldown:
                    self._state = "HALF_OPEN"
                    logger.info("CircuitBreaker: entering HALF_OPEN — sending probe.")
                    return
                raise CircuitOpenError(
                    "Circuit breaker is OPEN. Verification requests are suspended "
                    f"for {self._cooldown:.0f}s after {self._threshold} consecutive "
                    "failures. Retry after cooldown."
                )
            # HALF_OPEN: allow the probe through (no raise)

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            if self._state != "CLOSED":
                logger.info("CircuitBreaker: probe succeeded — circuit CLOSED.")
            self._state = "CLOSED"

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._state == "HALF_OPEN" or (
                self._state == "CLOSED"
                and self._consecutive_failures >= self._threshold
            ):
                self._state = "OPEN"
                self._opened_at = time.monotonic()
                logger.error(
                    f"CircuitBreaker: OPEN after {self._consecutive_failures} "
                    "consecutive failures. All modifications suspended for "
                    f"{self._cooldown:.0f}s."
                )


# ---------------------------------------------------------------------------
# Write-Ahead Log checkpoint store
# ---------------------------------------------------------------------------

_WAL_PATH = os.environ.get("PAAC_WAL_PATH", "checkpoints.wal")
_WAL_LOCK = threading.Lock()


@dataclass
class WALEntry:
    func_name: str
    old_code: str
    new_code: str
    pre_cond: str
    post_cond: str
    source_citation: str
    timestamp: float


def wal_append(entry: WALEntry) -> None:
    """Append one checkpoint entry to the WAL file (JSON-lines format)."""
    with _WAL_LOCK:
        with open(_WAL_PATH, "a") as fh:
            fh.write(json.dumps(asdict(entry)) + "\n")


def wal_load_latest() -> dict[str, WALEntry]:
    """
    Replay the WAL and return the most recent entry per func_name.
    Returns an empty dict if the WAL file does not exist.
    """
    if not os.path.exists(_WAL_PATH):
        return {}
    latest: dict[str, WALEntry] = {}
    with _WAL_LOCK:
        with open(_WAL_PATH) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entry = WALEntry(**data)
                    # Keep the most recent entry per function.
                    if (
                        entry.func_name not in latest
                        or entry.timestamp > latest[entry.func_name].timestamp
                    ):
                        latest[entry.func_name] = entry
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"WAL: skipping malformed line: {line[:80]}")
    logger.info(f"WAL: replayed {len(latest)} checkpoint(s) from '{_WAL_PATH}'.")
    return latest


# ---------------------------------------------------------------------------
# Registry persistence
# ---------------------------------------------------------------------------

_REGISTRY_PATH = os.environ.get("PAAC_REGISTRY_PATH", "live_registry.json")
_REGISTRY_LOCK = threading.Lock()


def registry_save(registry: dict[str, str]) -> None:
    """Atomically persist the live registry to disk."""
    tmp = _REGISTRY_PATH + ".tmp"
    with _REGISTRY_LOCK:
        with open(tmp, "w") as fh:
            json.dump(registry, fh, indent=2)
        os.replace(tmp, _REGISTRY_PATH)


def registry_load() -> dict[str, str]:
    """Load the persisted registry; return empty dict if not found."""
    if not os.path.exists(_REGISTRY_PATH):
        return {}
    with _REGISTRY_LOCK:
        with open(_REGISTRY_PATH) as fh:
            data: dict[str, Any] = json.load(fh)
    logger.info(
        f"Registry: loaded {len(data)} function(s) from '{_REGISTRY_PATH}'."
    )
    return {k: str(v) for k, v in data.items()}
