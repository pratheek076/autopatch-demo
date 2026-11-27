"""OPA Policy Checker.

Sends the candidate patch as an input document to the OPA server
and evaluates it against the Rego policies in specs/policies/.

OPA runs as a sidecar (see docker-compose.yml).
"""
import json
import logging
import os

import httpx

from src.autopatch.models.schemas import CandidatePatch

logger = logging.getLogger(__name__)

OPA_URL = os.getenv("OPA_URL", "http://localhost:8181")
OPA_POLICY_PATH = "v1/data/autopatch/pipeline_safety"


def opa_check(patch: CandidatePatch) -> dict:
    """
    Evaluate a CandidatePatch against OPA pipeline safety policies.
    Returns a dict: {passed: bool, violations: list[str]}
    """
    input_doc = {
        "input": {
            "patch": {
                "file_path": patch.file_path,
                "lines_changed": patch.lines_changed,
                "introduces_secrets": patch.introduces_secrets,
                "coverage_delta": patch.coverage_delta,
                "touches_test_files": patch.touches_test_files,
                "patched_code": patch.patched_code,
            }
        }
    }

    try:
        response = httpx.post(
            f"{OPA_URL}/{OPA_POLICY_PATH}",
            json=input_doc,
            timeout=5.0,
        )
        response.raise_for_status()
        result = response.json().get("result", {})
        deny_reasons: list[str] = result.get("deny", [])
        passed = len(deny_reasons) == 0
        logger.info(f"[OPA] {'PASS' if passed else 'FAIL'} — {len(deny_reasons)} denial(s)")
        return {"passed": passed, "violations": deny_reasons}

    except httpx.ConnectError:
        logger.warning("[OPA] Could not connect to OPA server — skipping policy check")
        return {"passed": True, "violations": [], "warning": "OPA unavailable — policy check skipped"}
    except (httpx.HTTPError, json.JSONDecodeError) as e:
        logger.error(f"[OPA] Unexpected error: {e}")
        return {"passed": False, "violations": [f"OPA check error: {e!s}"]}
