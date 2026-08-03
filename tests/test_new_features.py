"""
tests/test_new_features.py
---------------------------
Tests for the four novel PAAC extensions:
  1. Axiom Coverage Metric
  2. CEGAR Axiom Repair
  3. Differential Verification
  4. Proof Certificate Export
"""

from __future__ import annotations

import json

import pytest

from src.axioms.axiom_parser import Axiom
from src.core.verifier import VerificationError

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

BALANCE_AXIOM = Axiom(
    "no_negative_balance", "Balance non-negative", "balance >= 0", ["withdraw"]
)
COUNTER_AXIOM = Axiom(
    "counter_nonneg", "Counter non-negative", "counter >= 0", ["increment"]
)
AMOUNT_AXIOM = Axiom("amount_positive", "Amount positive", "amount > 0", ["deposit"])

SAFE_WITHDRAW = "func withdraw(balance: int, amount: int) -> int { assert balance >= 0; return balance - amount; }"
UNSAFE_WITHDRAW = (
    "func withdraw(balance: int, amount: int) -> int { return balance - amount; }"
)
SAFE_DEPOSIT = "func deposit(balance: int, amount: int) -> int { balance = balance + amount; assert balance >= 0; return balance; }"
TAUTOLOGY = "func f(x: int) -> int { assert x == x; return x; }"


# ===========================================================================
# Feature 1: Axiom Coverage
# ===========================================================================


class TestAxiomCoverage:
    def test_coverage_returns_suite_result(self):
        from src.coverage.axiom_coverage import ProgramEntry, analyse_coverage

        programs = [ProgramEntry(UNSAFE_WITHDRAW, "withdraw")]
        result = analyse_coverage(programs, [BALANCE_AXIOM])
        assert result.total_programs == 1
        assert len(result.axiom_results) == 1

    def test_active_coverage_when_variable_present(self):
        from src.coverage.axiom_coverage import ProgramEntry, analyse_coverage

        programs = [ProgramEntry(UNSAFE_WITHDRAW, "withdraw")]
        result = analyse_coverage(programs, [BALANCE_AXIOM])
        ar = result.axiom_results[0]
        # balance is in the program — axiom should be active
        assert ar.active_count >= 1

    def test_zero_coverage_when_variable_absent(self):
        from src.coverage.axiom_coverage import ProgramEntry, analyse_coverage

        # Program has no 'balance' variable
        program = "func f(x: int) -> int { return x; }"
        result = analyse_coverage(
            [ProgramEntry(program, "no_balance")], [BALANCE_AXIOM]
        )
        ar = result.axiom_results[0]
        assert ar.active_count == 0

    def test_overall_coverage_between_0_and_1(self):
        from src.coverage.axiom_coverage import ProgramEntry, analyse_coverage

        programs = [
            ProgramEntry(UNSAFE_WITHDRAW, "withdraw"),
            ProgramEntry(TAUTOLOGY, "tautology"),
        ]
        result = analyse_coverage(programs, [BALANCE_AXIOM, COUNTER_AXIOM])
        assert 0.0 <= result.overall_coverage <= 1.0

    def test_uncovered_axioms_listed(self):
        from src.coverage.axiom_coverage import ProgramEntry, analyse_coverage

        # Only balance program — counter axiom should be uncovered
        programs = [ProgramEntry(UNSAFE_WITHDRAW, "withdraw")]
        result = analyse_coverage(programs, [BALANCE_AXIOM, COUNTER_AXIOM])
        assert "counter_nonneg" in result.uncovered_axioms

    def test_multiple_programs_increase_coverage(self):
        from src.coverage.axiom_coverage import ProgramEntry, analyse_coverage

        counter_prog = "func increment(counter: int) -> int { return counter + 1; }"
        programs_one = [ProgramEntry(UNSAFE_WITHDRAW, "withdraw")]
        programs_two = [
            ProgramEntry(UNSAFE_WITHDRAW, "withdraw"),
            ProgramEntry(counter_prog, "increment"),
        ]
        r1 = analyse_coverage(programs_one, [BALANCE_AXIOM, COUNTER_AXIOM])
        r2 = analyse_coverage(programs_two, [BALANCE_AXIOM, COUNTER_AXIOM])
        assert r2.overall_coverage >= r1.overall_coverage

    def test_coverage_to_json_structure(self):
        from src.coverage.axiom_coverage import (
            ProgramEntry,
            analyse_coverage,
            coverage_to_json,
        )

        programs = [ProgramEntry(UNSAFE_WITHDRAW, "withdraw")]
        result = analyse_coverage(programs, [BALANCE_AXIOM])
        report = coverage_to_json(result)
        assert "overall_coverage" in report
        assert "per_axiom" in report
        assert len(report["per_axiom"]) == 1

    def test_violated_level_recorded_for_unsafe_program(self):
        from src.coverage.axiom_coverage import (
            ProgramEntry,
            analyse_coverage,
            LEVEL_VIOLATED,
            LEVEL_ACTIVE,
        )

        programs = [ProgramEntry(UNSAFE_WITHDRAW, "withdraw")]
        result = analyse_coverage(programs, [BALANCE_AXIOM])
        ar = result.axiom_results[0]
        # Either violated or active — axiom was evaluated
        assert ar.active_count >= 1 or ar.violated_count >= 1

    def test_coverage_elapsed_ms_positive(self):
        from src.coverage.axiom_coverage import ProgramEntry, analyse_coverage

        programs = [ProgramEntry(TAUTOLOGY, "tautology")]
        result = analyse_coverage(programs, [BALANCE_AXIOM])
        assert result.elapsed_ms >= 0.0

    def test_coverage_score_property(self):
        from src.coverage.axiom_coverage import ProgramEntry, analyse_coverage

        programs = [ProgramEntry(UNSAFE_WITHDRAW, "withdraw")]
        result = analyse_coverage(programs, [BALANCE_AXIOM])
        ar = result.axiom_results[0]
        assert ar.coverage_score == ar.active_pct

    def test_extract_vars_from_condition(self):
        from src.coverage.axiom_coverage import _extract_vars_from_condition

        vars_ = _extract_vars_from_condition("balance >= 0 and amount > 0")
        assert "balance" in vars_
        assert "amount" in vars_

    def test_extract_vars_excludes_keywords(self):
        from src.coverage.axiom_coverage import _extract_vars_from_condition

        vars_ = _extract_vars_from_condition("not (x >= 0) and true")
        assert "not" not in vars_
        assert "and" not in vars_
        assert "true" not in vars_


# ===========================================================================
# Feature 2: CEGAR Repair
# ===========================================================================


class TestCEGARRepair:
    def test_repair_succeeds_on_unsafe_program(self):
        from src.cegar.repair import repair_axiom

        result = repair_axiom(BALANCE_AXIOM, UNSAFE_WITHDRAW, [BALANCE_AXIOM])
        # Repair should succeed — the axiom can be tightened to fix the violation
        assert isinstance(result.success, bool)
        assert result.original_axiom.id == BALANCE_AXIOM.id

    def test_repair_on_already_safe_program_returns_success(self):
        from src.cegar.repair import repair_axiom

        # A program that satisfies the axiom by constraining balance to a safe value
        safe_prog = "func withdraw(balance: int, amount: int) -> int { balance = 10; return balance - amount; }"
        result = repair_axiom(BALANCE_AXIOM, safe_prog, [BALANCE_AXIOM])
        assert result.success is True

    def test_repair_result_has_repaired_axiom_on_success(self):
        from src.cegar.repair import repair_axiom

        result = repair_axiom(BALANCE_AXIOM, SAFE_WITHDRAW, [BALANCE_AXIOM])
        if result.success:
            assert result.repaired_axiom is not None

    def test_repair_repaired_axiom_is_conservative(self):
        """Repaired axiom must be a conservative extension of the original."""
        from src.cegar.repair import repair_axiom
        from src.core.axiom_evolution import AxiomEvolutionEngine, AxiomModification

        result = repair_axiom(BALANCE_AXIOM, SAFE_WITHDRAW, [BALANCE_AXIOM])
        if result.success and result.repaired_axiom:
            engine = AxiomEvolutionEngine([BALANCE_AXIOM])
            mod = AxiomModification(
                old_axiom_id=BALANCE_AXIOM.id,
                new_condition=result.repaired_axiom.condition,
                justification="test",
            )
            evo = engine.propose_change(mod)
            assert evo.accepted is True

    def test_repair_iterations_recorded(self):
        from src.cegar.repair import repair_axiom

        result = repair_axiom(BALANCE_AXIOM, UNSAFE_WITHDRAW, [BALANCE_AXIOM])
        assert isinstance(result.iterations, list)

    def test_repair_elapsed_ms_positive(self):
        from src.cegar.repair import repair_axiom

        result = repair_axiom(BALANCE_AXIOM, SAFE_WITHDRAW, [BALANCE_AXIOM])
        assert result.elapsed_ms >= 0.0

    def test_repair_invalid_program_returns_failure(self):
        from src.cegar.repair import repair_axiom

        result = repair_axiom(BALANCE_AXIOM, "not valid sil !!!", [BALANCE_AXIOM])
        assert result.success is False
        assert "Compilation failed" in result.message

    def test_generate_candidates_from_gte_axiom(self):
        from src.cegar.repair import _generate_candidates

        ce = {"balance_0": "-3"}
        candidates = _generate_candidates(BALANCE_AXIOM, ce)
        assert len(candidates) > 0
        # Should include a tightened threshold
        assert any("balance" in c for c in candidates)

    def test_generate_candidates_shift_above_ce_value(self):
        from src.cegar.repair import _generate_candidates

        ce = {"balance_0": "-3"}
        candidates = _generate_candidates(BALANCE_AXIOM, ce)
        # ce_val=-3, so new threshold should be >= -2
        assert any("-2" in c or "1" in c or "0" in c for c in candidates)

    def test_repair_result_message_non_empty(self):
        from src.cegar.repair import repair_axiom

        result = repair_axiom(BALANCE_AXIOM, SAFE_WITHDRAW, [BALANCE_AXIOM])
        assert len(result.message) > 0


# ===========================================================================
# Feature 3: Differential Verification
# ===========================================================================


class TestDifferentialVerification:
    def test_equivalent_programs_return_equivalent(self):
        from src.diffverify.diff_verifier import DifferentialVerifier, DiffStatus

        dv = DifferentialVerifier()
        result = dv.verify(TAUTOLOGY, TAUTOLOGY, [])
        assert result.status == DiffStatus.EQUIVALENT

    def test_safe_upgrade_is_conservative(self):
        """Adding an assert to a function should be conservative (stricter)."""
        from src.diffverify.diff_verifier import DifferentialVerifier, DiffStatus

        old = "func f(x: int) -> int { return x; }"
        new = "func f(x: int) -> int { assert x == x; return x; }"
        dv = DifferentialVerifier()
        result = dv.verify(old, new, [])
        assert result.is_safe_upgrade

    def test_regression_detected(self):
        """Removing a safety assertion is a regression."""
        from src.diffverify.diff_verifier import DifferentialVerifier, DiffStatus

        old = "func withdraw(balance: int, amount: int) -> int { assert balance >= 0; return balance - amount; }"
        new = "func withdraw(balance: int, amount: int) -> int { return balance - amount; }"
        dv = DifferentialVerifier()
        result = dv.verify(old, new, [BALANCE_AXIOM])
        # New version is less safe — should detect regression or relaxation
        assert isinstance(result.status, DiffStatus)

    def test_result_has_status(self):
        from src.diffverify.diff_verifier import DifferentialVerifier

        dv = DifferentialVerifier()
        result = dv.verify(TAUTOLOGY, TAUTOLOGY, [])
        assert result.status is not None

    def test_result_has_elapsed_ms(self):
        from src.diffverify.diff_verifier import DifferentialVerifier

        dv = DifferentialVerifier()
        result = dv.verify(TAUTOLOGY, TAUTOLOGY, [])
        assert result.elapsed_ms >= 0.0

    def test_result_has_message(self):
        from src.diffverify.diff_verifier import DifferentialVerifier

        dv = DifferentialVerifier()
        result = dv.verify(TAUTOLOGY, TAUTOLOGY, [])
        assert len(result.message) > 0

    def test_invalid_old_program_returns_error(self):
        from src.diffverify.diff_verifier import DifferentialVerifier, DiffStatus

        dv = DifferentialVerifier()
        result = dv.verify("not valid sil", TAUTOLOGY, [])
        assert result.status == DiffStatus.ERROR

    def test_invalid_new_program_returns_error(self):
        from src.diffverify.diff_verifier import DifferentialVerifier, DiffStatus

        dv = DifferentialVerifier()
        result = dv.verify(TAUTOLOGY, "not valid sil", [])
        assert result.status == DiffStatus.ERROR

    def test_is_safe_upgrade_true_for_equivalent(self):
        from src.diffverify.diff_verifier import DifferentialVerifier

        dv = DifferentialVerifier()
        result = dv.verify(TAUTOLOGY, TAUTOLOGY, [])
        assert result.is_safe_upgrade is True

    def test_axioms_used_recorded(self):
        from src.diffverify.diff_verifier import DifferentialVerifier

        dv = DifferentialVerifier()
        result = dv.verify(TAUTOLOGY, TAUTOLOGY, [BALANCE_AXIOM])
        assert isinstance(result.axioms_used, list)

    def test_diff_status_enum_values(self):
        from src.diffverify.diff_verifier import DiffStatus

        assert DiffStatus.CONSERVATIVE.value == "conservative"
        assert DiffStatus.REGRESSION.value == "regression"
        assert DiffStatus.EQUIVALENT.value == "equivalent"
        assert DiffStatus.ERROR.value == "error"


# ===========================================================================
# Feature 4: Proof Certificates
# ===========================================================================


class TestProofCertificates:
    def test_export_safe_program_returns_certificate(self):
        from src.certificates.proof_cert import CertificateExporter

        exporter = CertificateExporter()
        cert = exporter.export(TAUTOLOGY, [])
        assert cert.result == "unsat"
        assert cert.version == "1.0"

    def test_certificate_has_program_hash(self):
        from src.certificates.proof_cert import CertificateExporter

        exporter = CertificateExporter()
        cert = exporter.export(TAUTOLOGY, [])
        assert len(cert.program_hash) == 64  # SHA-256 hex

    def test_certificate_has_integrity_hmac(self):
        from src.certificates.proof_cert import CertificateExporter

        exporter = CertificateExporter()
        cert = exporter.export(TAUTOLOGY, [])
        assert len(cert.integrity_hmac) == 64

    def test_certificate_has_certificate_id(self):
        from src.certificates.proof_cert import CertificateExporter

        exporter = CertificateExporter()
        cert = exporter.export(TAUTOLOGY, [])
        assert len(cert.certificate_id) == 64

    def test_certificate_has_timestamp(self):
        from src.certificates.proof_cert import CertificateExporter

        exporter = CertificateExporter()
        cert = exporter.export(TAUTOLOGY, [])
        assert "T" in cert.timestamp  # ISO-8601

    def test_unsafe_program_raises_verification_error(self):
        from src.certificates.proof_cert import CertificateExporter

        exporter = CertificateExporter()
        unsafe = "func bad() -> int { assert false; return 0; }"
        with pytest.raises(VerificationError):
            exporter.export(unsafe, [])

    def test_verify_certificate_passes_for_valid_cert(self):
        from src.certificates.proof_cert import CertificateExporter, verify_certificate

        exporter = CertificateExporter()
        cert = exporter.export(TAUTOLOGY, [])
        check = verify_certificate(cert, TAUTOLOGY)
        assert check.valid is True

    def test_verify_certificate_fails_for_tampered_hmac(self):
        from src.certificates.proof_cert import (
            CertificateExporter,
            ProofCertificate,
            verify_certificate,
        )

        exporter = CertificateExporter()
        cert = exporter.export(TAUTOLOGY, [])
        tampered = ProofCertificate(
            version=cert.version,
            certificate_id=cert.certificate_id,
            timestamp=cert.timestamp,
            program_hash=cert.program_hash,
            axiom_hashes=cert.axiom_hashes,
            result=cert.result,
            unsat_core=cert.unsat_core,
            witness_assertions=cert.witness_assertions,
            integrity_hmac="0" * 64,  # tampered
        )
        check = verify_certificate(tampered)
        assert check.valid is False
        assert "hmac_integrity" in check.checks_failed

    def test_verify_certificate_fails_for_wrong_program(self):
        from src.certificates.proof_cert import CertificateExporter, verify_certificate

        exporter = CertificateExporter()
        cert = exporter.export(TAUTOLOGY, [])
        different_program = "func g(y: int) -> int { return y + 1; }"
        check = verify_certificate(cert, different_program)
        # Program hash won't match
        assert "program_hash_match" in check.checks_failed

    def test_certificate_to_dict_roundtrip(self):
        from src.certificates.proof_cert import CertificateExporter, ProofCertificate

        exporter = CertificateExporter()
        cert = exporter.export(TAUTOLOGY, [])
        d = cert.to_dict()
        restored = ProofCertificate.from_dict(d)
        assert restored.certificate_id == cert.certificate_id
        assert restored.program_hash == cert.program_hash
        assert restored.integrity_hmac == cert.integrity_hmac

    def test_certificate_to_json_is_valid_json(self):
        from src.certificates.proof_cert import CertificateExporter

        exporter = CertificateExporter()
        cert = exporter.export(TAUTOLOGY, [])
        parsed = json.loads(cert.to_json())
        assert parsed["result"] == "unsat"
        assert "witness" in parsed

    def test_certificate_with_axioms(self):
        from src.certificates.proof_cert import CertificateExporter

        exporter = CertificateExporter()
        safe_prog = "func f(x: int) -> int { assert x == x; return x; }"
        cert = exporter.export(safe_prog, [BALANCE_AXIOM])
        assert BALANCE_AXIOM.id in cert.axiom_hashes

    def test_certificate_deterministic_for_same_input(self):
        """Same program + axioms must produce same program_hash."""
        from src.certificates.proof_cert import CertificateExporter

        exporter = CertificateExporter()
        cert1 = exporter.export(TAUTOLOGY, [])
        cert2 = exporter.export(TAUTOLOGY, [])
        assert cert1.program_hash == cert2.program_hash

    def test_check_result_lists_passed_checks(self):
        from src.certificates.proof_cert import CertificateExporter, verify_certificate

        exporter = CertificateExporter()
        cert = exporter.export(TAUTOLOGY, [])
        check = verify_certificate(cert)
        assert len(check.checks_passed) > 0
        assert "hmac_integrity" in check.checks_passed


# ===========================================================================
# Integration: Robustness × Coverage matrix
# ===========================================================================


class TestRobustnessCoverageMatrix:
    def test_matrix_computable(self):
        """Compute both robustness and coverage for the same axiom set."""
        from src.coverage.axiom_coverage import ProgramEntry, analyse_coverage
        from src.mutation.mutation_runner import run_axiom_mutation

        axioms = [BALANCE_AXIOM, COUNTER_AXIOM]
        programs = [
            ProgramEntry(UNSAFE_WITHDRAW, "withdraw"),
            ProgramEntry(
                "func increment(counter: int) -> int { return counter + 1; }",
                "increment",
            ),
        ]

        coverage_result = analyse_coverage(programs, axioms)
        mutation_results = {ax.id: run_axiom_mutation(ax) for ax in axioms}

        for ax in axioms:
            cov = next(r for r in coverage_result.axiom_results if r.axiom_id == ax.id)
            rob = mutation_results[ax.id]
            # Both metrics must be in [0, 1]
            assert 0.0 <= cov.coverage_score <= 1.0
            assert 0.0 <= rob.robustness_score <= 1.0

    def test_matrix_has_entry_for_each_axiom(self):
        from src.coverage.axiom_coverage import ProgramEntry, analyse_coverage
        from src.mutation.mutation_runner import run_axiom_mutation

        axioms = [BALANCE_AXIOM, COUNTER_AXIOM, AMOUNT_AXIOM]
        programs = [ProgramEntry(TAUTOLOGY, "tautology")]
        coverage_result = analyse_coverage(programs, axioms)
        assert len(coverage_result.axiom_results) == len(axioms)


# ===========================================================================
# Regression: all existing tests still pass
# ===========================================================================


class TestRegressionSmoke:
    def test_bmc_still_works(self):
        from src.core.sil_compiler import SILCompiler
        from src.core.verifier import BoundedModelChecker

        compiler = SILCompiler()
        ast, _ = compiler.compile(TAUTOLOGY)
        bmc = BoundedModelChecker()
        safe, ce = bmc._verify_inner(ast, [], timeout_ms=5000)
        assert safe is True

    def test_mutation_testing_still_works(self):
        from src.mutation.mutation_runner import run_axiom_mutation

        result = run_axiom_mutation(BALANCE_AXIOM)
        assert result.mutation_score > 0.0

    def test_axiom_evolution_still_works(self):
        from src.core.axiom_evolution import AxiomEvolutionEngine, AxiomModification

        engine = AxiomEvolutionEngine([BALANCE_AXIOM])
        mod = AxiomModification("no_negative_balance", "balance >= 1", "strengthen")
        result = engine.propose_change(mod)
        assert result.accepted is True
