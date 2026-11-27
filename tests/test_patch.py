import json
from types import SimpleNamespace

from src.autopatch.agents import patch as patch_agent
from src.autopatch.models.schemas import AgentState, FailureType, PipelineFailure


def test_patch_uses_end_of_console_log(monkeypatch):
    log = "dependency installation output\n" * 500 + (
        "FAILED tests/test_calculator.py::test_add_returns_sum\n"
        "E assert -1 == 5"
    )
    captured = {}
    patch_response = {
        "file_path": "src/autopatch/calculator.py",
        "original_code": "return left - right",
        "patched_code": "return left + right",
        "explanation": "Use addition for the add operation.",
        "lines_changed": 1,
    }

    def fake_invoke_llm_with_fallback(_prompt, variables, temperature):
        captured.update(variables)
        return SimpleNamespace(content=json.dumps(patch_response))

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
    assert result["state"].patch.file_path == "src/autopatch/calculator.py"
