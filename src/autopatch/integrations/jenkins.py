"""Jenkins REST API client.

Wraps Jenkins API calls needed by the Monitor Agent:
- Fetch build console log
- Identify the failed stage/step
- Trigger a new build (for the Verifier agent)

Jenkins REST API docs: https://www.jenkins.io/doc/book/using/remote-access-api/
"""
import json
import logging
import os
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class JenkinsBuild:
    job_name: str
    build_number: int
    branch: str
    commit_sha: str
    result: str          # FAILURE | UNSTABLE | SUCCESS | ABORTED
    console_log: str
    failed_stage: str
    timestamp: str


class JenkinsClient:
    def __init__(self):
        self.base_url = os.getenv("JENKINS_URL", "http://localhost:8080").rstrip("/")
        self.user = os.getenv("JENKINS_USER", "admin")
        self.token = os.getenv("JENKINS_API_TOKEN", "")
        self._auth = (self.user, self.token)

    # ------------------------------------------------------------------
    # Core API helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, **kwargs) -> httpx.Response:
        url = f"{self.base_url}{path}"
        response = httpx.get(url, auth=self._auth, timeout=10.0, **kwargs)
        response.raise_for_status()
        return response

    def _post(self, path: str, **kwargs) -> httpx.Response:
        url = f"{self.base_url}{path}"
        response = httpx.post(url, auth=self._auth, timeout=10.0, **kwargs)
        response.raise_for_status()
        return response

    # ------------------------------------------------------------------
    # Monitor Agent methods
    # ------------------------------------------------------------------

    def get_build_info(self, job_name: str, build_number: int) -> dict:
        """Fetch JSON metadata for a specific build."""
        path = f"/job/{job_name}/{build_number}/api/json"
        return self._get(path).json()

    def get_console_log(self, job_name: str, build_number: int) -> str:
        """Fetch the full console text output for a build."""
        path = f"/job/{job_name}/{build_number}/consoleText"
        try:
            log = self._get(path).text
            return log[-20000:]  # Keep the latest output, where build failures are reported
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch console log: {e}")
            return f"[Log fetch failed: {e}]"

    def get_failed_stage(self, job_name: str, build_number: int) -> str:
        """
        Extract the failed stage/step from pipeline stage data.
        Uses the Workflow API (available when using Jenkins Pipelines).
        Falls back to log parsing if unavailable.
        """
        try:
            path = f"/job/{job_name}/{build_number}/wfapi/describe"
            data = self._get(path).json()
            for stage in data.get("stages", []):
                if stage.get("status") == "FAILED":
                    return stage.get("name", "unknown stage")
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            logger.info(f"Workflow API unavailable; falling back to console log: {e}")

        # Fallback: parse console log for failure markers
        log = self.get_console_log(job_name, build_number)
        return _parse_failed_stage_from_log(log)

    def get_build_scm_info(self, job_name: str, build_number: int) -> dict:
        """Extract branch name and commit SHA from build actions."""
        info = self.get_build_info(job_name, build_number)
        branch = "unknown"
        commit_sha = ""

        for action in info.get("actions", []):
            # Git plugin action
            last_built = action.get("lastBuiltRevision", {})
            branches = last_built.get("branch", [])
            if branches:
                branch = branches[0].get("name", "unknown").replace("origin/", "")
                commit_sha = branches[0].get("SHA1", "")
                break

            # Fallback: build data
            remote_urls = action.get("remoteUrls", [])
            if not branch and remote_urls:
                branch = info.get("displayName", "unknown")

        return {"branch": branch, "commit_sha": commit_sha}

    # ------------------------------------------------------------------
    # Verifier Agent methods
    # ------------------------------------------------------------------

    def trigger_build(self, job_name: str, branch: str) -> int | None:
        """
        Trigger a new build for a given branch (e.g. the patched branch).
        Returns the new build number, or None on failure.
        """
        try:
            path = f"/job/{job_name}/buildWithParameters"
            self._post(path, params={"BRANCH": branch})
            # Fetch the next build number
            info = self._get(f"/job/{job_name}/api/json").json()
            return info.get("nextBuildNumber")
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            logger.error(f"Failed to trigger Jenkins build: {e}")
            return None

    def get_build_result(self, job_name: str, build_number: int) -> str | None:
        """Poll a build result — returns None if still in progress."""
        info = self.get_build_info(job_name, build_number)
        return info.get("result")  # None while running, "SUCCESS"/"FAILURE" when done


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_failed_stage_from_log(log: str) -> str:
    """Heuristic: find the stage that Jenkins reported as failed."""
    stage_pattern = re.compile(r"\[Pipeline\] \{ \((.+?)\)")
    error_pattern = re.compile(r"ERROR|FAILED|error:", re.IGNORECASE)

    stages_seen = []
    for line in log.splitlines():
        m = stage_pattern.search(line)
        if m:
            stages_seen.append(m.group(1))
        if error_pattern.search(line) and stages_seen:
            return stages_seen[-1]

    return stages_seen[-1] if stages_seen else "unknown"
