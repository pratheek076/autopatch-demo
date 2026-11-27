"""Diagnosis Agent — classifies the failure type using LLM + heuristics."""
import json
import logging

from langchain_core.prompts import ChatPromptTemplate

from src.autopatch.agents._llm_utils import invoke_llm_with_fallback, parse_llm_json
from src.autopatch.models.schemas import AgentGraphState, AgentState, FailureType

logger = logging.getLogger(__name__)

DIAGNOSIS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a CI/CD failure diagnosis expert. 
Analyze the pipeline failure log and classify it into exactly one category:
- flaky_test: test passes sometimes, fails non-deterministically
- regression: a recent code change broke existing functionality  
- dependency: external package, version conflict, or missing dep
- infra: environment issue, runner problem, network timeout
- unknown: cannot determine from logs

Respond in JSON: {{"type": "<category>", "confidence": 0.0-1.0, "reason": "<one sentence>"}}
"""),
    ("human", "Failed step: {failed_step}\n\nLogs:\n{logs}"),
])


def diagnosis_node(state: AgentGraphState) -> AgentGraphState:
    """Uses an LLM to classify the type of CI/CD failure from logs."""
    agent_state: AgentState = state["state"]
    failure = agent_state.failure

    if failure is None:
        return state

    response = invoke_llm_with_fallback(
        DIAGNOSIS_PROMPT,
        {
            "failed_step": failure.failed_step,
            "logs": failure.logs[-4000:],  # Keep the failure details at the end of the log
        },
        temperature=0,
    )

    try:
        result = parse_llm_json(response.content)
        failure_type = FailureType(result.get("type", "unknown"))
        confidence = float(result.get("confidence", 0.0))
        logger.info(f"[Diagnosis] type={failure_type} confidence={confidence:.2f}")
    except (json.JSONDecodeError, ValueError):
        failure_type = FailureType.UNKNOWN
        confidence = 0.0
        logger.warning("[Diagnosis] Failed to parse LLM response")

    updated_failure = failure.model_copy(update={
        "failure_type": failure_type,
        "diagnosis_confidence": confidence,
    })
    return {**state, "state": agent_state.model_copy(update={
        "failure": updated_failure,
        "status": "diagnosed",
    })}
