"""FastAPI entrypoint — Jenkins webhook receiver + API.

Configure Jenkins to call this via:
  Manage Jenkins → Configure System → Notification Plugin
  OR use the Generic Webhook Trigger Plugin (recommended).

OpenAPI docs auto-served at http://localhost:8000/docs
"""
import hashlib
import hmac
import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

load_dotenv()

from src.autopatch.models.schemas import AgentState
from src.autopatch.agents.graph import build_graph

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AutoPatch",
    description=(
        "Self-Healing CI/CD Agent with Formal Guardrails. "
        "Receives Jenkins build failure webhooks and autonomously generates "
        "and formally verifies fixes before opening a PR."
    ),
    version="0.1.0",
)

agent_graph = build_graph()


# ---------------------------------------------------------------------------
# Jenkins webhook endpoint
#
# Configure in Jenkins via Generic Webhook Trigger Plugin:
#   POST URL: http://<your-server>:8000/webhook/jenkins?token=<WEBHOOK_TOKEN>
#   Post content type: application/json
#   Variable mappings:
#     job_name      → $.name
#     build_number  → $.build.number
#     result        → $.build.phase   (FINALIZED + status=FAILURE)
#     branch        → $.build.scm.branch
#     repo_url      → $.build.scm.url
# ---------------------------------------------------------------------------

@app.post("/webhook/jenkins", summary="Receive Jenkins build failure events")
async def jenkins_webhook(request: Request):
    """
    Entry point: Jenkins calls this when a build finishes.
    Only processes FAILURE results — all others are ignored.
    """
    _verify_webhook_token(request)

    payload = await request.json()

    # Jenkins Notification Plugin payload shape
    phase = payload.get("build", {}).get("phase", "")
    status = payload.get("build", {}).get("status", "")

    # Only act on completed failures
    if phase != "FINALIZED" or status not in ("FAILURE", "UNSTABLE"):
        return JSONResponse({
            "status": "ignored",
            "reason": f"phase={phase} status={status} — not a failure",
        })

    job_name = payload.get("name", "")
    build_number = payload.get("build", {}).get("number", 0)
    logger.info(f"Jenkins failure: {job_name}#{build_number}")

    # Normalize payload for the Monitor Agent
    normalized = {
        "job_name": job_name,
        "build_number": build_number,
        "repo_url": payload.get("build", {}).get("scm", {}).get("url", ""),
    }

    initial_state = AgentState()
    result = agent_graph.invoke({"state": initial_state, "raw_payload": normalized})
    final_state: AgentState = result["state"]

    return JSONResponse({
        "status": final_state.status,
        "job": job_name,
        "build": build_number,
        "failure_type": final_state.failure.failure_type.value if final_state.failure else None,
        "pr_url": final_state.pr_url,
    })


# ---------------------------------------------------------------------------
# Status & health endpoints
# ---------------------------------------------------------------------------

@app.get("/health", summary="Health check")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/runs/{job_name}/{build_number}", summary="Get agent run status")
async def get_run_status(job_name: str, build_number: int):
    """Check the current status of an agent run by Jenkins job + build number."""
    # TODO: fetch from Redis state store
    return {"job": job_name, "build": build_number, "status": "not_implemented_yet"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verify_webhook_token(request: Request):
    """
    Simple token-based auth for the Jenkins webhook.
    Jenkins sends ?token=<WEBHOOK_TOKEN> as a query param.
    Set JENKINS_WEBHOOK_TOKEN in .env.
    """
    expected = os.getenv("JENKINS_WEBHOOK_TOKEN", "")
    if not expected:
        logger.warning("JENKINS_WEBHOOK_TOKEN not set — skipping token check")
        return
    received = request.query_params.get("token", "")
    if not hmac.compare_digest(expected, received):
        raise HTTPException(status_code=401, detail="Invalid webhook token")
