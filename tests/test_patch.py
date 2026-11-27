import json
from types import SimpleNamespace

import pytest

from src.autopatch.agents import patch as patch_agent
from src.autopatch.models.schemas import AgentState, FailureType, PipelineFailure


@pytest.mark.parametrize(
    ("file_path", "expected_status"),
    [
        ("src/autopatch/calculator.py", "patched"),
        ("src/calculator.py", "patch_rejected"),
    ],
)
def test_patch_uses_source_context_and_rejects_invented_path(
    file_path,
    expected_status,
    monkeypatch,
):
    log = "dependency installation output\n" * 500 + (
        "FAILED tests/test_calculator.py::test_add_returns_sum\n"
        "E assert -1 == 5"
    )
    captured = {}
    test_source = "from src.autopatch.calculator import add\n\nassert add(2, 3) == 5\n"
    original_source = "def add(left: int, right: int) -> int:\n    return left - right\n"
    patch_response = {
        "file_path": file_path,
        "original_code": "return left - right",
        "patched_code": "return left + right",
        "explanation": "Use addition for the add operation.",
        "lines_changed": 1,
    }

    class FakeGitHubClient:
        def get_file_content(self, path, ref):
            assert ref == "abc123"
            return {
                "tests/test_calculator.py": test_source,
                "src/autopatch/calculator.py": original_source,
            }[path]

    def fake_invoke_llm_with_fallback(_prompt, variables, temperature):
        captured.update(variables)
        return SimpleNamespace(content=json.dumps(patch_response))

    monkeypatch.setattr(patch_agent, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(patch_agent, "invoke_llm_with_fallback", fake_invoke_llm_with_fallback)
    failure = PipelineFailure(
        run_id="autopatch-failure#3",
        repo="https://github.com/pratheek076/autopatch-demo.git",
        branch="demo/calculator-failure",
        commit_sha="abc123",
        workflow_name="autopatch-failure",
        failed_step="Test",
        logs=log,
        failure_type=FailureType.REGRESSION,
        diagnosis_confidence=0.98,
        triggered_at="",
    )

    result = patch_agent.patch_node({"state": AgentState(failure=failure), "raw_payload": {}})

    assert captured["logs"] == log[-6000:]
    assert f"Source file (src/autopatch/calculator.py):\n{original_source}" in captured["source_context"]
    assert result["state"].status == expected_status
    if expected_status == "patched":
        assert result["state"].patch.file_path == "src/autopatch/calculator.py"
        assert result["state"].patch.patched_code == original_source.replace(
            "return left - right",
            "return left + right",
            1,
        )
    else:
        assert result["state"].patch is None
