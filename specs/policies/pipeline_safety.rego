package autopatch.pipeline_safety

import rego.v1

# ============================================================
# OPA/Rego Policy: Pipeline Safety Rules
#
# These rules enforce what patches are ALLOWED to be merged.
# Any "deny" rule that fires will block the patch.
# ============================================================

default allow := false

allow if {
    count(deny) == 0
}

# --- Rule 1: Block patches that disable test stages ---
deny contains reason if {
    input.patch.touches_test_files == true
    contains(input.patch.patched_code, "skip(")
    reason := "Patch disables tests using skip() — cannot merge"
}

deny contains reason if {
    input.patch.touches_test_files == true
    contains(input.patch.patched_code, "pytest.mark.skip")
    reason := "Patch adds pytest.mark.skip — cannot merge"
}

# --- Rule 2: Block patches that introduce secrets ---
deny contains reason if {
    input.patch.introduces_secrets == true
    reason := "Patch introduces hardcoded secrets or credentials"
}

# --- Rule 3: Block oversized patches ---
deny contains reason if {
    input.patch.lines_changed > 150
    reason := sprintf("Patch too large: %d lines changed (max 150)", [input.patch.lines_changed])
}

# --- Rule 4: Block patches touching files outside allowed scope ---
deny contains reason if {
    not startswith(input.patch.file_path, "src/")
    not startswith(input.patch.file_path, "tests/")
    input.patch.file_path != "requirements.txt"
    input.patch.file_path != "pyproject.toml"
    reason := sprintf("Patch touches file outside allowed scope: %s", [input.patch.file_path])
}

# --- Rule 5: Block significant coverage regressions ---
deny contains reason if {
    input.patch.coverage_delta < -2.0
    reason := sprintf("Coverage dropped by %.1f%% (threshold: -2%%)", [input.patch.coverage_delta])
}
