"""Fixed repository identities and a bounded, read-only GitHub role diagnostic.

Private development tokens are never sent to the public repository. Neither this
module nor a role descriptor grants permission to merge, publish or access files.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

SOURCE_REPO = "oncoursemail/Star-AI-Private"
SOURCE_REPO_ID = 1412474221
RELEASE_REPO = "oncoursemail/Star-AI"
RELEASE_REPO_ID = 1424898960

ROLES = {
    "source": (SOURCE_REPO, SOURCE_REPO_ID, True),
    "releases": (RELEASE_REPO, RELEASE_REPO_ID, False),
}


def require_repository_identity(role: str, metadata: dict) -> None:
    """Refuse renamed/replaced/wrong-visibility repositories, including bool IDs."""
    if role not in ROLES or not isinstance(metadata, dict):
        raise ValueError("Unknown repository role or invalid metadata")
    name, identifier, private = ROLES[role]
    if (type(metadata.get("id")) is not int or metadata["id"] != identifier
            or metadata.get("full_name") != name or metadata.get("private") is not private):
        raise PermissionError("GitHub repository identity or visibility changed; owner review is required")


async def repository_overview(
    source_request: Callable[..., Awaitable[Any]], *, public_client=None,
) -> dict:
    """Read safe metadata for both roles; credentials stay with the source client.

    Does not enumerate private files, return API error bodies, write GitHub data,
    install credentials, or claim that source access implies release permission.
    An injected public_client is a trusted test adapter, not model supplied.
    """
    import httpx

    result = {}
    try:
        metadata = await source_request("GET", f"/repos/{SOURCE_REPO}")
        require_repository_identity("source", metadata)
        result["source"] = {"repository": SOURCE_REPO, "visibility": "private", "readable": True,
                            "default_branch": metadata.get("default_branch"), "purpose": "development"}
    except (httpx.HTTPError, RuntimeError, ValueError, PermissionError, KeyError, TypeError) as exc:
        result["source"] = {"repository": SOURCE_REPO, "readable": False, "error_type": type(exc).__name__}
    own = public_client is None
    client = public_client or httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False)
    try:
        response = await client.get(f"https://api.github.com/repos/{RELEASE_REPO}",
                                    headers={"Accept": "application/vnd.github+json"})
        response.raise_for_status()
        metadata = response.json()
        require_repository_identity("releases", metadata)
        result["releases"] = {"repository": RELEASE_REPO, "visibility": "public", "readable": True,
                              "default_branch": metadata.get("default_branch"), "purpose": "downloads"}
    except (httpx.HTTPError, RuntimeError, ValueError, PermissionError, KeyError, TypeError) as exc:
        result["releases"] = {"repository": RELEASE_REPO, "readable": False, "error_type": type(exc).__name__}
    finally:
        if own:
            await client.aclose()
    result["note"] = ("Read access does not authorize merging or publication. Source development and public "
                      "release publishing use different credentials. No release or test was performed.")
    return result
