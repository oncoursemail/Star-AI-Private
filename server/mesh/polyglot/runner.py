#!/usr/bin/env python3
"""star-polyglot: compile/type checks (and test runs) for code in many languages, inside the throwaway LXD container
`star-polyglot` on brain1 (no network device; CPU/RAM/process caps; every tool runs as an unprivileged user under
timeout + prlimit). Stdlib only. Listens on 127.0.0.1 inside the container; an LXD proxy device publishes it to the
star-mesh verifier. Bodies are never logged (they hold user code).

    GET  /health                         {"status", "tools": {...}, "workers": {...}}
    POST /check  {"language", "code", "context"?}   Bearer token
         -> {"language", "checked", "mode", "tool", "problems": [{kind, severity, name, message, suggestion, line}], "ms"}
    POST /run    {"language", "files": {name: text}, "run_s"?}     (tests; runs the code as the `sandbox` user)
         -> {"ok", "phase", "steps": [{cmd, rc, stdout, stderr, seconds, timed_out}], "stdout", "seconds", "error"}

Checks never execute the user's code: compilers, parsers and type checkers only, as the `pgcheck` user (warm workers for
TypeScript, C# and Java keep the libraries loaded). Severity: "error" only for what would stop the code from compiling
or loading in the language/engine the block targets; things the checker cannot know (third-party packages, the user's
other files, names defined in another block of the same answer) are never reported.
"""
from __future__ import annotations

import difflib
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PG = os.environ.get("PG_HOME", "/opt/pg")
APP = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get("PG_WORK", "/work")
TOKEN_FILE = os.environ.get("PG_TOKEN_FILE", "/etc/star-polyglot/token")
CHECK_UID = int(os.environ.get("PG_CHECK_UID", "1002"))     # pgcheck: compilers only, owns the warm caches
RUN_UID = int(os.environ.get("PG_RUN_UID", "1001"))         # sandbox: runs user code, owns nothing that persists
GOCACHE = "/var/cache/pg/go"
RUSTC = PG + "/rustup/toolchains/stable-x86_64-unknown-linux-gnu/bin/rustc"
GODOT = (sorted(glob.glob(PG + "/godot/Godot_v4*_linux.x86_64")) or ["/opt/godot/godot"])[-1]
RUFF = PG + "/venv/bin/ruff"
JDK = "/opt/jdk/bin"
DOTNET = "/usr/lib/dotnet"
NODE = "/usr/bin/node"
OUT_CAP = 64 * 1024
MAX_CODE = 200 * 1024
CHECK_S = 12
SEM = threading.BoundedSemaphore(int(os.environ.get("PG_PARALLEL", "4")))
RUN_LOCK = threading.Lock()      # one test run at a time: a run ends by killing every process of the run user


def problem(kind, message, line=None, severity="error", name=None, suggestion=None):
    return {"kind": kind, "severity": severity, "name": name, "message": message[:400], "suggestion": suggestion,
            "line": line}


# ---------------------------------------------------------------------------------------------- sandboxed processes
def _env(cwd: str, uid: int) -> list[str]:
    warm_go = uid == CHECK_UID and os.path.isdir(GOCACHE)      # test runs (sandbox user) get a private cache
    return ["HOME=" + cwd, "TMPDIR=" + cwd + "/.tmp", "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8",
            "GOCACHE=" + (GOCACHE if warm_go else cwd + "/.gocache"), "GOPATH=" + cwd + "/.gopath",
            "GOFLAGS=-mod=mod", "GOPROXY=off", "GOTOOLCHAIN=local", "GO111MODULE=on", "CGO_ENABLED=0",
            "DOTNET_CLI_HOME=" + cwd, "DOTNET_CLI_TELEMETRY_OPTOUT=1", "DOTNET_NOLOGO=1", "DOTNET_GCHeapHardLimit=0x30000000",
            "NODE_OPTIONS=--max-old-space-size=768", "PYTHONDONTWRITEBYTECODE=1", "GODOT_SILENCE_ROOT_WARNING=1",
            "XDG_DATA_HOME=" + cwd + "/.local/share", "XDG_CONFIG_HOME=" + cwd + "/.config", "XDG_CACHE_HOME=" + cwd + "/.cache"]


def limited(cmd: list[str], cwd: str, wall: int, uid: int, mem_mb: int | None = 2048, fsize: bool = True) -> list[str]:
    caps = ["--nproc=512", "--nofile=512", f"--cpu={wall}", "--core=0"] + (["--fsize=268435456"] if fsize else [])
    if mem_mb:
        caps.append(f"--as={mem_mb << 20}")
    return (["timeout", "-k", "2", "-s", "KILL", str(wall), "prlimit", *caps,
             "setpriv", f"--reuid={uid}", f"--regid={uid}", "--clear-groups", "--reset-env", "env", "-i", *_env(cwd, uid)]
            + cmd)


def run_limited(cmd, cwd, wall=CHECK_S, uid=CHECK_UID, stdin: bytes | None = None, mem_mb: int | None = 2048,
                fsize: bool = True) -> dict:
    t0 = time.monotonic()
    try:
        done = subprocess.run(limited(cmd, cwd, wall, uid, mem_mb, fsize), cwd=cwd, input=stdin, capture_output=True,
                              timeout=wall + 10)
        rc, out, err = done.returncode, done.stdout, done.stderr
    except subprocess.TimeoutExpired:
        rc, out, err = 137, b"", b"runner: hard timeout"
    secs = round(time.monotonic() - t0, 3)
    return {"cmd": [os.path.basename(cmd[0])] + cmd[1:3], "rc": rc, "seconds": secs, "timed_out": rc in (124, 137),
            "stdout": out[:OUT_CAP].decode("utf-8", "replace"), "stderr": err[:OUT_CAP].decode("utf-8", "replace")}


class Workdir:
    """A fresh folder under /work owned by `uid`, removed afterwards (with every process of a run user)."""

    def __init__(self, uid: int = CHECK_UID, files: dict[str, str] | None = None):
        self.uid, self.files = uid, files or {}

    def __enter__(self) -> str:
        self.path = os.path.join(WORK, ("c-" if self.uid == CHECK_UID else "r-") + uuid.uuid4().hex[:12])
        os.makedirs(self.path, mode=0o700)
        os.makedirs(os.path.join(self.path, ".tmp"))
        for name, text in self.files.items():
            full = os.path.join(self.path, name)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        for root, dirs, names in os.walk(self.path):
            os.chown(root, self.uid, self.uid)
            for n in names:
                os.chown(os.path.join(root, n), self.uid, self.uid)
        return self.path

    def __exit__(self, *exc):
        if self.uid == RUN_UID:
            subprocess.run(["pkill", "-KILL", "-u", str(RUN_UID)], capture_output=True)
        shutil.rmtree(self.path, ignore_errors=True)


class Worker:
    """A warm checker process (stdin/stdout lines) running as pgcheck; restarted when it dies or hangs."""

    def __init__(self, name: str, cmd: list[str], cwd: str, framing: str = "json", timeout: float = 8.0):
        self.name, self.cmd, self.cwd, self.framing, self.timeout = name, cmd, cwd, framing, timeout
        self.proc = None
        self.lock = threading.Lock()
        self.info: dict = {}

    def _start(self):
        os.makedirs(self.cwd + "/.tmp", exist_ok=True)
        os.chown(self.cwd, CHECK_UID, CHECK_UID)
        os.chown(self.cwd + "/.tmp", CHECK_UID, CHECK_UID)
        self.proc = subprocess.Popen(limited(self.cmd, self.cwd, 10 ** 7, CHECK_UID, None, fsize=False), cwd=self.cwd,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.info = self._read(60.0) or {}

    def _read(self, timeout: float):
        box = {}

        def reader():
            try:
                box["line"] = self.proc.stdout.readline()
            except (OSError, ValueError):
                pass
        t = threading.Thread(target=reader, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive() or not box.get("line"):
            self.kill()
            return None
        try:
            return json.loads(box["line"])
        except ValueError:
            return None

    def kill(self):
        if self.proc:
            try:
                self.proc.kill()
                self.proc.wait(2)
            except (OSError, subprocess.TimeoutExpired):
                pass
        self.proc = None

    def alive(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    def ask(self, req: dict) -> dict | None:
        with self.lock:
            for _ in range(2):
                if not self.alive():
                    self._start()
                    if not self.alive():
                        continue
                req = dict(req, id=uuid.uuid4().hex[:8])
                try:
                    if self.framing == "json":
                        self.proc.stdin.write((json.dumps(req) + "\n").encode())
                    else:
                        data = req["code"].encode()
                        self.proc.stdin.write(f"{req['id']} {req['mode']} {len(data)}\n".encode() + data)
                    self.proc.stdin.flush()
                except (OSError, ValueError):
                    self.kill()
                    continue
                reply = self._read(self.timeout)
                if reply is not None and reply.get("id") == req["id"]:
                    return reply
                self.kill()
            return None


def _dotnet_ref() -> str:
    refs = sorted(glob.glob(DOTNET + "/packs/Microsoft.NETCore.App.Ref/*/ref/net8.0"))
    return refs[-1] if refs else ""


WORKERS = {
    "ts": Worker("ts", [NODE, APP + "/workers/ts_worker.js"], "/var/cache/pg/work/ts"),
    "cs": Worker("cs", ["dotnet", PG + "/cscheck/CsCheck.dll", _dotnet_ref(), APP + "/workers/UnityStubs.cs"],
                 "/var/cache/pg/work/cs"),
    "java": Worker("java", [JDK + "/java", "-Xmx384m", "-XX:+UseSerialGC", "-XX:TieredStopAtLevel=1", "-cp",
                            PG + "/javacheck", "JavaCheck"], "/var/cache/pg/work/java", framing="hdr"),
}


# ------------------------------------------------------------------------------------------------------- helpers
def elsewhere(name: str, code: str, context: str) -> bool:
    """`name` is used or defined in another part of the answer (another block or the prose), not only here."""
    if not name or not context:
        return False
    rest = context.replace(code, "", 1)
    return re.search(r"(?<![\w$])" + re.escape(name) + r"(?![\w$])", rest) is not None


def closest(name: str, names, n: int = 1) -> str | None:
    hits = difflib.get_close_matches(name, list(names), n=n, cutoff=0.6)
    return " or ".join(hits) if hits else None


def wrap(prefix: str, code: str, suffix: str, indent: str = "") -> tuple[str, int]:
    body = "\n".join(indent + ln if ln.strip() else ln for ln in code.splitlines())
    return prefix + body + suffix, prefix.count("\n")


def shift(problems: list[dict], offset: int, max_line: int) -> list[dict]:
    for p in problems:
        if p.get("line"):
            p["line"] -= offset
            if p["line"] < 1 or p["line"] > max_line:
                p["line"] = None
    return problems


ELLIPSIS_LINE = re.compile(r"^[ \t]*(?:\.\.\.|…|// \.\.\..*|# \.\.\..*|/\* \.\.\. \*/)[ \t]*$", re.M)


def blank_ellipsis(code: str, comment: str) -> str:
    """A line that is only '...' means "the rest of your code": make it a comment so parsers accept it."""
    return ELLIPSIS_LINE.sub(lambda m: m.group(0).replace("...", comment + " ...", 1) if comment not in m.group(0)
                             else m.group(0), code)


# ------------------------------------------------------------------------------------------------------ Python
PY_DEF = re.compile(r"^(?:def|class|import|from|async\s+def|if __name__)\b", re.M)


def check_python(code: str, context: str) -> dict:
    fragment = not PY_DEF.search(code) and len(code.strip().splitlines()) <= 12
    with Workdir(files={"main.py": code}) as d:
        r = run_limited([RUFF, "check", "--no-cache", "--output-format=json", "--target-version=py313", "--isolated",
                         "--select=E9,F821,F822,F823,F701,F702,F704,F706,F632", "main.py"], d)
    try:
        rows = json.loads(r["stdout"] or "[]")
    except ValueError:
        return {"checked": False, "tool": "ruff", "error": (r["stderr"] or "")[:200]}
    probs = []
    for row in rows:
        code_id, msg = row.get("code"), row.get("message", "")
        line = (row.get("location") or {}).get("row")
        if code_id is None or code_id.startswith("E9") or "SyntaxError" in msg:
            probs.append(problem("syntax", "Python syntax error: " + msg, line))
        elif code_id == "F821":
            name = re.search(r"`([^`]+)`", msg)
            name = name.group(1) if name else None
            if fragment or elsewhere(name, code, context):
                continue
            probs.append(problem("name", f"undefined name '{name}' (NameError when this line runs)", line, name=name))
        else:
            probs.append(problem("compile", msg, line))
    return {"checked": True, "tool": "ruff", "mode": "fragment" if fragment else "file", "problems": probs}


# --------------------------------------------------------------------------------------------- JavaScript / TS
TS_DECL = re.compile(r"^\s*(?:export\s+|import\s+|function\b|class\b|interface\b|type\s+\w|const\b|let\b|var\b|enum\b|"
                     r"async\s+function\b|declare\b|abstract\s+class\b)", re.M)
JSX = re.compile(r"return\s*\(?\s*<[A-Za-z>]|=>\s*\(?\s*<[A-Za-z]|<[A-Z]\w*[^>]*/>|</\w+>")
MODULE = re.compile(r"^\s*(?:import|export)\b", re.M)
TS_IGNORE = {2307, 2792, 7016, 7005, 7006, 7008, 7010, 7011, 7019, 7022, 7023, 7024, 7031, 7034, 7053, 2580, 2591, 2593,
             1375, 1378, 1208, 2686, 2875, 6133, 6192, 6196, 6198, 2306, 2503, 7026, 2875}
TS_NAME = {2304, 2552, 2582, 2583, 2584, 2339, 2551, 2305, 2724, 2614, 2694}


def check_ts(code: str, context: str, lang: str) -> dict:
    tsx = bool(JSX.search(code))
    fragment = not TS_DECL.search(code)
    src = blank_ellipsis(code, "//")
    if not MODULE.search(src):
        src += "\nexport {};\n"         # a module, so names do not clash with lib.dom globals (name, status...)
    reply = WORKERS["ts"].ask({"code": src, "lang": "js" if lang == "javascript" else "ts", "tsx": tsx})
    if not reply or "diags" not in reply:
        return {"checked": False, "tool": "typescript", "error": (reply or {}).get("error", "worker down")}
    probs = []
    for d in reply["diags"]:
        c, msg, line = d["code"], d["message"], d.get("line")
        if d["syntactic"]:
            probs.append(problem("syntax", f"{'JavaScript' if lang == 'javascript' else 'TypeScript'} syntax error "
                                           f"TS{c}: {msg}", line))
            continue
        if c in TS_IGNORE or fragment:
            continue
        names = re.findall(r"'([^']+)'", msg)
        if c in TS_NAME:
            if c in (2304, 2552, 2582, 2583, 2584) and names and elsewhere(names[0], code, context):
                continue
            if c in (2339, 2551) and len(names) > 1 and re.match(r"^(typeof )?[A-Z]\w*$", names[1]) is None and \
                    names[1] not in ("string", "number", "boolean") and not names[1].endswith("[]"):
                continue      # a member on an anonymous/inferred object type: often a fragment of a bigger file
        sugg = None
        m = re.search(r"Did you mean '([^']+)'", msg)
        if m:
            sugg = m.group(1)
        probs.append(problem("type", f"TypeScript TS{c}: {msg}", line, name=names[0] if names else None,
                             suggestion=sugg))
    return {"checked": True, "tool": "typescript " + str(WORKERS["ts"].info.get("ts", "")),
            "mode": "syntax" if lang == "javascript" else ("fragment" if fragment else "file"), "problems": probs,
            "worker_ms": reply.get("ms")}


# ----------------------------------------------------------------------------------------------------- C# / Unity
CS_TYPE_DECL = re.compile(r"^\s*(?:\[[^\]]*\]\s*)*(?:(?:public|internal|private|protected|static|sealed|abstract|partial|"
                          r"readonly|file|unsafe)\s+)*(?:class|struct|record|interface|enum|namespace)\s+\w", re.M)
UNITY = re.compile(r"\busing\s+UnityEngine\b|:\s*(?:MonoBehaviour|ScriptableObject|NetworkBehaviour)\b|\bUnityEngine\.")
GODOT_CS = re.compile(r"\busing\s+Godot\b|:\s*(?:Node|Node2D|Node3D|CharacterBody[23]D|Control)\b")
BCL = {"string", "int", "float", "double", "bool", "char", "long", "object", "decimal", "byte", "List", "Dictionary",
       "HashSet", "Queue", "Stack", "IEnumerable", "IList", "ICollection", "Task", "StringBuilder", "DateTime",
       "TimeSpan", "Console", "Math", "File", "Path", "Directory", "Array", "Enumerable", "Random", "Guid", "Exception",
       "LinkedList", "SortedDictionary", "Tuple", "Span", "Stream", "StreamReader", "StreamWriter", "Regex", "Convert",
       "Environment", "Thread", "CancellationToken", "HttpClient", "JsonSerializer", "Encoding", "MathF", "Nullable"}
_UNITY_INDEX: dict = {}


def unity_index() -> dict:
    """{"now": set("Class.member"), "old": set(...), "bases": {cls: [base...]}} from the official Unity scripting
    reference search index (docs.unity3d.com .../ScriptReference/docdata/index.js), current and 2022.3 LTS."""
    if _UNITY_INDEX:
        return _UNITY_INDEX
    def load(path):
        try:
            text = open(path, encoding="utf-8").read()
        except OSError:
            return set()
        start = text.index("var pages") + len("var pages =")
        end = text.index("var info")
        rows = json.loads(text[start:end].strip().rstrip(";"))
        return {r[1] for r in rows if len(r) > 1}
    now, old = load(PG + "/data/unity-index.js"), load(PG + "/data/unity-index-2022.3.js")
    bases = {}
    stubs = open(APP + "/workers/UnityStubs.cs", encoding="utf-8").read()
    parent = dict(re.findall(r"class (\w+)\s*:\s*(?:[\w.]+\.)?(\w+)", stubs))
    for cls in parent:
        chain, c = [], cls
        while c in parent and len(chain) < 8:
            c = parent[c]
            chain.append(c)
        bases[cls] = chain
    _UNITY_INDEX.update(now=now, old=old, bases=bases, classes={n.split(".")[0] for n in now})
    return _UNITY_INDEX


UNITY_RENAMES = {"Rigidbody.velocity": "linearVelocity", "Rigidbody.drag": "linearDamping",
                 "Rigidbody.angularDrag": "angularDamping", "Rigidbody2D.velocity": "linearVelocity",
                 "Rigidbody2D.drag": "linearDamping", "Rigidbody2D.angularDrag": "angularDamping",
                 "Object.FindObjectOfType": "FindFirstObjectByType", "Object.FindObjectsOfType": "FindObjectsByType"}


def unity_member(cls: str, member: str) -> dict | None:
    """None when the docs list the member (a gap in our stubs); else a problem."""
    idx = unity_index()
    if not idx["now"]:
        return None
    owners = [cls] + idx["bases"].get(cls, []) + ["Object"]
    if any(f"{o}.{member}" in idx["now"] for o in owners):
        return None
    old = next((o for o in owners if f"{o}.{member}" in idx["old"]), None)
    real = sorted({n.split(".", 1)[1] for n in idx["now"] for o in owners if n.startswith(o + ".")})
    if old:
        sugg = UNITY_RENAMES.get(f"{old}.{member}") or closest(member, real)
        return problem("deprecated", f"{cls}.{member} is obsolete in Unity 6 (removed from the current scripting "
                                     f"reference)", severity="warning", name=f"{cls}.{member}", suggestion=sugg)
    return problem("api", f"'{cls}' has no member '{member}' in the Unity scripting reference", name=f"{cls}.{member}",
                   suggestion=closest(member, real))


def check_csharp(code: str, context: str) -> dict:
    src = blank_ellipsis(code, "//")
    unity = bool(UNITY.search(code))
    if not CS_TYPE_DECL.search(code):
        mode = "script"                 # statements/methods only: syntax (Roslyn script parse)
    elif GODOT_CS.search(code) and not unity:
        mode = "syntax"                 # Godot C#: no GodotSharp reference here
    else:
        mode = "unity" if unity else "dotnet"
    reply = WORKERS["cs"].ask({"code": src, "mode": mode})
    if not reply or "diags" not in reply:
        return {"checked": False, "tool": "roslyn", "error": (reply or {}).get("error", "worker down")}
    probs, declared = [], set(re.findall(r"\b(?:class|struct|record|interface|enum)\s+(\w+)", code))
    for d in reply["diags"]:
        cid, msg, line = d["code"], d["message"], d.get("line")
        if d["syntactic"]:
            probs.append(problem("syntax", f"C# syntax error {cid}: {msg}", line))
            continue
        names = re.findall(r"'([^']+)'", msg)
        if cid in ("CS1061", "CS0117") and len(names) >= 2:
            cls = names[0].split(".")[-1].split("<")[0]
            if unity and cls in unity_index()["classes"] and cls not in declared:
                p = unity_member(cls, names[1])
                if p:
                    p["line"] = line
                    probs.append(p)
                continue
            if mode == "dotnet" and (cls in BCL or cls in declared):
                probs.append(problem("api", f"C# {cid}: {msg.split(' and no accessible')[0]}", line,
                                     name=f"{cls}.{names[1]}"))
            continue
        if mode == "unity":
            if cid in ("CS0161", "CS0165", "CS0029", "CS0019") and not re.search(r"'[A-Z]\w*'", msg.replace("'string'", "")):
                probs.append(problem("compile", f"C# {cid}: {msg}", line))
            elif cid == "CS0103" and names and names[0] not in unity_index()["classes"] and \
                    not names[0][:1].isupper() and not elsewhere(names[0], code, context):
                probs.append(problem("name", f"C# {cid}: {msg}", line, name=names[0]))
            continue
        if cid in ("CS0246", "CS0234", "CS0012", "CS0400", "CS0122") or (cid == "CS0103" and names and
                                                                       elsewhere(names[0], code, context)):
            continue
        if d.get("severity") == "warning" and cid == "CS0618":
            probs.append(problem("deprecated", f"C# {cid}: {msg}", line, severity="warning"))
            continue
        probs.append(problem("compile", f"C# {cid}: {msg}", line))
    return {"checked": True, "tool": "roslyn" + (" + Unity reference" if unity else ""), "mode": mode,
            "problems": probs, "worker_ms": reply.get("ms")}


# --------------------------------------------------------------------------------------------------------- Java
JAVA_TYPE = re.compile(r"^\s*(?:@\w+(?:\([^)]*\))?\s*)*(?:(?:public|private|protected|static|final|abstract|sealed|"
                       r"non-sealed)\s+)*(?:class|interface|enum|record|@interface)\s+\w", re.M)
JAVA_METHOD = re.compile(r"^\s*(?:(?:public|private|protected|static|final|abstract|synchronized)\s+)*[\w<>\[\],\s]+\s+"
                         r"\w+\s*\([^;{]*\)\s*(?:throws [\w., ]+)?\s*\{", re.M)
JAVA_STD = re.compile(r"^\s*import\s+(?:static\s+)?(?!java\.|javax\.)[\w.]+", re.M)


def check_java(code: str, context: str) -> dict:
    src, offset, mode = blank_ellipsis(code, "//"), 0, "full"
    if not JAVA_TYPE.search(code):
        if JAVA_METHOD.search(code):
            src, offset = wrap("class Main {\n", src, "\n}\n")
        else:
            src, offset = wrap("class Main { void frag() throws Exception {\n", src, "\n}}\n")
        mode = "syntax"
    elif JAVA_STD.search(code):
        mode = "syntax"                  # Bukkit/Paper/LWJGL/libGDX imports: no jars here (mc-plugins lane has them)
    reply = WORKERS["java"].ask({"code": src, "mode": mode})
    if not reply or "diags" not in reply:
        return {"checked": False, "tool": "javac", "error": (reply or {}).get("error", "worker down")}
    probs = []
    for d in reply["diags"]:
        cid, msg = d["code"], d["message"]
        if "class.public.should.be.in.file" in cid or "doesnt.exist" in cid or "already.defined" in cid and offset:
            continue
        if "cant.resolve" in cid:
            sym = re.search(r"symbol:\s+\w+\s+(\w+)", msg) or re.search(r"(\w+)\s*$", msg)
            name = sym.group(1) if sym else None
            if elsewhere(name or "", code, context) or (name and name[:1].isupper() and not JAVA_STD.search(code)
                                                       and name not in ("String", "System", "Math", "List")):
                continue
            probs.append(problem("name", "Java: " + msg, d.get("line"), name=name))
            continue
        kind = "syntax" if d.get("syntactic") else "compile"
        sev = "warning" if "deprecat" in cid else "error"
        probs.append(problem(kind if sev == "error" else "deprecated", "Java: " + msg, d.get("line"), severity=sev))
    return {"checked": True, "tool": "javac 21", "mode": mode if not offset else "fragment",
            "problems": shift(probs, offset, len(code.splitlines())), "worker_ms": reply.get("ms")}


# -------------------------------------------------------------------------------------------------------- C / C++
STD_HEADERS = set("""algorithm any array atomic barrier bit bitset cassert cctype cerrno cfenv cfloat charconv chrono
cinttypes climits clocale cmath codecvt compare complex concepts condition_variable coroutine csetjmp csignal cstdarg
cstddef cstdint cstdio cstdlib cstring ctime cuchar cwchar cwctype deque exception execution expected filesystem format
forward_list fstream functional future generator initializer_list iomanip ios iosfwd iostream istream iterator latch
limits list locale map mdspan memory memory_resource mutex new numbers numeric optional ostream print queue random
ranges ratio regex scoped_allocator semaphore set shared_mutex source_location span spanstream sstream stack
stacktrace stdexcept stop_token streambuf string string_view syncstream system_error thread tuple type_traits typeindex
typeinfo unordered_map unordered_set utility valarray variant vector version assert.h ctype.h errno.h float.h
inttypes.h limits.h locale.h math.h setjmp.h signal.h stdarg.h stdbool.h stddef.h stdint.h stdio.h stdlib.h string.h
time.h wchar.h stdatomic.h threads.h unistd.h pthread.h sys/types.h sys/stat.h fcntl.h dirent.h bits/stdc++.h""".split())
INCLUDE = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', re.M)
UNREAL = re.compile(r"\bUCLASS\s*\(|\bGENERATED_BODY\s*\(|\bUPROPERTY\s*\(|\bUFUNCTION\s*\(|CoreMinimal\.h|\.generated\.h")
CPP_DEF = re.compile(r"^\s*(?:template\s*<[^>]*>\s*)?(?:class|struct|namespace|enum|union)\b|^[\w:<>,*&\s]+?\b\w+\s*\([^;]*\)"
                     r"\s*(?:const\s*)?(?:noexcept\s*)?(?:->\s*[\w:<>]+\s*)?\{|^\s*#\s*include", re.M)
CPP_DIAG = re.compile(r"^main\.(?:cpp|c):(\d+):\d+:\s*(error|warning):\s*(.*)$", re.M)


def check_cpp(code: str, context: str, lang: str) -> dict:
    if UNREAL.search(code):
        return {"checked": False, "tool": "g++", "mode": "unreal", "problems": [],
                "note": "Unreal C++ needs the engine headers (not available): not compiled"}
    unknown = [h for h in INCLUDE.findall(code) if h not in STD_HEADERS]
    if unknown:
        return {"checked": False, "tool": "g++", "mode": "external-headers", "problems": [],
                "note": "includes headers that are not in the standard library: " + ", ".join(unknown[:4])}
    is_c = lang == "c"
    src, offset, fragment = blank_ellipsis(code, "//"), 0, not CPP_DEF.search(code)
    if fragment:
        src, offset = wrap(("#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\nvoid frag(void) {\n"
                            if is_c else "#include <bits/stdc++.h>\nusing namespace std;\nvoid frag() {\n"), src, "\n}\n")
    name = "main.c" if is_c else "main.cpp"
    # (a precompiled <bits/stdc++.h> was measured slower for -fsyntax-only: 0.97 s vs 0.62 s for iostream+vector)
    cmd = (["gcc", "-fsyntax-only", "-std=gnu17", "-w", name] if is_c else
           ["g++", "-fsyntax-only", "-std=gnu++20", "-w", "-Wdeprecated-declarations", name])
    with Workdir(files={name: src}) as d:
        r = run_limited(cmd, d)
    if r["timed_out"]:
        return {"checked": False, "tool": cmd[0], "error": "timeout"}
    probs = []
    for m in CPP_DIAG.finditer(r["stderr"]):
        line, sev, msg = int(m.group(1)), m.group(2), m.group(3)
        if fragment and not re.search(r"expected|stray|missing terminating|unterminated|before '.*' token", msg):
            continue
        undeclared = re.search(r"'([\w:]+)' (?:was not declared|has not been declared|does not name a type)", msg)
        if undeclared and elsewhere(undeclared.group(1).split("::")[-1], code, context):
            continue
        probs.append(problem("compile" if sev == "error" else "deprecated", f"{'C' if is_c else 'C++'}: {msg}", line,
                             severity="error" if sev == "error" else "warning",
                             name=undeclared.group(1) if undeclared else None))
    return {"checked": True, "tool": cmd[0] + " 13", "mode": "fragment" if fragment else "file",
            "problems": shift(probs, offset, len(code.splitlines()))[:12]}


# ---------------------------------------------------------------------------------------------------------- Rust
RS_ITEM = re.compile(r"^\s*(?:pub(?:\([\w ]+\))?\s+)?(?:fn|struct|enum|impl|trait|mod|use|type|const|static|macro_rules!"
                     r"|extern|#!?\[|async\s+fn|unsafe\s+fn)\b", re.M)
RS_EXT = re.compile(r"^\s*(?:pub\s+)?use\s+(?:::)?(\w+)|^\s*extern\s+crate\s+(\w+)|(?<![\w:])([a-z_]\w*)::", re.M)
RS_LOCAL = {"std", "core", "alloc", "crate", "self", "super", "Self"}
RS_BORROW = {"E0382", "E0499", "E0502", "E0505", "E0506", "E0597", "E0716", "E0384", "E0596", "E0503", "E0373", "E0507"}


def check_rust(code: str, context: str) -> dict:
    src, offset = blank_ellipsis(code, "//"), 0
    fragment = not RS_ITEM.search(code)
    if fragment:
        src, offset = wrap("#[allow(unused)]\nfn main() {\n", src, "\n}\n")
    mods = set(re.findall(r"^\s*(?:pub\s+)?mod\s+(\w+)", code, re.M))
    ext = {g for m in RS_EXT.finditer(code) for g in m.groups() if g} - RS_LOCAL - mods
    ext = {e for e in ext if re.search(r"^\s*(?:pub\s+)?use\s+(?:::)?" + e + r"\b|extern\s+crate\s+" + e, code, re.M)}
    crate_type = "bin" if re.search(r"\bfn\s+main\s*\(", src) else "lib"
    with Workdir(files={"main.rs": src}) as d:
        r = run_limited([RUSTC, "--edition", "2021", "--crate-type", crate_type, "--emit=metadata", "-o", "out.rmeta",
                         "--error-format=json", "-A", "warnings", "-W", "deprecated", "main.rs"], d, mem_mb=None)
    if r["timed_out"]:
        return {"checked": False, "tool": "rustc", "error": "timeout"}
    probs = []
    for raw in r["stderr"].splitlines():
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        level, msg = d.get("level"), d.get("message", "")
        if level not in ("error", "warning") or msg.startswith(("aborting due to", "Some errors have", "For more information")):
            continue
        cid = (d.get("code") or {}).get("code") or ""
        span = next((s for s in d.get("spans") or [] if s.get("is_primary")), None)
        line = span["line_start"] if span else None
        if ext and cid in ("E0432", "E0433", "E0412", "E0425", "E0405", "E0422", "E0423", "E0603", "E0599", "E0277", "E0282"):
            continue                       # names from a crate that is not vendored here
        if fragment and cid and cid not in RS_BORROW:
            continue
        name = re.search(r"`([^`]+)`", msg)
        if cid in ("E0425", "E0412", "E0433") and name and elsewhere(name.group(1).split("::")[-1], code, context):
            continue
        if level == "warning":
            if "deprecated" in msg:
                probs.append(problem("deprecated", "Rust: " + msg, line, severity="warning"))
            continue
        sugg = None
        for child in d.get("children") or []:
            for s in child.get("spans") or []:
                if s.get("suggested_replacement"):
                    sugg = s["suggested_replacement"][:80]
                    break
        probs.append(problem("borrow" if cid in RS_BORROW else ("syntax" if not cid else "compile"),
                             f"Rust {cid}: {msg}".replace("Rust : ", "Rust: "), line, suggestion=sugg))
    return {"checked": True, "tool": "rustc 1.99", "mode": "fragment" if fragment else ("file+crates" if ext else "file"),
            "problems": shift(probs, offset, len(code.splitlines()))[:12]}


# ------------------------------------------------------------------------------------------------------------ Go
GO_DIAG = re.compile(r"(?:^|\s)(?:\./)?main\.go:(\d+):(?:\d+:)?\s*(.*)$", re.M)


def check_go(code: str, context: str) -> dict:
    src, offset = blank_ellipsis(code, "//"), 0
    if not re.search(r"^\s*package\s+\w+", src, re.M):
        if re.search(r"^func\s|^type\s|^import\b|^var\s|^const\s", src, re.M):
            src, offset = "package main\n" + src, 1
        else:
            src, offset = wrap("package main\nfunc frag() {\n", src, "\n}\n")
    third = re.search(r'"[a-z0-9-]+\.[a-z]{2,}[^"]*"', src) is not None     # github.com/..., golang.org/x/...
    with Workdir(files={"main.go": src, "go.mod": "module answer\n\ngo 1.22\n"}) as d:
        r = run_limited(["gofmt", "-e", "-l", "main.go"], d)
        syntax = r["rc"] != 0
        out = r["stderr"]
        if not syntax and not third and not offset == 2:
            r = run_limited(["go", "vet", "."], d, wall=20, mem_mb=None)
            out = r["stderr"] + r["stdout"]
    probs = []
    for m in GO_DIAG.finditer(out):
        line, msg = int(m.group(1)), m.group(2).strip()
        name = re.search(r"undefined: (\w+)", msg)
        if name and elsewhere(name.group(1), code, context):
            continue
        if offset >= 2 and not syntax:
            continue
        probs.append(problem("syntax" if syntax else "compile", "Go: " + msg, line,
                             name=name.group(1) if name else None))
    return {"checked": True, "tool": "go 1.22 vet" if not syntax else "gofmt",
            "mode": "fragment" if offset >= 2 else ("syntax" if third else "file"),
            "problems": shift(probs, offset, len(code.splitlines()))[:12]}


# ----------------------------------------------------------------------------------------------- GDScript / Godot
GD_DIAG = re.compile(r"SCRIPT ERROR: (?:Parse Error|Compile Error): (.*?)\n\s*at: [^\n]*?res://main\.gd:(\d+)", re.S)
GD_TOP = re.compile(r"^(?:extends|class_name|func|var|const|signal|enum|@|static|class)\b", re.M)
GODOT3 = re.compile(r"Godot 3|Godot 3\.\d|\bonready var\b|\bexport\(|\byield\(|KinematicBody2D|\.instance\(\)")


def check_gdscript(code: str, context: str) -> dict:
    if re.search(r"\bGodot\s*3(?:\.\d+)?\b", context or ""):
        return {"checked": False, "tool": "godot", "mode": "godot3", "problems": [], "note": "Godot 3 answer"}
    src, offset = code.replace("\r", ""), 0
    fragment = not GD_TOP.search(src)
    if fragment:
        indent = "    " if re.search(r"^ +\S", src, re.M) else "\t"
        src, offset = wrap("extends Node\nfunc frag():\n", src, "\n", indent)
    no_extends = not re.search(r"^extends\b", src, re.M)
    if no_extends:
        src, offset = "extends Node\n" + src, offset + 1
    files = {"main.gd": src, "project.godot": 'config_version=5\n\n[application]\n\nconfig/name="check"\n'}
    with Workdir(files=files) as d:
        r = run_limited([GODOT, "--headless", "--path", d, "--check-only", "-s", "main.gd"], d, wall=20, mem_mb=None)
    if r["timed_out"]:
        return {"checked": False, "tool": "godot", "error": "timeout"}
    probs, seen = [], set()
    for m in GD_DIAG.finditer(r["stdout"] + "\n" + r["stderr"]):
        msg, line = m.group(1).strip(), int(m.group(2))
        if (msg, line) in seen:
            continue
        seen.add((msg, line))
        ident = re.search(r'(?:Identifier|type|Could not find type|function|Function) "([^"(]+)', msg)
        name = ident.group(1) if ident else None
        if name and (elsewhere(name, code, context) or (name[:1].isupper() and "not declared" in msg)):
            continue      # another script's class_name or an autoload singleton
        if (fragment or no_extends) and ("not found in base self" in msg or "not declared in the current scope" in msg
                                         or "not found in base" in msg):
            continue
        if re.search(r"Cannot assign a value of type .* as|to variable .* with specified type", msg) and \
                any(p["line"] == line - offset for p in probs):
            continue
        probs.append(problem("compile", "GDScript (Godot 4): " + msg, line, name=name))
    return {"checked": True, "tool": "godot " + os.path.basename(GODOT).split("_")[1],
            "mode": "fragment" if fragment else "file", "problems": shift(probs, offset, len(code.splitlines()))[:12]}


# ----------------------------------------------------------------------------------------------------------- Lua
def check_lua(code: str, context: str) -> dict:
    with Workdir(files={"main.lua": blank_ellipsis(code, "--")}) as d:
        r = run_limited(["luacheck", "--codes", "--formatter=plain", "--no-color", "--std=max+love", "main.lua"], d)
    probs = []
    for m in re.finditer(r"^main\.lua:(\d+):\d+: \(E(\d+)\) (.*)$", r["stdout"], re.M):
        probs.append(problem("syntax", "Lua: " + m.group(3), int(m.group(1))))
    return {"checked": True, "tool": "luacheck", "mode": "syntax", "problems": probs}


# ----------------------------------------------------------------------------------------------------------- SQL
SQL_OTHER = re.compile(r"\bSERIAL\b|AUTO_INCREMENT|\bILIKE\b|::\w|\$\d|\bDECLARE\b|\bTOP\s+\d|NVARCHAR\s*\(\s*MAX|"
                       r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:FUNCTION|PROCEDURE|TRIGGER)|ENGINE\s*=|\bIDENTITY\b|\bGO\s*$|"
                       r"\bDELIMITER\b|\bUNSIGNED\b|\bLIMIT\s+\d+\s*,|\bRETURNING\b.*\bINTO\b|\bMERGE\b|\bLATERAL\b|"
                       r"\bJSONB?\b|\bUUID\b|\bTIMESTAMPTZ\b|\bBIGSERIAL\b|\bSHOW\b|\bUSE\s+\w+|\bOUTPUT\b|`", re.I | re.M)
SQL_SCRIPT = r"""
import json, sqlite3, sys
src = sys.stdin.read()
db = sqlite3.connect(":memory:")
out, buf, line, start = [], "", 1, 1
for ln in src.splitlines(True):
    if not buf.strip():
        start = line
    buf += ln
    line += 1
    if sqlite3.complete_statement(buf):
        try:
            db.execute(buf)
        except sqlite3.Error as e:
            out.append([start, str(e)])
        buf = ""
if buf.strip():
    try:
        db.execute(buf)
    except sqlite3.Error as e:
        out.append([start, str(e)])
print(json.dumps(out))
"""


def check_sql(code: str, context: str) -> dict:
    if SQL_OTHER.search(code) or re.search(r"PostgreSQL|Postgres|MySQL|MariaDB|SQL Server|T-SQL|Oracle", context or "",
                                           re.I) and not re.search(r"SQLite", context or "", re.I):
        return {"checked": False, "tool": "sqlite", "mode": "other-dialect", "problems": []}
    src = re.sub(r"^\s*--[^\n]*$", "", code, flags=re.M)
    with Workdir() as d:
        r = run_limited(["python3", "-I", "-c", SQL_SCRIPT], d, wall=5, stdin=src.encode())
    try:
        rows = json.loads(r["stdout"] or "[]")
    except ValueError:
        return {"checked": False, "tool": "sqlite", "error": "timeout" if r["timed_out"] else r["stderr"][:200]}
    probs = [problem("syntax", "SQL: " + msg, line) for line, msg in rows
             if re.search(r"syntax error|incomplete input|unrecognized token", msg)]
    return {"checked": True, "tool": "sqlite 3.45", "mode": "syntax", "problems": probs}


# --------------------------------------------------------------------------------------------------------- shell
def check_shell(code: str, context: str) -> dict:
    src = re.sub(r"^\$ ", "", code, flags=re.M)
    probs = []
    with Workdir(files={"main.sh": src}) as d:
        r = run_limited(["bash", "-n", "main.sh"], d, wall=5)
        for m in re.finditer(r"main\.sh: line (\d+): (.*)$", r["stderr"], re.M):
            probs.append(problem("syntax", "bash: " + m.group(2), int(m.group(1))))
        if not probs:
            r = run_limited(["shellcheck", "-s", "bash", "-S", "error", "-f", "json1", "main.sh"], d, wall=5)
            try:
                for c in json.loads(r["stdout"] or "{}").get("comments", []):
                    probs.append(problem("syntax", f"shellcheck SC{c['code']}: {c['message']}", c.get("line")))
            except ValueError:
                pass
    return {"checked": True, "tool": "bash -n + shellcheck", "mode": "syntax", "problems": probs}


CHECKS = {
    "python": check_python,
    "javascript": lambda c, x: check_ts(c, x, "javascript"),
    "typescript": lambda c, x: check_ts(c, x, "typescript"),
    "csharp": check_csharp,
    "java": check_java,
    "cpp": lambda c, x: check_cpp(c, x, "cpp"),
    "c": lambda c, x: check_cpp(c, x, "c"),
    "rust": check_rust,
    "go": check_go,
    "gdscript": check_gdscript,
    "lua": check_lua,
    "sql": check_sql,
    "shell": check_shell,
}


def check(language: str, code: str, context: str = "") -> dict:
    t0 = time.perf_counter()
    fn = CHECKS.get(language)
    if fn is None or not code.strip():
        out = {"checked": False, "problems": []}
    else:
        with SEM:
            try:
                out = fn(code, context or "")
            except Exception as e:          # a checker bug must never become a reported problem
                out = {"checked": False, "problems": [], "error": f"{type(e).__name__}: {e}"[:300]}
    out.setdefault("problems", [])
    syn = [p for p in out["problems"] if p["kind"] == "syntax"]
    if len(syn) > 2:                         # one typo makes parsers report a cascade: the first ones are the cause
        out["problems"] = [p for p in out["problems"] if p["kind"] != "syntax" or p in syn[:2]]
    out["language"] = language
    out["ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out


# ---------------------------------------------------------------------------------------- test runs (eval harness)
CSC = (sorted(glob.glob(DOTNET + "/sdk/*/Roslyn/bincore/csc.dll")) or [""])[-1]
RUN_RECIPES = {
    "python": {"run": ["python3", "-I", "-B", "main.py"]},
    "javascript": {"run": [NODE, "main.js"]},
    "typescript": {"compile": [[NODE, PG + "/node/node_modules/typescript/bin/tsc", "--target", "es2022", "--module",
                                "commonjs", "--skipLibCheck", "--types", "node", "--typeRoots",
                                PG + "/node/node_modules/@types", "main.ts"]], "run": [NODE, "main.js"]},
    "cpp": {"compile": [["g++", "-std=gnu++20", "-O1", "-w", "main.cpp", "-o", "a.out"]], "run": ["./a.out"]},
    "c": {"compile": [["gcc", "-std=gnu17", "-O1", "-w", "main.c", "-lm", "-o", "a.out"]], "run": ["./a.out"]},
    "rust": {"compile": [[RUSTC, "--edition", "2021", "-A", "warnings", "-O", "-o", "a.out", "main.rs"]], "run": ["./a.out"]},
    "go": {"compile": [["go", "build", "-o", "a.out", "."]], "run": ["./a.out"]},
    "java": {"compile": [[JDK + "/javac", "-d", "out", "*.java"]], "run": [JDK + "/java", "-Xmx256m", "-cp", "out", "Main"]},
    "csharp": {"compile": [["dotnet", CSC, "-nologo", "-nullable:enable", "-warn:0", "-langversion:latest", "-out:main.dll",
                            "-r:REF/System.Runtime.dll", "-r:REF/System.Console.dll", "-r:REF/System.Collections.dll",
                            "-r:REF/System.Linq.dll", "-r:REF/System.Text.RegularExpressions.dll", "-r:REF/System.Runtime.Numerics.dll",
                            "-r:REF/System.Collections.Concurrent.dll", "-r:REF/netstandard.dll", "*.cs"]],
               "run": ["dotnet", "main.dll"]},
    "lua": {"run": ["lua5.4", "main.lua"]},
    "gdscript": {"run": [GODOT, "--headless", "--path", ".", "--script", "test.gd"]},
    "sql": {"run": ["python3", "-I", "test.py"]},
    "shell": {"run": ["bash", "main.sh"]},
}
RUN_EXTRA = {
    "go": {"go.mod": "module answer\n\ngo 1.22\n"},
    "gdscript": {"project.godot": 'config_version=5\n\n[application]\n\nconfig/name="run"\n'},
}
NO_AS = {"csharp", "java", "go", "gdscript", "javascript", "typescript", "rust"}


def run_job(job: dict) -> dict:
    lang = str(job.get("language", ""))
    res = {"ok": False, "steps": [], "stdout": "", "seconds": 0.0, "error": "", "phase": ""}
    recipe = RUN_RECIPES.get(lang)
    files = job.get("files") or {}
    if recipe is None or not isinstance(files, dict) or not files or len(files) > 12:
        res["error"] = "bad job"
        return res
    clean = {}
    for name, text in {**RUN_EXTRA.get(lang, {}), **files}.items():
        base = os.path.basename(str(name))
        if not base or base.startswith(".") or not isinstance(text, str) or len(text) > MAX_CODE:
            res["error"] = "bad file"
            return res
        clean[base] = text
    if lang == "csharp" and not any(n.endswith(".runtimeconfig.json") for n in clean):
        shared = sorted(glob.glob(DOTNET + "/shared/Microsoft.NETCore.App/*"))
        clean["main.runtimeconfig.json"] = json.dumps({"runtimeOptions": {"tfm": "net8.0", "framework": {
            "name": "Microsoft.NETCore.App", "version": os.path.basename(shared[-1]) if shared else "8.0.0"}}})
    run_s = max(1, min(30, int(job.get("run_s") or 10)))
    t0 = time.monotonic()
    with Workdir(uid=RUN_UID, files=clean) as d:
        ok = True
        for step in recipe.get("compile", []):
            step = [s.replace("REF", _dotnet_ref()) for s in step]
            if "*.java" in step or "*.cs" in step:
                star = step.index("*.java" if "*.java" in step else "*.cs")
                ext = step[star][1:]
                step = step[:star] + sorted(n for n in clean if n.endswith(ext)) + step[star + 1:]
            out = run_limited(step, d, wall=60, uid=RUN_UID, mem_mb=None if lang in NO_AS else 2048,
                              fsize=lang != "csharp")
            res["steps"].append(out)
            if out["rc"] != 0:
                ok, res["phase"] = False, "compile"
                break
        run_cmd = list(recipe["run"])
        if lang == "java" and re.fullmatch(r"[A-Za-z_]\w*", str(job.get("main_class") or "")):
            run_cmd[-1] = job["main_class"]
        inputs = job.get("inputs")
        if ok and isinstance(inputs, list) and inputs:          # compile once, run once per stdin
            res["runs"], res["phase"] = [], "run"
            for text in inputs[:20]:
                out = run_limited(run_cmd, d, wall=run_s, uid=RUN_UID, mem_mb=None if lang in NO_AS else 2048,
                                  fsize=lang != "csharp", stdin=str(text).encode())
                res["runs"].append({k: out[k] for k in ("rc", "stdout", "stderr", "timed_out", "seconds")})
            ok = all(r["rc"] == 0 and not r["timed_out"] for r in res["runs"])
        elif ok:
            out = run_limited(run_cmd, d, wall=run_s, uid=RUN_UID, mem_mb=None if lang in NO_AS else 2048,
                              fsize=lang != "csharp", stdin=str(job.get("stdin") or "").encode())
            res["steps"].append(out)
            res["stdout"], res["phase"] = out["stdout"], "run"
            ok = out["rc"] == 0 and not out["timed_out"]
        res["ok"] = ok
    res["seconds"] = round(time.monotonic() - t0, 2)
    return res


# ------------------------------------------------------------------------------------------------------- HTTP
def tools() -> dict:
    return {"rustc": os.path.isfile(RUSTC), "godot": os.path.basename(GODOT), "ruff": os.path.isfile(RUFF),
            "unity_index": len(unity_index()["now"]), "unity_index_2022": len(unity_index()["old"]),
}


def make_handler(token: str):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "star-polyglot/1"

        def log_message(self, fmt, *args):
            pass

        def _send(self, status, obj):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                return self._send(200, {"status": "ok", "tools": tools(),
                                        "workers": {k: w.alive() for k, w in WORKERS.items()}})
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            auth = self.headers.get("Authorization", "")
            if not token or auth != "Bearer " + token:
                return self._send(401, {"error": "bad token"})
            n = int(self.headers.get("Content-Length") or 0)
            if n > 2 * MAX_CODE + 65536:
                return self._send(413, {"error": "too large"})
            try:
                req = json.loads(self.rfile.read(n) or b"{}")
                assert isinstance(req, dict)
            except (ValueError, AssertionError):
                return self._send(400, {"error": "bad json"})
            if self.path == "/check":
                code = req.get("code")
                if not isinstance(code, str) or len(code) > MAX_CODE:
                    return self._send(400, {"error": "send {language, code}"})
                ctx = req.get("context") if isinstance(req.get("context"), str) else ""
                return self._send(200, check(str(req.get("language", "")), code, ctx[:2 * MAX_CODE]))
            if self.path == "/run":
                with RUN_LOCK:
                    return self._send(200, run_job(req))
            return self._send(404, {"error": "not found"})

    return Handler


def main() -> int:
    token = open(TOKEN_FILE, encoding="utf-8").read().strip() if os.path.isfile(TOKEN_FILE) else ""
    os.makedirs(WORK, exist_ok=True)
    unity_index()
    for w in WORKERS.values():           # warm them before the first request
        threading.Thread(target=lambda w=w: w.ask({"code": "x", "mode": "syntax", "lang": "ts", "tsx": False}),
                         daemon=True).start()
    warm_go = ('package main\nimport (\n"bufio"\n"encoding/json"\n"errors"\n"fmt"\n"math"\n"net/http"\n"os"\n"sort"\n'
               '"strconv"\n"strings"\n"sync"\n"time"\n)\nvar _ = []any{bufio.NewReader, json.Marshal, errors.New, math.Abs,'
               ' http.Get, os.Exit, sort.Ints, strconv.Itoa, strings.Split, time.Now, fmt.Println}\nvar _ sync.Mutex\n'
               'func main() {}\n')
    threading.Thread(target=lambda: (check("go", warm_go), check("gdscript", "extends Node\n"),
                                     check("cpp", "#include <iostream>\nint main(){}\n")), daemon=True).start()
    srv = ThreadingHTTPServer((os.environ.get("PG_LISTEN", "127.0.0.1"), int(os.environ.get("PG_PORT", "8110"))),
                              make_handler(token))
    srv.daemon_threads = True
    print("star-polyglot ready", tools(), flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
