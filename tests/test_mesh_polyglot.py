"""star-polyglot (server/mesh/polyglot): the verifier routes non-Luau blocks to the compiler service (fake client here),
merges C# results with the light Unity checks, repairs compile errors through the fix loop, and the runner's filters
drop what a checker cannot know (other blocks, third-party modules, Unity docs gaps). No compilers are needed."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from mesh.polyglot import client as pg_client  # noqa: E402
from mesh.polyglot import note, runner  # noqa: E402,F401
from mesh.verify import core  # noqa: E402
from mesh.verify.apidump import ApiIndex  # noqa: E402
sys.path.remove(str(ROOT / "server"))

API = ApiIndex({"meta": {}, "classes": {}, "enums": {}})


def err(message, line=1, kind="compile"):
    return {"kind": kind, "severity": "error", "name": None, "message": message, "suggestion": None, "line": line}


class FakePolyglot:
    """Flags `undefined_thing` in any language; None (= checker down) for Go."""

    def __init__(self):
        self.calls, self.many = [], 0

    def check(self, language, code, context=""):
        self.calls.append(language)
        if language == "go":
            return None
        probs = [err("undefined name 'undefined_thing'", 2, "name")] if "undefined_thing" in code else []
        return {"checked": True, "problems": probs, "tool": "fake"}

    def check_many(self, items, context=""):
        self.many += 1
        return {i: self.check(i[0], i[1], context) for i in items}


def verifier(fake=None):
    return core.Verifier(API, None, polyglot=fake if fake is not None else FakePolyglot())


def test_python_block_checked_and_flagged():
    rep = verifier().verify("Here:\n```python\nx = 1\nprint(undefined_thing)\n```\n")
    b = rep["blocks"][0]
    assert b["language"] == "python" and b["checked"] and not b["ok"] and b["needs_fix"]
    assert rep["blocks"][0]["problems"][0]["answer_line"] == 4


def test_clean_rust_ok_and_down_checker_means_unchecked():
    rep = verifier().verify("```rust\nfn main() {}\n```\n\n```go\npackage main\n```\n")
    rust, go = rep["blocks"]
    assert rust["checked"] and rust["ok"] and not rust["needs_fix"]
    assert go["language"] == "go" and not go["checked"] and go["ok"]          # never a problem when it cannot answer
    assert rep["ok"] and not rep["needs_fix"]


def test_no_polyglot_keeps_old_behaviour():
    rep = core.Verifier(API, None, polyglot=None).verify("```python\nprint(undefined_thing)\n```\n")
    assert not rep["blocks"][0]["checked"] and rep["ok"]


def test_blocks_compiled_in_parallel_once():
    fake = FakePolyglot()
    verifier(fake).verify("```ts\nlet a = 1\n```\n```js\nlet b = 2\n```\n```cpp\nint main(){}\n```\n")
    assert fake.many == 1 and sorted(fake.calls) == ["cpp", "javascript", "typescript"]


def test_lua_block_routing_love_vs_roblox():
    love = "```lua\nfunction love.draw()\n  love.graphics.print('hi', 1, 1)\nend\n```\n"
    roblox = "```lua\nlocal Players = game:GetService('Players')\nprint(love)\n```\n"
    assert core.extract_blocks(love)[0]["language"] == "lua"
    assert core.extract_blocks(roblox)[0]["language"] == "luau"
    assert core.extract_blocks("```lua\nlocal x = 1\nprint(x)\nend\n```\n")[0]["language"] == "luau"


def test_csharp_merges_roslyn_with_unity_message_check():
    class CsFake(FakePolyglot):
        def check(self, language, code, context=""):
            return {"checked": True, "tool": "roslyn", "problems": [
                {"kind": "deprecated", "severity": "warning", "name": "Rigidbody.velocity", "line": 5,
                 "message": "Rigidbody.velocity is obsolete in Unity 6", "suggestion": "linearVelocity"}]}
    code = ("```csharp\nusing UnityEngine;\npublic class A : MonoBehaviour {\n  Rigidbody rb;\n  void update() {\n"
            "    rb.velocity = Vector3.zero;\n  }\n}\n```\n")
    probs = verifier(CsFake()).verify(code)["blocks"][0]["problems"]
    kinds = sorted(p["kind"] for p in probs)
    assert kinds == ["deprecated", "unity_message"]


def test_csharp_light_checks_when_checker_down():
    class Down(FakePolyglot):
        def check(self, language, code, context=""):
            return None
    probs = verifier(Down()).verify("```csharp\nclass A { void M() { \n```\n")["blocks"][0]["problems"]
    assert any(p["kind"] == "syntax" for p in probs)


def test_fix_loop_repairs_compile_error_with_compile_prompt():
    seen = []

    def model(messages):
        seen.append(messages[0]["content"])
        return "```python\nx = 1\nprint(x)\n```"
    out = verifier().fix("```python\nx = 1\nprint(undefined_thing)\n```\n", model)
    assert out["ok"] and out["before"]["errors"] == 1 and out["after"]["errors"] == 0
    assert "print(x)" in out["answer"] and seen and seen[0] == core.COMPILE_FIX_SYSTEM


def test_fix_rejected_when_not_better():
    out = verifier().fix("```python\nprint(undefined_thing)\n```\n", lambda m: "```python\nundefined_thing()\n```")
    assert "print(undefined_thing)" in out["answer"]
    assert any("rejected" in c for c in out["changes"])


def test_client_from_config(tmp_path):
    assert pg_client.Polyglot.from_config({"polyglot_url": "", "polyglot_token_file": str(tmp_path / "none")}) is None
    (tmp_path / "tok").write_text("abc\n")
    (tmp_path / "url").write_text("http://127.0.0.1:9\n")
    c = pg_client.Polyglot.from_config({"polyglot_url_file": str(tmp_path / "url"),
                                        "polyglot_token_file": str(tmp_path / "tok"), "polyglot_timeout_s": 0.5})
    assert c.url == "http://127.0.0.1:9" and c.token == "abc"
    assert c.check("python", "print(1)") is None          # nothing listens: no problem, no exception
    assert c.check("brainfuck", "+") is None


# ---------------------------------------------------------------------------------------------- runner filters
def test_runner_helpers():
    assert runner.elsewhere("Helper", "x = Helper()", "```py\nx = Helper()\n```\n```py\nclass Helper: pass\n```")
    assert not runner.elsewhere("Helper", "x = Helper()", "```py\nx = Helper()\n```")
    assert "// ..." in runner.blank_ellipsis("a();\n...\nb();\n", "//")
    src, off = runner.wrap("fn main() {\n", "let x = 1;", "\n}\n", "    ")
    assert off == 1 and "    let x = 1;" in src
    assert runner.shift([{"line": 3}, {"line": 1}], 1, 5) == [{"line": 2}, {"line": None}]


def test_ts_filters(monkeypatch):
    diags = [{"code": 2307, "line": 1, "syntactic": False, "message": "Cannot find module 'express'"},
             {"code": 2304, "line": 3, "syntactic": False, "message": "Cannot find name 'Player'."},
             {"code": 7006, "line": 4, "syntactic": False, "message": "Parameter 'x' implicitly has an 'any' type."},
             {"code": 2322, "line": 5, "syntactic": False, "message": "Type 'number' is not assignable to type 'string'."}]
    monkeypatch.setattr(runner.WORKERS["ts"], "ask", lambda req: {"diags": diags, "ms": 1})
    code = "import express from 'express';\nconst a = 1;\nnew Player();\nfunction f(x) {}\nconst s: string = 1;\n"
    out = runner.check_ts(code, "```ts\n" + code + "```\n```ts\nclass Player {}\n```", "typescript")
    assert [p["message"].split(":")[0] for p in out["problems"]] == ["TypeScript TS2322"]


def test_unity_member_truth(monkeypatch):
    monkeypatch.setattr(runner, "_UNITY_INDEX", {
        "now": {"Rigidbody.linearVelocity", "Rigidbody.AddForce", "Component.GetComponent", "Object.name"},
        "old": {"Rigidbody.velocity", "Rigidbody.AddForce"},
        "bases": {"Rigidbody": ["Component", "Object"]}, "classes": {"Rigidbody", "Component", "Object"}})
    assert runner.unity_member("Rigidbody", "AddForce") is None              # docs list it: a stub gap, not shown
    assert runner.unity_member("Rigidbody", "GetComponent") is None           # inherited
    dep = runner.unity_member("Rigidbody", "velocity")
    assert dep["severity"] == "warning" and dep["suggestion"] == "linearVelocity"
    bad = runner.unity_member("Rigidbody", "AddForceNow")
    assert bad["severity"] == "error" and bad["suggestion"] == "AddForce"


def test_check_never_raises(monkeypatch):
    def boom(code, context):
        raise RuntimeError("checker bug")
    monkeypatch.setitem(runner.CHECKS, "python", boom)
    out = runner.check("python", "print(1)")
    assert out["checked"] is False and out["problems"] == []


def test_plugin_java_left_to_the_mc_plugins_checker():
    fake = FakePolyglot()
    v = verifier(fake)
    v.verify("```java\nimport org.bukkit.plugin.java.JavaPlugin;\npublic class P extends JavaPlugin {}\n```\n")
    v.verify("```java\nimport java.util.List;\npublic class Main {}\n```\n")
    assert fake.calls == ["java"]


# ---------------------------------------------------------------------------------------------- the router note
def test_note_detects_other_languages_only():
    from mesh.polyglot import note
    assert note.detect("Write a complete Python program that reads n numbers and prints the sum") == "python"
    assert note.detect("Write a Node.js program that counts words from stdin") == "javascript"
    assert note.detect("In Godot 4, make a CharacterBody2D jump") == "gdscript"
    assert note.detect("Write a C++ program for shortest paths; each node has edges") == "cpp"
    assert note.detect("Make a single HTML page with a to-do list in JavaScript") == "web"
    assert note.detect("make my roblox door open with a lua script") is None
    assert note.detect("write a unity C# script for a jump") is None
    assert note.detect("python script for my minecraft server") is None
    assert note.detect("what is a python?") is None                      # no coding ask


def test_note_apply_once():
    from mesh.polyglot import note
    req = {"messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "Write a Rust function to parse a list"}]}
    assert note.apply(req) == {"X-Mesh-Polyglot": "rust"}
    assert "Rust 2021" in req["messages"][-1]["content"] and req["messages"][0]["content"] == "s"
    assert note.apply(req) == {}                                           # already has a note
    off = {"messages": [{"role": "user", "content": "Write a Rust function"}]}
    assert note.apply(off, {"polyglot_note": False}) == {} and "Note" not in off["messages"][-1]["content"]
