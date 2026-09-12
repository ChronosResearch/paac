# Copyright 2026 Shashank Kumar
# SPDX-License-Identifier: Apache-2.0
# This file is part of the PAAC (Provably Aligned Core) project.
# See LICENSE for terms.

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

import redis
from filelock import FileLock
from loguru import logger

from ..axioms.axiom_parser import Axiom, AxiomParser
from ..core.exceptions import (
    AxiomNotEncodableError,
    CompilationError,
    ConfigurationError,
    GroundingError,
    PreconditionUnsatisfiableError,
    VerificationError,
)
from ..core.failsafe import (
    CircuitBreaker,
    CircuitOpenError,
    WALEntry,
    registry_load,
    registry_save,
    wal_append,
    wal_load_latest,
)
from ..core.sil_compiler import SILCompiler, SILError as _SILError
from ..core.tcb_protect import protect_tcb
from ..core.verifier import BoundedModelChecker, check_precondition_satisfiable
from ..core.verifier import (
    VerificationError as _VerifierError,  # same class via re-export
)
from ..pcm.proof_checker import ProofChecker
from ..pcm.certificate import CertificateStore, generate_certificate

# Audit logger: writes counterexamples and rejections to a persistent file.
_audit_logger = logging.getLogger("paac.audit")
_audit_handler = logging.FileHandler("audit.log")
_audit_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
_audit_logger.addHandler(_audit_handler)
_audit_logger.setLevel(logging.INFO)

# Semaphore: at most 4 concurrent Z3 subprocesses to bound resource usage.
_VERIFY_SEMAPHORE = threading.Semaphore(4)

# Redis startup probe bounds. See the probe call site in __init__ for why a
# wall-clock deadline is needed in addition to the socket timeouts.
# The deadline is the larger of the two so that a socket-level timeout gets a
# chance to fire and report a precise error before the deadline abandons it.
_REDIS_PROBE_TIMEOUT_S: float = 1.0
_REDIS_PROBE_DEADLINE_S: float = 2.0

# R-6: Citation must be >= 20 chars and contain a dot (URL / DOI heuristic).
# Accepts: https://doi.org/..., https://github.com/..., http://..., doi:10....
_CITATION_RE = re.compile(r".{20,}")


@dataclass
class CodeModification:
    func_name: str
    old_code: str
    new_code: str
    pre_cond: str
    post_cond: str
    source_citation: str = ""
    # PCM fields -- optional; only required when pcm_mode=True
    proof: "dict | None" = None
    agent_id: str = "unknown-agent"


class CodeMonitor:
    # In-process function registry: func_name -> current live code string.
    _live_registry: dict[str, str] = {}  # noqa: RUF012

    # Shared circuit breaker: one instance per process.
    _circuit_breaker: CircuitBreaker = CircuitBreaker()

    def __init__(self, config: dict[str, Any]):
        # R-2: attempt to protect TCB pages read-only.
        protect_tcb()

        self.compiler = SILCompiler()
        self.checker = BoundedModelChecker()
        self.pcm_mode: bool = config.get("pcm_mode", False)
        self._pcm_store = CertificateStore(
            log_path=config.get("pcm_audit_log", "pcm_audit.jsonl")
        )
        self.grounding_config = config.get("grounding", {})
        self.lock_path = os.path.join(os.getcwd(), "paac_monitor.lock")
        self.verified_checkpoints: list[CodeModification] = []
        self.timeout_ms: int = config.get("verification_timeout_ms", 5000)

        axiom_path = config.get("axiom_path", os.path.join("config", "axioms.yaml"))
        self.axioms: list[Axiom] = self._load_axioms(axiom_path)
        if not self.axioms:
            raise ConfigurationError(
                f"No safety axioms loaded from '{axiom_path}'. "
                "PAAC cannot operate without axioms, failing closed."
            )
        logger.info(f"Loaded {len(self.axioms)} safety axioms from '{axiom_path}'.")

        # R-4: load persisted registry and WAL checkpoints on startup.
        saved_registry = registry_load()
        if saved_registry:
            CodeMonitor._live_registry.update(saved_registry)
        wal_entries = wal_load_latest()
        for func_name, entry in wal_entries.items():
            if func_name not in CodeMonitor._live_registry:
                CodeMonitor._live_registry[func_name] = entry.new_code
                logger.info(f"WAL: restored '{func_name}' from write-ahead log.")

        # Redis setup: degrade gracefully to WAL.
        #
        # The socket timeouts below are correct and wanted, but they are NOT
        # sufficient to bound this probe, and an earlier version of this fix
        # that relied on them alone did not work. redis-py forwards
        # socket_connect_timeout to socket.create_connection, which resolves
        # the host via getaddrinfo BEFORE it opens a socket, and getaddrinfo
        # is not covered by that timeout. The default REDIS_HOST is the bare
        # name "redis", which does not resolve outside a container network,
        # and a failing single-label lookup on Windows can fall through DNS
        # and then LLMNR/NetBIOS before giving up. Measured cost with
        # socket_connect_timeout=1.0 already in place: 28 seconds per
        # CodeMonitor construction, paid on every single construction.
        #
        # Enforcing a wall-clock deadline in a worker thread is what actually
        # bounds it, and it holds regardless of WHY the probe is slow: name
        # resolution, a blackholed address that never answers SYN, or a host
        # that completes the handshake and then stalls mid-command.
        redis_host = os.environ.get("REDIS_HOST", "redis")
        self.redis_client = redis.Redis(
            host=redis_host,
            port=6379,
            decode_responses=True,
            socket_connect_timeout=_REDIS_PROBE_TIMEOUT_S,
            socket_timeout=_REDIS_PROBE_TIMEOUT_S,
        )
        self.use_redis = self._probe_redis(redis_host)

        # Watchdog: two threads - liveness stamps every second,
        # monitor checks every 5 s.  Idle periods never trigger recovery.
        self._watchdog_running = True
        self._last_heartbeat = time.monotonic()
        self._heartbeat_lock = threading.Lock()
        self._liveness_thread = threading.Thread(
            target=self._liveness_loop, daemon=True, name="paac-liveness"
        )
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, daemon=True, name="paac-watchdog"
        )
        self._liveness_thread.start()
        self._watchdog_thread.start()

    # ------------------------------------------------------------------
    # Checkpoint store selection
    # ------------------------------------------------------------------

    def _probe_redis(self, redis_host: str) -> bool:
        """Ping Redis under a hard wall-clock deadline.

        Returns True if Redis is usable as the checkpoint store, False to fall
        back to the WAL. Never raises: every failure mode means the same thing
        operationally, which is "use the WAL".

        See the call site in __init__ for why the deadline is enforced here
        rather than left to socket_connect_timeout.
        """
        outcome: dict[str, BaseException | None] = {}

        def _ping() -> None:
            try:
                self.redis_client.ping()
                outcome["error"] = None
            except BaseException as exc:  # noqa: BLE001
                # Deliberately broad. This runs on a thread whose exceptions
                # would otherwise surface through the unraisable hook and be
                # reported as a crash, and the distinction between failure
                # modes does not change the decision we make below.
                outcome["error"] = exc

        probe = threading.Thread(target=_ping, name="paac-redis-probe", daemon=True)
        started = time.monotonic()
        probe.start()
        probe.join(timeout=_REDIS_PROBE_DEADLINE_S)
        elapsed = time.monotonic() - started

        if probe.is_alive():
            # The thread cannot be cancelled, so it is abandoned. That is safe:
            # it is a daemon, it only writes to the local `outcome` dict which
            # nothing reads after this point, and self.redis_client is left
            # unused once use_redis is False.
            logger.warning(
                f"Redis probe to '{redis_host}' exceeded "
                f"{_REDIS_PROBE_DEADLINE_S:.1f}s and was abandoned. Falling back "
                "to WAL checkpoint store. Checkpoints will be written to disk "
                "and replayed on restart."
            )
            return False

        error = outcome.get("error")
        if error is not None:
            logger.warning(
                f"Redis is unavailable ({type(error).__name__}) after "
                f"{elapsed:.2f}s. Falling back to WAL checkpoint store. "
                "Checkpoints will be written to disk and replayed on restart."
            )
            return False

        logger.info(f"Redis reachable at '{redis_host}' in {elapsed:.2f}s.")
        return True

    # ------------------------------------------------------------------
    # Watchdog
    # ------------------------------------------------------------------

    def heartbeat(self) -> None:
        """Optional: called by request handlers for application-level liveness.
        The liveness thread keeps the timestamp alive during idle periods."""
        with self._heartbeat_lock:
            self._last_heartbeat = time.monotonic()

    def _liveness_loop(self) -> None:
        """Stamps last_heartbeat every second while the process is alive.
        Prevents false watchdog triggers during idle periods."""
        _count = 0
        while self._watchdog_running:
            time.sleep(1)
            with self._heartbeat_lock:
                self._last_heartbeat = time.monotonic()
                _count += 1
            if _count % 10 == 0:
                logger.debug(f"CodeMonitor liveness thread alive, tick #{_count}.")

    def _watchdog_loop(self) -> None:
        _timeout = int(os.environ.get("PAAC_WATCHDOG_TIMEOUT", "60"))
        while self._watchdog_running:
            time.sleep(5)
            with self._heartbeat_lock:
                elapsed = time.monotonic() - self._last_heartbeat
            if elapsed > _timeout:
                logger.error(
                    f"Watchdog: liveness thread stalled for {elapsed:.1f}s, "
                    "triggering self-healing reset."
                )
                self._watchdog_recover()

    def _watchdog_recover(self) -> None:
        """Reset internal state on watchdog timeout."""
        with self._heartbeat_lock:
            self._last_heartbeat = time.monotonic()
        CodeMonitor._circuit_breaker = CircuitBreaker()
        logger.warning("Watchdog: circuit breaker reset. Service resuming.")

    def stop_watchdog(self) -> None:
        """Signal the internal watchdog thread to stop on its next iteration."""
        self._watchdog_running = False

    # ------------------------------------------------------------------
    # Axiom loading
    # ------------------------------------------------------------------

    def _load_axioms(self, path: str) -> list[Axiom]:
        if not os.path.exists(path):
            logger.error(f"Axiom file not found: {path}")
            return []
        with open(path) as fh:
            content = fh.read()
        try:
            return AxiomParser.parse(content)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Failed to parse axiom file '{path}': {exc}")
            return []

    # ------------------------------------------------------------------
    # Axiom filtering (A-05 fix)
    # ------------------------------------------------------------------

    def _get_applicable_axioms(self, func_name: str) -> list:
        """Return axioms that apply to func_name.

        An axiom applies when its target_functions list is empty, contains
        the wildcard "*", or explicitly names func_name.
        """
        result = []
        for axiom in self.axioms:
            tf = axiom.target_functions
            if not tf or "*" in tf or func_name in tf:
                result.append(axiom)
        return result

    # ------------------------------------------------------------------
    # Checkpoint / rollback
    # ------------------------------------------------------------------

    def _save_checkpoint(self, mod: CodeModification) -> None:
        # Always write to WAL first (R-4 durability).
        wal_append(
            WALEntry(
                func_name=mod.func_name,
                old_code=mod.old_code,
                new_code=mod.new_code,
                pre_cond=mod.pre_cond,
                post_cond=mod.post_cond,
                source_citation=mod.source_citation,
                timestamp=time.time(),
            )
        )
        if self.use_redis:
            try:
                key = f"checkpoint:{mod.func_name}"
                self.redis_client.lpush(key, json.dumps(mod.__dict__))
                self.redis_client.ltrim(key, 0, 9)
            except redis.ConnectionError:
                logger.error(
                    "Failed to store checkpoint in Redis; WAL is the fallback."
                )
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
                if checkpoints:
                    data = json.loads(checkpoints[0])
                    return CodeModification(**data)
                logger.warning(f"No Redis checkpoint for '{func_name}'.")
            except redis.ConnectionError:
                logger.warning("Redis unavailable during rollback; trying WAL/memory.")

        # Try WAL.
        wal_entries = wal_load_latest()
        if func_name in wal_entries:
            e = wal_entries[func_name]
            return CodeModification(
                func_name=e.func_name,
                old_code=e.old_code,
                new_code=e.new_code,
                pre_cond=e.pre_cond,
                post_cond=e.post_cond,
                source_citation=e.source_citation,
            )

        # Fall through to in-memory.
        for cp in reversed(self.verified_checkpoints):
            if cp.func_name == func_name:
                return cp
        logger.warning(f"No checkpoint found for '{func_name}'.")
        return None

    def _restore_state(self, checkpoint: CodeModification) -> None:
        """Restore the function to its last verified-safe code."""
        CodeMonitor._live_registry[checkpoint.func_name] = checkpoint.new_code
        registry_save(dict(CodeMonitor._live_registry))
        logger.info(
            f"Rolled back '{checkpoint.func_name}' to last verified checkpoint "
            f"(citation: {checkpoint.source_citation or 'n/a'})."
        )
        _audit_logger.info(
            f"ROLLBACK func={checkpoint.func_name} "
            f"restored_code_hash={hash(checkpoint.new_code)}"
        )
        self._save_checkpoint(checkpoint)

    # ------------------------------------------------------------------
    # Main interception entry point
    # ------------------------------------------------------------------

    def intercept_modification(self, mod: CodeModification) -> dict[str, Any]:
        """Verify a proposed code modification and apply it if safe.

        Compiles the new SIL code, runs the BMC pipeline with applicable axioms,
        and either accepts (checkpoints + updates registry) or rejects (rollback).

        Args:
            mod: The proposed modification containing func_name, old_code, new_code.

        Returns:
            A dict with keys: status (accepted/rejected/error), message, counterexample.
        """
        self.heartbeat()
        with FileLock(self.lock_path, timeout=60):
            try:
                # Circuit breaker check.
                try:
                    CodeMonitor._circuit_breaker.allow_request()
                except CircuitOpenError as exc:
                    return {"status": "error", "error": str(exc), "http_status": 503}

                # R-6: Citation validation: >= 20 chars with a dot.
                if self.grounding_config.get("require_source_citations", True):
                    citation = mod.source_citation or ""
                    stripped = citation.strip()
                    if not _CITATION_RE.fullmatch(stripped) or "." not in stripped:
                        raise GroundingError(
                            "Modification rejected: source_citation must be at least "
                            "20 characters and contain a dot (provide a URL or DOI)."
                        )

                ast, _cfgs = self.compiler.compile(mod.new_code)

                # Precondition satisfiability gate. Must run before BMC, not
                # instead of it, and must run for every mod regardless of
                # pcm_mode: an unsatisfiable pre_cond ("1 == 0", "x != x")
                # forces Z3's precondition-as-constraint encoding to make the
                # whole BMC query vacuously UNSAT, so every submission would
                # be accepted without a single axiom actually being checked.
                # mod.pre_cond is agent-supplied (see agent_adapter.py) and
                # reaches this point with no other validation, so this is the
                # only place that stands between an attacker-chosen
                # contradiction and a silent, total bypass of every axiom in
                # self.axioms. See PLAN_V8.md §0.5 for the full attack trace.
                target_func = next(
                    (f for f in ast.functions if f.name == mod.func_name), None
                )
                gate_params = (
                    [p.name for p in target_func.params] if target_func else []
                )
                check_precondition_satisfiable(
                    mod.pre_cond, gate_params, timeout_ms=self.timeout_ms
                )

                # A-05 fix: only pass axioms that target this function.
                applicable = self._get_applicable_axioms(mod.func_name)

                if self.pcm_mode:
                    # PCM mode: verify the proof, not the code.
                    return self._intercept_pcm(mod, applicable)

                with _VERIFY_SEMAPHORE:
                    safe, counterexample = self.checker.verify(
                        ast, applicable, timeout_ms=self.timeout_ms,
                        pre_cond=mod.pre_cond,
                    )

                if safe:
                    CodeMonitor._circuit_breaker.record_success()
                    CodeMonitor._live_registry[mod.func_name] = mod.new_code
                    registry_save(dict(CodeMonitor._live_registry))
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
                    # H-06. A reached verdict of "unsafe" is the verifier
                    # SUCCEEDING, so it is recorded as a success even though the
                    # modification is refused. This used to call
                    # record_failure(), which conflated two opposite things: "Z3
                    # is broken and I should stop" and "I correctly caught an
                    # attack and should keep going". Because rejection is the
                    # expected outcome for hostile input, an adversary could
                    # open the breaker with five bad submissions and suspend
                    # verification for 60 seconds at no cost.
                    CodeMonitor._circuit_breaker.record_success()
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

            except (CompilationError, _SILError) as exc:
                return {"status": "rejected", "error": f"Compilation failed: {exc}"}
            except PreconditionUnsatisfiableError as exc:
                # H-06: the gate firing is the mechanism working, not failing.
                CodeMonitor._circuit_breaker.record_success()
                _audit_logger.warning(
                    f"REJECTED func={mod.func_name} "
                    f"reason=unsatisfiable_precondition pre_cond={mod.pre_cond!r}"
                )
                return {
                    "status": "rejected",
                    "error": f"Unsatisfiable precondition: {exc}",
                }
            except (VerificationError, _VerifierError) as exc:
                # H-06: this one stays a failure, and is the only kind that
                # should be. Reaching here means no verdict was produced: a Z3
                # timeout, a crashed subprocess, or an unknown result. That is
                # the condition the breaker exists to detect, because retrying a
                # broken verifier in a tight loop helps nobody.
                CodeMonitor._circuit_breaker.record_failure()
                return {"status": "rejected", "error": f"Verification failed: {exc}"}
            except AxiomNotEncodableError as exc:
                # C-03: the axiom set cannot be evaluated against this function.
                # Fail closed, and count it as a mechanism failure, because the
                # operator has to change configuration before anything can be
                # verified. Unlike a rejection, retrying will not help.
                CodeMonitor._circuit_breaker.record_failure()
                _audit_logger.warning(
                    f"REJECTED func={mod.func_name} reason=axiom_not_encodable"
                )
                return {
                    "status": "rejected",
                    "error": f"Axiom set cannot be evaluated: {exc}",
                }
            except GroundingError as exc:
                return {"status": "rejected", "error": f"Grounding failed: {exc}"}

    # ------------------------------------------------------------------
    # PCM mode interception
    # ------------------------------------------------------------------

    def _intercept_pcm(
        self, mod: "CodeModification", applicable: list
    ) -> dict[str, Any]:
        """
        PCM mode: verify the proof submitted with the modification.

        The proof checker runs in pure Python (no Z3).  If the proof is
        accepted, a PCM certificate is generated and appended to the
        audit log.  The code is applied only after proof acceptance.
        """
        if mod.proof is None:
            _audit_logger.warning(
                f"PCM REJECTED func={mod.func_name}: no proof submitted."
            )
            return {
                "status": "rejected",
                "error": "PCM mode requires a proof. Submit a proof alongside the modification.",
            }

        axiom_dicts = [{"id": a.id, "condition": a.condition} for a in applicable]
        checker = ProofChecker(axiom_dicts)
        check_result = checker.check(mod.proof)

        if not check_result.accepted:
            # H-06: a rejected proof is the checker working. See the note on the
            # non-PCM rejection path above.
            CodeMonitor._circuit_breaker.record_success()
            _audit_logger.warning(
                f"PCM REJECTED func={mod.func_name} "
                f"reason={check_result.reason!r} "
                f"failed_step={check_result.failed_step}"
            )
            safe_state = self._rollback(mod.func_name)
            if safe_state:
                self._restore_state(safe_state)
            return {
                "status": "rejected",
                "error": f"Proof rejected: {check_result.reason}",
                "failed_step": check_result.failed_step,
                "proof_check_elapsed_ms": round(check_result.elapsed_ms, 3),
            }

        # Proof accepted -- generate certificate and apply modification
        import time as _time
        import hashlib as _hashlib
        mod_id = f"{mod.func_name}:{int(_time.time())}"
        cert = generate_certificate(
            modification_id=mod_id,
            code=mod.new_code,
            proof=mod.proof,
            agent_id=mod.agent_id,
            axioms_covered=check_result.covered_axioms,
        )
        self._pcm_store.save(cert)

        # Also generate Ed25519 attestation with proof_hash (paper §4.3).
        # This gives third parties a single verifiable record covering both
        # the code hash and the proof hash under the same Ed25519 key.
        try:
            from src.core.attestation import get_engine as _get_attest_engine
            _engine = _get_attest_engine()
            _prog_hash = _hashlib.sha256(mod.new_code.encode()).hexdigest()
            _axiom_hash = _engine.hash_axioms([a.condition for a in applicable])
            _proof_hash = _hashlib.sha256(
                json.dumps(mod.proof, sort_keys=True).encode()
            ).hexdigest()
            _engine.attest(
                mod_id, _prog_hash, _axiom_hash, True, None,
                proof_hash=_proof_hash,
            )
        except Exception as _ae:  # noqa: BLE001
            logger.warning(f"PCM attestation generation failed (non-fatal): {_ae}")

        CodeMonitor._circuit_breaker.record_success()
        CodeMonitor._live_registry[mod.func_name] = mod.new_code
        registry_save(dict(CodeMonitor._live_registry))
        self._save_checkpoint(mod)
        _audit_logger.info(
            f"PCM ACCEPTED func={mod.func_name} "
            f"mod_id={mod_id} "
            f"agent={mod.agent_id} "
            f"axioms={check_result.covered_axioms} "
            f"elapsed_ms={check_result.elapsed_ms:.2f}"
        )
        return {
            "status": "accepted",
            "message": "Proof verified and modification applied.",
            "modification_id": mod_id,
            "certificate": cert.to_dict(),
            "proof_check_elapsed_ms": round(check_result.elapsed_ms, 3),
        }
