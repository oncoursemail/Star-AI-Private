from __future__ import annotations

import json

import star.pr_promote as P

OK = [{"name": "Offline Python checks", "status": "completed", "conclusion": "SUCCESS"},
      {"name": "windows-build", "status": "completed", "conclusion": "SUCCESS"}]


def test_main_needs_green_checks_receipts_and_notes(tmp_path):
    sha = "a" * 40
    why = P.missing(sha, OK, [], tmp_path)
    assert why == [f"no acceptance.json receipt for {sha[:8]}", f"no install.json receipt for {sha[:8]}",
                   f"no release notes for {sha[:8]}"]
    d = tmp_path / sha
    d.mkdir()
    (d / "acceptance.json").write_text(json.dumps({"ok": True, "sha": sha}), encoding="utf-8")
    (d / "install.json").write_text(json.dumps({"ok": True, "sha": "b" * 40}), encoding="utf-8")   # another head
    (d / "notes.md").write_text("notes", encoding="utf-8")
    assert P.missing(sha, OK, [], tmp_path) == [f"install.json for {sha[:8]} did not pass"]
    (d / "install.json").write_text(json.dumps({"ok": True, "sha": sha}), encoding="utf-8")
    assert P.missing(sha, OK, [], tmp_path) == []
    assert "no successful Windows build" in P.missing(sha, OK[:1], [], tmp_path)[0]
    held = [{"pr": 7, "action": "hold", "merged": False, "review": {"risks": [{"severity": "high"}]}}]
    assert P.missing(sha, OK, held, tmp_path) == ["open high-risk findings on PRs #7"]
