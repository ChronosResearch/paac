# Copyright (c) 2026 Shashank Kumar. All rights reserved.
# This file is part of the PAAC (Provably Aligned Core) project.
# See LICENSE for terms.

import os
import json
from dataclasses import dataclass
from typing import Dict, Any, Optional

from filelock import FileLock
from loguru import logger
import redis

from ..core.sil_compiler import SILCompiler
from ..core.verifier import BoundedModelChecker
from ..core.exceptions import VerificationError, CompilationError, GroundingError, PAACError
from ..axioms.axiom_parser import AxiomParser, Axiom
from typing import List


@dataclass
class CodeModification:
    func_name: str
    old_code: str
    new_code: str
    pre_cond: str
    post_cond: str
    source_citation: str = ""


class ConfigurationError(PAACError):
    """Raised when PAAC is misconfigured (e.g. empty axiom set)."""
    pass


class CodeMonitor:
    def __init__(self, config: Dict[str, Any]):
        self.compiler = SILCompiler()
        self.checker = BoundedModelChecker()
        self.grounding_config = config.get("grounding", {})
        self.lock_path = os.path.join(os.getcwd(), "paac_monitor.lock")
        self.verified_checkpoints: List[CodeModification] = []
        self.timeout_ms: int = config.get("verification_timeout_ms", 5000)

        # Step 2: Load axioms at init time — fail closed if none found.
        axiom_path = config.get("axiom_path", os.path.join("config", "axioms.yaml"))
        self.axioms: List[Axiom] = self._load_axioms(axiom_path)
        if not self.axioms:
            raise ConfigurationError(
                f"No safety axioms loaded from '{axiom_path}'. "
                "PAAC cannot operate without axioms — failing closed."
            )
        logger.info(f"Loaded {len(self.axioms)} safety axioms from '{axiom_path}'.")

        # Redis setup — degrade gracefully but log clearly.
        redis_host = os.environ.get("REDIS_HOST", "redis")
        self.redis_client = redis.Redis(host=redis_host, port=6379, decode_responses=True)
        self.use_redis = True
        try:
            self.redis_client.ping()
        except redis.ConnectionError:
            logger.warning(
                "Redis is unavailable. Falling back to in-memory checkpoint store. "
                "Checkpoint history will be lost on process restart."
            )
            self.use_redis = False

    # ------------------------------------------------------------------
    # Axiom loading
    # ------------------------------------------------------------------

    def _load_axioms(self, path: str) -> List[Axiom]:
        """Load axioms from a YAML file that uses the flat `axioms:` list format."""
        if not os.path.exists(path):
            logger.error(f"Axiom file not found: {path}")
            return []
        with open(path, "r") as fh:
            content = fh.read()
        try:
            return AxiomParser.parse(content)
        except Exception as exc:
            logger.error(f"Failed to parse axiom file '{path}': {exc}")
            return []

    # ------------------------------------------------------------------
    # Checkpoint / rollback
    # ------------------------------------------------------------------

    def _save_checkpoint(self, mod: CodeModification) -> None:
        if self.use_redis:
            try:
                key = f"checkpoint:{mod.func_name}"
                self.redis_client.lpush(key, json.dumps(mod.__dict__))
                self.redis_client.ltrim(key, 0, 9)  # keep last 10
            except redis.ConnectionError:
                logger.error("Failed to store checkpoint in Redis; saving in-memory.")
                self._save_checkpoint_memory(mod)
        else:
            self._save_checkpoint_memory(mod)

    def _save_checkpoint_memory(self, mod: CodeModification) -> None:
        if len(self.verified_checkpoints) >= 10:
            self.verified_checkpoints.pop(0)
        self.verified_checkpoints.append(mod)

    def _rollback(self, func_name: str) -> Optional[CodeModification]:
        if self.use_redis:
            key = f"checkpoint:{func_name}"
            try:
                checkpoints = self.redis_client.lrange(key, 0, -1)
                if not checkpoints:
                    logger.warning(f"No Redis checkpoint for '{func_name}'.")
                    return None
                data = json.loads(checkpoints[0])
                return CodeModification(**data)
            except redis.ConnectionError:
                logger.warning("Redis unavailable during rollback; trying in-memory.")
        # Fall through to in-memory
        for cp in reversed(self.verified_checkpoints):
            if cp.func_name == func_name:
                return cp
        logger.warning(f"No in-memory checkpoint for '{func_name}'.")
        return None

    def _restore_state(self, checkpoint: CodeModification) -> None:
        """Apply a verified checkpoint — restores the function to its last known-good code."""
        # In a full deployment this would write back to the function registry / module loader.
        # Here we record the restoration so callers can observe it.
        logger.info(
            f"Restoring '{checkpoint.func_name}' to checkpoint "
            f"(citation: {checkpoint.source_citation or 'n/a'})."
        )
        self._save_checkpoint(checkpoint)

    # ------------------------------------------------------------------
    # Main interception entry point
    # ------------------------------------------------------------------

    def intercept_modification(self, mod: CodeModification) -> Dict[str, Any]:
        with FileLock(self.lock_path, timeout=60):
            try:
                # Grounding check
                if self.grounding_config.get("require_source_citations", True):
                    if not mod.source_citation or not mod.source_citation.strip():
                        raise GroundingError("Modification rejected: missing source citation.")

                # Step 1: Correctly unpack the (ProgramNode, CFGs) tuple.
                ast, _cfgs = self.compiler.compile(mod.new_code)

                # Step 2: Pass the loaded axiom set to the verifier.
                safe, counterexample = self.checker.verify(ast, self.axioms, timeout_ms=self.timeout_ms)

                if safe:
                    self._save_checkpoint(mod)
                    return {"status": "accepted", "message": "Modification verified and applied."}
                else:
                    # Step 9: Actually apply the rollback.
                    safe_state = self._rollback(mod.func_name)
                    if safe_state:
                        self._restore_state(safe_state)
                    else:
                        logger.error(f"No checkpoint for '{mod.func_name}'; entering safe mode.")
                    return {
                        "status": "rejected",
                        "counterexample": str(counterexample) if counterexample else None,
                    }

            except CompilationError as exc:
                return {"status": "rejected", "error": f"Compilation failed: {exc}"}
            except VerificationError as exc:
                return {"status": "rejected", "error": f"Verification failed: {exc}"}
            except GroundingError as exc:
                return {"status": "rejected", "error": f"Grounding failed: {exc}"}
