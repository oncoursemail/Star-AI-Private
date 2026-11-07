"""Static checks for a submitted Luau snippet: compile it, then type-analyse and lint it.

The snippet is NEVER executed. Two official Luau CLI tools are run on it:

  luau-compile --null snippet.luau     parse + compile to bytecode, discard the result
  luau-analyze snippet.luau            type checker and linter

Safety rules, all enforced here:
  * the code is written to a file in a fresh private directory and the tools get that file
    name as an argv element; no shell is involved and nothing from the request reaches a
    command line;
  * the child process has a wall-clock timeout, a CPU-time limit, an address-space limit, a
    file-size limit, no core dumps, an empty environment and its own session (so it can be
    killed as a group);
  * tool output goes to a size-limited file, only diagnostics for the submitted file are
    returned, and messages are length-capped.

Roblox globals (`game`, `workspace`, `Instance`, `Vector3`, ...) are declared to the analyzer
through a `.luaurc` next to the snippet as values of type `any`. That removes "unknown global"
noise, but it also means Roblox API names and argument types are NOT verified here: the result
says so in `roblox_api_types: false`. Use /api-lookup for names.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time

MAX_CODE_BYTES = 64 * 1024
TIMEOUT_SECONDS = 10.0
MEMORY_BYTES = 1024 * 1024 * 1024
OUTPUT_BYTES = 256 * 1024
MAX_DIAGNOSTICS = 40
MAX_MESSAGE = 300
TOOLS_DIR = Path(os.environ.get("STAR_LUAU_TOOLS", "/opt/star/knowledge/tools"))
FILE_NAME = "snippet.luau"

# Globals Roblox adds to Luau (engine singletons, data type constructors, libraries).
ROBLOX_GLOBALS = (
    "game", "workspace", "script", "plugin", "shared", "Enum", "Instance", "task", "tick", "time", "wait",
    "delay", "spawn", "warn", "elapsedTime", "settings", "UserSettings", "version", "printidentity",
    "DebuggerManager", "PluginManager", "stats",
    "Axes", "BrickColor", "CatalogSearchParams", "CFrame", "Color3", "ColorSequence", "ColorSequenceKeypoint",
    "Content", "DateTime", "DockWidgetPluginGuiInfo", "Faces", "FloatCurveKey", "Font", "NumberRange",
    "NumberSequence", "NumberSequenceKeypoint", "OverlapParams", "Path2DControlPoint", "PathWaypoint",
    "PhysicalProperties", "Random", "Ray", "RaycastParams", "Rect", "Region3", "Region3int16",
    "RotationCurveKey", "Secret", "SharedTable", "TweenInfo", "UDim", "UDim2", "ValueCurveKey", "Vector2",
    "Vector2int16", "Vector3", "Vector3int16",
)
_DIAGNOSTIC = re.compile(r"^(?:\./)?" + re.escape(FILE_NAME) + r"\((\d+),(\d+)\): ([A-Za-z]+): (.*)$")
_ERROR_KINDS = frozenset({"SyntaxError", "TypeError"})
_UNCHECKABLE = ("Unknown require",)   # module paths cannot be resolved for an isolated snippet
# `player: Player`, `part: BasePart`, `key: Enum.KeyCode`: the standalone checker has no Roblox type
# definitions, so it reports every engine type used in an annotation as unknown.
_UNKNOWN_TYPE = re.compile(r"^Unknown type '([A-Za-z_][A-Za-z0-9_]{0,63}(?:\.[A-Za-z_][A-Za-z0-9_]{0,63})?)'")


def tool_paths(tools_dir: Path = TOOLS_DIR) -> dict[str, Path]:
    return {"compile": tools_dir / "luau-compile", "analyze": tools_dir / "luau-analyze"}


def available(tools_dir: Path = TOOLS_DIR) -> bool:
    return (shutil.which("prlimit") is not None
            and all(path.is_file() and os.access(path, os.X_OK) for path in tool_paths(tools_dir).values()))


def tool_version(tools_dir: Path = TOOLS_DIR) -> str:
    """The Luau source revision recorded by the install script (a file, never a command)."""
    stamp = tools_dir / "VERSION"
    try:
        return stamp.read_text(encoding="utf-8").strip()[:120]
    except OSError:
        return "unknown"


def limited(argv: list[str], cpu_seconds: int, memory_bytes: int) -> list[str]:
    """argv under util-linux prlimit. Not preexec_fn: Python code between fork and exec can deadlock in a threaded
    server (the HTTP service is one), as the Python docs warn; luaurun.py avoids it the same way."""
    return [shutil.which("prlimit") or "prlimit", f"--cpu={cpu_seconds}", f"--as={memory_bytes}",
            f"--fsize={OUTPUT_BYTES}", "--core=0", "--nofile=64", "--", *argv]


def _run(argv: list[str], cwd: Path, *, timeout: float, memory_bytes: int) -> tuple[int | None, str, bool]:
    """Run one tool. Returns (exit code or None, combined output, timed_out)."""
    out_path = cwd / ("out-" + Path(argv[0]).name + ".txt")
    timed_out = False
    with open(out_path, "wb") as sink:
        proc = subprocess.Popen(
            limited(argv, int(timeout) + 1, memory_bytes), cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=sink,
            stderr=subprocess.STDOUT, env={"LANG": "C.UTF-8"}, close_fds=True, start_new_session=True, shell=False)
        try:
            code: int | None = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
            proc.wait(timeout=5)
            code = None
    with open(out_path, "rb") as source:
        text = source.read(OUTPUT_BYTES).decode("utf-8", errors="replace")
    return code, text, timed_out


def _parse(text: str) -> list[dict]:
    found = []
    for line in text.splitlines():
        match = _DIAGNOSTIC.match(line.strip())
        if match:
            found.append({"line": int(match.group(1)), "column": int(match.group(2)),
                          "kind": match.group(3), "message": match.group(4)[:MAX_MESSAGE]})
    return found


_TYPE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}(?:\.[A-Za-z_][A-Za-z0-9_]{0,63})?")


def is_engine_type(db, name) -> bool:
    """`Player`, `BasePart`, `Vector3`, `Enum.KeyCode`: a class, data type or enum in the indexed
    engine reference (`db` is the knowledge index). The standalone type checker knows none of them."""
    if not isinstance(name, str) or not _TYPE_NAME.fullmatch(name):
        return False
    return db.execute("SELECT 1 FROM chunks WHERE heading=? AND kind IN ('api-overview','enum') LIMIT 1",
                      (name,)).fetchone() is not None


def classify(diagnostics: list[dict], known_type=None) -> tuple[list[dict], list[dict], int, list[str]]:
    """Split analyzer diagnostics into (errors, warnings, unresolved requires, engine type names).

    An "Unknown type 'X'" error is not an error in the code when X is a class, data type or enum
    of the Roblox engine (`known_type(X)` is True): correct, idiomatic typed Luau would otherwise
    always fail this check. Such names are returned so the reply can say they were not verified.
    An unknown type that the engine does not have (`strng`) stays an error.
    """
    errors: list[dict] = []
    warnings: list[dict] = []
    engine_types: list[str] = []
    unresolved = 0
    for item in diagnostics:
        if item["kind"] not in _ERROR_KINDS:
            warnings.append(item)
            continue
        named = _UNKNOWN_TYPE.match(item["message"])
        if any(item["message"].startswith(prefix) for prefix in _UNCHECKABLE):
            unresolved += 1
        elif named and known_type is not None and known_type(named.group(1)):
            if named.group(1) not in engine_types:
                engine_types.append(named.group(1))
        else:
            errors.append(item)
    return errors, warnings, unresolved, engine_types


def check(code: str, *, mode: str | None = None, tools_dir: Path = TOOLS_DIR,
          timeout: float = TIMEOUT_SECONDS, memory_bytes: int = MEMORY_BYTES, known_type=None) -> dict:
    """Compile and analyse `code`. Raises ValueError for unusable input, RuntimeError when the
    tools are missing. The returned `ok` is True only when both tools ran to completion and
    reported no syntax or type error. `known_type(name) -> bool` says whether a type name is a
    Roblox engine type (see `classify`)."""
    if not isinstance(code, str) or not code.strip():
        raise ValueError("code must be non-empty text")
    raw = code.encode("utf-8")
    if len(raw) > MAX_CODE_BYTES:
        raise ValueError(f"code must be at most {MAX_CODE_BYTES} bytes")
    if "\x00" in code:
        raise ValueError("code must not contain NUL characters")
    if mode not in (None, "strict", "nonstrict"):
        raise ValueError("mode must be strict or nonstrict")
    tools = tool_paths(tools_dir)
    if not available(tools_dir):
        raise RuntimeError("Luau tools are not installed")
    started = time.perf_counter()
    workdir = Path(tempfile.mkdtemp(prefix="starkb-luau-"))
    try:
        (workdir / FILE_NAME).write_bytes(raw)
        (workdir / ".luaurc").write_text(json.dumps({"globals": list(ROBLOX_GLOBALS)}), encoding="utf-8")
        timing: dict[str, float] = {}
        t = time.perf_counter()
        compile_code, compile_out, compile_timeout = _run(
            [str(tools["compile"]), "--null", FILE_NAME], workdir, timeout=timeout, memory_bytes=memory_bytes)
        timing["compile_ms"] = (time.perf_counter() - t) * 1000
        syntax = [d for d in _parse(compile_out) if d["kind"] == "SyntaxError"]
        compiled = compile_code == 0 and not syntax and not compile_timeout
        analyzed = False
        analyze_timeout = False
        errors: list[dict] = list(syntax)
        warnings: list[dict] = []
        engine_types: list[str] = []
        notes: list[str] = []
        if compile_timeout:
            notes.append("The compiler hit the time limit; nothing was verified.")
        elif compile_code not in (0, 1) and not syntax:
            notes.append("The compiler stopped unexpectedly (resource limit); nothing was verified.")
        if compiled:
            argv = [str(tools["analyze"])] + (["--mode=" + mode] if mode else []) + [FILE_NAME]
            t = time.perf_counter()
            analyze_code, analyze_out, analyze_timeout = _run(argv, workdir, timeout=timeout,
                                                              memory_bytes=memory_bytes)
            timing["analyze_ms"] = (time.perf_counter() - t) * 1000
            analyzed = analyze_code in (0, 1) and not analyze_timeout
            if analyze_timeout:
                notes.append("The type checker hit the time limit; types were not verified.")
            elif not analyzed:
                notes.append("The type checker stopped unexpectedly (resource limit); types were not verified.")
            type_errors, warnings, unresolved, engine_types = classify(_parse(analyze_out), known_type)
            errors.extend(type_errors)
            if engine_types:
                notes.append("Roblox engine type name(s) used in annotations (" + ", ".join(engine_types[:8])
                             + ") are not known to the standalone Luau type checker; values of those "
                               "types were not verified.")
            if unresolved:
                notes.append(f"{unresolved} require() call(s) could not be resolved for an isolated snippet; "
                             "the required modules were not checked.")
        errors.sort(key=lambda d: (d["line"], d["column"]))
        warnings.sort(key=lambda d: (d["line"], d["column"]))
        timing["total_ms"] = (time.perf_counter() - started) * 1000
        return {
            "ok": compiled and analyzed and not errors,
            "executed": False,
            "compiled": compiled,
            "analyzed": analyzed,
            "errors": errors[:MAX_DIAGNOSTICS],
            "warnings": warnings[:MAX_DIAGNOSTICS],
            "error_count": len(errors),
            "warning_count": len(warnings),
            "notes": notes,
            "mode": mode or "file default (nonstrict unless the code says --!strict)",
            "roblox_api_types": False,
            "unverified_engine_types": engine_types[:20],
            "scope": "Syntax, Luau types and lints. Roblox globals are treated as type any, so Roblox API "
                     "names and argument types are not verified. The code was not run.",
            "tools": {"luau": tool_version(tools_dir)},
            "timing_ms": {k: round(v, 1) for k, v in timing.items()},
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
