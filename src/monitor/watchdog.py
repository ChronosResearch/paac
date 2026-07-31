# Copyright (c) 2026 Shashank Kumar. All rights reserved.
# This file is part of the PAAC (Provably Aligned AI Core) project.
# See LICENSE for terms.

import threading
import time
import os
from loguru import logger
from ..core.exceptions import SelfHealingError

class Watchdog:
    def __init__(self, config):
        sh_config = config.get("self_healing", {})
        self.enabled = sh_config.get("enabled", True)
        self.interval = sh_config.get("heartbeat_interval_secs", 5)
        self.timeout = sh_config.get("recovery_timeout_secs", 30)
        self.last_heartbeat = time.time()
        self.running = False
        self.thread = None

    def start(self):
        if not self.enabled:
            return
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        logger.info("Watchdog started.")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()

    def heartbeat(self):
        self.last_heartbeat = time.time()

    def _monitor_loop(self):
        redis_host = os.environ.get("REDIS_HOST", "redis")
        import redis
        try:
            r = redis.Redis(host=redis_host, port=6379, socket_timeout=0.1)
        except Exception:
            r = None
            
        while self.running:
            time.sleep(self.interval)
            elapsed = time.time() - self.last_heartbeat
            
            # Redis Health Check
            if r:
                try:
                    r.ping()
                except Exception as e:
                    logger.warning(f"Watchdog: Redis connection lost ({e}). CodeMonitor will degrade to in-memory mode.")
                    r = None # Stop pinging to avoid blocking the watchdog loop
            
            if elapsed > self.timeout:
                logger.error(f"Watchdog timeout: {elapsed}s since last heartbeat.")
                self._trigger_recovery()

    def _trigger_recovery(self):
        logger.warning("Triggering self-healing recovery... Restarting components.")
        # Level 1: Restart components (simulated by resetting state)
        self.last_heartbeat = time.time()
        # Full implementation would restart actual OS processes or containers
