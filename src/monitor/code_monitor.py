# Copyright (c) 2026 Shashank Kumar. All rights reserved.
# This file is part of the PAAC (Provably Aligned Core) project.
# See LICENSE for terms.

import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from typing import Any

import redis
from filelock import FileLock
from loguru import logger

from ..axioms.axiom_parser import Axiom, AxiomParser
from ..core.exceptions import (
    CompilationError,
    ConfigurationError,
    GroundingError,
    PAACError,
    VerificationError,
)
from ..core.sil_compiler import SILCompiler
from ..core.verifier import BoundedModelChecker
from ..core.verifier import VerificationError as _VerifierError  # same class via re-export

# Audit logger — writes counterexamples and rejections to a persistent file.
_audit_logger = logging.getLogger("paac.audit")
_audit_handler = logging.FileHandler("audit.log")
_audit_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
_audit_logger.addHandler(_audit_handler)
_audit_logger.setLevel(logging.INFO)

# Semaphore: at most 4 concurrent Z3 subprocesses to bound resource usage.
_VERIFY_SEMAPHORE = threading.Semaphore(4)

# Citation must be at least 10 chars and contain a dot (URL/DOI heuristic).
_CITATION_RE = re.compile(r".{10,}")


@dataclass
class CodeModification:
    func_name: str
    old_code: str
    new_code: str
    pre_cond: str
    post_cond: str
    source_citation: str = ""


class CodeMonitor:
    # In-process function registry: func_name -> current live code string.
    # In a real deployment this would be the module loader / hot-reload registry.
    _live_registry: dict[str, str] = {}
    def __init__(self, config: dict[str, Any]):
        self.compiler = SILCompiler()
        self.checker = BoundedModelChecker()
        self.grounding_config = config.get("grounding", {})
        self.lock_path = os.path.join(os.getcwd(), "paac_monitor.lock")
        self.verified_checkpoints: list[CodeModification] = []
        self.timeout_ms: int = config.get("verification_timeout_ms", 5000)

        axiom_path = config.get("axiom_path", os.path.join("config", "axioms.yaml"))
        self.axioms: list[Axiom] = self._load_axioms(axiom_path)
        if not self.axioms:
            raise ConfigurationError(
                f"No safety axioms loaded from '{axiom_path}'. "
                "PAAC cannot operate without axioms — failing closed."
            )
        logger.info(f"Loaded {len(self.axioms)} safety axioms from '{axiom_path}'.")

        redis_host = os.environ.get("REDIS_HOST", "redis")
        self.redis_client = redis.Redis(
            host=redis_host, port=6379, decode_responses=True
        )
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

    def _load_axioms(self, path: str) -> list[Axiom]:
        """Load axioms from a YAML file that uses the flat `axioms:` list format."""
        if not os.path.exists(path):
            logger.error(f"Axiom file not found: {path}")
            return []
        with open(path, "r") as fh:
            content = fh.read()
        try:
            return AxiomParser.parse(content)
        except Exception as exc:  # noqa: BLE001
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

    def _rollback(self, func_name: str) -> CodeModification | None:
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
        """Restore the function to its last verified-safe code.

        Writes checkpoint.old_code back into the in-process live registry so
        subsequent calls see the rolled-back version.  In a full deployment
        this would also push to the module loader / hot-reload registry.
        """
        CodeMonitor._live_registry[checkpoint.func_name] = checkpoint.new_code
        logger.info(
            f"Rolled back '{checkpoint.func_name}' to last verified checkpoint "
            f"(citation: {checkpoint.source_citation or 'n/a'})."
        )
        _audit_logger.info(
            f"ROLLBACK func={checkpoint.func_name} "
            f"restored_code_hash={hash(checkpoint.old_code)}"
        )
        # Re-save so it stays at the head of the checkpoint stack.
        self._save_checkpoint(checkpoint)

    # ------------------------------------------------------------------
    # Main interception entry point
    # ------------------------------------------------------------------

    def intercept_modification(self, mod: CodeModification) -> dict[str, Any]:
        with FileLock(self.lock_path, timeout=60):
            try:
                # Citation validation: must be >= 10 chars (URL / DOI heuristic).
                if self.grounding_config.get("require_source_citations", True):
                    citation = mod.source_citation or ""
                    if not _CITATION_RE.fullmatch(citation.strip()):
                        raise GroundingError(
                            "Modification rejected: source_citation must be at least "
                            "10 characters (provide a URL or DOI)."
                        )

                ast, _cfgs = self.compiler.compile(mod.new_code)

                with _VERIFY_SEMAPHORE:
                    safe, counterexample = self.checker.verify(
                        ast, self.axioms, timeout_ms=self.timeout_ms
                    )

                if safe:
                    CodeMonitor._live_registry[mod.func_name] = mod.new_code
                    self._save_checkpoint(mod)
                    _audit_logger.info(
                        f"ACCEPTED func={mod.func_name} "
                        f"citation={mod.source_citation!r}"
                    )
                    return {
                        "status": "accepted",
                        "message": "Modification verified and applied.",
                    }
                else:
                    ce_str = str(counterexample) if counterexample else None
                    _audit_logger.warning(
                        f"REJECTED func={mod.func_name} "
                        f"citation={mod.source_citation!r} "
                        f"counterexample={ce_str!r}"
                    )
                    safe_state = self._rollback(mod.func_name)
                    if safe_state:
                        self._restore_state(safe_state)
                    else:
                        logger.error(
                            f"No checkpoint for '{mod.func_name}'; entering safe mode."
                        )
                    return {"status": "rejected", "counterexample": ce_str}

            except CompilationError as exc:
                return {"status": "rejected", "error": f"Compilation failed: {exc}"}
            except (VerificationError, _VerifierError) as exc:
                return {"status": "rejected", "error": f"Verification failed: {exc}"}
            except GroundingError as exc:
                return {"status": "rejected", "error": f"Grounding failed: {exc}"}
