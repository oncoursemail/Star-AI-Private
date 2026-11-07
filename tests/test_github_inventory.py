"""Offline protocol checks for pagination, rename identity, and credential boundaries."""
import asyncio
import hashlib
import json

import httpx
import pytest

from star import github_inventory as module
from star.github_inventory import GitHubInventoryReader


TOKEN = "fixture-read-token-never-log"
COMMIT = "c" * 40


def record(repository_id=11, full_name="owner/Original", **kwargs):
    return {"id": repository_id, "node_id": f"R_fixture{repository_id}", "full_name": full_name,
            "private": True, "visibility": "private", "default_branch": "main", "archived": False,
            "permissions": {"pull": True, "push": False}, **kwargs}


def reply_node(repository_id=11, name="owner/Renamed", **kwargs):
    return {"data": {"node": {
        "__typename": "Repository", "databaseId": repository_id, "id": f"R_fixture{repository_id}",
        "nameWithOwner": name, "visibility": "PRIVATE", "isArchived": False,
        "defaultBranchRef": {"name": "develop"}, "revision": {"__typename": "Commit", "oid": COMMIT},
        **kwargs,
    }}}


def blob(text="print('fixture')\n", **kwargs):
    raw = text.encode("utf-8")
    digest = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    return {"__typename": "Blob", "oid": digest, "byteSize": len(raw), "isBinary": False, "text": text, **kwargs}


def reader(handler, *, kind="user", max_pages=100):
    calls = []

    def handle(request):
        calls.append(request)
        assert request.url.host == "api.github.com"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        return handler(request)

    return GitHubInventoryReader(TOKEN, token_kind=kind, max_pages=max_pages,
                                  transport=httpx.MockTransport(handle)), calls


def normal_handler(request):
    if request.method == "GET":
        return httpx.Response(200, json=[record()])
    payload = json.loads(request.content)
    if "StarRepositoryIdentity" in payload["query"]:
        return httpx.Response(200, json=reply_node())
    return httpx.Response(200, json=reply_node(object=blob()))


def test_all_user_repository_pages_preserve_id_and_unknown_permissions():
    def handler(request):
        page = request.url.params["page"]
        assert request.url.path == "/user/repos"
        assert request.url.params["visibility"] == "all"
        assert request.url.params["affiliation"] == "owner,collaborator,organization_member"
        if page == "1":
            return httpx.Response(200, json=[record()], headers={
                "Link": '<https://api.github.com/user/repos?per_page=100&page=2>; rel="next"'})
        return httpx.Response(200, json=[record(22, "owner/Another", permissions={})])

    client, calls = reader(handler)
    result = asyncio.run(client.inventory())
    assert result["complete"] and result["repository_count"] == 2 and len(calls) == 2
    unknown = next(item for item in result["repositories"] if item["repository_id"] == 22)
    assert unknown["reported_permissions"]["push"] is None
    assert unknown["contents_read_verified"] is False
    assert TOKEN not in json.dumps(result)


def test_installation_pages_use_its_actual_total_count():
    def handler(request):
        assert request.url.path == "/installation/repositories"
        second = request.url.params["page"] == "2"
        return httpx.Response(200, json={"total_count": 2, "repositories": [record(22 if second else 11)]},
                              headers={} if second else {"Link": '<https://api.github.com/installation/repositories?per_page=100&page=2>; rel="next"'})

    client, _ = reader(handler, kind="installation")
    # Distinct IDs at the same name is a coherent-dataset failure, not a successful inventory.
    result = asyncio.run(client.inventory())
    assert result["repository_count"] == 2 and not result["complete"]


@pytest.mark.parametrize("mode", ["duplicate", "count_changed", "missing_total"])
def test_incomplete_installation_inventory_is_never_presented_as_complete(mode):
    def handler(request):
        page = int(request.url.params["page"])
        payload = {"total_count": 2 + (page - 1 if mode == "count_changed" else 0),
                   "repositories": [record(11 if mode == "duplicate" else page, f"owner/repo{page}")]}
        if mode == "missing_total":
            payload.pop("total_count")
        return httpx.Response(200, json=payload, headers={} if page == 2 else {
            "Link": '<https://api.github.com/installation/repositories?per_page=100&page=2>; rel="next"'})

    client, _ = reader(handler, kind="installation")
    if mode == "missing_total":
        with pytest.raises(ValueError, match="count"):
            asyncio.run(client.inventory())
    else:
        assert not asyncio.run(client.inventory())["complete"]


def test_page_limit_exposes_partial_result_and_refuses_resolution():
    client, calls = reader(lambda request: httpx.Response(200, json=[record()], headers={
        "Link": '<https://api.github.com/user/repos?per_page=100&page=2>; rel="next"'}), max_pages=1)
    result = asyncio.run(client.inventory())
    assert not result["complete"] and result["repository_count"] == 1
    with pytest.raises(RuntimeError, match="incomplete"):
        asyncio.run(client.resolve(11))
    assert all(call.method == "GET" for call in calls)


@pytest.mark.parametrize("link", [
    "https://evil.example/user/repos?per_page=100&page=2",
    "http://api.github.com/user/repos?per_page=100&page=2",
    "https://api.github.com@evil.example/user/repos?per_page=100&page=2",
    "https://api.github.com/user/emails?per_page=100&page=2",
    "https://api.github.com/user/repos?per_page=100&page=1",
    "https://api.github.com/user/repos?per_page=100&page=3",
    "https://api.github.com/user/repos?per_page=100&page=2&page=3",
    "https://api.github.com/user/repos?per_page=100&page=2&token=fixture",
    "https://api.github.com/user/repos?per_page=100&page=2#fragment",
])
def test_untrusted_pagination_cannot_leak_the_token_or_select_a_new_endpoint(link):
    client, calls = reader(lambda request: httpx.Response(200, json=[record()], headers={"Link": f'<{link}>; rel="next"'}))
    with pytest.raises(ValueError, match="pagination"):
        asyncio.run(client.inventory())
    assert len(calls) == 1


@pytest.mark.parametrize("status", [301, 302, 401, 403, 404, 429, 500])
def test_http_errors_do_not_follow_redirects_or_echo_credentials(status):
    client, calls = reader(lambda request: httpx.Response(status, json={"message": TOKEN},
                                                        headers={"Location": "https://evil.example/"}))
    with pytest.raises(RuntimeError) as error:
        asyncio.run(client.inventory())
    assert str(status) in str(error.value) and TOKEN not in str(error.value) and len(calls) == 1


def test_transport_failure_is_sanitized():
    def handler(request):
        raise httpx.ConnectError(TOKEN, request=request)

    client, _ = reader(handler)
    with pytest.raises(RuntimeError) as error:
        asyncio.run(client.inventory())
    assert TOKEN not in str(error.value)


@pytest.mark.parametrize("updates", [
    {"id": True}, {"id": -1}, {"node_id": ""}, {"private": "false"},
    {"full_name": "https://evil.example"}, {"full_name": "owner/.."},
    {"permissions": {"push": "yes"}}, {"visibility": "public"},
])
def test_bad_repository_records_are_refused(updates):
    client, _ = reader(lambda request: httpx.Response(200, json=[record(**updates)]))
    with pytest.raises(ValueError):
        asyncio.run(client.inventory())


def test_unneeded_api_fields_and_temp_clone_tokens_never_reach_output():
    client, _ = reader(lambda request: httpx.Response(200, json=[record(temp_clone_token=TOKEN, description=TOKEN)]))
    result = asyncio.run(client.inventory())
    assert TOKEN not in json.dumps(result)


def test_rename_and_old_name_reuse_remain_bound_to_the_original_id():
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=[record(11, "owner/New"), record(22, "owner/Original")])
        variables = json.loads(request.content)["variables"]
        assert variables["id"] == "R_fixture11"
        return httpx.Response(200, json=reply_node(11, "new-owner/RenamedAgain"))

    client, calls = reader(handler)
    result = asyncio.run(client.resolve(11))
    assert result["full_name"] == "new-owner/RenamedAgain" and result["repository_id"] == 11
    assert result["name_changed_since_inventory"] and result["commit_sha"] == COMMIT
    assert len(calls) == 2 and "/repos/owner/Original" not in str(calls[-1].url)


def test_removed_access_does_not_fall_back_to_public_or_same_name_repository():
    client, calls = reader(lambda request: httpx.Response(200, json=[record(22)]))
    with pytest.raises(PermissionError, match="not visible"):
        asyncio.run(client.resolve(11))
    assert len(calls) == 1


@pytest.mark.parametrize("payload", [{"data": {"node": None}}, {"errors": [{"message": TOKEN}]},
                                     reply_node(22), reply_node(__typename="User"), reply_node(databaseId=True)])
def test_graphql_identity_or_authorization_failure_refuses_source(payload):
    client, _ = reader(lambda request: httpx.Response(200, json=[record()] if request.method == "GET" else payload))
    with pytest.raises(PermissionError) as error:
        asyncio.run(client.read(11, "README.md"))
    assert TOKEN not in str(error.value)


def test_source_is_read_at_pinned_commit_with_verified_blob_and_no_mutations():
    client, calls = reader(normal_handler)
    result = asyncio.run(client.read(11, "README.md"))
    assert result["content"] == "print('fixture')\n" and result["contents_read_verified"]
    assert result["commit_sha"] == COMMIT and result["full_name"] == "owner/Renamed"
    assert result["source_url"] == f"https://github.com/owner/Renamed/blob/{COMMIT}/README.md"
    for call in calls[1:]:
        query = json.loads(call.content)["query"]
        assert query.startswith("query ") and "mutation" not in query
    assert json.loads(calls[-1].content)["variables"]["expression"] == COMMIT + ":README.md"


@pytest.mark.parametrize("updates", [
    {"isBinary": True}, {"isBinary": None}, {"text": None}, {"byteSize": True},
    {"byteSize": 65001}, {"byteSize": 0}, {"oid": "f" * 40}, {"__typename": "Tree"},
])
def test_invalid_source_hash_size_and_binary_content_are_refused(updates):
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=[record()])
        query = json.loads(request.content)["query"]
        payload = reply_node() if "StarRepositoryIdentity" in query else reply_node(object={**blob(), **updates})
        return httpx.Response(200, json=payload)

    client, _ = reader(handler)
    with pytest.raises(ValueError):
        asyncio.run(client.read(11, "README.md"))


def test_source_truncation_is_explicit_and_hash_is_for_the_whole_verified_blob():
    def handler(request):
        result = normal_handler(request)
        if request.method == "POST" and "StarRepositorySource" in json.loads(request.content)["query"]:
            result = httpx.Response(200, json=reply_node(object=blob("é" * 2000)))
        return result

    client, _ = reader(handler)
    result = asyncio.run(client.read(11, "README.md", max_chars=1000))
    assert result["content"] == "é" * 1000 and result["byte_size"] == 4000 and result["truncated"]


@pytest.mark.parametrize("path", ["../README.md", ".env", "src/.env", "src/private_token.py", "/README.md",
                                  "src//main.py", "https://evil.example", "src\\main.py", "model.gguf",
                                  "README.md:main", "x\nREADME.md"])
def test_source_path_errors_make_no_network_requests(path):
    client, calls = reader(normal_handler)
    with pytest.raises((ValueError, PermissionError)):
        asyncio.run(client.read(11, path))
    assert not calls


@pytest.mark.parametrize("repository_id", [0, -1, True, "11", None])
def test_invalid_ids_make_no_network_requests(repository_id):
    client, calls = reader(normal_handler)
    with pytest.raises(ValueError):
        asyncio.run(client.resolve(repository_id))
    assert not calls


def test_response_byte_limit(monkeypatch):
    monkeypatch.setattr(module, "MAX_RESPONSE_BYTES", 20)
    client, _ = reader(lambda request: httpx.Response(200, content=b"x" * 21))
    with pytest.raises(ValueError, match="bounded"):
        asyncio.run(client.inventory())


def test_configuration_never_falls_back_to_another_token_or_key(monkeypatch):
    monkeypatch.delenv("STAR_GITHUB_READ_CREDENTIAL_SOURCE", raising=False)
    monkeypatch.delenv("STAR_GITHUB_READ_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.setenv("GH_TOKEN", TOKEN)
    with pytest.raises(ValueError, match="credential"):
        module.from_env()
    monkeypatch.setenv("STAR_GITHUB_READ_TOKEN", TOKEN)
    monkeypatch.setenv("STAR_GITHUB_READ_TOKEN_KIND", "installation")
    assert module.from_env().token_kind == "installation"
    assert TOKEN not in repr(module.from_env())


def test_explicit_github_cli_credential_stays_out_of_arguments_files_and_output(monkeypatch, capsys):
    from subprocess import CompletedProcess

    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return CompletedProcess(argv, 0, stdout=TOKEN + "\n")

    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.delenv("STAR_GITHUB_READ_TOKEN", raising=False)
    client = module.from_env(credential_source="gh")
    assert client.token_kind == "user" and TOKEN not in repr(client)
    assert calls[0][0] == ["gh", "auth", "token", "--hostname", "github.com"]
    assert not calls[0][1].get("shell") and calls[0][1]["timeout"] == 10
    assert capsys.readouterr().out == ""


def test_failed_github_cli_lookup_does_not_fall_back_or_echo_stderr(monkeypatch):
    from subprocess import CompletedProcess

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: CompletedProcess(args, 1, stdout="", stderr=TOKEN))
    monkeypatch.setenv("STAR_GITHUB_READ_TOKEN", TOKEN)
    with pytest.raises(RuntimeError) as error:
        module.from_env(credential_source="gh")
    assert TOKEN not in str(error.value)


@pytest.mark.parametrize("source", ["", [], {}, False])
def test_invalid_explicit_credential_source_never_falls_back_to_environment(monkeypatch, source):
    monkeypatch.setenv("STAR_GITHUB_READ_TOKEN", TOKEN)
    with pytest.raises(ValueError, match="source"):
        module.from_env(credential_source=source)
