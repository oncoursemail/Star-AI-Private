"""Read-only discovery and source retrieval using an already granted GitHub token.

REST inventory retains repository IDs and live names across pagination. GraphQL
direct node queries bind subsequent reads to repository identity, so reusing an old
name cannot silently select another repository. No tokens are minted or persisted.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import PurePosixPath
import re
import subprocess
from urllib.parse import parse_qs, quote, urlsplit

import httpx

from .project_catalog import project_catalog, project_for_repository

API_ROOT = "https://api.github.com"
MAX_PAGES = 100
MAX_RESPONSE_BYTES = 2_000_000
MAX_FILE_BYTES = 65_000
MAX_OPERATION_SECONDS = 60
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_NODE = re.compile(r"[A-Za-z0-9_+/=-]{1,200}\Z")
_OID = re.compile(r"(?:[a-f0-9]{40}|[a-f0-9]{64})\Z")
_SOURCE_SUFFIXES = frozenset({
    ".py", ".md", ".txt", ".toml", ".json", ".yaml", ".yml", ".xml", ".css",
    ".html", ".tsx", ".ts", ".jsx", ".js", ".luau", ".lua", ".java", ".kt",
    ".kts", ".gradle", ".cs", ".cpp", ".cc", ".c", ".h", ".hpp", ".rs",
    ".go", ".gd", ".godot", ".shader", ".hlsl", ".glsl", ".sql", ".sh", ".ps1",
})
_METADATA_QUERY = """query StarRepositoryIdentity($id: ID!, $revision: String!) {
  node(id: $id) { __typename ... on Repository {
    id databaseId nameWithOwner visibility isArchived
    defaultBranchRef { name }
    revision: object(expression: $revision) { __typename oid }
  } }
}"""
_READ_QUERY = """query StarRepositorySource($id: ID!, $expression: String!) {
  node(id: $id) { __typename ... on Repository {
    id databaseId nameWithOwner
    object(expression: $expression) { __typename ... on Blob {
      oid byteSize isBinary text
    } }
  } }
}"""


def _positive_id(value) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("Repository ID must be a positive integer")
    return value


def _name(value) -> str:
    if (not isinstance(value, str) or len(value) > 250 or not _REPO.fullmatch(value)
            or any(part in {".", ".."} for part in value.split("/"))):
        raise ValueError("GitHub returned an invalid repository name")
    return value


def _node_id(value) -> str:
    if not isinstance(value, str) or not _NODE.fullmatch(value):
        raise ValueError("GitHub returned an invalid repository node ID")
    return value


def _record(raw) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("GitHub returned an invalid repository record")
    repository_id = _positive_id(raw.get("id"))
    full_name = _name(raw.get("full_name"))
    private = raw.get("private")
    if type(private) is not bool:
        raise ValueError("GitHub omitted repository visibility")
    visibility = raw.get("visibility", "private" if private else "public")
    if not isinstance(visibility, str) or visibility not in {"public", "private", "internal"} or (visibility == "public") == private:
        raise ValueError("GitHub returned inconsistent repository visibility")
    branch = raw.get("default_branch")
    if branch is not None and (not isinstance(branch, str) or len(branch) > 255):
        raise ValueError("GitHub returned an invalid default branch")
    permissions = raw.get("permissions", {})
    if not isinstance(permissions, dict):
        raise ValueError("GitHub returned invalid permission metadata")
    observed = {}
    for key in ("pull", "push", "admin", "maintain", "triage"):
        value = permissions.get(key)
        if value is not None and type(value) is not bool:
            raise ValueError("GitHub returned non-boolean permission metadata")
        observed[key] = value
    return {
        "repository_id": repository_id, "node_id": _node_id(raw.get("node_id")),
        "full_name": full_name, "html_url": f"https://github.com/{full_name}",
        "visibility": visibility, "default_branch": branch,
        "archived": raw.get("archived") if type(raw.get("archived")) is bool else None,
        "reported_permissions": observed, "contents_read_verified": False,
        "project": project_for_repository(repository_id),
    }


def validate_source_path(path: str) -> str:
    if (not isinstance(path, str) or not 1 <= len(path) <= 240
            or not re.fullmatch(r"[A-Za-z0-9_./ -]+", path)):
        raise ValueError("Source path must be a repository-relative path")
    parts = path.split("/")
    if any(not part or part in {".", ".."} or part.startswith(".") for part in parts):
        raise ValueError("Hidden paths and traversal are not source inputs")
    if any(any(word in part.casefold() for word in ("secret", "credential", "token", "private-key"))
           for part in parts):
        raise PermissionError("Credential-related paths cannot be loaded as source context")
    if PurePosixPath(path).suffix.lower() not in _SOURCE_SUFFIXES and path not in {"LICENSE", "Dockerfile"}:
        raise ValueError("Choose a supported text source or documentation file")
    return path


def _revision(value: str) -> str:
    if (not isinstance(value, str) or not 1 <= len(value) <= 255
            or not re.fullmatch(r"[A-Za-z0-9_./-]+", value)
            or ".." in value or value.startswith("/") or value.endswith("/")):
        raise ValueError("Choose a branch name or full commit ID")
    return value


class GitHubInventoryReader:
    """An explicit credential-scoped reader. Nothing runs merely by importing it."""

    def __init__(self, token: str, *, token_kind: str = "user", max_pages: int = MAX_PAGES,
                 transport=None):
        if (not isinstance(token, str) or not token or len(token) > 1000
                or any(ord(char) <= 32 or ord(char) > 126 for char in token)):
            raise ValueError("Configure an existing GitHub read credential")
        if not isinstance(token_kind, str) or token_kind not in {"user", "installation"}:
            raise ValueError("Credential kind must be user or installation")
        if type(max_pages) is not int or not 1 <= max_pages <= MAX_PAGES:
            raise ValueError("Inventory page limit must be 1–100")
        self._token = token
        self.token_kind = token_kind
        self.max_pages = max_pages
        self._transport = transport

    def _client(self):
        return httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False,
                                 transport=self._transport, headers={
                                     "Authorization": "Bearer " + self._token,
                                     "Accept": "application/vnd.github+json",
                                     "X-GitHub-Api-Version": "2022-11-28",
                                 })

    async def _request(self, client, method, url, **kwargs):
        # Only fixed GitHub endpoints and locally validated pagination links reach here.
        try:
            async with client.stream(method, url, **kwargs) as response:
                if response.status_code != 200:
                    raise RuntimeError(f"GitHub read returned HTTP {response.status_code}; access was not expanded")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise ValueError("GitHub response exceeded the bounded read limit")
                try:
                    payload = json.loads(body)
                except (ValueError, UnicodeError):
                    raise ValueError("GitHub returned invalid JSON") from None
                return payload, response.links
        except httpx.HTTPError:
            # Raw exception/request objects may contain credential-bearing headers.
            raise RuntimeError("GitHub read failed at the transport; retry after checking connectivity") from None

    def _next_page(self, links, path, page) -> str | None:
        next_link = links.get("next")
        if next_link is None:
            return None
        value = next_link.get("url", "")
        parts = urlsplit(value)
        query = parse_qs(parts.query, keep_blank_values=True)
        allowed = {"page", "per_page", "visibility", "affiliation", "sort", "direction"}
        if (parts.scheme != "https" or parts.netloc != "api.github.com" or parts.path != path
                or parts.fragment or not set(query) <= allowed
                or any(len(items) != 1 for items in query.values())
                or query.get("page") != [str(page + 1)] or query.get("per_page") != ["100"]):
            raise ValueError("GitHub returned an unsafe or inconsistent pagination link")
        # Reconstruct the next request locally so link metadata cannot narrow visibility.
        return self._page_url(path, page + 1)

    def _page_url(self, path, page):
        query = f"?per_page=100&page={page}"
        if self.token_kind == "user":
            query += "&visibility=all&affiliation=owner,collaborator,organization_member&sort=full_name&direction=asc"
        return API_ROOT + path + query

    async def _inventory(self, client) -> dict:
        path = "/installation/repositories" if self.token_kind == "installation" else "/user/repos"
        url = self._page_url(path, 1)
        records, names, issues = {}, {}, []
        totals = set()
        pages = 0
        while url and pages < self.max_pages:
            payload, links = await self._request(client, "GET", url)
            pages += 1
            if self.token_kind == "installation":
                if (not isinstance(payload, dict) or type(payload.get("total_count")) is not int
                        or payload["total_count"] < 0):
                    raise ValueError("GitHub omitted the installation inventory count")
                totals.add(payload["total_count"])
                raw_records = payload.get("repositories")
            else:
                raw_records = payload
            if not isinstance(raw_records, list) or len(raw_records) > 100:
                raise ValueError("GitHub returned an invalid repository page")
            for raw in raw_records:
                record = _record(raw)
                key = record["repository_id"]
                name_key = record["full_name"].casefold()
                if key in records:
                    issues.append("Repository IDs repeated across pages; inventory may have changed during collection")
                if name_key in names and names[name_key] != key:
                    issues.append("A repository name referred to multiple IDs during collection")
                records[key] = record
                names[name_key] = key
            url = self._next_page(links, path, pages)
        if url:
            issues.append("Page limit reached; additional repositories may be visible")
        if len(totals) > 1 or (totals and next(iter(totals)) != len(records)):
            issues.append("Installation total_count changed or did not match the collected unique IDs")
        unique_issues = list(dict.fromkeys(issues))
        return {
            "schema_version": "star-github-inventory-v1", "credential_kind": self.token_kind,
            "scope": "repositories_visible_to_this_credential", "complete": not unique_issues,
            "observed_at": datetime.now(timezone.utc).isoformat(), "pages_read": pages,
            "repository_count": len(records), "repositories": sorted(records.values(), key=lambda item: item["full_name"].casefold()),
            "issues": unique_issues, "read_only": True,
            "access_note": "Metadata visibility and reported roles do not prove contents or write access. No permissions were granted.",
        }

    async def inventory(self) -> dict:
        async with asyncio.timeout(MAX_OPERATION_SECONDS), self._client() as client:
            return await self._inventory(client)

    async def _identity(self, client, repository_id: int, revision: str) -> dict:
        inventory = await self._inventory(client)
        if not inventory["complete"]:
            raise RuntimeError("Repository inventory is incomplete; refresh before selecting a repository")
        record = next((item for item in inventory["repositories"] if item["repository_id"] == repository_id), None)
        if record is None:
            raise PermissionError("Repository ID is not visible to this credential; it may be unavailable or outside its granted scope")
        payload, _ = await self._request(client, "POST", API_ROOT + "/graphql",
                                         json={"query": _METADATA_QUERY,
                                               "variables": {"id": record["node_id"], "revision": revision}})
        node = self._repository_node(payload, repository_id)
        commit = node.get("revision")
        if not isinstance(commit, dict) or commit.get("__typename") != "Commit" or not _OID.fullmatch(str(commit.get("oid", ""))):
            raise ValueError("Selected revision is unavailable or is not a commit; choose a branch or commit ID")
        branch = node.get("defaultBranchRef")
        default_branch = branch.get("name") if isinstance(branch, dict) else None
        visibility = node.get("visibility")
        if (not isinstance(visibility, str) or visibility not in {"PUBLIC", "PRIVATE", "INTERNAL"}
                or type(node.get("isArchived")) is not bool):
            raise ValueError("GitHub omitted current repository visibility or archive status")
        return {**record, "node_id": _node_id(node.get("id")), "full_name": _name(node.get("nameWithOwner")),
                "html_url": "https://github.com/" + _name(node.get("nameWithOwner")),
                "default_branch": default_branch, "visibility": visibility.lower(),
                "archived": node["isArchived"], "commit_sha": commit["oid"],
                "requested_revision": revision, "name_changed_since_inventory": record["full_name"] != node["nameWithOwner"]}

    @staticmethod
    def _repository_node(payload, repository_id):
        if not isinstance(payload, dict) or payload.get("errors"):
            raise PermissionError("GitHub did not authorize or complete the repository query")
        data = payload.get("data")
        node = data.get("node") if isinstance(data, dict) else None
        if (not isinstance(node, dict) or node.get("__typename") != "Repository"
                or type(node.get("databaseId")) is not int or node["databaseId"] != repository_id):
            raise PermissionError("GitHub did not return the selected repository identity")
        _name(node.get("nameWithOwner"))
        return node

    async def resolve(self, repository_id: int, *, revision: str = "HEAD") -> dict:
        repository_id = _positive_id(repository_id)
        revision = _revision(revision)
        async with asyncio.timeout(MAX_OPERATION_SECONDS), self._client() as client:
            result = await self._identity(client, repository_id, revision)
        return {**result, "read_only": True, "untrusted_reference_only": True}

    async def read(self, repository_id: int, path: str, *, revision: str = "HEAD", max_chars: int = 18000) -> dict:
        repository_id = _positive_id(repository_id)
        path, revision = validate_source_path(path), _revision(revision)
        if type(max_chars) is not int or not 1000 <= max_chars <= 22000:
            raise ValueError("Source character limit must be 1,000–22,000")
        async with asyncio.timeout(MAX_OPERATION_SECONDS), self._client() as client:
            identity = await self._identity(client, repository_id, revision)
            payload, _ = await self._request(client, "POST", API_ROOT + "/graphql", json={
                "query": _READ_QUERY, "variables": {
                    "id": identity["node_id"], "expression": identity["commit_sha"] + ":" + path}})
            node = self._repository_node(payload, repository_id)
        blob = node.get("object")
        if (not isinstance(blob, dict) or blob.get("__typename") != "Blob"
                or blob.get("isBinary") is not False or type(blob.get("byteSize")) is not int
                or not 0 <= blob["byteSize"] <= MAX_FILE_BYTES or not isinstance(blob.get("text"), str)):
            raise ValueError("Selected object is not a supported small text source file")
        raw = blob["text"].encode("utf-8")
        oid = blob.get("oid")
        if len(raw) != blob["byteSize"] or not isinstance(oid, str) or not _OID.fullmatch(oid):
            raise ValueError("GitHub source metadata did not match the returned text")
        hash_name = "sha1" if len(oid) == 40 else "sha256"
        digest = hashlib.new(hash_name, b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
        if digest != oid:
            raise ValueError("GitHub source did not match its declared Git blob identity")
        full_name = node["nameWithOwner"]
        return {
            "repository_id": repository_id, "full_name": full_name,
            "project": identity["project"], "commit_sha": identity["commit_sha"],
            "path": path, "blob_sha": oid, "byte_size": len(raw),
            "source_url": f"https://github.com/{full_name}/blob/{identity['commit_sha']}/{quote(path, safe='/')}",
            "content": blob["text"][:max_chars], "truncated": len(blob["text"]) > max_chars,
            "contents_read_verified": True, "read_only": True, "untrusted_reference_only": True,
        }


def from_env(*, credential_source: str | None = None) -> GitHubInventoryReader:
    """Use an explicit token or the existing GitHub CLI credential, only in memory."""
    source = os.environ.get("STAR_GITHUB_READ_CREDENTIAL_SOURCE", "env") if credential_source is None else credential_source
    if not isinstance(source, str) or source not in {"env", "gh"}:
        raise ValueError("Reader credential source must be env or gh")
    if source == "gh":
        try:
            response = subprocess.run(["gh", "auth", "token", "--hostname", "github.com"],
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                      text=True, encoding="utf-8", timeout=10, check=False)
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError("GitHub CLI credential is unavailable; check this account's gh sign-in") from None
        if response.returncode != 0:
            raise RuntimeError("GitHub CLI did not provide a credential for github.com")
        token = response.stdout.strip()
    else:
        token = os.environ.get("STAR_GITHUB_READ_TOKEN", "")
    return GitHubInventoryReader(token,
                                 token_kind=os.environ.get("STAR_GITHUB_READ_TOKEN_KIND", "user"))


async def cli_result(command: str, *, repository_id: int | None = None, path: str = "", revision: str = "HEAD",
                     credential_source: str | None = None) -> dict:
    if command == "project-catalog":
        return project_catalog()
    reader = from_env(credential_source=credential_source)
    if command == "github-inventory":
        return await reader.inventory()
    if command == "github-resolve":
        return await reader.resolve(repository_id, revision=revision)
    if command == "github-read":
        return await reader.read(repository_id, path, revision=revision)
    raise ValueError("Unknown GitHub discovery command")
