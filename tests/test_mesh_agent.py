"""Agent mode (server/mesh/agent): example extraction, routing, the bounded fix loop, run checks, the HTTP service.
Model, verifier, sandbox and loads are faked."""
import json
import sys
import threading
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from mesh.agent import checks as ck, examples, loop, mcjob, route, service  # noqa: E402

# `server/` holds a `discord` folder: leaving it on sys.path would shadow the discord package for tests collected later
sys.path.remove(str(Path(__file__).resolve().parents[1] / "server"))


def user(text):
    return [{"role": "system", "content": "sys"}, {"role": "user", "content": text}]


# ------------------------------------------------------------------------------------------------- examples / route
def test_io_examples_fenced_and_inline():
    q = "Sum the numbers.\n\nInput:\n```\n2\n3 4\n```\nOutput:\n```\n7\n```\n"
    assert examples.io_examples(q) == [("2\n3 4\n", "7")]
    q2 = "For example, with this input\n```\n1 2\n```\nthe program should print\n```\n3\n```"
    assert examples.io_examples(q2) == [("1 2\n", "3")]
    assert examples.io_examples("Input: 5\nOutput: 120\n") == [("5\n", "120")]
    assert examples.io_examples("Write a program that reads a grid.") == []


def test_call_examples():
    q = "For example `f([1, 2])` should give `\"1-2\"` and `f([])` returns `\"\"`."
    assert examples.call_examples(q) == [("f([1, 2])", '"1-2"'), ("f([])", '""')]
    assert examples.call_examples("fact(5) returns 120.") == [("fact(5)", "120")]


def test_same_output():
    assert examples.same_output("1 2  \n3\n\n", "1 2\n3")
    assert examples.same_output("1  2\n3", "1 2 3")
    assert not examples.same_output("1 2", "1 3")


def test_wants_agent():
    assert route.wants_agent(user("Make me a Paper 1.21.11 plugin with /heal"))
    assert route.wants_agent(user("Fabric mod for 1.21.11: /back teleports you to your death point"))
    assert route.wants_agent(user("fix this\n```lua\nprint(x\n```"))
    for chat in ("What is a RemoteEvent?", "hi", "Explain how DataStores work", "How do I install a mod?",
                 "write me a story about a dragon"):
        assert not route.wants_agent(user(chat)), chat


# ---------------------------------------------------------------------------------------------------- loop
class FakeChecks:
    """Scores answers by the word BUG: each BUG is a run failure; NOCODE = no code at all."""
    verifier = None

    def evaluate(self, answer, question, finish="stop", build=True):
        n = answer.count("BUG")
        probs = [{"stage": "run", "rank": 2, "message": "example output differs"} for _ in range(n)]
        return {"problems": probs, "passed": [] if n else ["ran the 1 example from your question"], "warnings": 0,
                "score": ck.score(probs), "verify": None}


def test_loop_fixes_until_clean():
    replies = iter([("```py\nBUG BUG\n```", "stop"), ("```py\nBUG\n```", "stop"), ("```py\nok\n```", "stop")])
    seen = []

    def call(messages, temperature, max_tokens):
        seen.append(messages)
        return next(replies)

    out = loop.Agent(call, FakeChecks(), max_rounds=4).run(user("write a program"))
    assert out["ok"] and out["rounds"] == 2 and "ok" in out["answer"]
    assert out["verified"].startswith("> verified: ran the 1 example")
    assert loop.AGENT_NOTE in seen[0][-1]["content"]                 # build note on the first write
    assert "example output differs" in seen[1][-1]["content"]          # the real error goes back to the model
    assert seen[1][2] == {"role": "assistant", "content": "```py\nBUG BUG\n```"}


def test_loop_never_keeps_a_worse_answer_and_stops_on_stall():
    replies = iter([("```py\nBUG\n```", "stop")] + [("```py\nBUG BUG\n```", "stop")] * 5)
    out = loop.Agent(lambda m, t, k: next(replies), FakeChecks(), max_rounds=4).run(user("write a program"))
    assert out["answer"] == "```py\nBUG\n```" and out["rounds"] == 2      # two failed revisions -> stop
    assert out["verified"].startswith("> not verified: run problem left")


def test_loop_time_budget():
    clock = iter(range(0, 10_000, 100))
    out = loop.Agent(lambda m, t, k: ("```py\nBUG\n```", "stop"), FakeChecks(), budget_s=150,
                     clock=lambda: next(clock)).run(user("write a program"))
    assert out["rounds"] == 0 and out["trace"][-1]["how"] == "stop"


# ---------------------------------------------------------------------------------------------- checks (run stage)
class FakeSandbox:
    def __init__(self, stdout="7\n", rc=0):
        self.jobs, self.stdout, self.rc = [], stdout, rc

    def run(self, job):
        self.jobs.append(job)
        if "inputs" in job:
            return {"phase": "run", "runs": [{"rc": self.rc, "stdout": self.stdout, "stderr": "", "timed_out": False}
                                             for _ in job["inputs"]]}
        code = next(iter(job["files"].values()))
        if "@@g0" in code:                         # call examples: echo canonical values the way the program would
            return {"phase": "run", "steps": [{"rc": 0}], "stdout": '@@e0 "1-2"\n@@g0 "1-3"\n'}
        return {"phase": "run", "steps": [{"rc": self.rc, "stderr": "Traceback: boom", "timed_out": False}],
                "stdout": ""}


Q_IO = "Write a Python program that adds.\n\nInput:\n```\n3 4\n```\nOutput:\n```\n7\n```"
ANS_IO = "Here:\n\n```python\na, b = map(int, input().split())\nprint(a + b)\n```\n"


def test_run_examples_pass_and_fail():
    c = ck.Checks(None, FakeSandbox("7\n"))
    rep = c.evaluate(ANS_IO, Q_IO)
    assert ck.clean(rep["score"]) and "output matches" in rep["passed"][0]
    assert c.sandbox.jobs[0]["inputs"] == ["3 4\n"]
    rep = ck.Checks(None, FakeSandbox("8\n")).evaluate(ANS_IO, Q_IO)
    assert rep["score"][2] == 1 and "expected output is\n7" in rep["problems"][0]["message"]


def test_call_examples_mismatch():
    q = "Write a JavaScript function `r(xs)`. For example `r([1, 2])` should give `\"1-2\"`."
    ans = "```javascript\nexport function r(xs) { return '1-3'; }\n```"
    sb = FakeSandbox()
    rep = ck.Checks(None, sb).evaluate(ans, q)
    assert rep["score"][2] == 1 and "should give" in rep["problems"][0]["message"]
    assert "export function" not in sb.jobs[0]["files"]["main.js"]


def test_smoke_run_crash_and_skips():
    ans = "```python\nprint(undefined_name)\n```"
    rep = ck.Checks(None, FakeSandbox(rc=1)).evaluate(ans, "Write a python script that prints hi")
    assert rep["score"][2] == 1 and "crashed" in rep["problems"][0]["message"]
    sb = FakeSandbox(rc=1)
    ck.Checks(None, sb).evaluate("```python\nimport pygame\npygame.init()\n```", "make a pygame game")
    assert sb.jobs == []                                # third-party package: not run
    ck.Checks(None, sb).evaluate("```cpp\nint add(int a, int b) { return a + b; }\n```", "write an add function")
    assert sb.jobs == []                                # no entry point: not run


def test_incomplete_and_no_code():
    rep = ck.Checks().evaluate("Sure! Want the full version?", "make a plugin")
    assert rep["score"][0] == 1 and rep["score"][3] == 1
    rep = ck.Checks().evaluate("```lua\nprint(1)\n```", "make a script", finish="length")
    assert rep["score"][0] == 1
    rep = ck.Checks().evaluate("```java\n" + "import a.B;\n" * 12 + "```", "make a plugin")
    assert rep["score"][0] == 1 and "repeats" in rep["problems"][0]["message"]


# ----------------------------------------------------------------------------------------------- plugin load stage
PAPER = """Main class:

```java
package com.x.heal;

import org.bukkit.plugin.java.JavaPlugin;

public class HealPlugin extends JavaPlugin {
    @Override
    public void onEnable() { }
}
```

plugin.yml:

```yaml
name: HealPlugin
main: com.x.heal.HealPlugin
version: 1.0
api-version: '1.21'
commands:
  heal:
    description: Heal
  feed:
    description: Feed
```

config.yml:

```yaml
name: ignored
main: not.the.Main
```
"""


def test_plugin_job_and_load_problems():
    j = mcjob.plugin_job(PAPER, "t1")
    assert j["target"] == "paper" and "com/x/heal/HealPlugin.java" in j["sources"]
    assert j["commands"] == ["heal", "feed"] and "HealPlugin" in j["ids"]
    assert "main: com.x.heal.HealPlugin" in j["resources"]["plugin.yml"] and "config.yml" in j["resources"]
    calls = []

    def loader(kind, job):
        calls.append((kind, job))
        return {"stage": "load", "target": "paper", "loaded": True, "errors": [],
                "commands": {"heal": "ok", "feed": "exception"}}

    rep = ck.Checks(None, None, loader).evaluate(PAPER, "Make me a Paper 1.21.11 plugin")
    assert calls[0][0] == "plugin"
    assert rep["score"][2] == 1 and "/feed" in rep["problems"][0]["message"]

    rep = ck.Checks(None, None, lambda k, j: {"stage": "ok", "target": "paper", "loaded": True, "errors": [],
                                              "commands": {"heal": "ok", "feed": "ok"}}).evaluate(PAPER, "plugin")
    assert rep["passed"] == ["loaded in a real Paper 1.21.11 server (/heal, /feed ran)"]


def test_brigadier_commands():
    java = 'dispatcher.register(CommandManager.literal("back").executes(ctx -> 1));'
    assert mcjob.commands("", java, "fabric") == ["back"]


# --------------------------------------------------------------------------------------------------- service
class Keys:
    def check(self, token):
        return token == "k"


class FakeAgent:
    def __init__(self, progress):
        self.progress = progress

    def run(self, messages, temperature, max_tokens, build=True):
        self.progress("Round 0: all checks pass")
        return {"answer": "x", "content": "x\n\n> verified: ok (1 s)", "verified": "> verified: ok (1 s)", "ok": True,
                "rounds": 0, "score": [0, 0, 0, 0], "passed": ["ok"], "problems": [], "trace": [{"round": 0}],
                "seconds": 1.0}


def _serve():
    from http.server import ThreadingHTTPServer
    cfg = dict(service.DEFAULTS, port=0)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), service.make_handler(cfg, Keys(), lambda r, a, p: FakeAgent(p)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _post(url, body, key="k"):
    req = urllib.request.Request(url + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": "Bearer " + key})
    return urllib.request.urlopen(req, timeout=10)


def test_service_nonstream_and_stream():
    srv, url = _serve()
    try:
        data = json.loads(_post(url, {"model": "litha-agent", "messages": user("make a plugin")}).read())
        assert data["choices"][0]["message"]["content"].endswith("> verified: ok (1 s)")
        assert data["mesh_agent"]["ok"] is True
        raw = _post(url, {"model": "litha-agent", "stream": True, "messages": user("make a plugin")}).read().decode()
        events = [json.loads(ln[6:]) for ln in raw.splitlines() if ln.startswith("data: {")]
        assert any(e.get("choices") and e["choices"][0]["delta"].get("reasoning_content") for e in events)
        assert any(e.get("object") == "mesh.agent" for e in events)
        assert raw.rstrip().endswith("data: [DONE]")
        try:
            _post(url, {"messages": user("x")}, key="bad")
            raise AssertionError("no 401")
        except urllib.error.HTTPError as e:
            assert e.code == 401
    finally:
        srv.shutdown()
