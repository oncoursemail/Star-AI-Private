"""The real checks of one answer, as one report the loop can rank and the model can read.

    checks = Checks(verify=..., run=..., load=...)
    rep = checks.evaluate(answer, question, finish="stop", build=True)
    rep = {"problems": [{"stage", "rank", "message"}], "passed": ["compiled ...", ...], "score": (...), "verify": {...}}

Stages and ranks (lower score = better; a rank-3+ problem stops the later stages, so ranks compare fairly):
    4  no usable answer: no code block for a build task, cut off by the length limit, the same line repeated over
       and over, a plugin answer without any Java class
    3  static/compile: the verifier (Roblox API dump + luau-analyze, javac against the Paper/Fabric/NeoForge jars,
       the game's own Minecraft command/pack data, star-polyglot compilers), Roblox rules (measured precision), no code
    2  run/load: the program run in the star-polyglot sandbox on the examples the user wrote (or a smoke run of a
       program that reads no input), the plugin/mod loaded in a real server with its commands typed in the console,
       the data pack loaded in a real vanilla server with every function run
    1  complete: cut off, "rest stays the same", unclosed fence
Warnings (deprecated APIs) only break ties.
"""
from __future__ import annotations

import ast
import json
import re
import sys
import urllib.request
from pathlib import Path

from ..verify import core
from . import examples, mcjob

try:
    from ..rules import rules as roblox_rules
except ImportError:                    # pragma: no cover
    roblox_rules = None

PLATFORM = {"paper": "Paper 1.21.11", "spigot": "Paper 1.21.11 (Spigot API)", "velocity": "Velocity 3.5.1",
            "fabric": "Fabric 1.21.11", "fabric-mojmap": "Fabric 1.21.11", "neoforge": "NeoForge 21.11 (1.21.11)"}
RUN_FILE = {"python": "main.py", "javascript": "main.js", "typescript": "main.ts", "c": "main.c", "cpp": "main.cpp",
            "rust": "main.rs", "go": "main.go", "csharp": "main.cs", "lua": "main.lua", "java": "Main.java"}
READS_STDIN = {
    "python": r"\binput\s*\(|sys\.stdin|fileinput",
    "javascript": r"process\.stdin|readline|readFileSync\(\s*(?:0|['\"]/dev/stdin['\"]|process\.stdin)",
    "typescript": r"process\.stdin|readline|readFileSync\(\s*(?:0|['\"]/dev/stdin['\"]|process\.stdin)",
    "c": r"\bscanf\b|\bgetchar\b|\bfgets\b|\bgetline\b|\bread\s*\(\s*0|\bstdin\b",
    "cpp": r"\bcin\b|\bscanf\b|\bgetline\b|\bgetchar\b|\bstdin\b",
    "rust": r"\bstdin\s*\(",
    "go": r"os\.Stdin|fmt\.Scan",
    "java": r"System\.in\b",
    "csharp": r"Console\.(?:Read|In\b)",
    "lua": r"io\.read|io\.lines\s*\(\s*\)|io\.stdin",
}
ENTRY = {"c": r"\bint\s+main\s*\(", "cpp": r"\bint\s+main\s*\(", "rust": r"\bfn\s+main\s*\(",
         "go": r"package\s+main\b[\s\S]*\bfunc\s+main\s*\(", "java": r"static\s+void\s+main\s*\(",
         "csharp": r"static\s+(?:async\s+)?(?:void|int|Task)\s+Main\s*\("}
NODE_BUILTIN = {"fs", "path", "os", "util", "events", "readline", "crypto", "child_process", "assert", "url",
                "querystring", "string_decoder", "stream", "zlib", "buffer", "process", "timers", "perf_hooks"}
INCOMPLETE = re.compile(r"want the full version\??|(?://|--|#)\s*\.\.\.\s*(?:rest|more|other|same|remaining)|"
                        r"(?://|--|#)\s*(?:rest of (?:the )?(?:code|file|class)|same as (?:before|above))|"
                        r"\(same as (?:before|above)\)|\.\.\. ?\(unchanged\)", re.I)
STDLIB = set(getattr(sys, "stdlib_module_names", ())) or {
    "sys", "os", "re", "math", "json", "collections", "itertools", "functools", "heapq", "bisect", "datetime", "time",
    "random", "string", "typing", "dataclasses", "fractions", "decimal", "statistics", "operator", "copy", "enum"}


def post_json(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


class VerifierClient:
    """The live verifier (:8101): static + compile checks; ?fix=1 = its measured block repair (one round)."""

    def __init__(self, url: str, auth: str, timeout_s: float = 30.0):
        self.url, self.auth, self.timeout_s = url.rstrip("/"), auth, timeout_s

    def verify(self, answer: str, question: str) -> dict | None:
        try:
            return post_json(self.url + "/mesh/verify", {"answer": answer, "question": question},
                             {"Authorization": self.auth}, self.timeout_s)
        except (OSError, ValueError):
            return None

    def fix(self, answer: str, question: str, timeout_s: float = 200.0) -> dict | None:
        try:
            return post_json(self.url + "/mesh/verify?fix=1", {"answer": answer, "question": question, "rounds": 1},
                             {"Authorization": self.auth}, timeout_s)
        except (OSError, ValueError):
            return None


class SandboxClient:
    """star-polyglot POST /run (no-network container, unprivileged user, CPU/RAM/process caps)."""

    def __init__(self, url: str, token: str, timeout_s: float = 90.0):
        self.url, self.token, self.timeout_s = url.rstrip("/"), token, timeout_s

    @classmethod
    def from_files(cls, url: str = "", url_file: str = "", token_file: str = "") -> "SandboxClient | None":
        if not url and url_file and Path(url_file).is_file():
            url = Path(url_file).read_text(encoding="utf-8").strip()
        if not url or not token_file or not Path(token_file).is_file():
            return None
        return cls(url, Path(token_file).read_text(encoding="utf-8").strip())

    def run(self, job: dict) -> dict | None:
        try:
            return post_json(self.url + "/run", job, {"Authorization": "Bearer " + self.token}, self.timeout_s)
        except (OSError, ValueError):
            return None


class LoadClient:
    """Real-server loads (server/mesh/agent/loadfront.py in the mc-plugins container): POST /load {kind, job}."""

    def __init__(self, url: str, token: str, timeout_s: float = 400.0):
        self.url, self.token, self.timeout_s = url.rstrip("/"), token, timeout_s

    def __call__(self, kind: str, job: dict) -> dict | None:
        try:
            return post_json(self.url + "/load", {"kind": kind, "job": job},
                             {"Authorization": "Bearer " + self.token}, self.timeout_s)
        except (OSError, ValueError):
            return None


def _p(stage: str, rank: int, message: str) -> dict:
    return {"stage": stage, "rank": rank, "message": message[:900]}


def score(problems: list[dict], warnings: int = 0) -> tuple:
    return tuple(sum(p["rank"] == r for p in problems) for r in (4, 3, 2, 1)) + (warnings,)


def clean(sc) -> bool:
    """No problem left (warnings do not count)."""
    return not any(sc[:-1])


def repeated_line(text: str, times: int = 8) -> str | None:
    run, prev = 0, None
    for ln in text.splitlines():
        s = ln.strip()
        if s and s == prev:
            run += 1
            if run >= times:
                return s
        else:
            run, prev = 1, s
    return None


class Checks:
    def __init__(self, verify: VerifierClient | None = None, run: SandboxClient | None = None, load=None,
                 load_datapacks: bool = False):
        self.verifier, self.sandbox, self.loader, self.load_datapacks = verify, run, load, load_datapacks
        self.n = 0

    # ------------------------------------------------------------------------------------------------ evaluate
    def evaluate(self, answer: str, question: str, finish: str | None = "stop", build: bool = True) -> dict:
        self.n += 1
        problems: list[dict] = []
        passed: list[str] = []
        warnings = 0
        blocks = core.extract_blocks(answer)
        if build and not blocks:
            problems.append(_p("complete", 4, "the answer has no code block: the task asks for working code"))
        if finish == "length":
            problems.append(_p("complete", 4, "the answer was cut off by the length limit: write it shorter (only the "
                                              "files that are needed, no repeated lines) so it is complete"))
        rep_line = repeated_line(answer)
        if rep_line:
            problems.append(_p("complete", 4, f"the answer repeats the same line over and over ('{rep_line[:80]}')"))
        m = INCOMPLETE.search(answer)
        if m:
            problems.append(_p("complete", 1, f"the answer leaves code out ('{m.group(0).strip()}'): give every file "
                                              "in full"))
        rep = self.verifier.verify(answer, question) if self.verifier and blocks else None
        if rep:
            for b in rep.get("blocks", []):
                for pr in b.get("problems", []):
                    if pr.get("severity") == "error":
                        where = f"block {b['index'] + 1} ({b.get('language') or 'code'})"
                        line = f" line {pr['line']}" if pr.get("line") else ""
                        sug = f" -> use: {pr['suggestion']}" if pr.get("suggestion") else ""
                        problems.append(_p("compile" if pr.get("kind") in ("compile", "syntax", "type", "javac")
                                           else "static", 3, f"{where}{line}: {pr.get('message')}{sug}"))
                    elif pr.get("severity") == "warning":
                        warnings += 1
            for pr in rep.get("problems", []):
                if pr.get("severity") == "error":
                    problems.append(_p("static", 3, pr.get("message", "")))
            checked = [b for b in rep.get("blocks", []) if b.get("checked")]
            if checked and not any(p["rank"] >= 3 for p in problems):
                passed.append(_checked_phrase(rep, checked))
        roblox = any(b["language"] == "luau" for b in blocks)
        if roblox and roblox_rules is not None:
            for h in roblox_rules.errors(roblox_rules.check(answer, question)):
                problems.append(_p("static", 3, f"Roblox rule {h.get('rule')}: {h.get('message')}"))
        if not any(p["rank"] >= 3 for p in problems):
            self._run(answer, question, blocks, problems, passed)
            self._load(answer, question, problems, passed)
        return {"problems": problems, "passed": passed, "warnings": warnings,
                "score": score(problems, warnings), "verify": rep}

    # ---------------------------------------------------------------------------------------------------- run
    def _run(self, answer: str, question: str, blocks: list[dict], problems: list[dict], passed: list[str]):
        if not self.sandbox:
            return
        cands = [b for b in blocks if b["language"] in RUN_FILE
                 and not (b["language"] == "csharp" and "UnityEngine" in b["code"])
                 and not (b["language"] == "java" and core.JAVA_PLUGIN.search(b["code"]))]
        if not cands:
            return
        b = max(cands, key=lambda x: len(x["code"]))
        lang, code = b["language"], b["code"]
        ios = examples.io_examples(question)
        calls = examples.call_examples(question) if lang in ("python", "javascript", "typescript") else []
        reads = bool(re.search(READS_STDIN.get(lang, r"$^"), code))
        if ios and reads:
            res = self.sandbox.run(_job(lang, code, inputs=[i for i, _ in ios]))
            if res is None:
                return
            if res.get("phase") == "compile":
                problems.append(_p("compile", 3, f"the {lang} compiler in the sandbox: {_tail(res)}"))
                return
            bad = 0
            for (inp, want), run in zip(ios, res.get("runs") or []):
                if run.get("timed_out"):
                    bad += 1
                    problems.append(_p("run", 2, f"on the example input from the question\n{inp.rstrip()}\nthe "
                                                 "program did not finish within 10 s (endless loop or waiting for "
                                                 "more input)"))
                elif run.get("rc") != 0 or not examples.same_output(run.get("stdout", ""), want):
                    bad += 1
                    err = (run.get("stderr") or "").strip()[-700:]
                    problems.append(_p("run", 2, f"on the example input from the question\n{inp.rstrip()}\nthe "
                                                 f"expected output is\n{want.strip()}\nbut the program printed\n"
                                                 f"{(run.get('stdout') or '').strip()[:600] or '(nothing)'}"
                                                 + (f"\nexit code {run.get('rc')}, stderr:\n{err}" if err else "")))
            if not bad:
                passed.append(f"ran the {len(ios)} example{'s' if len(ios) > 1 else ''} from your question in a "
                              f"sandbox ({lang}): output matches")
            return
        if calls:
            prog = _call_program(lang, code, calls)
            if prog is None:
                return
            res = self.sandbox.run(_job(lang, prog, stdin=""))
            if res is None:
                return
            if res.get("phase") == "compile":
                problems.append(_p("compile", 3, f"the {lang} compiler in the sandbox: {_tail(res)}"))
                return
            out = res.get("stdout") or ""
            got = dict(re.findall(r"^@@g(\d+) (.*)$", out, re.M))
            exp = dict(re.findall(r"^@@e(\d+) (.*)$", out, re.M))
            ran = bad = 0
            for i, (call, want) in enumerate(calls):
                if str(i) not in exp:
                    continue               # the example's expected value is not code we can evaluate: skipped
                ran += 1
                g = got.get(str(i))
                if g is None or g.startswith("!") or g != exp[str(i)]:
                    bad += 1
                    shown = "nothing (crashed before it)" if g is None else (g[1:] if g.startswith("!") else g)
                    problems.append(_p("run", 2, f"the question's example `{call}` should give `{want}`, but the "
                                                 f"code {'raised ' if g and g.startswith('!') else 'gave '}{shown[:400]}"
                                                 + (f"\nstderr: {_tail(res)}" if g is None else "")))
            if ran and not bad:
                passed.append(f"ran the {ran} example call{'s' if ran > 1 else ''} from your question in a sandbox: "
                              "results match")
            return
        if reads or (lang in ENTRY and not re.search(ENTRY[lang], code)) or not _deps_ok(lang, code):
            return                          # needs input we do not have / a library / no entry point: not run
        res = self.sandbox.run(_job(lang, code, stdin=""))
        if res is None:
            return
        if res.get("phase") == "compile":
            problems.append(_p("compile", 3, f"the {lang} compiler in the sandbox: {_tail(res)}"))
            return
        step = (res.get("steps") or [{}])[-1]
        if step.get("timed_out"):
            return                          # a server / game loop: no verdict
        if step.get("rc") not in (0, None):
            problems.append(_p("run", 2, f"running the program crashed (exit code {step.get('rc')}):\n{_tail(res)}"))
        else:
            passed.append(f"ran without errors in a sandbox ({lang})")

    # --------------------------------------------------------------------------------------------------- load
    def _load(self, answer: str, question: str, problems: list[dict], passed: list[str]):
        if not self.loader:
            return
        job = mcjob.plugin_job(answer, f"agent{self.n}-{abs(hash(answer)) % 10**8}")
        if job is not None and not job["sources"] and (job["resources"] or re.search(
                r"\b(plugin|mod)\b", question, re.I)):
            problems.append(_p("complete", 4, f"no complete Java class (package + class declaration) for the "
                                              f"{PLATFORM.get(job['target'], job['target'])} plugin/mod: give every Java "
                                              "file in full, each in its own code block"))
            return
        if job is not None and job["sources"]:
            res = self.loader("plugin", job)
            if res is None:
                return
            plat = PLATFORM.get(res.get("target") or job["target"], job["target"])
            stage = res.get("stage")
            if stage == "compile":
                for d in (res.get("compile") or [])[:6]:
                    problems.append(_p("compile", 3, f"javac ({plat} API): {d.get('file')}:{d.get('line')}: "
                                                     f"{d.get('message')}"))
            elif stage == "build":
                problems.append(_p("compile", 3, f"the Gradle build ({plat}) failed:\n" +
                                   "\n".join((res.get("errors") or [])[-12:])))
            elif stage in ("load", "ok"):
                for e in (res.get("errors") or [])[:5]:
                    problems.append(_p("load", 2, f"the real {plat} server log: {e}"))
                if not res.get("loaded") and not res.get("errors"):
                    tail = "\n".join((res.get("log_excerpt") or res.get("log_tail") or [])[-12:])
                    problems.append(_p("load", 2, f"the plugin/mod did not load in a real {plat} server"
                                                  + (f"; server log:\n{tail}" if tail else "")))
                bad_cmds = {c: v for c, v in (res.get("commands") or {}).items() if v != "ok"}
                for c, v in bad_cmds.items():
                    what = "is unknown to the server (not registered)" if v == "unknown" else \
                        "threw an exception" if v == "exception" else f"failed ({v})"
                    problems.append(_p("load", 2, f"the command /{c} typed in the {plat} console with no "
                                                  f"arguments {what}"))
                if res.get("loaded") and not bad_cmds and not res.get("errors"):
                    cmds = list((res.get("commands") or {}).keys())
                    passed.append(f"loaded in a real {plat} server" +
                                  (f" ({', '.join('/' + c for c in cmds)} ran)" if cmds else ""))
            return
        if not self.load_datapacks:
            return
        dj = mcjob.datapack_job(answer, f"agent{self.n}-{abs(hash(answer)) % 10**8}")
        if dj is None:
            return
        res = self.loader("datapack", dj)
        if res is None:
            return
        for e in (res.get("load_errors") or [])[:5]:
            problems.append(_p("load", 2, f"the real Minecraft 1.21.11 server log while loading the pack: {e}"))
        if res.get("pack_enabled") is False:
            problems.append(_p("load", 2, "the real 1.21.11 server did not enable the data pack (pack.mcmeta / "
                                          "pack format)"))
        for path, v in (res.get("functions") or {}).items():
            v = v if isinstance(v, dict) else {"fn": path, "status": v}
            if v.get("status") != "ok":
                problems.append(_p("load", 2, f"/function {v.get('fn') or path} in the real 1.21.11 server: "
                                              f"{v.get('status')} {(v.get('out') or '')[:300]}"))
        for c in res.get("commands") or []:
            if c.get("parse_error"):
                problems.append(_p("load", 2, f"the 1.21.11 console rejected `/{c.get('cmd')}`: "
                                              f"{' '.join(c.get('out') or [])[:300]}"))
        if not res.get("fail"):
            nf = len(res.get("functions") or {})
            passed.append(f"loaded in a real Minecraft 1.21.11 server ({nf} function{'s' if nf != 1 else ''} ran)")


def _checked_phrase(rep: dict, checked: list[dict]) -> str:
    langs = sorted({b.get("language") or "code" for b in checked})
    java = rep.get("java") or {}
    if java.get("compiled"):
        target = str(java.get("target") or "")
        return f"compiled against the {PLATFORM.get(target, target)} API (javac)"
    if "luau" in langs:
        return "Roblox API + luau-analyze clean"
    return "compiler/type checks clean (" + ", ".join(langs) + ")"


def _tail(res: dict, n: int = 900) -> str:
    step = (res.get("steps") or [{}])[-1]
    return ((step.get("stderr") or "") + ("\n" + step["stdout"] if step.get("stdout") and step.get("rc") else "")
            or res.get("error") or "").strip()[-n:]


def _deps_ok(lang: str, code: str) -> bool:
    if lang == "python":
        mods = re.findall(r"^\s*(?:from\s+([\w]+)|import\s+([\w]+))", code, re.M)
        return all((a or b) in STDLIB for a, b in mods)
    if lang in ("javascript", "typescript"):
        mods = re.findall(r"require\(\s*['\"]([^'\"]+)['\"]\s*\)|from\s+['\"]([^'\"]+)['\"]", code)
        return all((a or b).removeprefix("node:").split("/")[0] in NODE_BUILTIN for a, b in mods)
    return True


def _job(lang: str, code: str, inputs: list[str] | None = None, stdin: str | None = None) -> dict:
    files = {RUN_FILE[lang]: _strip_exports(code) if lang in ("javascript", "typescript") else code}
    job: dict = {"language": lang, "files": files, "run_s": 10}
    if lang == "java":
        m = re.search(r"public\s+(?:final\s+)?class\s+(\w+)", code)
        name = m.group(1) if m else "Main"
        mains = re.findall(r"class\s+(\w+)[^{]*\{(?:(?!\bclass\b).)*?static\s+void\s+main", code, re.S)
        job["files"] = {name + ".java": code}
        job["main_class"] = name if ("static void main" in code and m) else (mains[0] if mains else name)
    if inputs is not None:
        job["inputs"] = inputs
    else:
        job["stdin"] = stdin or ""
    return job


def _strip_exports(code: str) -> str:
    return re.sub(r"^(\s*)export\s+(?:default\s+)?(?=(?:async\s+)?(?:function|class|const|let|var|interface|type|enum)\b)",
                  r"\1", code, flags=re.M)


PY_CANON = ("\nimport json as _aj\n"
            "def _ac(v):\n    return _aj.dumps(v, sort_keys=True, default=repr, separators=(',', ':'))\n")
JS_CANON = ("\nfunction __ac(v){const s=(x)=>Array.isArray(x)?x.map(s):(x&&typeof x==='object'&&!(x instanceof Map)"
            "&&!(x instanceof Set))?Object.keys(x).sort().reduce((o,k)=>{o[k]=s(x[k]);return o},{}):x instanceof Set?"
            "[...x].map(s):x instanceof Map?Object.fromEntries([...x].map(([k,v])=>[k,s(v)])):x;"
            "return JSON.stringify(s(v))}\n")

TS_CANON = ("\nfunction __ac(v: any): string{const s=(x: any): any=>Array.isArray(x)?x.map(s):(x&&typeof x==='object'"
            "&&!(x instanceof Map)&&!(x instanceof Set))?Object.keys(x).sort().reduce((o: any,k: string)=>{o[k]=s(x[k]);"
            "return o},{}):x instanceof Set?Array.from(x).map(s):x instanceof Map?Object.fromEntries(Array.from(x)"
            ".map((e: any)=>[e[0],s(e[1])])):x;return JSON.stringify(s(v))}\n")


def _call_program(lang: str, code: str, calls: list[tuple[str, str]]) -> str | None:
    if lang == "python":
        lines = [code.rstrip(), PY_CANON]
        for i, (call, want) in enumerate(calls):
            want_py = _py_literal(want)
            if want_py is not None:
                lines.append(f"print('@@e{i} ' + _ac({want_py}))")
            lines.append(f"try:\n    print('@@g{i} ' + _ac({call}))\nexcept Exception as _e:\n"
                         f"    print('@@g{i} !' + type(_e).__name__ + ': ' + str(_e)[:200])")
        return "\n".join(lines) + "\n"
    if lang in ("javascript", "typescript"):
        cast = " as any" if lang == "typescript" else ""
        lines = [code.rstrip(), TS_CANON if lang == "typescript" else JS_CANON]
        for i, (call, want) in enumerate(calls):
            lines.append(f"try{{console.log('@@e{i} '+__ac(({want}){cast}))}}catch(e){{}}")
            lines.append(f"try{{console.log('@@g{i} '+__ac(({call}){cast}))}}catch(e){{console.log('@@g{i} !'+"
                         f"String(e).slice(0,200))}}")
        return "\n".join(lines) + "\n"
    return None


def _py_literal(text: str) -> str | None:
    t = text.strip()
    t2 = {"true": "True", "false": "False", "null": "None"}.get(t, t)
    try:
        ast.literal_eval(t2)
        return t2
    except (ValueError, SyntaxError):
        return None
