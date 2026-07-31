# Copyright (c) 2026 Shashank Kumar. All rights reserved.
# This file is part of the PAAC (Provably Aligned Core) project.
# See LICENSE for terms.

from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
import yaml
from .monitor.code_monitor import CodeMonitor, CodeModification
from .monitor.watchdog import Watchdog

app = FastAPI(title="PAAC API", description="Provably Aligned Core Verification API v2")

try:
    with open("config/default.yaml", "r") as f:
        config = yaml.safe_load(f)
except FileNotFoundError:
    config = {}

monitor = CodeMonitor(config)
watchdog = Watchdog(config)
watchdog.start()

class ModificationRequest(BaseModel):
    func_name: str
    old_code: str
    new_code: str
    pre_cond: str
    post_cond: str
    source_citation: str = ""

@app.post("/verify")
def verify_modification(req: ModificationRequest, background_tasks: BackgroundTasks):
    watchdog.heartbeat() # Dead man's switch reset
    mod = CodeModification(**req.model_dump())
    result = monitor.intercept_modification(mod)
    return result

@app.on_event("shutdown")
def shutdown_event():
    watchdog.stop()
