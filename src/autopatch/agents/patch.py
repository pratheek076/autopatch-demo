"""Patch Agent — generates a candidate code fix using the LLM.

Only attempts to patch if diagnosis confidence meets the threshold
defined in the agent's YAML contract (specs/agents/patch_agent.yaml).
"""
import json
import logging

from langchain_core.prompts import ChatPromptTemplate

from src.autopatch.agents._llm_utils import invoke_llm_with_fallback, parse_llm_json
from src.autopatch.guardrails.spec_loader import load_agent_spec
from src.autopatch.models.schemas import AgentGraphState, AgentState, CandidatePatch

logger = logging.getLogger(__name__)

PATCH_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an expert software engineer fixing a CI/CD pipeline failure.
Given the failing code and error logs, produce a minimal, targeted fix.
Rules:
- Change as few lines as possible
- Do NOT disable or skip tests
- Do NOT introduce hardcoded secrets or credentials
- Do NOT change unrelated files
- Only change dependencies when the failure log shows a dependency problem
- For assertion failures, target the application code responsible for the incorrect result
Respond in JSON:
{{
  "file_path": "<relative path>",
  "original_code": "<exact original snippet>",
  "patched_code": "<fixed snippet>",
  "explanation": "<what you changed and why>",
  "lines_changed": <int>
}}
"""),
    ("human", "Failure type: {failure_type}\nFailed step: {failed_step}\n\nLogs:\n{logs}"),
])


def patch_node(state: AgentGraphState) -> AgentGraphState:
    """Generates a candidate patch, respecting the agent contract preconditions."""
    agent_state: AgentState = state["state"]
    failure = agent_state.failure

    if failure is None:
        return state

    # --- Precondition check from YAML contract ---
    spec = load_agent_spec("patch_agent")
    min_confidence = spec.get("preconditions", {}).get("diagnosis_confidence_min", 0.8)
    allowed_types = spec.get("preconditions", {}).get("failure_type_allowlist", [])

    if failure.diagnosis_confidence < min_confidence:
        logger.info(f"[Patch] Skipping — confidence {failure.diagnosis_confidence} < {min_confidence}")
        return {**state, "state": agent_state.model_copy(update={"status": "skipped_low_confidence"})}

    if allowed_types and failure.failure_type.value not in allowed_types:
        logger.info(f"[Patch] Skipping — failure type {failure.failure_type} not in allowlist")
        return {**state, "state": agent_state.model_copy(update={"status": "skipped_unknown_type"})}

    response = invoke_llm_with_fallback(
        PATCH_PROMPT,
        {
            "failure_type": failure.failure_type.value,
            "failed_step": failure.failed_step,
            "logs": failure.logs[-6000:],
        },
        temperature=0.2,
    )

    try:
        result = parse_llm_json(response.content)
        patch = CandidatePatch(
            failure_id=failure.run_id,
            file_path=result["file_path"],
            original_code=result["original_code"],
            patched_code=result["patched_code"],
            explanation=result["explanation"],
            lines_changed=result.get("lines_changed", 0),
        )
        logger.info(f"[Patch] Generated patch for {patch.file_path} ({patch.lines_changed} lines)")
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"[Patch] Failed to parse LLM patch response: {e}")
        return state

    return {**state, "state": agent_state.model_copy(update={"patch": patch, "status": "patched"})}
