# Copyright (c) 2026 Shashank Kumar. All rights reserved.
# This file is part of the PAAC (Provably Aligned AI Core) project.
# See LICENSE for terms.

import pytest
import time
from src.monitor.watchdog import Watchdog

def test_watchdog_timeout_triggers_recovery():
    config = {"self_healing": {"enabled": True, "heartbeat_interval_secs": 1, "recovery_timeout_secs": 2}}
    watchdog = Watchdog(config)
    
    watchdog.start()
    
    # Wait for timeout
    time.sleep(3)
    
    # Watchdog should have triggered recovery and reset last_heartbeat
    assert watchdog.last_heartbeat > time.time() - 2
    watchdog.stop()
