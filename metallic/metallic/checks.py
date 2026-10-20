"""Built-in Metallic checks. Each looks at the change from a base tree to a tree and returns a CheckResult.

Findings carry file, line, rule and a message; the secret scan never returns or prints the matched text.
"""
from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time

from . import gitutil
from .config import Config, fnmatch_any, matches

PASS, FAIL, WARN, SKIP, INFO = "pass", "fail", "warn", "skip", "info"


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str = ""
    findings: list[dict] = field(default_factory=list)
    seconds: float = 0.0
    cached: bool = False
    blocking: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Context:
    root: Path
    cfg: Config
    base_tree: str
    tree: str
    files: dict[str, str]          # path -> blob in `tree`
    changed: list[str]
    branch: str
    _added: dict[str, list[tuple[int, str]]] | None = None

    def added(self) -> dict[str, list[tuple[int, str]]]:
        """file -> [(line number in the new file, added line)] parsed from a zero-context diff."""
        if self._added is None:
            self._added = parse_added(gitutil.diff_text(self.base_tree, self.tree, self.root))
        return self._added


def parse_added(diff: str) -> dict[str, list[tuple[int, str]]]:
    out: dict[str, list[tuple[int, str]]] = {}
    cur, line = None, 0
    for ln in diff.split("\n"):
        if ln.startswith("+++ "):
            p = ln[4:].strip()
            cur = None if p == "/dev/null" else (p[2:] if p.startswith("b/") else p)
            continue
        if ln.startswith("--- "):
            continue
        m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", ln)
        if m:
            line = int(m.group(1))
            continue
        if ln.startswith("+") and cur:
            out.setdefault(cur, []).append((line, ln[1:]))
            line += 1
    return out


def finding(file: str, line: int, rule: str, message: str, severity: str = FAIL) -> dict:
    return {"file": file, "line": line, "rule": rule, "message": message, "severity": severity}


def _status(findings: list[dict]) -> str:
    sev = {f["severity"] for f in findings}
    return FAIL if FAIL in sev else WARN if WARN in sev else INFO if sev else PASS


# ---------------------------------------------------------------- git diff --check

def check_diff(ctx: Context) -> CheckResult:
    proc = subprocess.run(["git", "diff", "--check", "--no-color", ctx.base_tree, ctx.tree], cwd=str(ctx.root),
                          capture_output=True)
    out = []
    for ln in proc.stdout.decode("utf-8", "replace").splitlines():
        m = re.match(r"^(.+?):(\d+): (.+)$", ln)
        if m and not ln.startswith(("+", "-")):
            out.append(finding(m.group(1), int(m.group(2)), "diff-check", m.group(3).rstrip(".")))
    return CheckResult("diff-check", _status(out), f"{len(out)} whitespace/conflict-marker problem(s)", out)


# ---------------------------------------------------------------- secrets, private addresses, server user names
# Same patterns as the workspace's `star commit` scan (tools/star.py), so a diff that passes here passes there.

_IP_RE = re.compile(r"(?<![\w.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![\w])(?!\.\d)")
TOKEN_PATTERNS = [
    ("private key block", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("API key (sk- style)", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{30,}")),
    ("JSON web token", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
]
_ASSIGN_RE = re.compile(
    r"""(?ix)
    (?:api[_-]?key|secret|token|passw(?:or)?d|passwd|credential|auth[_-]?key|private[_-]?key)[A-Za-z0-9_.-]{0,40}
    ["']?\s*(?::=|=>|[:=])\s*["']?
    (?P<val>[A-Za-z0-9+/=_\-.~!@\#$%^&*]{20,})""")
_PLACEHOLDER = re.compile(r"(?i)example|your|xxxx|changeme|placeholder|dummy|sample|<|\$\{|%\(|\bnone\b|redacted")


def _entropy(s: str) -> float:
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    return -sum(c / len(s) * math.log2(c / len(s)) for c in counts.values()) if s else 0.0


def _looks_secret(val: str) -> bool:
    if _PLACEHOLDER.search(val):
        return False
    classes = sum(bool(re.search(p, val)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]"))
    return classes >= 2 and bool(re.search(r"[0-9]", val)) and _entropy(val) >= 3.2


def scan_line(line: str, private_names: list[str]) -> list[str]:
    """Categories found in one line; the matched text itself is never returned."""
    if "star:allow" in line or "metallic:allow" in line:
        return []
    found = []
    for m in _IP_RE.finditer(line):
        o = [int(x) for x in m.groups()]
        if any(x > 255 for x in o):
            continue
        if o[0] == 10 or (o[0] == 192 and o[1] == 168) or (o[0] == 172 and 16 <= o[1] <= 31):
            found.append("private network address")
            break
    for name in private_names:
        if name and re.search(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", line, re.I):
            found.append("server user name or private host name")
            break
    for cat, rx in TOKEN_PATTERNS:
        if rx.search(line):
            found.append("key or token (" + cat + ")")
    for m in _ASSIGN_RE.finditer(line):
        if _looks_secret(m.group("val")):
            found.append("key or token (secret-looking value assigned to a secret-looking name)")
            break
    return found


def check_secrets(ctx: Context, private_names: list[str]) -> CheckResult:
    out = []
    for f, lines in ctx.added().items():
        for n, text in lines:
            for cat in dict.fromkeys(scan_line(text, private_names)):
                out.append(finding(f, n, "secret", cat))
    note = "" if private_names else " (no private names configured: ~/.metallic/private_names.txt)"
    return CheckResult("secrets", _status(out), f"{len(out)} finding(s) in added lines{note}", out)


# ---------------------------------------------------------------- forbidden files and protected paths

MODEL_EXTS = {".gguf", ".safetensors", ".ckpt", ".pt", ".pth", ".onnx", ".h5", ".tflite", ".mlmodel", ".joblib",
              ".pkl", ".engine", ".trt", ".npz", ".pb"}
AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".aiff", ".aif", ".wma"}
SECRET_BASENAMES = {".env", "star.env", "auth.json", "server_api_key", "id_rsa", "id_ed25519", "id_ecdsa"}
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx")


def check_files(ctx: Context) -> CheckResult:
    out = []
    for f in ctx.changed:
        if f not in ctx.files:
            continue
        b = f.rsplit("/", 1)[-1].lower()
        ext = os.path.splitext(b)[1]
        why = None
        if ext in MODEL_EXTS:
            why = "model file (" + ext + ")"
        elif ext in AUDIO_EXTS:
            why = "audio file (" + ext + ")"
        elif b in SECRET_BASENAMES or b.endswith(SECRET_SUFFIXES) or (b.startswith(".env.") and b != ".env.example"):
            why = "credential or key file"
        elif ctx.cfg.forbidden_files and matches(f, ctx.cfg.forbidden_files):
            why = "forbidden by metallic.toml (" + matches(f, ctx.cfg.forbidden_files) + ")"
        else:
            size = int(gitutil.git(["cat-file", "-s", ctx.files[f]], ctx.root).strip() or 0)
            if size > ctx.cfg.max_file_mb * 1024 * 1024:
                why = f"larger than {ctx.cfg.max_file_mb:g} MB ({size / 1048576:.1f} MB)"
        if why:
            out.append(finding(f, 0, "file", why))
    return CheckResult("files", _status(out), f"{len(out)} forbidden file(s)", out)


def check_protected(ctx: Context) -> CheckResult:
    cfg = ctx.cfg
    if not cfg.generator_branches:
        return CheckResult("protected-paths", SKIP, "no generator branches configured")
    if not fnmatch_any(ctx.branch, cfg.generator_branches):
        return CheckResult("protected-paths", PASS, f"{ctx.branch} is not a generator branch")
    out = [finding(f, 0, "protected", f"generator branch may not touch the evaluation closure ({p})")
           for f in ctx.changed if (p := matches(f, cfg.protected_paths))]
    return CheckResult("protected-paths", _status(out), f"{len(out)} protected path(s) touched by {ctx.branch}", out)


# ---------------------------------------------------------------- anti-slop for code diffs

_TEST_FILE = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]*\.py$|_test\.(py|go)$|\.(test|spec)\.[jt]sx?$"
                        r"|\.spec\.luau$")
SLOP_RULES = [
    # (rule id, file regex, line regex, severity, message)
    ("S01.todo", r".", r"(#|//|--|/\*)\s*(TODO|FIXME|XXX|HACK)\b(?!.*(#\d+|https?://))", "warn",
     "TODO/FIXME without an issue number"),
    ("S02.focused-test", r"\.[jt]sx?$", r"\b(it|describe|test)\.only\s*\(|\b(fit|fdescribe)\s*\(", "fail",
     "focused test: every other test in the file is silently skipped"),
    ("S03.skip-no-reason", r"\.py$", r"@pytest\.mark\.skip\s*$|@pytest\.mark\.skip\(\s*\)", "warn",
     "skipped test without a reason"),
    ("S03.skip-no-reason", r"\.[jt]sx?$", r"\b(it|describe|test)\.skip\s*\(|\bxit\s*\(", "warn", "skipped test"),
    ("S04.vacuous-assert", r".", r"^\s*assert\s+(True|1)\s*(#.*)?$|expect\(\s*true\s*\)\.toBe\(\s*true\s*\)"
     r"|assertTrue\(\s*True\s*\)|assert\.ok\(\s*true\s*\)", "fail", "assertion that can never fail"),
    ("S05.debugger", r"\.py$", r"^\s*(breakpoint\(\)|import pdb|pdb\.set_trace\(\))", "fail", "debugger left in"),
    ("S05.debugger", r"\.[jt]sx?$", r"^\s*debugger\s*;?\s*$", "fail", "debugger left in"),
    ("S06.placeholder", r".", r"(?i)lorem ipsum|your code here|implement (this|me)\b"
     r"|\bplaceholder implementation", "warn", "placeholder text"),
    ("S07.swallowed", r"\.py$", r"^\s*except(\s+(Exception|BaseException))?\s*:\s*pass\s*$", "warn",
     "exception swallowed silently"),
]
_SLOP_COMPILED = [(r, re.compile(fp), re.compile(lp), s, m) for r, fp, lp, s, m in SLOP_RULES]


def _commented_code(line: str) -> bool:
    s = line.strip()
    if not s.startswith("# ") or len(s) < 8:
        return False
    body = s[2:]
    if body.endswith((".", ":")) and " " in body and not re.search(r"[()=\[\]]", body):
        return False
    try:
        tree = ast.parse(body)
    except SyntaxError:
        try:
            tree = ast.parse("def _f():\n    " + body)     # return/yield only parse inside a function
        except SyntaxError:
            return False
    return any(isinstance(n, (ast.Call, ast.Assign, ast.Return, ast.Import, ast.ImportFrom, ast.AugAssign))
               for n in ast.walk(tree))


_STRING = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'')


def _in_string(line: str, pos: int) -> bool:
    """A match inside a quoted literal is a fixture or a message (checker code, tests of checkers), not slop."""
    return any(m.start() < pos < m.end() for m in _STRING.finditer(line))


ALLOW = "metallic:allow"          # on a line: the diff checks skip it (a fixture that must contain the pattern)


def check_slop(ctx: Context) -> CheckResult:
    out = []
    for f, lines in ctx.added().items():
        is_test = bool(_TEST_FILE.search(f))
        lines = [(n, t) for n, t in lines if ALLOW not in t]
        for n, text in lines:
            for rule, frx, lrx, sev, msg in _SLOP_COMPILED:
                if rule == "S04.vacuous-assert" and not is_test:
                    continue
                if frx.search(f) and any(not _in_string(text, m.start()) for m in lrx.finditer(text)):
                    out.append(finding(f, n, rule, msg, sev))
        if f.endswith(".py"):
            run = []
            for n, text in lines + [(-1, "")]:
                if n != -1 and _commented_code(text) and (not run or run[-1] == n - 1):
                    run.append(n)
                    continue
                if len(run) >= 3:
                    out.append(finding(f, run[0], "S08.commented-code", f"{len(run)} lines of commented-out code",
                                       WARN))
                run = [n] if n != -1 and _commented_code(text) else []
    return CheckResult("anti-slop", _status(out), f"{len(out)} finding(s) in added lines", out)


# ---------------------------------------------------------------- Luau / Roblox API

_API_CACHE: dict[str, tuple[set, set, set]] = {}


def _api(path: Path) -> tuple[set, set, set]:
    k = str(path)
    if k not in _API_CACHE:
        data = json.loads(path.read_text(encoding="utf-8"))
        classes, services, creatable = set(), set(), set()
        for c in data.get("Classes", []):
            tags = c.get("Tags") or []
            classes.add(c["Name"])
            if "Service" in tags:
                services.add(c["Name"])
            if "NotCreatable" not in tags and "Service" not in tags:
                creatable.add(c["Name"])
        _API_CACHE[k] = (classes, services, creatable)
    return _API_CACHE[k]


_GETSERVICE = re.compile(r"""\bGetService\s*\(\s*["']([^"']+)["']""")
_INSTANCE_NEW = re.compile(r"""\bInstance\.new\s*\(\s*["']([^"']+)["']""")
_DEPRECATED = re.compile(r"(?<![\w.:])(wait|spawn|delay)\s*\(")


def check_luau(ctx: Context) -> CheckResult:
    luau = {f: ls for f, ls in ctx.added().items() if f.endswith((".lua", ".luau"))}
    if not luau:
        return CheckResult("luau-api", SKIP, "no Luau changes")
    dump = os.environ.get("METALLIC_ROBLOX_API_DUMP") or (
        str(ctx.root / ctx.cfg.luau_api_dump) if ctx.cfg.luau_api_dump else "")
    out = []
    api = _api(Path(dump)) if dump and Path(dump).exists() else None
    for f, lines in luau.items():
        for n, text in lines:
            if ALLOW in text:
                continue
            code = text.split("--", 1)[0]
            if api:
                classes, services, creatable = api
                for m in _GETSERVICE.finditer(code):
                    if m.group(1) not in services:
                        out.append(finding(f, n, "L01.unknown-service", f"GetService(\"{m.group(1)}\"): not a service "
                                           "in the API dump"))
                for m in _INSTANCE_NEW.finditer(code):
                    if m.group(1) not in creatable:
                        why = "not creatable" if m.group(1) in classes else "unknown class"
                        out.append(finding(f, n, "L02.instance-new", f"Instance.new(\"{m.group(1)}\"): {why}"))
            for m in _DEPRECATED.finditer(code):
                out.append(finding(f, n, "L03.deprecated", f"{m.group(1)}() is deprecated: use task.{m.group(1)}()",
                                   WARN))
    summary = f"{len(out)} finding(s) in {len(luau)} Luau file(s)" + ("" if api else " (no API dump: class checks off)")
    return CheckResult("luau-api", _status(out), summary, out)


# ---------------------------------------------------------------- eval gate (paired verdict required)

def check_eval(ctx: Context, verdict_file: str | None, state: Path) -> CheckResult:
    hit = [f for f in ctx.changed if ctx.cfg.eval_paths and matches(f, ctx.cfg.eval_paths)]
    blocking = ctx.cfg.eval_blocking
    if not ctx.cfg.eval_paths:
        return CheckResult("eval-gate", SKIP, "no eval-sensitive paths configured", blocking=blocking)
    if not hit:
        return CheckResult("eval-gate", PASS, "no eval-sensitive file changed", blocking=blocking)
    path = Path(verdict_file) if verdict_file else state / "eval" / (ctx.tree + ".json")
    try:
        v = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        msg = ("eval-sensitive change needs a paired verdict: python -m star.evals gate --paired-session --json "
               f"... > {path.name} (then --eval-verdict FILE)")
        return CheckResult("eval-gate", FAIL if blocking else WARN, msg,
                           [finding(f, 0, "eval", "eval-sensitive file changed", FAIL if blocking else WARN)
                            for f in hit[:20]], blocking=blocking)
    allowed = bool(v.get("allowed")) and int(v.get("exit_code", 1)) == 0
    return CheckResult("eval-gate", PASS if allowed else FAIL,
                       ("paired verdict allows the change" if allowed else
                        f"paired verdict does not allow it (exit {v.get('exit_code')})"), blocking=True)


ALL = ["diff-check", "secrets", "files", "protected-paths", "anti-slop", "luau-api", "eval-gate"]


def run_builtin(ctx: Context, names: list[str], *, verdict_file: str | None, state: Path,
                private_names: list[str]) -> list[CheckResult]:
    fns = {"diff-check": lambda: check_diff(ctx), "secrets": lambda: check_secrets(ctx, private_names),
           "files": lambda: check_files(ctx), "protected-paths": lambda: check_protected(ctx),
           "anti-slop": lambda: check_slop(ctx), "luau-api": lambda: check_luau(ctx),
           "eval-gate": lambda: check_eval(ctx, verdict_file, state)}
    out = []
    for n in names:
        t = time.monotonic()
        r = fns[n]()
        r.seconds = round(time.monotonic() - t, 3)
        out.append(r)
    return out
