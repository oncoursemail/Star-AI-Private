import json
from types import SimpleNamespace

from litha import claude, pr_fixer


def test_cost_and_caps(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST")                   # tests never pay: ready() is off under pytest
    monkeypatch.setattr(claude, "KEY", tmp_path / "anthropic.key")
    monkeypatch.setattr(claude, "HOME", tmp_path)
    monkeypatch.setattr(claude, "LEDGER", tmp_path / "spend.jsonl")
    assert not claude.ready()                                   # no key: never asks
    claude.KEY.write_text("test", encoding="utf-8")
    assert claude.ready()
    usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=100_000, cache_creation_input_tokens=0,
                            cache_read_input_tokens=0)
    assert claude.cost(usage, "claude-opus-5-5") == 4.0 + 2.0
    day = __import__("datetime").date.today().isoformat()
    claude.LEDGER.write_text(json.dumps({"day": day, "usd": 30.0}) + "\n", encoding="utf-8")
    assert claude.spent() == (30.0, 30.0) and not claude.ready()   # the day's cap is reached
    (tmp_path / "cap.json").write_text('{"day": 50}', encoding="utf-8")
    assert claude.ready()
    claude.LEDGER.write_text(json.dumps({"day": "2000-01-01", "usd": 300.0}) + "\n", encoding="utf-8")
    assert not claude.ready()                                   # the total cap is reached


def test_claude_only_after_her_model_fails(monkeypatch):
    text = "a\n<<<<<<< ours\nx = 1\n||||||| base\nx = 0\n=======\nx = 2\n>>>>>>> theirs\nb\n"
    calls = []
    def local(prompt):
        calls.append("local")
        return "not json"
    def paid(prompt, effort="medium"):
        calls.append("claude")
        return json.dumps({"resolved": "x = 3\n"})
    monkeypatch.setattr(pr_fixer, "ask", local)
    monkeypatch.setattr(pr_fixer, "ask_claude", paid)
    monkeypatch.setattr(pr_fixer.claude, "ready", lambda: True)
    out, why = pr_fixer.resolve_text("notes.txt", text, "t", asker=local)
    assert calls == ["local"] * 3 + ["claude"] and out == "a\nx = 3\nb\n", why
    calls.clear()
    out, why = pr_fixer.resolve_text("notes.txt", text, "t", asker=lambda p: calls.append("test") or "bad")
    assert "claude" not in calls and out is None              # a test's own asker never reaches the paid model


def test_code_goes_to_claude_first(monkeypatch):
    text = "a\n<<<<<<< ours\nx = 1\n||||||| base\nx = 0\n=======\nx = 2\n>>>>>>> theirs\nb\n"
    calls = []
    def local(prompt):
        calls.append("local")
        return "not json"
    monkeypatch.setattr(pr_fixer, "ask", local)
    monkeypatch.setattr(pr_fixer, "ask_claude", lambda p, effort="medium": calls.append("claude") or "{}")
    monkeypatch.setattr(pr_fixer.claude, "ready", lambda: True)
    pr_fixer.resolve_text("src/a.py", text, "t", asker=local)
    assert calls == ["claude", "claude", "local"]


def test_claude_review_vetoes_a_merge_once_per_head(tmp_path, monkeypatch):
    from litha import pr_merger
    monkeypatch.setattr(claude, "HOME", tmp_path)
    monkeypatch.setattr(claude, "ready", lambda: True)
    monkeypatch.setattr(pr_merger, "gh", lambda *a, **k: "diff")
    asked = []
    answer = {"verdict": "hold", "risks": [{"file": "a.py", "line": 3, "severity": "high", "why": "crash"}]}
    monkeypatch.setattr(claude, "ask", lambda *a, **k: asked.append(1) or json.dumps(answer))
    pr = {"number": 7, "headRefOid": "abc"}
    row = {"action": "merge"}
    assert pr_merger.vetoed(row, pr) and row["action"] == "hold" and "a.py:3 crash" in row["reasons"][0]
    assert pr_merger.vetoed({}, pr) and len(asked) == 1         # same head: no second paid call
    answer["verdict"] = "merge"
    assert not pr_merger.vetoed({}, {"number": 8, "headRefOid": "def"})


def test_second_key_is_found(tmp_path, monkeypatch):
    monkeypatch.setattr(claude, "KEY", tmp_path / "anthropic.key")
    (tmp_path / "anthropic2.key").write_text("b", encoding="utf-8")
    assert claude.keys() == [tmp_path / "anthropic2.key"]
    claude.KEY.write_text("a", encoding="utf-8")
    assert claude.keys() == [tmp_path / "anthropic.key", tmp_path / "anthropic2.key"]
