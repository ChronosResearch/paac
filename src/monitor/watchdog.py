# Copyright (c) 2026 Shashank Kumar. All rights reserved.
# This file is part of the PAAC (Provably Aligned Core) project.
# See LICENSE for terms.

import os
import threading
import time

from loguru import logger

# Configurable via environment variables.
_DEFAULT_HEARTBEAT_INTERVAL = int(os.environ.get("PAAC_WATCHDOG_HEARTBEAT_INTERVAL", "1"))
_DEFAULT_MONITOR_INTERVAL = int(os.environ.get("PAAC_WATCHDOG_MONITOR_INTERVAL", "5"))
_DEFAULT_TIMEOUT = int(os.environ.get("PAAC_WATCHDOG_TIMEOUT", "60"))


class Watchdog:
    """
    Two-thread watchdog design:

    1. _liveness_thread  — runs every `heartbeat_interval` seconds and stamps
       `last_heartbeat` as long as the process is alive.  This is the
       continuous heartbeat; it is completely independent of request traffic.

    2. _monitor_thread   — runs every `monitor_interval` seconds and compares
       `last_heartbeat` against `timeout`.  It only fires _trigger_recovery()
       when the liveness thread itself has stopped updating the timestamp,
       which means the process is genuinely hung or the liveness thread died.

    Callers (e.g. the /verify endpoint) may still call heartbeat() to signal
    application-level liveness, but that is now optional — idle periods will
    not cause false positives.
    """

    def __init__(self, config: dict):
        sh_config = config.get("self_healing", {})
        self.enabled: bool = sh_config.get("enabled", True)
        self.heartbeat_interval: int = sh_config.get(
            "heartbeat_interval_secs", _DEFAULT_HEARTBEAT_INTERVAL
        )
        self.monitor_interval: int = sh_config.get(
            "monitor_interval_secs", _DEFAULT_MONITOR_INTERVAL
        )
        self.timeout: int = sh_config.get("recovery_timeout_secs", _DEFAULT_TIMEOUT)

        self._last_heartbeat: float = time.monotonic()
        self._lock = threading.Lock()
        self.running: bool = False
        self._liveness_running: bool = False   # controls liveness thread only
        self._monitor_running: bool = False    # controls monitor thread only
        self._liveness_thread: threading.Thread | None = None
        self._monitor_thread: threading.Thread | None = None
        self._heartbeat_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        if not self.enabled:
            return
        self.running = True
        self._liveness_running = True
        self._monitor_running = True
        self._liveness_thread = threading.Thread(
            target=self._liveness_loop,
            daemon=True,
            name="paac-watchdog-liveness",
        )
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="paac-watchdog-monitor",
        )
        self._liveness_thread.start()
        self._monitor_thread.start()
        logger.info(
            f"Watchdog started — liveness every {self.heartbeat_interval}s, "
            f"monitor every {self.monitor_interval}s, timeout {self.timeout}s."
        )

    def stop(self) -> None:
        self.running = False
        self._liveness_running = False
        self._monitor_running = False
        # Threads are daemons; join with a short grace period.
        for t in (self._liveness_thread, self._monitor_thread):
            if t and t.is_alive():
                t.join(timeout=self.monitor_interval + 1)

    def heartbeat(self) -> None:
        """Optional: called by request handlers to signal application-level
        liveness.  The liveness thread keeps the timestamp alive during idle
        periods, so this is supplementary, not required."""
        with self._lock:
            self._last_heartbeat = time.monotonic()

    # ------------------------------------------------------------------
    # Internal threads
    # ------------------------------------------------------------------

    def _liveness_loop(self) -> None:
        """Stamps last_heartbeat every heartbeat_interval seconds.
        As long as this thread is scheduled by the OS, the watchdog will
        not fire — idle periods are safe."""
        while self._liveness_running:
            time.sleep(self.heartbeat_interval)
            if not self._liveness_running:
                break
            with self._lock:
                self._last_heartbeat = time.monotonic()
                self._heartbeat_count += 1
                count = self._heartbeat_count
            if count % 10 == 0:
                logger.debug(
                    f"Watchdog liveness thread alive — heartbeat #{count}."
                )

    def _monitor_loop(self) -> None:
        """Checks elapsed time since last heartbeat every monitor_interval
        seconds.  Only fires when the liveness thread itself has stalled."""
        redis_host = os.environ.get("REDIS_HOST", "redis")
        import redis as _redis

        try:
            r = _redis.Redis(host=redis_host, port=6379, socket_timeout=0.5)
            r.ping()
        except Exception:
            r = None

        while self._monitor_running:
            time.sleep(self.monitor_interval)
            if not self._monitor_running:
                break

            with self._lock:
                elapsed = time.monotonic() - self._last_heartbeat

            # Optional Redis health check — non-blocking, best-effort.
            if r:
                try:
                    r.ping()
                except Exception as e:
                    logger.warning(
                        f"Watchdog: Redis connection lost ({e}). "
                        "CodeMonitor will degrade to in-memory mode."
                    )
                    r = None

            if elapsed > self.timeout:
                logger.error(
                    f"Watchdog timeout: {elapsed:.1f}s since last heartbeat "
                    f"(threshold {self.timeout}s). Triggering self-healing."
                )
                self._trigger_recovery()

    def _trigger_recovery(self) -> None:
        logger.warning("Triggering self-healing recovery... Restarting components.")
        with self._lock:
            self._last_heartbeat = time.monotonic()
        # Full implementation would restart actual OS processes or containers.
