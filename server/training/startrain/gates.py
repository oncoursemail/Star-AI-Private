"""The verification gates G0..G8 (docs/research/training-plan.md section 3.2). A candidate is kept only if it
passes all of them; the first failing gate (cheapest first) is the recorded reason.

  G0 shape: length bounds, credential pattern, header rules, no require / loadstring, enough assertions
  G6 deprecation lint: wait, spawn, delay, tick, :connect, ... (owner-approvable list in DEPRECATED)
  G8 decontamination (text): exact and fuzzy match against every item of the evaluation suites
  G7 near-duplicates (text): exact and 5-gram Jaccard against everything kept so far
  G1 the code compiles (luau-compile)
  G2 type analysis: pure tasks strict with zero errors; Roblox-flavoured tasks non-strict with zero errors
  G3 the tests pass in the standalone Luau VM under time and memory limits, twice with the same result
  G4 test sanity: the tests must fail on an empty stub and kill at least 70 percent of mechanical mutants
  G7e / G8e near-duplicate and decontamination by task-text embedding cosine (needs the embedding model)
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re

from . import harness, mutate
from . import similarity as sim

_SECRET = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\b(?:github_pat_|ghp_|sk-)[A-Za-z0-9_-]{16,}",
                     re.IGNORECASE)
# (regex on code with comments and strings blanked, what to use instead)
DEPRECATED: list[tuple[re.Pattern, str, bool]] = [
    (re.compile(r"(?<![\w.:])wait\s*\("), "task.wait", False),
    (re.compile(r"(?<![\w.:])spawn\s*\("), "task.spawn", False),
    (re.compile(r"(?<![\w.:])delay\s*\("), "task.delay", False),
    (re.compile(r"(?<![\w.:])tick\s*\("), "os.clock or workspace:GetServerTimeNow", False),
    (re.compile(r":(?:connect|disconnect)\s*\("), ":Connect / :Disconnect", False),
    (re.compile(r":remove\s*\(\s*\)"), ":Destroy()", False),
    (re.compile(r"\bgame\.Workspace\b"), "the workspace global", False),
    (re.compile(r"\bInstance\.new\s*\(\s*[\"'][A-Za-z0-9_]+[\"']\s*,\s*[^\s)]"), "set .Parent after configuring", True),
    (re.compile(r"\b(?:table\.getn|table\.foreach|table\.foreachi|string\.gfind|math\.pow|getfenv|setfenv)\b"), "current Luau API", False),
    (re.compile(r"[\"'](?:BodyVelocity|BodyPosition|BodyGyro|BodyForce|BodyAngularVelocity|BodyThrust)[\"']"), "LinearVelocity / AlignPosition", True),
    (re.compile(r":FindPartOnRay\w*\s*\("), "workspace:Raycast", False),
]
# Self-correction text a teacher sometimes leaves in a task ("... is not needed, just ...", "No, just check ...").
_RAMBLING = re.compile(r"\$\\|\$[A-Za-z(]|\b(?:no, just|actually,|hmm|let me|on second thought|scratch that|wait,)", re.I)
_RAMBLING_CHECK = re.compile(r"check\s*\(\s*[\"'][^\"']*(?:\?|\bno, just\b|\bhmm\b|\bactually\b)", re.I)
_STRICT_HEAD = re.compile(r"\A\s*--!strict\b")


@dataclass
class Verdict:
    ok: bool = True
    gate: str = ""
    code: str = ""
    detail: str = ""
    info: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.gate}:{self.code}"


def reject(gate: str, code: str, detail: str = "") -> Verdict:
    return Verdict(False, gate, code, detail[:300])


def _blank(code: str) -> str:
    return mutate.mask(code)


def g0_shape(c: dict, s) -> Verdict:
    prompt, code, tests, resp = c["prompt"], c["code"], c["tests"], c["response"]
    if not 60 <= len(prompt) <= 2200:
        return reject("G0", "prompt_length", f"{len(prompt)} chars")
    if not 120 <= len(code) <= 9000:
        return reject("G0", "code_length", f"{len(code)} chars")
    if not 150 <= len(tests) <= 10000:
        return reject("G0", "tests_length", f"{len(tests)} chars")
    if len(resp) > 12000:
        return reject("G0", "response_length")
    if _SECRET.search(prompt) or _SECRET.search(resp) or _SECRET.search(tests):
        return reject("G0", "credential_pattern")
    if "\x00" in prompt + resp + tests:
        return reject("G0", "nul_byte")
    if _RAMBLING.search(prompt) or _RAMBLING_CHECK.search(tests):
        return reject("G0", "teacher_rambling", "self-correction or LaTeX text leaked into the task or the test names")
    masked = _blank(code)
    if re.search(r"\b(loadstring|dofile|getfenv|setfenv)\b|(?<![\w.])require\s*\(", masked):
        return reject("G0", "forbidden_call", "loadstring / require / environment access")
    if "--!nocheck" in code or re.search(r"--!nonstrict", code) and c["mode"] == "pure":
        return reject("G0", "checking_disabled")
    if c["mode"] == "pure":
        if not _STRICT_HEAD.match(code):
            return reject("G0", "missing_strict_header")
        if re.search(r"::\s*any\b", masked):
            return reject("G0", "cast_to_any")
    elif _STRICT_HEAD.match(code):
        return reject("G0", "strict_unverifiable", "Roblox-flavoured code can only be analysed non-strict here")
    if len(re.findall(r"(?<![\w.])check\s*\(", _blank(tests))) < s.min_assertions:
        return reject("G0", "few_checks_written", f"fewer than {s.min_assertions} check() calls")
    if re.search(r"check\s*\([^,]*,\s*([\w.:]+(?:\([^()]*\))?)\s*==\s*\1\s*\)", _blank(tests)):
        return reject("G0", "tautological_check", "a check compares a value with itself")
    if re.search(r"check\s*\([^,]*,\s*(?:true|not\s+false)\s*\)", _blank(tests)):
        return reject("G0", "constant_check", "a check that is always true")
    if "load_answer" not in tests:
        return reject("G0", "tests_do_not_load_answer")
    if re.search(r"(?<![\w.])print\s*\(", _blank(code)):
        return reject("G0", "debug_print")
    return Verdict()


def g6_deprecated(c: dict) -> Verdict:
    blanked = _blank(c["code"])                 # comments and strings blanked
    uncommented = sim.strip_comments(c["code"])  # comments removed, strings kept (class-name patterns)
    for pattern, use, needs_strings in DEPRECATED:
        match = pattern.search(uncommented if needs_strings else blanked)
        if match:
            return reject("G6", "deprecated_api", f"{match.group(0).strip()[:40]} (use {use})")
    return Verdict()


def run_tests(tools, code: str, tests: str, *, mutant: bool = False):
    script = harness.build_test_script(tools.prelude, code, tests)
    result = tools.run_script(script, mutant=mutant)
    return result, harness.parse_output(result.stdout)


if "tests/" in tests:
    # Ensure we don't accidentally modify the test files themselves during repair
    pass


def g1_g2(c: dict, tools) -> Verdict:
    mode = "strict" if c["mode"] == "pure" else "nonstrict"
    report = tools.analyse(c["code"], mode)
    if not report.get("compiled"):
        first = (report.get("errors") or [{}])[0]
        return reject("G1", "does_not_compile", f"line {first.get('line')}: {first.get('message', '')}")
    if not report.get("analyzed"):
        return reject("G2", "analyzer_failed", "; ".join(report.get("notes") or [])[:200])
    errors = report.get("errors") or []
    if errors:
        first = errors[0]
        return reject("G2", "type_errors", f"{len(errors)} error(s); line {first.get('line')}: {first.get('message', '')}")
    return Verdict(info={"warnings": report.get("warning_count", 0), "analyser_mode": mode})


def g3_tests(c: dict, tools, s) -> Verdict:
    result, out = run_tests(tools, c["code"], c["tests"])
    if result.timed_out:
        return reject("G3", "timeout", f"more than {s.vm_wall_s}s of wall time")
    if result.killed_by_limit:
        return reject("G3", "resource_limit", "memory or CPU limit")
    if out.load_error:
        return reject("G3", "solution_does_not_load", out.load_error)
    if out.error:
        return reject("G3", "test_aborted", out.error)
    if not out.done:
        return reject("G3", "incomplete", "the harness did not finish")
    if len(out.results) < s.min_assertions:
        return reject("G3", "too_few_assertions", f"{len(out.results)} ran")
    if out.failed:
        names = "; ".join(n for n, ok in out.results if not ok)[:200]
        return reject("G3", "assertion_failed", f"{out.failed} of {len(out.results)}: {names}")
    again, out2 = run_tests(tools, c["code"], c["tests"])
    if out2.results != out.results or again.timed_out:
        return reject("G3", "nondeterministic", "two runs disagree")
    return Verdict(info={"assertions": len(out.results), "vm_seconds": result.seconds})


def g4_sanity(c: dict, tools, s, seed: int) -> Verdict:
    _, stub = run_tests(tools, "return {}\n", c["tests"])
    if stub.all_pass(1):
        return reject("G4", "passes_on_empty_stub", "the tests accept an empty module")
    valid = killed = 0
    survivors: list[str] = []
    tried = 0
    for m in mutate.select(c["code"], seed, limit=s.mutant_max_valid * 3):
        if valid >= s.mutant_max_valid:
            break
        tried += 1
        result, out = run_tests(tools, m.code, c["tests"], mutant=True)
        if out.load_error and not out.results:
            continue                                   # the mutant does not even load: not a usable mutant
        valid += 1
        if result.timed_out or result.killed_by_limit or out.error or not out.done or out.failed:
            killed += 1
        else:
            survivors.append(f"{m.kind}@{m.line}")
    info = {"mutants": valid, "killed": killed, "tried": tried, "survivors": survivors[:6]}
    if valid < s.mutant_min_valid:
        return reject("G4", "too_few_mutants", f"{valid} usable mutants")
    rate = killed / valid
    info["kill_rate"] = round(rate, 3)
    if rate < s.mutant_kill_rate:
        return Verdict(False, "G4", "weak_tests", f"killed {killed} of {valid} mutants; survivors {survivors[:4]}", info)
    return Verdict(info=info)


class Memory:
    """Everything kept so far, for the near-duplicate gates."""

    def __init__(self):
        self.items: list[dict] = []        # {id, prompt_hash, code_hash, prompt_sh5, code_sh5}
        self.vectors: list[tuple[str, list[float]]] = []

    def add(self, cid: str, fp: dict, vector: list[float] | None) -> None:
        self.items.append({"id": cid, **{k: fp[k] for k in ("prompt_hash", "code_hash", "prompt_sh5", "code_sh5")}})
        if vector is not None:
            self.vectors.append((cid, vector))

    def duplicate_of(self, fp: dict, s) -> str:
        for it in self.items:
            if fp["prompt_hash"] == it["prompt_hash"] or fp["code_hash"] == it["code_hash"]:
                return it["id"]
            if sim.jaccard(fp["code_sh5"], it["code_sh5"]) >= s.dup_jaccard \
                    or sim.jaccard(fp["prompt_sh5"], it["prompt_sh5"]) >= s.dup_jaccard:
                return it["id"]
        return ""

    def nearest(self, vector: list[float]) -> tuple[str, float]:
        best_id, best = "", 0.0
        for cid, other in self.vectors:
            value = sim.cosine(vector, other)
            if value > best:
                best_id, best = cid, value
        return best_id, best


def gate_log_hash(c: dict, infos: dict) -> str:
    blob = json.dumps({"prompt": c["prompt"], "code": c["code"], "tests": c["tests"], "gates": infos},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
