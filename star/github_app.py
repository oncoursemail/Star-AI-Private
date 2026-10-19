"""GitHub App installation authentication and private developer-branch proposals.

The developer App never publishes public releases or merges PRs. Source and public
release credentials are separate. Branches and draft PRs use an owner-configured
work branch, not the default branch. Actual runtime proposals carry a run receipt;
that receipt does not assert that testing, human review or publication occurred.
"""
import os
import re
import time
from pathlib import Path, PurePosixPath
from urllib.parse import quote
from uuid import uuid4

import httpx
import jwt

from .repository_roles import SOURCE_REPO as REPO, require_repository_identity, repository_overview

BRANCH = re.compile(r"^star/[a-z0-9][a-z0-9._-]{0,49}$")
SAFE_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
NO_MAIN = ("STAR opens pull requests only against a star/<name> work branch, never main or the repository's "
           "default branch. Set STAR_GITHUB_BASE_BRANCH to the work branch.")


def valid_upload_path(path: str) -> bool:
    """Skill modules and their documentation only; never graders, policies or release files."""
    if not isinstance(path, str) or not path or len(path) > 170 or "\\" in path:
        return False
    parts = PurePosixPath(path)
    if (path != parts.as_posix() or parts.is_absolute() or ".." in parts.parts
            or any(part.startswith(".") for part in parts.parts)):
        return False
    if path == "star/skills/__init__.py":
        return False
    return ((path.startswith("star/skills/") and path.endswith(".py")) or
            (path.startswith("docs/skills/") and path.endswith(".md")))


class GitHubApp:
    def __init__(self, app_id: str, installation_id: str, key_file: Path, repo: str, base_branch: str = ""):
        if not (app_id.isdigit() and installation_id.isdigit() and SAFE_REPO.fullmatch(repo)):
            raise ValueError("GitHub App config requires numeric IDs and owner/repo")
        if base_branch and not BRANCH.fullmatch(base_branch):
            raise ValueError(NO_MAIN)
        if not key_file.is_file():
            raise ValueError("GitHub App private key is missing")
        if key_file.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
            raise ValueError("GitHub App private key must be outside the project repository")
        self.repo = repo
        self.base_branch = base_branch
        self.app_id = app_id
        self.installation_id = installation_id
        self.key_file = key_file
        self.token = ""
        self.token_expires = 0.0
        self.run_id = uuid4().hex
        self.last_activity = None

    async def _install_token(self):
        if self.repo != REPO:
            raise PermissionError("Set STAR_GITHUB_REPO to the private Star-AI-Private source repository")
        if self.token and time.time() + 120 < self.token_expires:
            return self.token
        now = int(time.time())
        assertion = jwt.encode({"iat": now - 60, "exp": now + 540, "iss": self.app_id},
                               self.key_file.read_text(encoding="utf-8"), algorithm="RS256")
        async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.post(f"https://api.github.com/app/installations/{self.installation_id}/access_tokens",
                                         headers={"Authorization": f"Bearer {assertion}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
                                         json={"repositories": [self.repo.split("/", 1)[1]],
                                               "permissions": {"contents": "write", "pull_requests": "write"}})
            response.raise_for_status()
            info = response.json()
        self.token = info["token"]
        from datetime import datetime
        expiry = info.get("expires_at")
        self.token_expires = (datetime.fromisoformat(expiry.replace("Z", "+00:00")).timestamp()
                              if expiry else time.time() + 3000)
        return self.token

    async def request(self, method: str, path: str, **kwargs):
        token = await self._install_token()
        async with httpx.AsyncClient(timeout=40, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, "https://api.github.com" + path,
                                            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}, **kwargs)
        if response.status_code >= 300:
            raise RuntimeError(f"GitHub returned HTTP {response.status_code} for {method} {path}")
        return response.json() if response.content else {}

    async def check(self):
        return await self.request("GET", "/installation/repositories?per_page=100")

    async def repository_status(self, *, public_client=None):
        """Read both roles without sending the private token to public endpoints."""
        return await repository_overview(self.request, public_client=public_client)

    async def create_branch(self, name: str):
        if self.repo != REPO:
            raise PermissionError("STAR GitHub App can modify only the canonical private STAR source repository")
        if not BRANCH.fullmatch(name):
            raise ValueError("Only names star/<safe-name> are permitted")
        repo = quote(self.repo, safe="/")
        base = await self.work_base(name)
        ref = await self.request("GET", f"/repos/{repo}/git/ref/heads/{quote(base, safe='/')}")
        await self.request("POST", f"/repos/{repo}/git/refs", json={"ref": "refs/heads/" + name, "sha": ref["object"]["sha"]})
        self.last_activity = {"actor": "star-ai", "run_id": self.run_id, "stage": "branch-created", "branch": name}
        return base

    async def work_base(self, head: str) -> str:
        """Require the exact private repository identity and non-default work branch."""
        if self.repo != REPO:
            raise PermissionError("Development work must target the private STAR source repository")
        base = self.base_branch
        if not base or not BRANCH.fullmatch(base) or base == head:
            raise PermissionError(NO_MAIN)
        info = await self.request("GET", f"/repos/{quote(self.repo, safe='/')}")
        require_repository_identity("source", info)
        if not info.get("default_branch") or base == info["default_branch"]:
            raise PermissionError(NO_MAIN)
        return base

    async def write_branch_file(self, branch: str, path: str, raw: bytes, message: str):
        if self.repo != REPO:
            raise PermissionError("STAR GitHub App cannot upload source to the public download repository")
        if not BRANCH.fullmatch(branch) or not valid_upload_path(path):
            raise ValueError("Branch or file outside STAR's allowed write scope")
        if branch == self.base_branch:
            raise PermissionError("STAR writes to its own proposal branch, not straight into the work branch")
        if len(raw) > 300_000:
            raise ValueError("Text file is too large for this starter")
        await self.work_base(branch)
        import base64
        endpoint = f"/repos/{quote(self.repo, safe='/')}/contents/{quote(path, safe='/')}"
        sha = None
        try:
            existing = await self.request("GET", endpoint, params={"ref": branch})
            sha = existing.get("sha")
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc):
                raise
        # The trusted host creates the execution receipt. Model prose is only the
        # commit subject; it cannot fabricate additional identity/test trailers.
        subject = " ".join(str(message).splitlines())[:200]
        commit_message = (subject + "\n\nAI-Actor: Star AI\nAI-Run-ID: " + self.run_id
                          + "\nAI-Stage: proposed\nAI-Tests: not-recorded\n")
        payload = {"message": commit_message, "content": base64.b64encode(raw).decode("ascii"), "branch": branch}
        if sha:
            payload["sha"] = sha
        result = await self.request("PUT", endpoint, json=payload)
        commit = result.get("commit") or {}
        self.last_activity = {"actor": "star-ai", "run_id": self.run_id, "stage": "committed-proposal",
                              "branch": branch, "path": path, "commit_sha": commit.get("sha"), "tests": "not-recorded"}
        return result

    async def open_pr(self, base: str, head: str, title: str, body: str):
        if self.repo != REPO:
            raise PermissionError("STAR GitHub App cannot open development PRs outside the private source repository")
        if not BRANCH.fullmatch(head):
            raise ValueError("Not a STAR work branch")
        if not isinstance(base, str) or not BRANCH.fullmatch(base) or base != await self.work_base(head):
            raise PermissionError(NO_MAIN)
        receipt = ("\n\n---\n### STAR runtime receipt\n"
                   f"<!-- star-ai-run:{self.run_id} -->\n"
                   f"GitHub App ID: {self.app_id}\n\nRun ID: `{self.run_id}`\n\n"
                   "Stage: proposed. This action has not verified tests, human review, merging or release. "
                   "Confirm the authenticated GitHub App author before treating this as Star AI activity.\n")
        result = await self.request("POST", f"/repos/{quote(self.repo, safe='/')}/pulls",
                                    json={"title": title[:200], "body": body[:8500] + receipt,
                                          "base": base, "head": head, "draft": True})
        self.last_activity = {"actor": "star-ai", "run_id": self.run_id, "stage": "pull-request-proposed",
                              "number": result.get("number"), "tests": "not-recorded"}
        return result


def from_env() -> GitHubApp:
    key = os.environ.get("STAR_GITHUB_PRIVATE_KEY_FILE", "")
    if not key:
        raise ValueError("Configure STAR_GITHUB_PRIVATE_KEY_FILE outside the repository")
    repo = os.environ.get("STAR_GITHUB_REPO", REPO).strip()
    if repo != REPO:
        raise ValueError("STAR_GITHUB_REPO must be oncoursemail/Star-AI-Private; Star-AI is for public downloads")
    return GitHubApp(os.environ.get("STAR_GITHUB_APP_ID", ""),
                     os.environ.get("STAR_GITHUB_INSTALLATION_ID", ""), Path(key).expanduser(), repo,
                     base_branch=os.environ.get("STAR_GITHUB_BASE_BRANCH", "").strip())
