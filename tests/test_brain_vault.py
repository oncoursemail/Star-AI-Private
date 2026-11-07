"""The brain vault generator: redaction, layout, safe regeneration and that STAR's own Obsidian bridge can use the result."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

import pytest

from star import brain_vault
from star.brain_vault import redact
from star.obsidian_bridge import ObsidianVault

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
# Stand-in secrets, assembled from pieces so no real or look-alike value sits in the source as one string.
ADMIN = "svc" + "admin"                                    # a server user name
IP = "10." + "9.8.7"                                       # a private address
KEY = "sk-" + "abcdefghijklmnopqrstuvwxyz"
GH = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
PW = "Zk39xQv81LmN02" + "pRt77wYh"


@pytest.fixture(autouse=True)
def _names(monkeypatch, tmp_path):
    monkeypatch.setenv(brain_vault.PRIVATE_NAMES_ENV, ADMIN)
    monkeypatch.setattr(brain_vault, "PRIVATE_NAMES_FILE", tmp_path / "no-such-names.txt")


def test_redact_replaces_private_values_and_keeps_harmless_ones():
    others = ("192." + "168.1.5", "172." + "20.3.4", "100." + "80.1.2")
    text = (f"ssh {ADMIN}@{IP} then {others[0]}, {others[1]} and {others[2]}; public 8.8.8.8 stays; "
            "bad octet 999.1.1.1 stays; commit 0123456789abcdef0123456789abcdef01234567")
    out, found = redact(text)
    assert "[user]@[private-ip]" in out and out.count("[private-ip]") == 4
    for secret in (IP, *others, ADMIN):
        assert secret not in out
    assert "8.8.8.8" in out and "999.1.1.1" in out and "0123456789abcdef0123456789abcdef01234567" in out
    assert found["private-ip"] == 4


def test_redact_keys_tokens_assignments_emails_and_user_paths():
    out, found = redact(
        f"key {KEY} and {GH} and Bearer abcdefghijklmnopqrstuvwxyz0123456789; password = {PW}; "
        "mail someone@example.com; C:\\Users\\sam\\Documents\\x and /home/sam/y")
    assert "sk-abc" not in out and "ghp_" not in out and "Bearer abc" not in out and "Zk39" not in out
    assert "password = [redacted-key]" in out and "[email]" in out
    assert "C:\\Users\\[user]\\Documents" in out and "/home/[user]/y" in out
    assert found["key-or-token"] == 4 and found["email"] == 1


def test_redact_leaves_placeholders_and_plain_prose_alone_and_is_idempotent():
    plain = "Set the token to <your token here>, api_key = \"your-key-here-xxxxxxxxxxxxxxxx\", version 1.2.3."
    assert redact(plain)[0] == plain
    once, _ = redact(f"ssh {ADMIN}@{IP} password: {PW}")
    again, found = redact(once)
    assert again == once and not found


def test_the_account_running_the_generator_is_redacted_as_a_whole_word(monkeypatch):
    monkeypatch.setattr(brain_vault.getpass, "getuser", lambda: "morgan")
    out, _ = redact("owner morgan wrote C--Users-morgan-Documents; morganite is a gem")
    assert "owner [user] wrote C--Users-[user]-Documents" in out and "morganite" in out


GRAPH = {"directed": False, "nodes": [
    {"id": "a", "label": "slop.py", "file_type": "code", "source_file": "star/slop.py", "source_location": "L1"},
    {"id": "a1", "label": "check_prose()", "file_type": "code", "source_file": "star/slop.py", "source_location": "L12"},
    {"id": "a2", "label": "Report", "file_type": "code", "source_file": "star/slop.py", "source_location": "L3"},
    {"id": "ad", "label": "Anti-slop checker: findings for " + IP, "file_type": "rationale",
     "source_file": "star/slop.py", "source_location": "L1"},
    {"id": "b", "label": "agent.py", "file_type": "code", "source_file": "star/agent.py", "source_location": "L1"},
    {"id": "t", "label": "test_slop.py", "file_type": "code", "source_file": "tests/test_slop.py", "source_location": "L1"},
    {"id": "ext", "label": "json", "file_type": "code", "source_file": "", "source_location": ""},
], "links": [
    {"source": "a", "target": "a1", "relation": "contains"}, {"source": "a", "target": "a2", "relation": "contains"},
    {"source": "ad", "target": "a", "relation": "rationale_for"},
    {"source": "b", "target": "a", "relation": "imports_from"}, {"source": "a", "target": "ext", "relation": "imports"},
    {"source": "t", "target": "a", "relation": "imports_from"}]}


def _workspace(root: Path) -> Path:
    agents = root / "docs" / "agents"
    agents.mkdir(parents=True)
    (agents / "night-school.md").write_text(
        f"# Night school\n\nIt practises at night. Reach server 1 with ssh {ADMIN}@{IP}.\n"
        f"Never paste {KEY} anywhere.\n", encoding="utf-8")
    (root / "docs" / "research").mkdir()
    (root / "docs" / "research" / "voice.md").write_text("---\ntitle: Voice\n---\nWarm voices, original only.\n",
                                                          encoding="utf-8")
    (root / "STATE.md").write_text("# STATE\n\nThe weekly limit resets on Monday.\n", encoding="utf-8")
    return root


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                   check=True, capture_output=True)


def _repo(root: Path) -> Path:
    root.mkdir()
    (root / "docs" / "release" / "v2.0").mkdir(parents=True)
    (root / "docs" / "release" / "v2.0" / "STATUS.md").write_text("# v2.0 status\n\nBlockers: the release channel.\n",
                                                                   encoding="utf-8")
    (root / "graphify-out").mkdir()
    (root / "graphify-out" / "graph.json").write_text(json.dumps(GRAPH), encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    _git(root, "add", "docs")
    env = {**os.environ, "GIT_COMMITTER_DATE": "2026-10-18T10:00:00Z", "GIT_AUTHOR_DATE": "2026-10-18T10:00:00Z"}
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "commit", "-qm", f"[claude] add status for {IP}"], check=True, capture_output=True, env=env)
    return root


@pytest.fixture()
def built(tmp_path):
    workspace, repo = _workspace(tmp_path / "ws"), _repo(tmp_path / "repo")
    out = tmp_path / "vault"
    manifest = brain_vault.build(out, workspace=workspace, repo=repo, now=NOW)
    return out, manifest, workspace, repo


def test_build_writes_notes_daily_code_map_and_home(built):
    out, manifest, _, _ = built
    assert (out / "Home.md").is_file() and (out / brain_vault.MARKER).is_file()
    assert (out / "notes/agents/night-school.md").is_file() and (out / "notes/research/voice.md").is_file()
    assert (out / "notes/root/STATE.md").is_file() and (out / "notes/release/v2.0--STATUS.md").is_file()
    assert manifest["notes"] == 4 and manifest["private"] is True
    slop = (out / "code/star/slop_py.md").read_text(encoding="utf-8")
    assert "# star/slop.py" in slop and "`check_prose()` (line 12)" in slop and "`Report` (line 3)" in slop
    assert "Anti-slop checker: findings for [private-ip]" in slop
    assert "[[code/star/agent_py|star/agent.py]]" in slop and "[[code/tests/test_slop_py|tests/test_slop.py]]" in slop
    assert not (out / "code/tests/test_slop_py.md").exists()      # tests are linked, not mapped
    assert "[[code/star/slop_py|star/slop.py]]" in (out / "code/star/_overview.md").read_text(encoding="utf-8")
    assert manifest["code"]["files"] == 2


def test_nothing_private_survives_anywhere_in_the_vault(built):
    out, manifest, _, _ = built
    everything = "\n".join(f.read_text(encoding="utf-8") for f in out.rglob("*") if f.is_file())
    for secret in (IP, ADMIN, KEY):
        assert secret not in everything
    assert manifest["redactions"]["private-ip"] >= 3 and manifest["redactions"]["key-or-token"] >= 1


def test_daily_notes_use_commit_dates_and_list_commits(built):
    out, _, _, _ = built
    day = (out / "daily/2026-10-18.md").read_text(encoding="utf-8")
    assert "[[notes/release/v2.0--STATUS|v2.0 status]]" in day
    assert "[claude] add status for [private-ip]" in day
    assert (out / "notes/release/v2.0--STATUS.md").read_text(encoding="utf-8").startswith("---\ntitle: \"v2.0 status\"")


def test_rebuild_replaces_owned_folders_and_keeps_the_owners_files(built):
    out, _, workspace, repo = built
    (out / "mine").mkdir()
    (out / "mine" / "idea.md").write_text("my own note", encoding="utf-8")
    (out / ".obsidian").mkdir()
    (out / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    (out / "notes" / "stale.md").write_text("old", encoding="utf-8")
    (workspace / "docs" / "agents" / "night-school.md").unlink()
    brain_vault.build(out, workspace=workspace, repo=repo, now=NOW)
    assert not (out / "notes/agents/night-school.md").exists() and not (out / "notes/stale.md").exists()
    assert (out / "mine/idea.md").read_text(encoding="utf-8") == "my own note"
    assert (out / ".obsidian/app.json").is_file()
    assert not out.with_name(out.name + ".building").exists()


def test_build_refuses_a_foreign_folder_and_a_git_checkout(tmp_path):
    workspace = _workspace(tmp_path / "ws")
    foreign = tmp_path / "docs-folder"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="not a STAR brain vault"):
        brain_vault.build(foreign, workspace=workspace)
    assert (foreign / "keep.txt").exists() and len(list(foreign.iterdir())) == 1
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    with pytest.raises(ValueError, match="Git checkout"):
        brain_vault.build(checkout / "vault", workspace=workspace)
    assert not (checkout / "vault").exists()


def test_status_reports_age_and_counts(built):
    out, _, _, _ = built
    state = brain_vault.status(out)
    assert state["exists"] and state["notes"] == 4 and state["code"]["files"] == 2
    assert brain_vault.status(out / "nope") == {"vault": str(out / "nope"), "exists": False}


def test_extract_needs_graphify_and_a_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(brain_vault, "find_graphify", lambda: None)
    with pytest.raises(RuntimeError, match="not installed"):
        brain_vault.extract_graph(tmp_path)
    with pytest.raises(ValueError, match="--repo"):
        brain_vault.build(tmp_path / "v", extract=True)


def test_the_obsidian_bridge_finds_and_links_the_generated_notes(built):
    out, _, _, _ = built
    vault = ObsidianVault(out)
    hit = vault.search("when does night school practise")
    assert hit["notes"][0]["path"] == "notes/agents/night-school.md"
    code = vault.search("check_prose")
    assert code["notes"][0]["path"] == "code/star/slop_py.md"
    assert "code/star/agent_py.md" in {x["path"] for x in vault.links("code/star/slop_py.md")["outgoing"]}
    assert "code/star/slop_py.md" in {x["path"] for x in vault.links("code/star/_overview.md")["outgoing"]}


def test_the_raw_graphify_export_is_redacted_too(tmp_path, monkeypatch):
    target = tmp_path / "raw"

    def fake_run(command, **kwargs):
        assert command[:4] == ["graphify", "export", "obsidian", "--graph"] and command[-2:] == ["--dir", str(target)]
        (target / "node.md").write_text(f"# check()\n\nCalls ssh {ADMIN}@{IP} to restart.\n", encoding="utf-8")
        (target / "clean.md").write_text("# clean()\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(brain_vault, "find_graphify", lambda: ["graphify"])
    monkeypatch.setattr(brain_vault.subprocess, "run", fake_run)
    notes, found = brain_vault.export_raw_graph(tmp_path / "graph.json", target)
    assert notes == 2 and found["private-ip"] == 1
    assert (target / "node.md").read_text(encoding="utf-8") == "# check()\n\nCalls ssh [user]@[private-ip] to restart.\n"


def test_private_names_come_from_the_environment_the_file_and_the_account(monkeypatch, tmp_path):
    listed = tmp_path / "names.txt"
    listed.write_text("# comment\nfileuser\n\nshort\n", encoding="utf-8")
    monkeypatch.setattr(brain_vault, "PRIVATE_NAMES_FILE", listed)
    monkeypatch.setenv(brain_vault.PRIVATE_NAMES_ENV, "envuser, other")
    monkeypatch.setattr(brain_vault.getpass, "getuser", lambda: "me")      # under 4 characters: not used
    assert brain_vault.private_names() == ("envuser", "other", "fileuser", "short")
    monkeypatch.setattr(brain_vault.getpass, "getuser", lambda: "account")
    assert brain_vault.private_names()[-1] == "account"


def test_a_build_without_a_graph_keeps_the_last_code_map(built):
    out, _, workspace, repo = built
    (repo / "graphify-out" / "graph.json").unlink()
    manifest = brain_vault.build(out, workspace=workspace, repo=repo, now=NOW)
    assert (out / "code/star/slop_py.md").is_file() and manifest["code"]["files"] == 2
    assert "Code map: 2 source files" in (out / "Home.md").read_text(encoding="utf-8")
