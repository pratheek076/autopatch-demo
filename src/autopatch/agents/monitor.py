"""Monitor Agent — fetches pipeline failure details from Jenkins."""
import logging

from src.autopatch.integrations.jenkins import JenkinsClient
from src.autopatch.models.schemas import AgentGraphState, AgentState, PipelineFailure

logger = logging.getLogger(__name__)


def monitor_node(state: AgentGraphState) -> AgentGraphState:
    """
    Fetches full console log and metadata for a failed Jenkins build.
    Populates AgentState.failure.

    Jenkins webhook payload (from Generic Webhook Trigger plugin) contains:
      - job_name, build_number, result, branch, etc.
    """
    agent_state: AgentState = state["state"]
    raw_payload: dict = state.get("raw_payload", {})

    job_name = raw_payload.get("job_name", "")
    build_number = int(raw_payload.get("build_number", 0))

    if not job_name or not build_number:
        logger.error("[Monitor] Missing job_name or build_number in webhook payload")
        return state

    jenkins = JenkinsClient()

    # Fetch console log and SCM info
    console_log = jenkins.get_console_log(job_name, build_number)
    failed_stage = jenkins.get_failed_stage(job_name, build_number)
    scm_info = jenkins.get_build_scm_info(job_name, build_number)
    build_info = jenkins.get_build_info(job_name, build_number)

    failure = PipelineFailure(
        run_id=f"{job_name}#{build_number}",
        repo=raw_payload.get("repo_url", job_name),
        branch=scm_info["branch"],
        commit_sha=scm_info["commit_sha"],
        workflow_name=job_name,
        failed_step=failed_stage,
        logs=console_log,
        triggered_at=str(build_info.get("timestamp", "")),
    )

    logger.info(
        f"[Monitor] Captured Jenkins failure: {job_name}#{build_number} "
        f"branch={scm_info['branch']} failed_stage={failed_stage}"
    )
    return {**state, "state": agent_state.model_copy(update={"failure": failure, "status": "monitored"})}
