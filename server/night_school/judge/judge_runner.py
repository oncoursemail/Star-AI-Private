#!/usr/bin/env python3
"""The judge: runs untrusted code + tests inside the `star-judge` LXD container (no network device, CPU/RAM/process
limits), as the unprivileged user `sandbox`, in a tmpfs work folder, under `timeout` and `prlimit`.

Interface (narrow, file based): a shared folder (host /data/star-re/star-judge/queue, mounted in the brain container at /opt/star/learning/judge
and in the judge at /judge/queue). A client drops `<id>.job.json`:
  {"id": "...", "language": "python", "files": {"main.py": "..."}, "run_s": 10}
The runner renames it to `<id>.running.json` (its claim), writes the files to /work/<id>/, runs the language recipe
(compile step(s), then the run step) and writes `<id>.result.json` (atomically: .tmp then rename):
  {"id": ..., "ok": bool, "steps": [{"cmd": [...], "rc": int, "stdout": str, "stderr": str, "seconds": float,
   "timed_out": bool}], "stdout": str (of the last step), "seconds": float, "error": str}
Nothing but these JSON files crosses the boundary. The runner never reads the brain's data. Stdlib only.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import time

QUEUE = os.environ.get("JUDGE_QUEUE", "/judge/queue")
WORK = os.environ.get("JUDGE_WORK", "/work")
SANDBOX_UID = int(os.environ.get("JUDGE_UID", "1001"))
OUT_CAP = 64 * 1024
MAX_FILES, MAX_FILE_BYTES = 12, 200 * 1024
COMPILE_S, RUN_S_DEFAULT, RUN_S_MAX = 90, 10, 60
MEM_MB = int(os.environ.get("JUDGE_MEM_MB", "4096"))     # address-space cap per run (the container caps real RAM)
NPROC = 96
NO_ADDRESS_CAP = {"csharp", "java", "go"}     # runtimes that reserve a huge address space; the container RAM cap holds them
NO_FSIZE_CAP = {"csharp"}                      # dotnet dies with SIGXFSZ under any fsize limit (the 2 GB tmpfs bounds it)

JDK = "/opt/jdk/bin"          # a copy of /data/star-re/tools/jdk-21 (that mount is read-only and not world-executable)
DOTNET = "/usr/lib/dotnet"
GODOT = "/opt/godot/godot"


def _dotnet_paths() -> tuple[str, str, str]:
    sdk = sorted(glob.glob(DOTNET + "/sdk/*/Roslyn/bincore/csc.dll"))
    ref = sorted(glob.glob(DOTNET + "/packs/Microsoft.NETCore.App.Ref/*/ref/net8.0"))
    shared = sorted(glob.glob(DOTNET + "/shared/Microsoft.NETCore.App/*"))
    return (sdk[-1] if sdk else "", ref[-1] if ref else "", os.path.basename(shared[-1]) if shared else "")


CSC, CS_REF, CS_RUNTIME = _dotnet_paths()

# language -> (compile steps, run step). "{d}" = the work folder. Every file name is fixed by the recipe so the client
# cannot pick paths; the client's `files` are written only inside the work folder (base names only).
RECIPES: dict[str, dict] = {
    "python": {"run": ["python3", "-I", "-B", "main.py"]},
    "javascript": {"run": ["node", "main.js"]},
    "ts2js": {"compile": [["tsc", "--strict", "--target", "es2020", "--module", "commonjs", "--lib", "es2020,dom",
                           "--skipLibCheck", "main.ts"]], "run": ["cat", "main.js"]},   # the generator derives JS references
    "typescript": {"compile": [["tsc", "--strict", "--target", "es2020", "--module", "commonjs", "--lib", "es2020,dom",
                                "--skipLibCheck", "main.ts"]], "run": ["node", "main.js"]},
    "c": {"compile": [["gcc", "-std=c11", "-O1", "-Wall", "main.c", "-lm", "-o", "a.out"]], "run": ["./a.out"]},
    "cpp": {"compile": [["g++", "-std=c++17", "-O1", "-Wall", "main.cpp", "-o", "a.out"]], "run": ["./a.out"]},
    "csharp": {"compile": [["dotnet", CSC, "-nologo", "-nostdlib", "-nullable:enable", "-warn:0", "-out:main.dll",
                            "-r:" + CS_REF + "/System.Runtime.dll", "-r:" + CS_REF + "/System.Console.dll",
                            "-r:" + CS_REF + "/System.Collections.dll", "-r:" + CS_REF + "/System.Linq.dll",
                            "-r:" + CS_REF + "/System.Text.RegularExpressions.dll",
                            "-r:" + CS_REF + "/System.Runtime.Numerics.dll", "-r:" + CS_REF + "/netstandard.dll", "main.cs"]],
               "run": ["dotnet", "main.dll"]},
    "java": {"compile": [[JDK + "/javac", "-d", "out", "Main.java", "Solution.java"]],
             "run": [JDK + "/java", "-Xmx256m", "-XX:+UseSerialGC", "-XX:TieredStopAtLevel=1", "-cp", "out", "Main"]},
    "go": {"compile": [["go", "build", "-o", "a.out", "."]], "run": ["./a.out"]},
    "rust": {"compile": [["rustc", "--edition", "2021", "-A", "warnings", "-o", "a.out", "main.rs"]], "run": ["./a.out"]},
    "lua": {"run": ["lua5.4", "main.lua"]},
    "gdscript": {"run": [GODOT, "--headless", "--path", ".", "--script", "test.gd"]},
    "glsl": {"run": ["sh", "-c", "glslangValidator shader.* || { cat -A shader.*; exit 1; }"]},   # shader.frag | shader.vert | shader.comp
    "hlsl": {"run": ["glslangValidator", "-D", "-e", "main", "-S", "frag", "-V", "-o", "out.spv", "shader.hlsl"]},
}
EXTRA_FILES = {
    "csharp": {"main.runtimeconfig.json": json.dumps({"runtimeOptions": {"tfm": "net8.0", "framework": {
        "name": "Microsoft.NETCore.App", "version": CS_RUNTIME}}})},
    "go": {"go.mod": "module judge\n\ngo 1.22\n"},
    "gdscript": {"project.godot": "config_version=5\n\n[application]\n\nconfig/name=\"judge\"\n"},
}


def limited(cmd: list[str], cwd: str, wall: int, language: str = "") -> list[str]:
    env = ["HOME=" + cwd, "TMPDIR=" + cwd + "/.tmp", "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8",
           "GOCACHE=" + cwd + "/.gocache", "GOPATH=" + cwd + "/.gopath", "GOFLAGS=-mod=mod", "GOPROXY=off", "GOTOOLCHAIN=local",
           "DOTNET_CLI_HOME=" + cwd, "DOTNET_CLI_TELEMETRY_OPTOUT=1", "DOTNET_NOLOGO=1", "DOTNET_GCHeapHardLimit=0x20000000",
           "NODE_OPTIONS=--max-old-space-size=512", "PYTHONDONTWRITEBYTECODE=1", "PYTHONHASHSEED=0",
           "XDG_DATA_HOME=" + cwd + "/.local/share", "XDG_CONFIG_HOME=" + cwd + "/.config", "XDG_CACHE_HOME=" + cwd + "/.cache"]
    return (["timeout", "-k", "2", "-s", "KILL", str(wall),
             "prlimit", f"--nproc={NPROC}", *([] if language in NO_ADDRESS_CAP else [f"--as={MEM_MB * 1024 * 1024}"]),
             *([] if language in NO_FSIZE_CAP else ["--fsize=268435456"]), "--nofile=256",
             f"--cpu={wall}", "--core=0",
             "setpriv", f"--reuid={SANDBOX_UID}", f"--regid={SANDBOX_UID}", "--clear-groups", "--reset-env",
             "env", "-i", *env] + cmd)


def run_step(cmd: list[str], cwd: str, wall: int, language: str = "") -> dict:
    started = time.monotonic()
    try:
        done = subprocess.run(limited(cmd, cwd, wall, language), cwd=cwd, capture_output=True, timeout=wall + 15)
        rc, out, err = done.returncode, done.stdout, done.stderr
    except subprocess.TimeoutExpired:
        rc, out, err = 137, b"", b"runner: hard timeout"
    seconds = round(time.monotonic() - started, 2)
    return {"cmd": cmd[:4], "rc": rc, "stdout": out[:OUT_CAP].decode("utf-8", "replace"),
            "stderr": err[:OUT_CAP].decode("utf-8", "replace"), "seconds": seconds,
            "timed_out": rc in (124, 137) or seconds >= wall}


def run_job(job: dict) -> dict:
    job_id = str(job.get("id", ""))
    language = str(job.get("language", ""))
    result = {"id": job_id, "ok": False, "steps": [], "stdout": "", "seconds": 0.0, "error": ""}
    recipe = RECIPES.get(language)
    if recipe is None:
        result["error"] = "unknown language " + language[:30]
        return result
    files = job.get("files") or {}
    if not isinstance(files, dict) or not files or len(files) > MAX_FILES:
        result["error"] = "bad files"
        return result
    run_s = max(1, min(RUN_S_MAX, int(job.get("run_s") or RUN_S_DEFAULT)))
    cwd = os.path.join(WORK, "j-" + "".join(c for c in job_id if c.isalnum() or c in "-_")[:60])
    shutil.rmtree(cwd, ignore_errors=True)
    os.makedirs(cwd, mode=0o700)
    for name, text in {**EXTRA_FILES.get(language, {}), **files}.items():
        base = os.path.basename(str(name))
        if not base or base.startswith(".") or not isinstance(text, str) or len(text) > MAX_FILE_BYTES:
            result["error"] = "bad file " + base[:40]
            shutil.rmtree(cwd, ignore_errors=True)
            return result
        with open(os.path.join(cwd, base), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    os.makedirs(os.path.join(cwd, "out"), exist_ok=True)
    os.makedirs(os.path.join(cwd, ".tmp"), exist_ok=True)
    for root, dirs, names in os.walk(cwd):
        os.chown(root, SANDBOX_UID, SANDBOX_UID)
        for n in names:
            os.chown(os.path.join(root, n), SANDBOX_UID, SANDBOX_UID)
    started = time.monotonic()
    ok = True
    for step in recipe.get("compile", []):
        outcome = run_step(step, cwd, COMPILE_S, language)
        result["steps"].append(outcome)
        if outcome["rc"] != 0:
            ok = False
            result["phase"] = "compile"
            break
    if ok:
        outcome = run_step(recipe["run"], cwd, run_s, language)
        result["steps"].append(outcome)
        result["stdout"] = outcome["stdout"]
        ok = outcome["rc"] == 0 and not outcome["timed_out"]
        result["phase"] = "run"
    result["ok"] = ok
    result["seconds"] = round(time.monotonic() - started, 2)
    subprocess.run(["pkill", "-KILL", "-u", str(SANDBOX_UID)], capture_output=True)   # nothing survives a job
    shutil.rmtree(cwd, ignore_errors=True)
    return result


def write_result(path: str, result: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(result, handle)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def main() -> int:
    os.makedirs(WORK, exist_ok=True)
    for stale in glob.glob(os.path.join(QUEUE, "*.running.json")):      # a job cut short by a restart: report it
        job_id = os.path.basename(stale)[: -len(".running.json")]
        write_result(os.path.join(QUEUE, job_id + ".result.json"),
                     {"id": job_id, "ok": False, "steps": [], "stdout": "", "seconds": 0, "error": "runner restarted"})
        os.remove(stale)
    print("judge runner ready", {k: bool(v) for k, v in (("csc", CSC), ("ref", CS_REF), ("runtime", CS_RUNTIME))}, flush=True)
    while True:
        jobs = sorted(glob.glob(os.path.join(QUEUE, "*.job.json")), key=os.path.getmtime)
        if not jobs:
            time.sleep(0.2)
            continue
        for path in jobs[:1]:
            job_id = os.path.basename(path)[: -len(".job.json")]
            running = os.path.join(QUEUE, job_id + ".running.json")
            try:
                os.rename(path, running)
                with open(running, encoding="utf-8") as handle:
                    job = json.load(handle)
                if not isinstance(job, dict):
                    raise ValueError("job is not an object")
                job["id"] = job_id
                result = run_job(job)
            except (OSError, ValueError) as exc:
                result = {"id": job_id, "ok": False, "steps": [], "stdout": "", "seconds": 0,
                          "error": "bad job: " + type(exc).__name__}
            write_result(os.path.join(QUEUE, job_id + ".result.json"), result)
            try:
                os.remove(running)
            except OSError:
                pass
            print(time.strftime("%H:%M:%S"), job_id, job.get("language") if isinstance(job, dict) else "?",
                  "ok" if result["ok"] else "FAIL", result["seconds"], result.get("error", ""), flush=True)


if __name__ == "__main__":
    sys.exit(main())
