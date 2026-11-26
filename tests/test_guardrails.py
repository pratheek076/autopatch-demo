"""Tests for the formal guardrail layer.

These tests verify that the Z3 and OPA checkers correctly block
patches that violate invariants, and pass compliant patches.
"""
import pytest
from src.autopatch.models.schemas import CandidatePatch
from src.autopatch.guardrails.z3_checker import z3_check


def make_patch(**overrides) -> CandidatePatch:
    defaults = dict(
        failure_id="run-001",
        file_path="src/autopatch/agents/diagnosis.py",
        original_code="x = 1",
        patched_code="x = 2",
        explanation="Fixed off-by-one",
        lines_changed=5,
        touches_test_files=False,
        introduces_secrets=False,
        coverage_delta=0.0,
    )
    return CandidatePatch(**{**defaults, **overrides})


class TestZ3Checker:
    def test_valid_patch_passes(self):
        patch = make_patch()
        result = z3_check(patch)
        assert result["passed"] is True
        assert result["violations"] == []

    def test_oversized_patch_blocked(self):
        patch = make_patch(lines_changed=200)
        result = z3_check(patch)
        assert result["passed"] is False
        assert any("exceeds max" in v for v in result["violations"])

    def test_secret_in_patch_blocked(self):
        patch = make_patch(patched_code="api_key=sk-supersecret123")
        result = z3_check(patch)
        assert result["passed"] is False
        assert any("secret" in v.lower() for v in result["violations"])

    def test_test_disabling_blocked(self):
        patch = make_patch(patched_code="@pytest.mark.skip\ndef test_foo(): pass")
        result = z3_check(patch)
        assert result["passed"] is False
        assert any("test" in v.lower() for v in result["violations"])

    def test_coverage_drop_blocked(self):
        patch = make_patch(coverage_delta=-5.0)
        result = z3_check(patch)
        assert result["passed"] is False
        assert any("coverage" in v.lower() for v in result["violations"])

    def test_minor_coverage_drop_allowed(self):
        patch = make_patch(coverage_delta=-1.5)
        result = z3_check(patch)
        assert result["passed"] is True
