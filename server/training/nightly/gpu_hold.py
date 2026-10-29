"""Borrow the owner-PC GPU from the Litha mesh node, run one command, give the card back.

Protocol (docs/agents/mesh-node-20261027.md, docs/agents/gpu-lab-schedule.md):
  1. the node must be idle or away (busy = the owner/STAR is using the card: refuse);
  2. append "HOLD <holder> <utc> planned end ..." to the schedule, POST /unload, wait until the VRAM is free;
  3. run the command at below-normal priority without a window; stop it when the deadline passes, the local
     clock reaches --until (default 07:45, the owner wakes at 08:00), the owner touches mouse/keyboard, a game or
     stream starts (the node turns busy) or the STOP file exists;
  4. always POST /load (retried: the node waits 180 s of free card after any other program) and append FREE.

usage: python -m training.nightly.gpu_hold --holder NAME --minutes N [--until HH:MM] -- command ...
exit: the command's code; 75 = refused (node busy / owner active / past --until), 124 = stopped early.
"""
from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

NODE = os.environ.get("STAR_NODE_URL", "http://127.0.0.1:8099")
TOKEN_FILE = Path(os.path.expanduser("~/.star/mesh_token"))
SOFT_BUSY = ("another program", "other programs", "the computer is busy", "only ")  # memory/load: our own use


def find_schedule() -> Path | None:
    """docs/agents/gpu-lab-schedule.md of the workspace above this file (or STAR_GPU_SCHEDULE)."""
    env = os.environ.get("STAR_GPU_SCHEDULE")
    if env:
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        cand = parent / "docs" / "agents" / "gpu-lab-schedule.md"
        if cand.exists():
            return cand
    return None
NO_WINDOW, BELOW_NORMAL = 0x08000000, 0x00004000
REFUSED, STOPPED = 75, 124
TURBO_OFF = Path(os.environ.get("STAR_TURBO_HOME", os.path.expanduser("~/.star/night-turbo"))) / "OFF"
TURBO_MARK = "paused by training.nightly.gpu_hold"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def idle_seconds() -> float:
    """Seconds since the last keyboard/mouse input on this PC (Windows); a large number elsewhere."""
    if os.name != "nt":
        return 1e9

    class LII(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    lii = LII(ctypes.sizeof(LII), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
        return 1e9
    return ((ctypes.windll.kernel32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF) / 1000.0


def minutes_until(hhmm: str, now: dt.datetime | None = None) -> float:
    """Minutes from now (local clock) to the next HH:MM; negative never (wraps to tomorrow)."""
    now = now or dt.datetime.now()
    h, m = (int(x) for x in hhmm.split(":"))
    end = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if end <= now:
        end += dt.timedelta(days=1)
    return (end - now).total_seconds() / 60


def in_window(now: dt.datetime | None = None, start: str = "00:00", end: str = "07:45") -> bool:
    """True when the local time is inside [start, end) (both HH:MM, start < end, same day)."""
    now = now or dt.datetime.now()
    t = now.hour * 60 + now.minute
    s = int(start[:2]) * 60 + int(start[3:])
    e = int(end[:2]) * 60 + int(end[3:])
    return s <= t < e


def node(path: str, body: dict | None = None, timeout: float = 30) -> tuple[int, dict]:
    tok = TOKEN_FILE.read_text(encoding="utf-8").split()[0] if TOKEN_FILE.exists() else ""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(NODE + path, data, {"Authorization": "Bearer " + tok,
                                                     "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:  # noqa: BLE001
            return e.code, {}
    except (OSError, ValueError) as e:
        return 0, {"error": str(e)}


def vram_used_mb() -> int:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW if os.name == "nt" else 0)
        return int(out.stdout.strip().split()[0])
    except Exception:  # noqa: BLE001
        return -1


def log_schedule(line: str) -> None:
    path = find_schedule()
    print(line, flush=True)
    if path is None:
        return
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def owner_active(min_idle: float) -> str:
    """'' when the card may stay borrowed, else why not."""
    if idle_seconds() < min_idle:
        return f"owner input {idle_seconds():.0f} s ago"
    code, st = node("/status", timeout=5)
    reason = str(st.get("reason", ""))
    if code == 200 and st.get("state") == "busy" and not reason.startswith(SOFT_BUSY):
        return "node busy: " + reason                       # a game/stream/VR/full-screen program, not our GPU use
    return ""


def acquire(holder: str, minutes: int, note: str, min_idle: float) -> str:
    """Unload the node; '' on success, else the refusal reason (nothing changed)."""
    why = owner_active(min_idle)
    if why:
        return why
    code, st = node("/status", timeout=5)
    if code != 200:
        return f"node status failed ({code} {st.get('error', '')})"
    if st.get("state") not in ("idle", "away"):
        return f"node {st.get('state')}: {st.get('reason')}"      # off = another lane switched it off: not ours
    other = open_hold(holder)
    if other:
        return "another lane holds the card: " + other
    log_schedule(f"HOLD {holder} {utc_now()} planned end +{minutes} min ({note})")
    pause_turbo()
    code, _ = node("/unload", {}, timeout=60)
    for _ in range(30):
        if 0 <= vram_used_mb() < 2500:
            return ""
        time.sleep(2)
    release(holder, "card not free after unload (someone else is on it)")
    return "card not free after unload"


def open_hold(holder: str, hours: float = 6) -> str:
    """The newest HOLD line of ANOTHER holder in the schedule without a later FREE from it (within `hours`)."""
    path = find_schedule()
    if path is None or not path.exists():
        return ""
    now = dt.datetime.now(dt.timezone.utc)
    open_: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) < 3 or parts[0] not in ("HOLD", "FREE") or parts[1] == holder:
            continue
        try:
            when = dt.datetime.strptime(parts[2][:17], "%Y-%m-%dT%H:%MZ").replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
        if parts[0] == "HOLD" and now - when < dt.timedelta(hours=hours):
            open_[parts[1]] = line[:120]
        elif parts[0] == "FREE":
            open_.pop(parts[1], None)
    return next(iter(open_.values()), "")


def pause_turbo() -> None:
    """Night turbo (server/night_school/pc/turbo.py) would grab the card the moment the node unloads: its OFF file
    pauses it. Only an OFF file we created is removed again."""
    if TURBO_OFF.parent.exists() and not TURBO_OFF.exists():
        TURBO_OFF.write_text(TURBO_MARK + "\n", encoding="utf-8")


def resume_turbo() -> None:
    try:
        if TURBO_OFF.read_text(encoding="utf-8").strip() == TURBO_MARK:
            TURBO_OFF.unlink()
    except OSError:
        pass


def release(holder: str, note: str = "") -> dict:
    """Reload the node (retry ~5 min: the node waits 180 s of free card), resume night turbo, log FREE."""
    st: dict = {}
    for _ in range(16):
        code, st = node("/load", {"model": "litha-fast", "wait": True}, timeout=200)
        if code == 200:
            break
        time.sleep(20)
    _, st = node("/status", timeout=10)
    resume_turbo()
    log_schedule(f"FREE {holder} {utc_now()} (node {st.get('state')} / {st.get('reason')}){' ' + note if note else ''}")
    return st


def run(cmd: list[str], holder: str, minutes: int, until: str, min_idle: float, note: str, stop_file: Path,
        log: str = "") -> int:
    budget = min(minutes, minutes_until(until))
    anytime = os.environ.get("STAR_HOLD_ANYTIME") == "1"      # owner idle in the day: short tests only
    if budget < 2 or not (anytime or in_window(start="00:00", end=until)):
        print(f"refused: outside the night window (until {until}, budget {budget:.0f} min)", flush=True)
        return REFUSED
    why = acquire(holder, int(budget), note, min_idle)
    if why:
        print("refused:", why, flush=True)
        return REFUSED
    deadline = time.time() + budget * 60
    rc, stopped = None, ""
    proc = None
    try:
        flags = NO_WINDOW | BELOW_NORMAL if os.name == "nt" else 0
        out = open(log, "a", encoding="utf-8") if log else None     # a windowless child loses inherited handles
        proc = subprocess.Popen(cmd, creationflags=flags, stdout=out, stderr=subprocess.STDOUT if out else None,
                                stdin=subprocess.DEVNULL)
        while rc is None:
            time.sleep(5)
            rc = proc.poll()
            if rc is not None:
                break
            if time.time() > deadline:
                stopped = "deadline"
            elif stop_file.exists():
                stopped = "STOP file"
            else:
                stopped = owner_active(min_idle)
            if stopped:
                print("stopping:", stopped, flush=True)
                (stop_file.parent / "STOP-SOFT").write_text(stopped, encoding="utf-8")  # trainer saves and exits
                for _ in range(24):
                    if proc.poll() is not None:
                        break
                    time.sleep(5)
                if proc.poll() is None:
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True) \
                        if os.name == "nt" else proc.kill()
                rc = STOPPED
    finally:
        if proc and proc.poll() is None:
            proc.kill()
        (stop_file.parent / "STOP-SOFT").unlink(missing_ok=True)
        st = release(holder, f"rc {rc}{' stopped: ' + stopped if stopped else ''}")
        print("node:", st.get("state"), st.get("reason"), flush=True)
    return int(rc)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" not in argv:
        print(__doc__)
        return 2
    i = argv.index("--")
    ap = argparse.ArgumentParser()
    ap.add_argument("--holder", required=True)
    ap.add_argument("--minutes", type=int, required=True)
    ap.add_argument("--until", default="07:45", help="local HH:MM by which the card is given back")
    ap.add_argument("--min-idle", type=float, default=120, help="owner counts as active below this many idle seconds")
    ap.add_argument("--note", default="nightly training")
    ap.add_argument("--log", default="", help="file for the command's output")
    ap.add_argument("--stop-file", default=str(Path.home() / ".star" / "nightly" / "STOP"))
    a = ap.parse_args(argv[:i])
    stop = Path(a.stop_file)
    stop.parent.mkdir(parents=True, exist_ok=True)
    return run(argv[i + 1:], a.holder, a.minutes, a.until, a.min_idle, a.note, stop, a.log)


if __name__ == "__main__":
    sys.exit(main())
