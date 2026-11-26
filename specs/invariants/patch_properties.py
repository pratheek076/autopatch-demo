"""
Z3 Invariant Specifications — Human-readable reference.

This file documents the formal invariants that z3_checker.py encodes.
Think of this as the "spec sheet" for the Z3 checker — the authoritative
description of what mathematical properties every patch must satisfy.

These are NOT executed directly — they're reference specs that z3_checker.py
implements. Keeping them here makes the invariants auditable and reviewable
independently of the implementation.
"""

INVARIANTS = {
    "INV-001": {
        "name": "Patch Size Bound",
        "formal": "lines_changed(patch) ≤ MAX_LINES",
        "rationale": (
            "LLM-generated patches larger than MAX_LINES are empirically less reliable. "
            "Large patches likely indicate the agent is overreaching its mandate."
        ),
        "z3_encoding": "solver.add(lines_changed <= max_lines)",
        "default_max": 150,
    },
    "INV-002": {
        "name": "Coverage Non-Regression",
        "formal": "coverage_delta(patch) ≥ MIN_COVERAGE_DELTA",
        "rationale": (
            "A patch that substantially drops coverage is weakening the test suite. "
            "Small drops (up to 2%) are acceptable for targeted fixes."
        ),
        "z3_encoding": "solver.add(coverage_delta >= min_coverage_delta * 100)",
        "default_min": -2.0,
    },
    "INV-003": {
        "name": "No Secrets Introduction",
        "formal": "¬introduces_secrets(patch)",
        "rationale": (
            "An automated agent must never commit secrets to source control. "
            "This is a hard invariant with no threshold."
        ),
        "z3_encoding": "solver.add(Not(introduces_secrets))",
        "heuristic_patterns": ["password=", "api_key=", "secret=", "token="],
    },
    "INV-004": {
        "name": "No Test Disabling",
        "formal": "¬disables_tests(patch)",
        "rationale": (
            "A self-healing agent that fixes failures by skipping tests is not "
            "actually fixing anything — it is hiding failures. Hard block."
        ),
        "z3_encoding": "solver.add(Not(disables_tests))",
        "heuristic_patterns": ["skip(", "@pytest.mark.skip", "xit("],
    },
}
