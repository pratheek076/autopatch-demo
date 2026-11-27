"""Patch Agent — generates a candidate code fix using the LLM.

Only attempts to patch if diagnosis confidence meets the threshold
defined in the agent's YAML contract (specs/agents/patch_agent.yaml).
"""
import ast
import json
import logging
import re

from github import GithubException
from langchain_core.prompts import ChatPromptTemplate

from src.autopatch.agents._llm_utils import invoke_llm_with_fallback, parse_llm_json
from src.autopatch.guardrails.spec_loader import load_agent_spec
from src.autopatch.integrations.github import GitHubClient
from src.autopatch.models.schemas import AgentGraphState, AgentState, CandidatePatch

logger = logging.getLogger(__name__)

FAILED_TEST_PATTERN = re.compile(r"(?m)^\s*FAILED\s+(tests/[^\s:]+\.py)::")

PATCH_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an expert software engineer fixing a CI/CD pipeline failure.
Given the failing code, source context, and error logs, produce a minimal, targeted fix.
Rules:
- Change as few lines as possible
- Do NOT disable or skip tests
- Do NOT introduce hardcoded secrets or credentials
- Do NOT change unrelated files
- Only change dependencies when the failure log shows a dependency problem
- For assertion failures, target the application code responsible for the incorrect result
- When source files are provided, choose exactly one of those paths; never invent a path
- `original_code` must be an exact snippet from that file
- `patched_code` must be only the replacement snippet, not the whole file
Respond in JSON:
{{
  "file_path": "<relative path>",
  "original_code": "<exact original snippet>",
  "patched_code": "<fixed snippet>",
  "explanation": "<what you changed and why>",
  "lines_changed": <int>
}}
"""),
    (
        "human",
    (
        "Failure type: {failure_type}\nFailed step: {failed_step}\n\n"
        "Source context:\n{source_context}\n\nLogs:\n{logs}"
    ),
    ),
])


def _load_test_source_context(
    github: GitHubClient,
    failure_logs: str,
    ref: str,
) -> tuple[str, dict[str, str]]:
    """Fetch the failing pytest file and the local modules it imports."""
    match = FAILED_TEST_PATTERN.search(failure_logs)
    if match is None:
        return "", {}

    test_path = match.group(1)
    test_source = github.get_file_content(test_path, ref)
    try:
        test_tree = ast.parse(test_source, filename=test_path)
    except SyntaxError as e:
        raise ValueError(f"Could not parse failing test file {test_path}") from e

    module_names: set[str] = set()
    for node in ast.walk(test_tree):
        if isinstance(node, ast.Import):
            module_names.update(
                alias.name for alias in node.names if alias.name.startswith("src.")
            )
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("src."):
            module_names.add(node.module)

    source_paths = sorted({f"{name.replace('.', '/')}.py" for name in module_names})
    if not source_paths:
        raise ValueError(f"No local source imports found in failing test {test_path}")

    source_files = {
        path: github.get_file_content(path, ref)
        for path in source_paths
    }
    context = "\n\n".join(
        [f"Failing test ({test_path}):\n{test_source}"]
        + [f"Source file ({path}):\n{content}" for path, content in source_files.items()]
    )
    return context, source_files


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

    failure_logs = failure.logs[-6000:]
    github = None
    source_files: dict[str, str] = {}
    source_context = ""
    try:
        if FAILED_TEST_PATTERN.search(failure_logs):
            github = GitHubClient()
            source_context, source_files = _load_test_source_context(
                github,
                failure_logs,
                failure.commit_sha or failure.branch,
            )
    except (GithubException, OSError, TypeError, ValueError) as e:
        logger.error(f"[Patch] Could not load source context: {e}")
        return {**state, "state": agent_state.model_copy(update={"status": "source_context_error"})}

    response = invoke_llm_with_fallback(
        PATCH_PROMPT,
        {
            "failure_type": failure.failure_type.value,
            "failed_step": failure.failed_step,
            "source_context": source_context,
            "logs": failure_logs,
        },
        temperature=0.2,
    )

    try:
        result = parse_llm_json(response.content)
        file_path = result["file_path"]
        original_code = result["original_code"]
        patched_snippet = result["patched_code"]

        if source_files and file_path not in source_files:
            logger.error(f"[Patch] Rejected path not present in source context: {file_path}")
            return {**state, "state": agent_state.model_copy(update={"status": "patch_rejected"})}

        if github is None:
            github = GitHubClient()
        original_file = source_files.get(file_path)
        if original_file is None:
            original_file = github.get_file_content(
                file_path,
                failure.commit_sha or failure.branch,
            )
        if not original_code or original_code not in original_file:
            logger.error(f"[Patch] Rejected patch; original snippet not found in {file_path}")
            return {**state, "state": agent_state.model_copy(update={"status": "patch_rejected"})}

        patched_file = original_file.replace(original_code, patched_snippet, 1)
        patch = CandidatePatch(
            failure_id=failure.run_id,
            file_path=file_path,
            original_code=original_code,
            patched_code=patched_file,
            explanation=result["explanation"],
            lines_changed=result.get("lines_changed", 0),
        )
        logger.info(f"[Patch] Generated patch for {patch.file_path} ({patch.lines_changed} lines)")
    except (GithubException, OSError, TypeError, ValueError, json.JSONDecodeError, KeyError) as e:
        logger.error(f"[Patch] Failed to parse or validate LLM patch response: {e}")
        return {**state, "state": agent_state.model_copy(update={"status": "patch_rejected"})}

    return {**state, "state": agent_state.model_copy(update={"patch": patch, "status": "patched"})}
