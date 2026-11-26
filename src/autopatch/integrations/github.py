"""GitHub API client — wraps PyGithub for clean agent-facing methods."""
import base64
import io
import logging
import os
import zipfile

from github import Github, GithubException

logger = logging.getLogger(__name__)


class GitHubClient:
    def __init__(self):
        token = os.getenv("GITHUB_TOKEN")
        if not token:
            raise EnvironmentError("GITHUB_TOKEN is not set")
        self._gh = Github(token)
        owner = os.getenv("GITHUB_REPO_OWNER", "")
        repo = os.getenv("GITHUB_REPO_NAME", "")
        self._repo = self._gh.get_repo(f"{owner}/{repo}")

    def get_run_logs(self, run_id: str) -> str:
        """Download and return the text logs for a workflow run."""
        try:
            run = self._repo.get_workflow_run(int(run_id))
            # GitHub API returns a redirect URL for logs (zip archive)
            log_url = run.logs_url
            import httpx, io, zipfile
            resp = httpx.get(log_url, headers={"Authorization": f"token {os.getenv('GITHUB_TOKEN')}"}, follow_redirects=True)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                logs = []
                for name in z.namelist():
                    logs.append(f"=== {name} ===\n" + z.read(name).decode("utf-8", errors="replace"))
            return "\n".join(logs)[:20000]  # Cap at 20k chars
        except Exception as e:
            logger.error(f"Failed to fetch logs for run {run_id}: {e}")
            return f"[Log fetch failed: {e}]"

    def get_failed_step(self, run_id: str) -> str:
        """Return the name of the first failed step in a workflow run."""
        try:
            run = self._repo.get_workflow_run(int(run_id))
            for job in run.jobs():
                for step in job.steps:
                    if step.conclusion == "failure":
                        return f"{job.name} / {step.name}"
            return "unknown"
        except Exception as e:
            logger.error(f"Failed to get failed step for run {run_id}: {e}")
            return "unknown"

    def create_patch_pr(
        self,
        base_branch: str,
        new_branch: str,
        file_path: str,
        patched_content: str,
        commit_message: str,
        pr_title: str,
        pr_body: str,
    ) -> str:
        """Create a branch with the patch applied and open a draft PR."""
        # Get base ref
        base_ref = self._repo.get_branch(base_branch)
        sha = base_ref.commit.sha

        # Create new branch
        self._repo.create_git_ref(ref=f"refs/heads/{new_branch}", sha=sha)

        # Get current file (to update it)
        try:
            existing_file = self._repo.get_contents(file_path, ref=base_branch)
            self._repo.update_file(
                path=file_path,
                message=commit_message,
                content=patched_content,
                sha=existing_file.sha,
                branch=new_branch,
            )
        except GithubException:
            # File doesn't exist yet — create it
            self._repo.create_file(
                path=file_path,
                message=commit_message,
                content=patched_content,
                branch=new_branch,
            )

        # Open draft PR
        pr = self._repo.create_pull(
            title=pr_title,
            body=pr_body,
            head=new_branch,
            base=base_branch,
            draft=True,
        )
        return pr.html_url

    def open_issue(self, title: str, body: str) -> str:
        """Open a GitHub issue (used when patch is rejected by guardrail)."""
        issue = self._repo.create_issue(title=title, body=body, labels=["autopatch", "needs-review"])
        return issue.html_url
