"""PX progress data: roadmap rules, forge numbers without fake percentages, public mode keeps private things out."""
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from launcher.px import build as px
from launcher.px.service import PxService

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
REPO = Path(__file__).resolve().parents[1]


def fake_get(table):
    def get(path):
        base = path.split("?")[0]
        data = table.get(base)
        if data is None:
            raise px.PxError(f"forge request failed for {base}: 404")
        if "page=" in path and "page=1" not in path:
            return []
        return data
    return get


def issue(n, state="open", created="2026-10-20T10:00:00Z", closed=None, pr=False):
    d = {"number": n, "state": state, "title": f"SECRET TITLE {n}", "created_at": created, "closed_at": closed,
         "pull_request": {"merged": True} if pr else None}  # the real forge sends the key with null for issues
    return d


def forge_for(repo_tables):
    table = {}
    for repo, t in repo_tables.items():
        base = f"/repos/metallic/{repo}"
        table[f"{base}/milestones"] = t.get("milestones", [])
        table[f"{base}/releases"] = t.get("releases", [])
        table[f"{base}/issues"] = t.get("issues", [])
    return px.Forge("http://forge.invalid", get=fake_get(table))


ROADMAP = {"projects": [
    {"id": "rc", "name": "RC", "role": "r", "repo": "A", "private": False, "items": [
        {"id": "a", "title": "Backend", "state": "tested", "evidence": "2026-10-21", "note": "n"},
        {"id": "b", "title": "Room", "state": "planned", "evidence": "2026-10-21", "depends": ["a"], "blockers": ["login"]},
        {"id": "c", "title": "Voice", "state": "planned", "evidence": "2026-10-22", "depends": ["b"]}]},
    {"id": "star", "name": "STAR", "role": "r", "repo": "B", "private": True, "items": [
        {"id": "d", "title": "One", "state": "released", "evidence": "2026-10-14"}]}]}

TABLES = {
    "A": {"issues": [issue(1, "closed", closed="2026-10-21T00:00:00Z"), issue(2), issue(3), issue(4, pr=True)],
          "milestones": [{"title": "M1", "open_issues": 2, "closed_issues": 1, "due_on": None, "state": "open"}]},
    "B": {"issues": [issue(1), issue(2, "closed", closed="2026-10-25T00:00:00Z")],
          "releases": [{"tag_name": "v1.0.0", "name": "STAR v1", "published_at": "2026-10-14T09:00:00Z",
                        "body": "internal note about the brain", "draft": False},
                       {"tag_name": "v1.1.0", "name": "draft", "draft": True}]},
}


def test_real_roadmap_loads_and_uses_only_the_five_states():
    data = px.load_roadmap()
    assert [p["id"] for p in data["projects"]] == ["rc", "mc", "rb", "litha", "launcher", "star"]
    assert all(i["state"] in px.STATES for p in data["projects"] for i in p["items"])
    assert not px.scrub({"mode": "public", **data})  # the curated file itself is public-safe


def test_roadmap_rejects_unknown_states_duplicates_and_dangling_dependencies(tmp_path):
    def load(obj):
        f = tmp_path / "r.json"
        f.write_text(json.dumps(obj))
        return px.load_roadmap(f)
    item = {"id": "x", "title": "t", "state": "done", "evidence": "2026-01-01"}
    with pytest.raises(px.PxError, match="unknown state"):
        load({"projects": [{"items": [item]}]})
    ok = dict(item, state="planned")
    with pytest.raises(px.PxError, match="duplicate"):
        load({"projects": [{"items": [ok, ok]}]})
    with pytest.raises(px.PxError, match="unknown"):
        load({"projects": [{"items": [dict(ok, depends=["nope"])]}]})


def test_state_counts_come_from_items_and_no_percentage_is_invented():
    data = px.build(ROADMAP, None, now=NOW)
    rc = data["projects"][0]
    assert rc["states"] == {"planned": 2, "implemented": 0, "tested": 1, "accepted": 0, "released": 0}
    assert rc["total"] == 3 and rc["tracker"] is None
    assert "percent" not in json.dumps(data).lower()
    assert data["forge"]["state"] == "off"
    room = [i for i in rc["items"] if i["id"] == "b"][0]
    assert room["blockers"] == ["login"] and room["waiting_on"] == []  # its dependency is tested, not waiting
    voice = [i for i in rc["items"] if i["id"] == "c"][0]
    assert voice["waiting_on"] == ["b"]


def test_forge_numbers_ignore_pull_requests_and_use_real_timestamps():
    data = px.build(ROADMAP, forge_for(TABLES), now=NOW)
    t = data["projects"][0]["tracker"]
    assert (t["open"], t["closed"]) == (2, 1)  # the pull request is not an issue, even with "pull_request": null on issues
    assert t["milestones"] == [{"title": "M1", "open": 2, "closed": 1, "due": None, "state": "open"}]
    weeks = {w["start"]: w for w in t["weeks"]}
    assert len(t["weeks"]) == 12 and "2026-10-19" in weeks
    assert weeks["2026-10-19"]["closed"] == 1 and weeks["2026-10-19"]["opened"] == 3
    assert data["forge"]["state"] == "online"


def test_internal_build_keeps_release_notes_and_public_build_drops_them():
    internal = px.build(ROADMAP, forge_for(TABLES), now=NOW)
    star = internal["projects"][1]
    assert [r["tag"] for r in star["releases"]] == ["v1.0.0"]  # drafts are skipped
    assert star["releases"][0]["notes"] == "internal note about the brain" and star["tracker"]["open"] == 1
    public = px.build(ROADMAP, forge_for(TABLES), public=True, now=NOW)
    star = public["projects"][1]
    assert "notes" not in star["releases"][0] and star["tracker"] is None  # private repo: no numbers
    assert public["projects"][0]["tracker"] is not None  # public repo numbers stay
    text = json.dumps(public)
    assert "SECRET TITLE" not in text and "internal note" not in text
    assert all("text" not in c for c in public["changelog"] if c["kind"] == "release")


def test_changelog_lists_releases_and_confirmed_work_newest_first():
    data = px.build(ROADMAP, forge_for(TABLES), now=NOW)
    dates = [c["date"] for c in data["changelog"]]
    assert dates == sorted(dates, reverse=True)
    kinds = {(c["project"], c["kind"]) for c in data["changelog"]}
    assert ("rc", "tested") in kinds and ("star", "release") in kinds and ("star", "released") in kinds
    assert not any(c["title"] == "Room" for c in data["changelog"])  # planned work is not news


def test_unreachable_forge_degrades_to_the_roadmap():
    broken = px.Forge("http://forge.invalid", get=lambda p: (_ for _ in ()).throw(px.PxError("down")))
    data = px.build(ROADMAP, broken, now=NOW)
    assert data["forge"]["state"] == "offline" and data["projects"][0]["tracker"] is None
    assert data["projects"][0]["states"]["tested"] == 1


def test_public_output_is_scanned_and_refused_when_it_leaks(tmp_path):
    leaky = px.build(ROADMAP, None, public=True, now=NOW)
    leaky["projects"][0]["items"][0]["note"] = "runs on 10.17.0.140 as alexbuz"  # star:allow
    assert set(px.scrub(leaky)) == {"private address", "server user name"}
    with pytest.raises(px.PxError, match="refused"):
        px.write(leaky, tmp_path / "px.json")
    assert not (tmp_path / "px.json").exists()
    for text, label in [("ghp_" + "a" * 30, "token"), ("C:\\Users\\bob\\x", "local path"),
                        ("-----BEGIN OPENSSH PRIVATE KEY-----", "private key"), ("192.168.1.5", "private address")]:  # star:allow
        d = px.build(ROADMAP, None, public=True, now=NOW)
        d["projects"][0]["items"][0]["note"] = text
        assert label in px.scrub(d)
    ok = px.write(px.build(ROADMAP, None, public=True, now=NOW), tmp_path / "px.json")
    assert json.loads(ok.read_text())["mode"] == "public"


def test_forge_pagination_walks_every_page():
    pages = {1: [{"n": i} for i in range(50)], 2: [{"n": 99}], 3: []}
    seen = []

    def get(path):
        page = int(path.split("page=")[1])
        seen.append(page)
        return pages[page]
    assert len(px.Forge("http://x", get=get).pages("/things?state=all")) == 51
    assert seen == [1, 2]


def test_cli_writes_px_json_from_the_roadmap_alone(tmp_path):
    out = tmp_path / "px.json"
    assert px.main(["--out", str(out), "--public"]) == 0
    data = json.loads(out.read_text())
    assert data["mode"] == "public" and data["forge"]["state"] == "off" and len(data["projects"]) == 6
    assert px.main(["--out", str(tmp_path / "x.json"), "--roadmap", str(tmp_path / "missing.json")]) == 2


def test_service_caches_and_survives_a_dead_forge(tmp_path):
    svc = PxService(tmp_path, {"px": {}})
    first = json.loads(svc.data())
    assert first["forge"]["state"] == "off" and len(first["projects"]) == 6
    assert (tmp_path / "px" / "px.json").is_file()
    assert svc.data() == (tmp_path / "px" / "px.json").read_text()  # fresh cache is served as is
    cached = json.loads((tmp_path / "px" / "px.json").read_text())
    cached["forge"] = {"state": "online", "detail": ""}
    (tmp_path / "px" / "px.json").write_text(json.dumps(cached))
    dead = PxService(tmp_path, {"px": {"forge": "http://127.0.0.1:9"}})
    stale = json.loads(dead.data(refresh=True))
    assert stale["forge"]["state"] == "stale"  # shows the saved copy and says so


def test_page_script_is_valid_javascript_and_never_uses_innerhtml():
    js = (REPO / "launcher/web/px/px.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js and "outerHTML" not in js and "insertAdjacentHTML" not in js and "eval(" not in js
    css = (REPO / "launcher/web/px/px.css").read_text(encoding="utf-8")
    assert "--s-planned" in css
    node = shutil.which("node") or next(iter(Path.home().glob(".cache/codex-runtimes/**/node.exe")), None)
    if node:
        res = subprocess.run([str(node), "--check", str(REPO / "launcher/web/px/px.js")], capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
