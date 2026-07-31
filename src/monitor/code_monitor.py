# Copyright (c) 2026 Shashank Kumar. All rights reserved.
# This file is part of the PAAC (Provably Aligned AI Core) project.
# See LICENSE for terms.

from dataclasses import dataclass
from ..core.sil_compiler import SILCompiler
from ..core.verifier import Verifier
from ..core.exceptions import VerificationError, CompilationError, GroundingError
from filelock import FileLock
import os
import json
from loguru import logger

import redis

@dataclass
class CodeModification:
    func_name: str
    old_code: str
    new_code: str
    pre_cond: str
    post_cond: str
    source_citation: str = ""

class CodeMonitor:
    def __init__(self, config):
        self.compiler = SILCompiler()
        self.verifier = Verifier(config)
        self.grounding_config = config.get("grounding", {})
        self.lock_path = os.path.join(os.getcwd(), "paac_monitor.lock")
        self.verified_checkpoints = []
        
        # Redis setup
        redis_host = os.environ.get("REDIS_HOST", "redis")
        self.redis_client = redis.Redis(host=redis_host, port=6379, decode_responses=True)
        self.use_redis = True
        try:
            self.redis_client.ping()
        except redis.ConnectionError:
            logger.warning("Redis is down. Falling back to in-memory degraded mode.")
            self.use_redis = False

    def _rollback(self, func_name: str):
        if self.use_redis:
            key = f"checkpoint:{func_name}"
            try:
                checkpoints = self.redis_client.lrange(key, 0, -1)
                if not checkpoints:
                    logger.warning("No verified checkpoints to rollback to in Redis.")
                    return None
                logger.info("Rolling back to last verified state from Redis.")
                return json.loads(checkpoints[0])
            except redis.ConnectionError:
                logger.warning("Redis connection failed during rollback.")
                return None
        else:
            if not self.verified_checkpoints:
                logger.warning("No verified checkpoints to rollback to.")
                return None
            logger.info("Rolling back to last verified state.")
            return self.verified_checkpoints[-1]

    def intercept_modification(self, mod: CodeModification):
        # Concurrent access serialization
        with FileLock(self.lock_path, timeout=60):
            try:
                # Grounding check: Source citations
                if self.grounding_config.get("require_source_citations", True):
                    if not mod.source_citation:
                        raise GroundingError("Modification rejected: Missing source citation.")
                
                # Parse and type-check SIL code
                ast = self.compiler.compile(mod.new_code)
                
                # Verify safety
                result = self.verifier.verify(mod.func_name, ast, mod.pre_cond)
                
                if result.get("safe"):
                    # Record checkpoint
                    if self.use_redis:
                        try:
                            key = f"checkpoint:{mod.func_name}"
                            self.redis_client.lpush(key, json.dumps(mod.__dict__))
                            self.redis_client.ltrim(key, 0, 9) # Keep last 10
                        except redis.ConnectionError:
                            logger.error("Failed to store checkpoint in Redis.")
                    else:
                        if len(self.verified_checkpoints) >= 10:
                            self.verified_checkpoints.pop(0)
                        self.verified_checkpoints.append(mod)
                        
                    return {"status": "accepted", "message": "Modification applied."}
                else:
                    self._rollback(mod.func_name)
                    return {"status": "rejected", "counterexample": result.get("counterexample")}
                    
            except CompilationError as e:
                return {"status": "rejected", "error": f"Compilation failed: {e}"}
            except VerificationError as e:
                return {"status": "rejected", "error": f"Verification failed: {e}"}
            except GroundingError as e:
                return {"status": "rejected", "error": f"Grounding failed: {e}"}
