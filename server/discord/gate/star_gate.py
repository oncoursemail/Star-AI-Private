#!/usr/bin/env python3
"""STAR's Discord bot gate: the ONLY things the bot may read or do on a brain container, as a fixed allow-list.

Runs as root inside a brain's LXD container (standard library only, Python 3.10+). Two ways in, both installed by
`server/discord/deploy.sh gate`:

* brain 1 (another machine): the bot's own SSH key is in the LXD host user's authorized_keys with
  `restrict,command="~/.local/bin/star-bot-gate"`; that wrapper runs `lxc exec starai -- python3 star_gate.py
  "$SSH_ORIGINAL_COMMAND"`, so the key can do nothing but name a verb below.
* brain 2 (the bot's own container): systemd socket star-discord-gate.socket (a Unix socket only the star-discord
  user can open) starts `star_gate.py --socket` per connection; the first line is the verb.

A verb's extra text (a practice idea) comes on stdin, at most 2000 bytes. Every answer is one JSON object on stdout,
except the two legacy `cat` commands of star/discord_bot/digest_task.py, which print the file as before.

Verbs: facts | ns-start | ns-stop | ns-pause | ns-resume | idea | knowledge-eval | studio-lab-run | restart:<unit>
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys

ROOT = Path(os.environ.get("STAR_GATE_ROOT", "/"))           # tests point this at a temporary folder
LEARNING = "opt/star/learning"
KNOWLEDGE = "opt/star/knowledge"
STUDIO_LAB = "opt/star/studio-lab"
LEGACY = {
    "lxc exec starai -- cat /opt/star/learning/report/latest.md": "opt/star/learning/report/latest.md",
    "lxc exec starai -- cat /opt/star/knowledge/data/watchdog.json": "opt/star/knowledge/data/watchdog.json",
}
RESTARTABLE = ("star-brain", "star-knowledge", "star-search-gateway", "star-night-school", "star-ns-brain",
               "star-discord", "searxng")
HOURS = 36                      # hourly practice buckets kept in `facts` (enough for "today" in any zone)
TAIL_BYTES = 4_000_000
MAX_IDEA = 2000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp: str) -> datetime | None:
    try:
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _run(args: list[str], timeout: float = 20) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, check=False)


def _tail_lines(path: Path, limit: int = TAIL_BYTES) -> list[str]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - limit))
            data = handle.read()
    except OSError:
        return []
    lines = data.decode("utf-8", "replace").splitlines()
    return lines[1:] if size > limit else lines      # the first line of a cut tail is partial


def _read_json(path: Path, limit: int = 64_000):
    try:
        if path.stat().st_size > limit:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _number(text: str, pattern: str):
    match = re.search(pattern, text, re.M)
    return int(match.group(1)) if match else None


# ------------------------------------------------------------------------------------------------ facts

def services(run=_run) -> list[dict]:
    listed = run(["systemctl", "list-units", "--all", "--plain", "--no-legend", "--type=service,timer",
                  "star-*", "searxng*"])
    names = sorted({line.split()[0] for line in listed.stdout.splitlines() if line.strip()})
    if not names:
        return []
    shown = run(["systemctl", "show", "--timestamp=unix", "-p", "Id,ActiveState,SubState,ActiveEnterTimestamp,"
                 "NRestarts,Result", *names])
    rows, row = [], {}
    for line in shown.stdout.splitlines() + [""]:
        if not line.strip():
            if row.get("Id"):
                since = row.get("ActiveEnterTimestamp", "").lstrip("@")
                rows.append({"unit": row["Id"], "active": row.get("ActiveState", ""), "sub": row.get("SubState", ""),
                             "since": _stamp(datetime.fromtimestamp(int(since), timezone.utc))
                             if since.isdigit() and int(since) > 0 else "",
                             "restarts": int(row["NRestarts"]) if row.get("NRestarts", "").isdigit() else 0,
                             "result": row.get("Result", "")})
            row = {}
            continue
        key, _, value = line.partition("=")
        row[key] = value
    return rows


def night_school(root: Path, now: datetime) -> dict | None:
    home = root / LEARNING
    if not (home / "data").is_dir():
        return None
    out: dict = {"paused": (home / "data" / "HOLD").exists()}
    try:
        report = (home / "report" / "latest.md").read_text(encoding="utf-8", errors="replace")[:64_000]
    except OSError:
        report = ""
    written = re.search(r"^written (\S+Z)", report, re.M)
    status = re.search(r"^status: (.{1,120})$", report, re.M)
    speed = re.search(r"^speed: .*?= ([0-9.]+) answers per active hour", report, re.M)
    out["report"] = {
        "written": written.group(1) if written else "",
        "status": status.group(1).strip() if status else "",
        "attempts_total": _number(report, r"^task attempts: (\d+)"),
        "passed_first_total": _number(report, r"^passed first time: (\d+)"),
        "fixed_by_lesson_total": _number(report, r"^fixed by a lesson: (\d+)"),
        "examples_total": _number(report, r"^verified worked examples stored: (\d+)"),
        "lessons_active_total": _number(report, r"^promoted to active: (\d+)"),
        "lessons_candidate_total": _number(report, r"kept as candidate \(fixed its task\): (\d+)"),
        "answers_per_active_hour": float(speed.group(1)) if speed else None,
    }
    since = now - timedelta(hours=HOURS)
    hours: dict[str, Counter] = defaultdict(Counter)
    for line in _tail_lines(home / "data" / "attempts.jsonl"):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        moment = _parse(row.get("ts", ""))
        if moment is None or moment < since:
            continue
        bucket = hours[row["ts"][:13]]
        kind = str(row.get("purpose", "")).split(" ")[0]
        kind = {"new": "lesson", "candidate": "lesson"}.get(kind, kind)
        if row.get("error"):
            bucket["error"] += 1
        elif kind in {"first", "lesson", "validation"}:
            bucket[kind] += 1
            if row.get("passed") is True:
                bucket[kind + "_pass"] += 1
    gates = []
    for line in _tail_lines(home / "data" / "events.jsonl", 1_500_000):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        moment = _parse(row.get("ts", ""))
        if moment is None or moment < since:
            continue
        event = str(row.get("event", ""))
        if event == "lesson discarded":
            hours[row["ts"][:13]]["discarded"] += 1
            continue
        lesson = row.get("lesson") if isinstance(row.get("lesson"), dict) else {}
        gates.append({"ts": row["ts"], "event": event[:60], "lesson": str(lesson.get("id", ""))[:12],
                      "text": " ".join(str(lesson.get("text", "")).split())[:160]})
    out["hours"] = {key: dict(value) for key, value in sorted(hours.items())}
    out["gates"] = gates[-12:]
    return out


def conductor(root: Path) -> dict | None:
    folder = root / LEARNING / "conductor"
    reports = sorted(folder.glob("report-2*.md")) if folder.is_dir() else []
    if not reports:
        return None
    text = reports[-1].read_text(encoding="utf-8", errors="replace")[:32_000]
    written = re.search(r"^written (\S+Z)", text, re.M)
    return {"night": reports[-1].stem.removeprefix("report-"), "written": written.group(1) if written else "",
            "cycles": _number(text, r"\| cycles (\d+)"), "created": _number(text, r"^created \(proposed by the model\): (\d+)"),
            "accepted": _number(text, r"^accepted into \S+: (\d+)"), "rejected": _number(text, r"^rejected: (\d+)"),
            "off": (root / LEARNING / "data" / "CONDUCTOR_OFF").exists()}


def knowledge_watchdog(root: Path) -> dict | None:
    state = _read_json(root / KNOWLEDGE / "data" / "watchdog.json")
    if not isinstance(state, dict):
        return None
    restarts = [r for r in state.get("restarts", []) if isinstance(r, dict)][-5:]
    return {"ok": state.get("ok") is True, "checked_at": str(state.get("checked_at", ""))[:20],
            "failures": int(state.get("failures") or 0),
            "restarts": [{"at": str(r.get("at", ""))[:20], "done": r.get("done") is True,
                          "reason": re.sub(r"[^A-Za-z0-9 :._-]", "", str(r.get("reason", "")))[:80]} for r in restarts]}


def studio_lab(root: Path, run=_run) -> dict | None:
    evidence = root / STUDIO_LAB / "evidence"
    runs = sorted(evidence.glob("nightly-*"), key=lambda p: p.name.split("-")[-1]) if evidence.is_dir() else []
    if not runs:
        return None
    latest = runs[-1]
    nightly = _read_json(latest / "nightly.json", 512_000) or {}
    summary = nightly.get("summary") if isinstance(nightly.get("summary"), dict) else {}
    keep = ("specs", "specs_ran", "passed", "first_pass", "fixed_then_passed", "playtests", "lessons", "wall_seconds")
    out = {"run": latest.name, "ok": nightly.get("ok") is True,
           **{key: summary.get(key) for key in keep if isinstance(summary.get(key), (int, float))}}
    try:
        uid = int(run(["id", "-u", "star"]).stdout.strip())
        state = run(["runuser", "-u", "star", "--", "env", f"XDG_RUNTIME_DIR=/run/user/{uid}", "systemctl",
                     "--user", "is-active", "star-studio-lab-nightly.service"]).stdout.strip()
        out["running"] = state in {"active", "activating"}
    except (ValueError, OSError, subprocess.SubprocessError):
        pass
    return out


def load(root: Path) -> dict:
    out: dict = {}
    try:
        out["load1"] = round(os.getloadavg()[0], 2)
    except (OSError, AttributeError):        # AttributeError: no load average on Windows (tests)
        pass
    try:
        info = (root / "proc" / "meminfo").read_text()
        avail = re.search(r"^MemAvailable:\s+(\d+) kB", info, re.M)
        if avail:
            out["mem_available_gb"] = round(int(avail.group(1)) / 1048576, 1)
    except OSError:
        pass
    return out


def facts(root: Path = ROOT, run=_run, now: datetime | None = None) -> dict:
    now = now or _now()
    out = {"v": 1, "at": _stamp(now), "host": socket.gethostname()[:40], "services": services(run),
           "load": load(root)}
    for name, value in (("night_school", night_school(root, now)), ("conductor", conductor(root)),
                        ("knowledge_watchdog", knowledge_watchdog(root)), ("studio_lab", studio_lab(root, run))):
        if value is not None:
            out[name] = value
    return out


# ------------------------------------------------------------------------------------------------ actions

def _unit_exists(unit: str, run=_run) -> bool:
    return run(["systemctl", "cat", unit + ".service"]).returncode == 0


def _systemctl(action: str, unit: str, run=_run) -> dict:
    if not _unit_exists(unit, run):
        return {"ok": False, "text": f"{unit} is not installed on this brain"}
    result = run(["systemctl", action, unit + ".service"], timeout=120)
    state = run(["systemctl", "is-active", unit + ".service"]).stdout.strip()
    return {"ok": result.returncode == 0, "text": f"{action} {unit}: exit {result.returncode}, now {state}"}


def save_idea(text: str, root: Path = ROOT, now: datetime | None = None, run=_run) -> dict:
    cleaned = "".join(ch for ch in text if ch == "\n" or ch.isprintable()).strip()[:MAX_IDEA]
    if len(cleaned) < 10:
        return {"ok": False, "text": "the idea is empty or too short"}
    folder = root / LEARNING / "docs-recent"
    if not folder.is_dir():
        return {"ok": False, "text": "no night school docs-recent folder on this brain"}
    now = now or _now()
    path = folder / f"owner-idea-{now:%Y%m%dT%H%M%SZ}.md"
    path.write_text("# Practice idea from the owner (Discord)\n\n" + cleaned + "\n", encoding="utf-8")
    if root == Path("/"):
        run(["chown", "star:star", str(path)])
    return {"ok": True, "text": f"saved as {path.name}; the night conductor turns recent notes into checked "
                                "practice tasks between 18:00 and 09:00 owner-local"}


def knowledge_eval(root: Path = ROOT, run=_run) -> dict:
    app = root / KNOWLEDGE / "app"
    if not app.is_dir():
        return {"ok": False, "text": "no knowledge service on this brain"}
    result = run(["runuser", "-u", "star", "--", "nice", "-n", "10", str(root / KNOWLEDGE / "venv/bin/python"),
                  "-m", "starkb", "eval", "--modes", "bm25,vector"], timeout=600)
    if result.returncode != 0:
        return {"ok": False, "text": f"starkb eval exit {result.returncode}: {result.stderr.strip()[-200:]}"}
    try:
        summary = json.loads(result.stdout[result.stdout.index("{"):])
    except ValueError:
        return {"ok": False, "text": "starkb eval printed no summary"}
    return {"ok": True, "text": "knowledge search eval (eval30 questions)", "summary": summary}


def studio_lab_run(root: Path = ROOT, run=_run) -> dict:
    if not (root / STUDIO_LAB / "app").is_dir():
        return {"ok": False, "text": "Studio Lab is not installed on this brain"}
    uid = run(["id", "-u", "star"]).stdout.strip()
    if not uid.isdigit():
        return {"ok": False, "text": "no star user"}
    result = run(["runuser", "-u", "star", "--", "env", f"XDG_RUNTIME_DIR=/run/user/{uid}", "systemctl", "--user",
                  "start", "--no-block", "star-studio-lab-nightly.service"])
    return {"ok": result.returncode == 0, "text": "Studio Lab nightly run started (up to 45 min)"
            if result.returncode == 0 else f"could not start Studio Lab: {result.stderr.strip()[-200:]}"}


def handle(verb: str, payload: str = "", root: Path = ROOT, run=_run) -> tuple[int, str]:
    """(exit code, output). Unknown verbs are refused without running anything."""
    verb = verb.strip()
    if verb in LEGACY:
        try:
            return 0, (root / LEGACY[verb]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return 1, ""
    home = root / LEARNING / "data"
    if verb == "facts":
        result = {"ok": True, "facts": facts(root, run)}
    elif verb in {"ns-start", "ns-stop"}:
        result = _systemctl(verb[3:], "star-night-school", run)
    elif verb == "ns-pause":
        if not home.is_dir():
            result = {"ok": False, "text": "no night school on this brain"}
        else:
            (home / "HOLD").write_text("paused from Discord by the owner\n", encoding="utf-8")
            result = {"ok": True, "text": "night school paused (HOLD file); the current answer is dropped"}
    elif verb == "ns-resume":
        existed = (home / "HOLD").exists()
        (home / "HOLD").unlink(missing_ok=True)
        result = {"ok": True, "text": "night school resumed (HOLD removed)" if existed else "night school was not paused"}
    elif verb == "idea":
        result = save_idea(payload, root, run=run)
    elif verb == "knowledge-eval":
        result = knowledge_eval(root, run)
    elif verb == "studio-lab-run":
        result = studio_lab_run(root, run)
    elif verb.startswith("restart:") and verb[8:] in RESTARTABLE:
        result = _systemctl("restart", verb[8:], run)
    else:
        return 2, json.dumps({"ok": False, "text": "refused: not an allowed verb"})
    result["verb"] = verb
    return (0 if result.get("ok") else 1), json.dumps(result, separators=(",", ":"))


def main(argv: list[str]) -> int:
    if argv[:1] == ["--socket"]:
        verb = sys.stdin.readline(200)
    elif len(argv) == 1:
        verb = argv[0]
    else:
        print(json.dumps({"ok": False, "text": "usage: star_gate.py VERB | --socket"}))
        return 2
    payload = sys.stdin.read(MAX_IDEA * 4) if verb.strip() == "idea" else ""
    code, output = handle(verb, payload)
    sys.stdout.write(output + ("" if output.endswith("\n") else "\n"))
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
