from types import SimpleNamespace

from src.autopatch.agents import diagnosis
from src.autopatch.models.schemas import AgentState, FailureType, PipelineFailure


def test_diagnosis_uses_end_of_console_log(monkeypatch):
    log = "dependency installation output\n" * 300 + "AssertionError: expected 5, got -1"
    captured = {}

    def fake_invoke_llm_with_fallback(_prompt, variables, temperature):
        captured.update(variables)
        return SimpleNamespace(
            content='{"type": "regression", "confidence": 0.9, "reason": "Assertion failed"}'
        )

    monkeypatch.setattr(diagnosis, "invoke_llm_with_fallback", fake_invoke_llm_with_fallback)
    failure = PipelineFailure(
        run_id="autopatch-failure#1",
        repo="https://github.com/pratheek076/autopatch-demo.git",
        branch="demo/calculator-failure",
        commit_sha="abc123",
        workflow_name="autopatch-failure",
        failed_step="Test",
        logs=log,
        triggered_at="",
    )

    result = diagnosis.diagnosis_node({"state": AgentState(failure=failure), "raw_payload": {}})

    assert captured["logs"] == log[-4000:]
    assert result["state"].failure.failure_type == FailureType.REGRESSION
