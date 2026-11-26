"""Z3 Formal Invariant Checker.

Encodes patch properties as SMT constraints and checks them with Z3.
If any constraint is violated, the patch is BLOCKED.

Invariants checked:
  1. Patch size must be within the max_lines_changed bound
  2. Coverage delta must not drop below the minimum threshold
  3. Patch must not introduce secrets (heuristic + Z3 encoding)
  4. Patch must not disable test stages
"""
import logging
from z3 import (
    Int, Bool, Solver, And, Or, Not, sat, unsat, ArithRef, BoolRef
)
from src.autopatch.models.schemas import CandidatePatch
from src.autopatch.guardrails.spec_loader import load_agent_spec

logger = logging.getLogger(__name__)

# Heuristic patterns that suggest a secret was introduced
SECRET_PATTERNS = ["password=", "api_key=", "secret=", "token=", "AUTH_"]
TEST_DISABLE_PATTERNS = ["skip(", "@pytest.mark.skip", "xit(", "xdescribe(", "#pytest: no cover"]


def z3_check(patch: CandidatePatch) -> dict:
    """
    Run Z3 SMT solver checks on a candidate patch.
    Returns a dict: {passed: bool, violations: list[str], model: str}
    """
    spec = load_agent_spec("patch_agent")
    postconditions = spec.get("postconditions", {})
    max_lines = postconditions.get("max_lines_changed", 150)
    min_coverage_delta = postconditions.get("min_coverage_delta", -2.0)

    solver = Solver()
    violations = []

    # --- Z3 Variables ---
    lines_changed = Int("lines_changed")
    coverage_delta = Int("coverage_delta")          # scaled x100 for int arithmetic
    introduces_secrets = Bool("introduces_secrets")
    disables_tests = Bool("disables_tests")

    # --- Assign concrete values from patch ---
    solver.add(lines_changed == patch.lines_changed)
    solver.add(coverage_delta == int(patch.coverage_delta * 100))

    # Heuristic: detect secrets in patched code
    secret_found = any(p in patch.patched_code for p in SECRET_PATTERNS)
    solver.add(introduces_secrets == secret_found)

    # Heuristic: detect test disabling patterns
    test_disabled = any(p in patch.patched_code for p in TEST_DISABLE_PATTERNS)
    solver.add(disables_tests == test_disabled)

    # --- Invariant 1: Patch size ---
    inv_size = lines_changed <= max_lines
    solver.push()
    solver.add(Not(inv_size))
    if solver.check() == sat:
        violations.append(
            f"Patch exceeds max allowed lines: {patch.lines_changed} > {max_lines}"
        )
    solver.pop()

    # --- Invariant 2: Coverage delta ---
    inv_coverage = coverage_delta >= int(min_coverage_delta * 100)
    solver.push()
    solver.add(Not(inv_coverage))
    if solver.check() == sat:
        violations.append(
            f"Coverage drop too large: {patch.coverage_delta:.1f}% < {min_coverage_delta}%"
        )
    solver.pop()

    # --- Invariant 3: No secrets ---
    solver.push()
    solver.add(introduces_secrets)
    if solver.check() == sat:
        violations.append("Patch appears to introduce hardcoded secrets or credentials")
    solver.pop()

    # --- Invariant 4: No test disabling ---
    solver.push()
    solver.add(disables_tests)
    if solver.check() == sat:
        violations.append("Patch disables or skips existing tests")
    solver.pop()

    passed = len(violations) == 0
    logger.info(f"[Z3] {'PASS' if passed else 'FAIL'} — {len(violations)} violation(s)")

    return {
        "passed": passed,
        "violations": violations,
        "checked_invariants": ["size", "coverage_delta", "no_secrets", "no_test_disabling"],
    }
