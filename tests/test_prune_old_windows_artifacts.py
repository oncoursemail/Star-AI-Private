"""Exercise the manual helper against fake GitHub state; never contact GitHub."""
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

SPEC = importlib.util.spec_from_file_location("pruner", Path(__file__).parents[1] / "scripts/prune_old_windows_artifacts.py")
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)
NOW = datetime(2026, 10, 19, 3, tzinfo=timezone.utc)
OLD = "2026-10-10T01:00:00Z"
SHA = "a" * 40


def artifact(identifier=1, name="STAR-Fast-Brain-Preview"):
    return {"id": identifier, "name": name, "size_in_bytes": 100 * identifier,
            "expired": False, "created_at": OLD, "updated_at": OLD,
            "expires_at": "2026-11-01T01:00:00Z", "workflow_run": {
                "id": 91, "repository_id": p.REPO_ID, "head_repository_id": p.REPO_ID,
                "head_branch": "star/old-work", "head_sha": SHA}}


class Fake:
    def __init__(self, count=1):
        self.items = {i: artifact(i) for i in range(1, count + 1)}
        self.meta = {"id": p.REPO_ID, "full_name": p.REPO, "private": True, "default_branch": "main"}
        self.run = {"id": 91, "workflow_id": p.WINDOWS_WORKFLOW_ID,
                    "path": p.WINDOWS_WORKFLOW_PATH, "run_attempt": 1, "event": "pull_request",
                    "status": "completed", "conclusion": "success", "created_at": OLD,
                    "updated_at": OLD, "head_sha": SHA, "head_branch": "star/old-work",
                    "repository": {"id": p.REPO_ID},
                    "head_repository": {"id": p.REPO_ID, "owner": {"login": "oncoursemail"}},
                    "pull_requests": []}
        self.pr = {"id": 1510, "number": 151, "state": "closed", "closed_at": OLD,
                   "base": {"repo": {"id": p.REPO_ID}},
                   "head": {"sha": SHA, "ref": "star/old-work", "repo": {"id": p.REPO_ID}}}
        self.other_open = []
        self.associations = [self.pr]
        self.head_associations = []
        self.deleted, self.calls, self.delete_errors = [], [], {}
        self.page_overrides, self.get_errors = {}, {}

    def get(self, path):
        self.calls.append(("GET", path))
        if path in self.get_errors:
            raise self.get_errors[path]
        if path == p.ROOT:
            return copy.deepcopy(self.meta)
        if path == p.ROOT + "/actions/runs/91":
            return copy.deepcopy(self.run)
        for pr in [self.pr, *self.associations, *self.head_associations]:
            if path == p.ROOT + f"/pulls/{pr['number']}":
                return copy.deepcopy(pr)
        if path.startswith(p.ROOT + "/actions/artifacts/"):
            identifier = int(path.rsplit("/", 1)[1])
            if identifier not in self.items:
                raise p.ApiError("Missing artifact", 404)
            return copy.deepcopy(self.items[identifier])
        raise AssertionError(path)

    def pages(self, path):
        self.calls.append(("PAGES", path))
        if path in self.page_overrides:
            value = self.page_overrides[path]
            if isinstance(value, Exception):
                raise value
            return copy.deepcopy(value)
        if path == p.ROOT + "/pulls?state=open&per_page=100":
            rows = self.other_open + ([self.pr] if self.pr["state"] == "open" else [])
            return [copy.deepcopy(rows)]
        if path == p.ROOT + f"/commits/{SHA}/pulls?per_page=100":
            return [copy.deepcopy(self.associations)]
        if path.startswith(p.ROOT + "/pulls?state=all&head="):
            rows = self.head_associations
            return copy.deepcopy([rows[i:i + 100] for i in range(0, len(rows), 100)] or [[]])
        if path in (p.ROOT + "/actions/artifacts?per_page=100", p.ROOT + "/actions/runs/91/artifacts?per_page=100"):
            rows = list(self.items.values())
            batches = [rows[i:i + 100] for i in range(0, len(rows), 100)] or [[]]
            return copy.deepcopy([{"artifacts": batch, "total_count": len(rows)} for batch in batches])
        raise AssertionError(path)

    def delete(self, identifier):
        self.calls.append(("DELETE", identifier))
        if identifier in self.delete_errors:
            raise self.delete_errors[identifier]
        self.deleted.append(identifier)
        del self.items[identifier]


def plan(client, **kwargs):
    return p.create_plan(client, NOW, **kwargs)


def apply(client, manifest, emit=lambda event: None, current=NOW):
    return p.apply_plan(client, manifest, emit, clock=lambda: current)


def test_read_only_plan_resolves_empty_run_association_and_counts_preserved_files():
    client = Fake(3)
    client.items[2]["name"] = "STAR-Windows-vNext"
    client.items[3]["name"] = "windows-tests-shard-1"
    manifest = plan(client)
    assert [e["artifact"]["id"] for e in manifest["artifacts"]] == [1]
    assert manifest["artifacts"][0]["pull_requests"][0]["number"] == 151
    assert manifest["statistics"] == {"listed_count": 3, "listed_bytes": 600,
        "candidate_count": 1, "candidate_bytes": 100, "preserved_count": 2, "preserved_bytes": 500,
        "preserved_reasons": {"other artifact family": 2}}
    assert not client.deleted
    assert not any(call[0] == "DELETE" for call in client.calls)


@pytest.mark.parametrize("change", [
    {"event": "push"}, {"event": "workflow_dispatch"}, {"status": "in_progress"},
    {"head_branch": "main"}, {"updated_at": "2026-10-18T01:00:00Z"},
    {"repository": {"id": 999}}, {"run_attempt": None}, {"id": 92},
])
def test_non_pr_recent_incomplete_and_foreign_runs_are_preserved(change):
    client = Fake()
    client.run.update(change)
    assert plan(client)["artifacts"] == []


@pytest.mark.parametrize("change", [
    {"workflow_id": 7}, {"path": ".github/workflows/release.yml"}, {"path": None},
])
def test_same_named_artifact_from_wrong_workflow_is_preserved_and_rechecked(change):
    client = Fake()
    manifest = plan(client)
    client.run.update(change)
    assert plan(client)["artifacts"] == []
    with pytest.raises(p.Stop):
        apply(client, manifest)
    assert client.deleted == []


@pytest.mark.parametrize("change", [
    {"expired": True}, {"name": "STAR-Windows-vNext"}, {"size_in_bytes": True},
    {"created_at": "2026-10-18T01:00:00Z"}, {"expires_at": "2026-10-18T01:00:00Z"},
    {"updated_at": "not-a-date"}, {"workflow_run": None},
])
def test_unverified_or_retained_artifacts_are_not_candidates(change):
    client = Fake()
    client.items[1].update(change)
    if "size_in_bytes" in change:
        with pytest.raises(p.Stop):
            plan(client)
    else:
        assert plan(client)["artifacts"] == []


@pytest.mark.parametrize("same_branch", [True, False])
def test_another_open_pr_protects_branch_or_source_sha(same_branch):
    client = Fake()
    extra = copy.deepcopy(client.pr)
    extra.update(id=1520, number=152, state="open")
    extra["head"] = {"ref": "star/old-work" if same_branch else "another", "sha": "b" * 40 if same_branch else SHA}
    client.other_open = [extra]
    assert plan(client)["artifacts"] == []


def test_explicit_keep_unknown_association_and_reopened_pr_are_preserved():
    client = Fake()
    assert plan(client, keep=[91])["artifacts"] == []
    client.associations = []
    assert plan(client)["artifacts"] == []
    client.associations = [client.pr]
    client.pr["state"] = "open"
    assert plan(client)["artifacts"] == []


def test_foreign_pr_number_cannot_be_resolved_as_an_unrelated_closed_local_pr():
    client = Fake()
    foreign = copy.deepcopy(client.pr)
    foreign["base"]["repo"]["id"] = 999
    client.run["pull_requests"] = [foreign]
    assert plan(client)["artifacts"] == []
    assert ("GET", p.ROOT + "/pulls/151") not in client.calls


@pytest.mark.parametrize("wrong_repository", [False, True])
def test_fallback_commit_association_requires_matching_original_run_branch(wrong_repository):
    client = Fake()
    manifest = plan(client)
    assert manifest["statistics"]["candidate_count"] == 1
    if wrong_repository:
        client.pr["head"]["repo"]["id"] = 999
    else:
        client.pr["head"]["ref"] = "unrelated-pr-containing-the-same-commit"
    assert plan(client)["artifacts"] == []
    with pytest.raises(p.Stop):
        apply(client, manifest)
    assert client.deleted == []


def test_matching_fallback_branch_does_not_bypass_other_open_associations():
    client = Fake()
    other = copy.deepcopy(client.pr)
    other.update(id=1520, number=152, state="open")
    other["head"]["ref"] = "another-branch"
    client.associations.append(other)
    original_get = client.get
    client.get = lambda path: copy.deepcopy(other) if path == p.ROOT + "/pulls/152" else original_get(path)
    assert plan(client)["artifacts"] == []
    assert client.deleted == []


HEAD_LOOKUP = p.ROOT + "/pulls?state=all&head=oncoursemail%3Astar%2Fold-work&per_page=100"


def needs_head_lookup():
    client = Fake()
    original = copy.deepcopy(client.pr)
    original.update(id=1160, number=116)
    client.pr["head"]["ref"] = "another-pr-containing-the-commit"
    client.head_associations = [original]
    return client


@pytest.mark.parametrize("empty_commit_associations", [False, True])
def test_real_head_lookup_proves_original_pr_and_keeps_all_commit_associations(empty_commit_associations):
    client = needs_head_lookup()
    if empty_commit_associations:
        client.associations = []
    manifest = plan(client)
    assert manifest["statistics"]["candidate_count"] == 1
    assert [pr["number"] for pr in manifest["artifacts"][0]["pull_requests"]] == (
        [116] if empty_commit_associations else [116, 151])
    assert ("PAGES", HEAD_LOOKUP) in client.calls
    assert ("GET", p.ROOT + "/pulls/116") in client.calls
    assert client.deleted == []


@pytest.mark.parametrize("change", ["missing", "branch", "repository", "base", "open", "ambiguous"])
def test_unverified_or_ambiguous_head_lookup_preserves_artifacts(change):
    client = needs_head_lookup()
    original = client.head_associations[0]
    if change == "missing":
        client.head_associations = []
    elif change == "branch":
        original["head"]["ref"] = "another-branch"
    elif change == "repository":
        original["head"]["repo"]["id"] = 999
    elif change == "base":
        original["base"]["repo"]["id"] = 999
    elif change == "open":
        original["state"] = "open"
    else:
        duplicate_branch = copy.deepcopy(original)
        duplicate_branch.update(id=1170, number=117)
        client.head_associations.append(duplicate_branch)
    assert plan(client)["artifacts"] == []
    assert client.deleted == []


def test_head_lookup_does_not_bypass_open_commit_association():
    client = needs_head_lookup()
    client.pr["state"] = "open"
    client.pr["head"]["sha"] = "b" * 40  # Global open refs do not mask this specific association check.
    assert plan(client)["artifacts"] == []
    assert ("PAGES", HEAD_LOOKUP) in client.calls


def test_head_lookup_is_repeated_and_reopened_original_blocks_delete():
    client = needs_head_lookup()
    manifest = plan(client)
    def emit(event):
        if event["status"] == "preflight_passed":
            client.head_associations[0]["state"] = "open"
    with pytest.raises(p.Stop):
        apply(client, manifest, emit)
    assert client.calls.count(("PAGES", HEAD_LOOKUP)) == 3
    assert client.deleted == []


@pytest.mark.parametrize("failure", [p.ApiError("Forbidden", 403), [[] , []]])
def test_head_lookup_api_errors_and_incomplete_pagination_stop(failure):
    client = needs_head_lookup()
    client.page_overrides[HEAD_LOOKUP] = failure
    with pytest.raises(p.Stop):
        plan(client)
    assert client.deleted == []


def test_full_pagination_and_selected_run_scope():
    client = Fake(101)
    manifest = plan(client, scope_runs=[91])
    assert manifest["scope_run_ids"] == [91]
    assert manifest["statistics"]["listed_count"] == 101
    assert manifest["statistics"]["candidate_count"] == 101
    assert ("PAGES", p.ROOT + "/actions/artifacts?per_page=100") not in client.calls


@pytest.mark.parametrize("pages", [
    [], [{"artifacts": [artifact()], "total_count": 2}],
    [{"artifacts": [artifact(), artifact()], "total_count": 2}],
    [{"artifacts": [artifact()], "total_count": 1}, {"artifacts": [], "total_count": 1}],
    [{"artifacts": [artifact(i) for i in range(1, 101)], "total_count": 101},
     {"artifacts": [artifact(101)], "total_count": 102}],
])
def test_incomplete_duplicate_or_changing_inventory_fails_closed(pages):
    client = Fake()
    client.page_overrides[p.ROOT + "/actions/artifacts?per_page=100"] = pages
    with pytest.raises(p.Stop):
        plan(client)
    assert client.deleted == []


@pytest.mark.parametrize("mutation", [
    lambda m: m["artifacts"][0]["artifact"].update(size_in_bytes=1),
    lambda m: m.update(repository="oncoursemail/Star-AI"),
    lambda m: m.update(min_age_days=2, sha256="recompute"),
    lambda m: m["artifacts"].append(copy.deepcopy(m["artifacts"][0])),
])
def test_tampered_or_widened_manifest_stops_before_api_calls(mutation):
    client = Fake()
    manifest = plan(client)
    mutation(manifest)
    if manifest["sha256"] == "recompute":
        manifest["sha256"] = p.digest(manifest)
    client.calls.clear()
    with pytest.raises(p.Stop):
        apply(client, manifest)
    assert client.calls == []


@pytest.mark.parametrize("offset", [timedelta(hours=24, seconds=1), timedelta(seconds=-1)])
def test_expired_or_future_plan_stops_before_any_api_call(offset):
    client = Fake()
    manifest = plan(client)
    client.calls.clear()
    with pytest.raises(p.Stop):
        apply(client, manifest, current=NOW + offset)
    assert client.calls == []


def test_full_manifest_preflight_prevents_partial_deletion_on_last_candidate_change():
    client = Fake(2)
    manifest = plan(client)
    client.items[2]["size_in_bytes"] += 1
    with pytest.raises(p.Stop, match="changed"):
        apply(client, manifest)
    assert client.deleted == []


@pytest.mark.parametrize("change", ["reopen", "rerun", "new_pr"])
def test_state_changes_after_preflight_stop_before_delete(change):
    client = Fake()
    manifest = plan(client)
    def emit(event):
        if event["status"] == "preflight_passed":
            if change == "reopen":
                client.pr["state"] = "open"
            elif change == "rerun":
                client.run["run_attempt"] = 2
            else:
                extra = copy.deepcopy(client.pr)
                extra.update(id=1520, number=152, state="open")
                client.other_open.append(extra)
    with pytest.raises(p.Stop):
        apply(client, manifest, emit)
    assert client.deleted == []


def test_api_error_during_planning_is_not_silently_skipped():
    client = Fake()
    client.get_errors[p.ROOT + "/pulls/151"] = p.ApiError("Forbidden", 403)
    with pytest.raises(p.ApiError):
        plan(client)
    assert client.deleted == []


def test_missing_artifact_before_apply_is_not_misreported_as_our_deletion():
    client = Fake()
    manifest = plan(client)
    client.items.clear()
    with pytest.raises(p.ApiError):
        apply(client, manifest)
    assert client.deleted == []


def test_successful_apply_deletes_only_exact_candidates_and_verifies_absence():
    client = Fake(2)
    client.items[2]["name"] = "STAR-Windows-vNext"
    manifest, events = plan(client), []
    apply(client, manifest, events.append)
    assert client.deleted == [1]
    assert set(client.items) == {2}
    assert events[-2] == {"artifact_id": 1, "status": "delete_acknowledged", "run_id": 91,
                          "bytes": 100, "manifest_sha256": manifest["sha256"]}
    assert events[-1] == {"artifact_id": 1, "status": "deleted_and_absence_verified", "bytes": 100}
    assert ("PAGES", p.ROOT + "/actions/runs/91/artifacts?per_page=100") in client.calls


def test_delete_failure_stops_and_reports_partial_results_without_retry():
    client = Fake(3)
    manifest, events = plan(client), []
    client.delete_errors[2] = p.ApiError("Forbidden", 403)
    with pytest.raises(p.ApiError):
        apply(client, manifest, events.append)
    assert client.deleted == [1]
    assert [e.get("artifact_id") for e in events[1:]] == [1, 1, 2]
    assert events[-1]["status"] == "stopped"
    assert ("DELETE", 3) not in client.calls


def test_404_after_delete_is_not_enough_if_artifact_still_listed():
    client = Fake()
    manifest, events = plan(client), []
    def pretend_delete(identifier):
        client.get_errors[f"{p.ROOT}/actions/artifacts/{identifier}"] = p.ApiError("Not found", 404)
    client.delete = pretend_delete
    with pytest.raises(p.Stop, match="still listed"):
        apply(client, manifest, events.append)
    assert any(e["status"] == "delete_acknowledged" for e in events)
    assert not any(e["status"] == "deleted_and_absence_verified" for e in events)


def test_cli_default_is_json_read_only(monkeypatch, capsys):
    client = Fake()
    monkeypatch.setattr(p, "GitHub", lambda: client)
    monkeypatch.setattr(p, "now_utc", lambda: NOW)
    assert p.main([]) == 0
    assert json.loads(capsys.readouterr().out)["statistics"]["candidate_count"] == 1
    assert client.deleted == []


def test_cli_uses_existing_gh_auth_explicit_host_and_no_shell_or_error_secret(monkeypatch):
    calls = []
    def execute(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 1, "", "sensitive provider text (HTTP 403)")
    monkeypatch.setattr(p.subprocess, "run", execute)
    with pytest.raises(p.ApiError) as caught:
        p.GitHub().get(p.ROOT)
    assert "sensitive" not in str(caught.value)
    args, options = calls[0]
    assert args[:6] == ["gh", "api", "--hostname", "github.com", "--method", "GET"]
    assert options["shell"] is False
    assert "auth" not in args
    with pytest.raises(p.Stop):
        p.GitHub()._call("repos/other/repo/actions/artifacts/1", "DELETE")
    assert len(calls) == 1
