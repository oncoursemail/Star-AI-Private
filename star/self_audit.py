"""Weekly self-audit (issue #555 B5): a short report of STAR's own measured strengths and weaknesses.

Built only from data STAR already stores; it never runs a model and never opens a blind or holdout suite:
  evals      per-skill pass rates and the week-over-week trend, and the top failure classes
             (eval result files, star/failure_ledger.py's labels; skill = the suite's task category)
  mistakes   the check-fix ladder's mistake log of the last 7 days (star/verify_ladder.py)
  lessons    night-school lessons that went live, expired, were kept or undone (learned_items table)
  receipts   automatic promotions, refusals and rollbacks (star/integrity.py's receipts folder)
  curiosity  what the queue recorded, studied and still holds (star/curiosity.py)
  api dump   age of the bundled Roblox API dump and its latest list of changes (star/api_dump_diff.py)
A source that does not exist on this machine is named under "missing", never guessed.

The report is written to `<STAR data folder>/self_audit/` as latest.json, latest.md and a dated copy. The desktop host
builds a new one when the newest is 7 days old (`run_if_due`, in a background thread) and answers the `selfAudit`
action with the latest, which the "What STAR learned this week" page shows. `python -m star.self_audit run [--force]`.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time

from . import curiosity

WINDOW_DAYS = 7
MIN_SKILL_TASKS = 5          # fewer scored tasks than this is not called a strength or a weakness
MIN_TREND_TASKS = 3          # per window, for a trend
STRONG, WEAK, MOVE = 0.75, 0.5, 0.10
ACTIONS = frozenset({"selfAudit"})
ROOT = Path(__file__).resolve().parents[1]
_lock = threading.Lock()


def _epoch(stamp) -> float:
    try:
        text = str(stamp).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()
    except ValueError:
        return 0.0


def _iso(moment: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(moment))


def _rate(passed: int, total: int) -> float | None:
    return round(passed / total, 3) if total else None


def default_sources(home: Path) -> dict:
    results = os.environ.get("STAR_EVAL_RESULTS")
    dirs = [Path(p) for p in results.split(os.pathsep) if p] if results else [ROOT / "evals" / "results"]
    return {"results_dirs": dirs,
            "suites_dir": ROOT / "evals" / "roblox",
            "mistakes": Path(os.environ.get("STAR_MISTAKE_LOG") or home / "verify_ladder" / "mistakes.jsonl"),
            "lessons_db": home / "knowledge" / "knowledge.sqlite3",
            "receipts_dir": Path(os.environ.get("STAR_RECEIPTS_DIR") or Path.home() / ".star" / "receipts"),
            "curiosity_file": curiosity.queue_path(),
            "dump_file": ROOT / "data" / "roblox_api" / "roblox_api.json",
            "changes_file": ROOT / "data" / "roblox_api" / "changes.json"}


# --- sections -------------------------------------------------------------------------------------------------------

def _evals(dirs, suites_dir, now: float) -> dict | None:
    from . import failure_ledger
    cache: dict = {}
    skills: dict[str, dict] = {}
    causes_all, causes_week, failed_tasks, files = Counter(), Counter(), 0, 0
    for folder in dirs:
        for path in sorted(Path(folder).glob("*.json")) if Path(folder).is_dir() else ():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                tasks, suite = data["tasks"], str((data.get("suite") or {}).get("file") or "")
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if not isinstance(tasks, dict) or "holdout" in Path(suite).name.casefold():
                continue
            started = _epoch((data.get("run") or {}).get("started_at"))
            try:
                topics = failure_ledger._topics(suite, Path(suites_dir), cache) if suite else {}
            except (OSError, ValueError, KeyError, TypeError):
                topics = {}
            files += 1
            for task_id, record in tasks.items():
                if not isinstance(record, dict) or record.get("status") not in ("pass", "fail"):
                    continue          # infrastructure errors are not the model's failures
                skill = topics.get(task_id) or str(task_id).split("-")[0].lower() or "other"
                row = skills.setdefault(skill, {"all": [0, 0], "recent": [0, 0], "prev": [0, 0]})
                windows = ["all"]
                if started and now - WINDOW_DAYS * 86400 <= started <= now:
                    windows.append("recent")
                elif started and now - 2 * WINDOW_DAYS * 86400 <= started < now - WINDOW_DAYS * 86400:
                    windows.append("prev")
                for name in windows:
                    row[name][1] += 1
                    row[name][0] += record["status"] == "pass"
                if record["status"] == "fail":
                    failed_tasks += 1
                    labelled = failure_ledger.label_failure(record)
                    if labelled:
                        causes_all[labelled[0]] += 1
                        if "recent" in windows:
                            causes_week[labelled[0]] += 1
    if not files:
        return None
    table = []
    for skill, row in skills.items():
        recent, prev = row["recent"], row["prev"]
        trend = ""
        if recent[1] >= MIN_TREND_TASKS and prev[1] >= MIN_TREND_TASKS:
            delta = recent[0] / recent[1] - prev[0] / prev[1]
            trend = "up" if delta >= MOVE else "down" if delta <= -MOVE else "flat"
        table.append({"skill": skill, "scored": row["all"][1], "passed": row["all"][0],
                      "rate": _rate(*row["all"]), "recent": {"scored": recent[1], "rate": _rate(*recent)},
                      "previous": {"scored": prev[1], "rate": _rate(*prev)}, "trend": trend})
    table.sort(key=lambda r: (-r["scored"], r["skill"]))
    return {"result_files": files, "skills": table, "failed_tasks": failed_tasks,
            "failure_classes": [{"cause": c, "failed": n, "this_week": causes_week[c]}
                                for c, n in causes_all.most_common(5)]}


def _rows(path: Path):
    try:
        with Path(path).open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    yield row
    except OSError:
        return


def _mistakes(path: Path, now: float) -> dict | None:
    if not Path(path).is_file():
        return None
    week = [r for r in _rows(path) if _epoch(r.get("ts")) >= now - WINDOW_DAYS * 86400]
    return {"this_week": len(week), "verified_fixes": sum(bool(r.get("verified")) for r in week),
            "by_rung": dict(Counter(str(r.get("rung", "?")) for r in week).most_common(6)),
            "top": [{"signature": s[:120], "count": n}
                    for s, n in Counter(str(r.get("signature", "")) for r in week if not r.get("verified")).most_common(5)]}


def _lessons(db_path: Path, now: float) -> dict | None:
    if not Path(db_path).is_file():
        return None
    try:
        db = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
        try:
            counts = dict(db.execute("SELECT state, COUNT(*) FROM learned_items GROUP BY state"))
            live = db.execute("SELECT COUNT(*) FROM learned_items WHERE live_at>=?",
                              (_iso(now - WINDOW_DAYS * 86400),)).fetchone()[0]
        finally:
            db.close()
    except sqlite3.Error:
        return None
    return {"went_live_this_week": int(live), "by_state": {k: int(v) for k, v in counts.items()}}


def _receipts(folder: Path, now: float) -> dict | None:
    if not Path(folder).is_dir():
        return None
    kinds, recent = Counter(), []
    for path in sorted(Path(folder).glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(row, dict) and _epoch(row.get("at")) >= now - WINDOW_DAYS * 86400:
            kinds[str(row.get("kind", "?"))] += 1
            recent.append({"kind": row.get("kind"), "change": str(row.get("change"))[:100], "at": row.get("at"),
                           "why": str((row.get("reasons") or row.get("problems") or [""])[0])[:140]})
    return {"this_week": dict(kinds), "latest": recent[-5:]}


def _curiosity(path: Path, now: float) -> dict | None:
    if not Path(path).is_file():
        return None
    since = _iso(now - WINDOW_DAYS * 86400)
    recorded, studied, tried = Counter(), 0, 0
    for row in curiosity._rows(path):
        if row["ts"] < since:
            continue
        if row.get("resolved") is None:
            count = row.get("count")
            recorded[str(row.get("kind", "?"))] += count if type(count) is int and count > 0 else 1
        elif row["resolved"] in ("taught", "answered"):
            studied += 1
        elif row["resolved"] == "tried":
            tried += 1
    items = curiosity.load(path)
    openers = curiosity.ranked(5, paths=(path,), now=now)
    return {"recorded_this_week": dict(recorded), "studied_this_week": studied, "tried_without_result": tried,
            "open": sum(1 for i in items.values() if i.kind in curiosity.PRACTICE_KINDS and i.is_open()),
            "top_open": [{"kind": i.kind, "topic": i.topic, "count": i.count} for i in openers],
            "studied_topics": [{"topic": i.topic, "by": i.by[:2]} for i in items.values() if i.taught >= since][:5]}


def _api(dump_file: Path, changes_file: Path, now: float) -> dict | None:
    out: dict = {}
    try:
        source = json.loads(Path(dump_file).read_text(encoding="utf-8")).get("StarSource") or {}
        out = {"studio_version": source.get("studioVersion"), "generated": source.get("generated"),
               "age_days": int((now - _epoch(source.get("generated"))) // 86400) if source.get("generated") else None}
    except (OSError, ValueError, AttributeError):
        return None
    try:
        changes = json.loads(Path(changes_file).read_text(encoding="utf-8"))
        out["latest_changes"] = {"generated": changes.get("generated"),
                                 "added_members": changes.get("added_members_total", 0),
                                 "newly_deprecated": changes.get("newly_deprecated_total", 0),
                                 "added_classes": changes.get("added_classes_total", 0)}
    except (OSError, ValueError, AttributeError):
        pass
    return out


# --- the report -----------------------------------------------------------------------------------------------------

def _verdicts(sections: dict) -> tuple[list[str], list[str]]:
    strengths, weaknesses = [], []
    for row in (sections.get("evals") or {}).get("skills", []):
        if row["scored"] < MIN_SKILL_TASKS:
            continue
        text = f"{row['skill']}: {round(row['rate'] * 100)}% of {row['scored']} scored tasks"
        if row["rate"] >= STRONG:
            strengths.append(text)
        elif row["rate"] <= WEAK:
            weaknesses.append(text)
        if row["trend"] in ("up", "down"):
            moved = f"{row['skill']} went {row['trend']} this week: {round(row['previous']['rate'] * 100)}% to {round(row['recent']['rate'] * 100)}%"
            (strengths if row["trend"] == "up" else weaknesses).append(moved)
    classes = (sections.get("evals") or {}).get("failure_classes") or []
    if classes:
        weaknesses.append(f"most common failure class: {classes[0]['cause']} ({classes[0]['failed']} failed tasks)")
    mistakes = sections.get("mistakes") or {}
    if mistakes.get("this_week"):
        share = mistakes["verified_fixes"] / mistakes["this_week"]
        (strengths if share >= 0.5 else weaknesses).append(
            f"the check-fix ladder cleared {mistakes['verified_fixes']} of {mistakes['this_week']} mistakes this week")
    rolled = ((sections.get("receipts") or {}).get("this_week") or {}).get("rollback", 0)
    if rolled:
        weaknesses.append(f"{rolled} automatic change(s) were rolled back this week")
    seen = sections.get("curiosity") or {}
    if seen.get("studied_this_week"):
        strengths.append(f"night school studied {seen['studied_this_week']} curiosity item(s) this week")
    if seen.get("open", 0) >= 20:
        weaknesses.append(f"{seen['open']} curiosity items are still waiting to be studied")
    age = (sections.get("api_dump") or {}).get("age_days")
    if isinstance(age, int) and age > 30:
        weaknesses.append(f"the bundled Roblox API dump is {age} days old")
    return strengths, weaknesses


def build(now: float | None = None, *, home: Path | None = None, **override) -> dict:
    """The audit as a dict. `override` replaces any key of default_sources() (used by tests and by other tools)."""
    now = time.time() if now is None else now
    if home is None:
        from .desktop_core import app_data
        home = app_data()
    src = {**default_sources(Path(home)), **override}
    sections = {"evals": _evals(src["results_dirs"], src["suites_dir"], now),
                "mistakes": _mistakes(src["mistakes"], now), "lessons": _lessons(src["lessons_db"], now),
                "receipts": _receipts(src["receipts_dir"], now), "curiosity": _curiosity(src["curiosity_file"], now),
                "api_dump": _api(src["dump_file"], src["changes_file"], now)}
    strengths, weaknesses = _verdicts(sections)
    return {"generated": _iso(now), "window_days": WINDOW_DAYS, "strengths": strengths, "weaknesses": weaknesses,
            "missing": sorted(k for k, v in sections.items() if v is None),
            **{k: v for k, v in sections.items() if v is not None}}


def render(report: dict) -> str:
    lines = [f"# STAR weekly self-audit ({report['generated'][:10]})", "",
             "Measured from stored data only (no model was run). Window: the last %d days." % report["window_days"], "",
             "## Strengths"] + ([f"- {s}" for s in report["strengths"]] or ["- none measured yet"])
    lines += ["", "## Weaknesses"] + ([f"- {w}" for w in report["weaknesses"]] or ["- none measured"])
    evals = report.get("evals")
    if evals:
        lines += ["", f"## Skills ({evals['result_files']} result files)"]
        for row in evals["skills"][:12]:
            trend = f", {row['trend']} vs last week" if row["trend"] else ""
            lines.append(f"- {row['skill']}: {round((row['rate'] or 0) * 100)}% of {row['scored']}{trend}")
        if evals["failure_classes"]:
            lines += ["", "## Top failure classes"] + [
                f"- {c['cause']}: {c['failed']} failed tasks ({c['this_week']} in eval runs this week)"
                for c in evals["failure_classes"]]
    seen = report.get("curiosity")
    if seen:
        lines += ["", "## Curiosity queue",
                  f"- recorded this week: {sum(seen['recorded_this_week'].values())} "
                  f"({json.dumps(seen['recorded_this_week'], sort_keys=True)}); studied: {seen['studied_this_week']}; "
                  f"tried without result: {seen['tried_without_result']}; open: {seen['open']}"]
        lines += [f"- open: {i['topic']} (x{i['count']})" for i in seen["top_open"]]
        lines += [f"- studied: {i['topic']}" for i in seen["studied_topics"]]
    api = report.get("api_dump")
    if api:
        changes = api.get("latest_changes") or {}
        lines += ["", "## Roblox API dump", f"- Studio {api.get('studio_version')}, generated {api.get('generated')} "
                  f"({api.get('age_days')} days old)"]
        if changes:
            lines.append(f"- latest change list ({changes.get('generated')}): {changes.get('added_members')} members and "
                         f"{changes.get('added_classes')} classes added, {changes.get('newly_deprecated')} deprecated")
    if report["missing"]:
        lines += ["", "## No data on this machine for", ", ".join(report["missing"])]
    return "\n".join(lines) + "\n"


def audit_dir(home: Path) -> Path:
    return Path(home) / "self_audit"


def write(report: dict, home: Path) -> Path:
    folder = audit_dir(home)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = report["generated"][:10].replace("-", "")
    body = json.dumps(report, indent=1, ensure_ascii=False) + "\n"
    for name, text in (("latest.json", body), (f"{stamp}.md", render(report)), ("latest.md", render(report))):
        tmp = folder / (name + ".tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, folder / name)
    for old in sorted(folder.glob("2*.md"))[:-12]:      # keep the last 12 weekly copies
        old.unlink(missing_ok=True)
    return folder / "latest.json"


def latest(home: Path) -> dict | None:
    try:
        report = json.loads((audit_dir(home) / "latest.json").read_text(encoding="utf-8"))
        return report if isinstance(report, dict) and isinstance(report.get("generated"), str) else None
    except (OSError, ValueError):
        return None


def due(home: Path, now: float | None = None) -> bool:
    found = latest(home)
    return found is None or (time.time() if now is None else now) - _epoch(found["generated"]) >= WINDOW_DAYS * 86400


def run(home: Path | None = None, *, force: bool = False, now: float | None = None, **override) -> dict | None:
    """Build and store the audit if the newest is a week old (or `force`); None when nothing was due."""
    if home is None:
        from .desktop_core import app_data
        home = app_data()
    if not force and not due(home, now):
        return None
    report = build(now, home=home, **override)
    write(report, home)
    return report


def run_if_due(home: Path | None = None, **override) -> bool:
    """Start the weekly audit in a background thread when it is due. Never raises, never waits; True if started."""
    try:
        if home is None:
            from .desktop_core import app_data
            home = app_data()
        if not due(home) or not _lock.acquire(blocking=False):
            return False

        def work():
            try:
                run(home, **override)
            except Exception:
                pass
            finally:
                _lock.release()
        threading.Thread(target=work, name="star-self-audit", daemon=True).start()
        return True
    except Exception:
        return False


def handle_action(home: Path, project: str, action: str, body: dict) -> dict:
    """`selfAudit`: the newest stored report (None until the first one is written). Read only."""
    if action not in ACTIONS:
        raise PermissionError("Action not permitted")
    return {"report": latest(home)}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["run"]:
        report = run(force="--force" in args)
        print(render(report) if report else "not due: the newest self-audit is less than 7 days old (use --force)")
        return 0
    if args[:1] == ["show"]:
        from .desktop_core import app_data
        report = latest(app_data())
        print(render(report) if report else "no self-audit has been written yet")
        return 0
    print("usage: python -m star.self_audit run [--force] | show", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
