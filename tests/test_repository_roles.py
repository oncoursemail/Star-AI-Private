"""Hermetic repository-role checks. No real GitHub requests or credentials."""
import asyncio

import httpx
import pytest

from star.repository_roles import (
    SOURCE_REPO, SOURCE_REPO_ID, RELEASE_REPO, RELEASE_REPO_ID,
    require_repository_identity, repository_overview,
)
from star.version import REPO


def metadata(source=True):
    return {"id": SOURCE_REPO_ID if source else RELEASE_REPO_ID,
            "full_name": SOURCE_REPO if source else RELEASE_REPO,
            "private": source, "default_branch": "main"}


def test_updater_stays_public_and_development_is_private():
    assert REPO == RELEASE_REPO and SOURCE_REPO != RELEASE_REPO
    require_repository_identity("source", metadata())
    require_repository_identity("releases", metadata(False))


@pytest.mark.parametrize("change", [
    {"id": True}, {"id": "1412474221"}, {"id": RELEASE_REPO_ID},
    {"private": False}, {"private": 1}, {"full_name": RELEASE_REPO},
])
def test_source_role_refuses_replacements_or_visibility_changes(change):
    with pytest.raises(PermissionError):
        require_repository_identity("source", {**metadata(), **change})


def test_roles_and_shapes_are_explicit():
    for role, value in [("unknown", metadata()), ("source", None), ("source", [])]:
        with pytest.raises(ValueError):
            require_repository_identity(role, value)


def test_both_roles_can_be_checked_without_a_private_token_on_public_requests():
    private_calls = []
    public_calls = []

    async def private_request(method, path):
        private_calls.append((method, path))
        return metadata()

    def public_handler(request):
        public_calls.append(str(request.url))
        assert "authorization" not in request.headers
        assert str(request.url) == f"https://api.github.com/repos/{RELEASE_REPO}"
        return httpx.Response(200, json=metadata(False))

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(public_handler)) as client:
            return await repository_overview(private_request, public_client=client)

    result = asyncio.run(exercise())
    assert private_calls == [("GET", f"/repos/{SOURCE_REPO}")]
    assert len(public_calls) == 1
    assert result["source"]["readable"] and result["releases"]["readable"]
    assert result["source"]["purpose"] == "development"
    assert result["releases"]["purpose"] == "downloads"
    assert "does not authorize" in result["note"]


def test_source_failure_is_not_replaced_with_public_source_or_secret_error_text():
    async def private_request(method, path):
        raise RuntimeError("secret-token-in-untrusted-provider-error")

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json=metadata(False)))) as client:
            return await repository_overview(private_request, public_client=client)

    result = asyncio.run(exercise())
    assert not result["source"]["readable"]
    assert result["releases"]["readable"]
    assert "secret-token" not in str(result)


def test_public_repository_replacement_is_reported_not_trusted():
    async def private_request(method, path):
        return metadata()

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={**metadata(False), "id": 999}))) as client:
            return await repository_overview(private_request, public_client=client)

    result = asyncio.run(exercise())
    assert result["source"]["readable"]
    assert not result["releases"]["readable"]
    assert result["releases"]["error_type"] == "PermissionError"
