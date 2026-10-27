"""Her own life on the PC (#613 requirement 1): interests she weights, goals, verified history, variety, bounds.

Files under <home>/life/ (plain JSON, so the owner can read them):
  interests.json  {name: {"weight": float, "about": str}}; STAR changes weights herself (brain tool set_interest),
                  and every session nudges the weight: verified success x1.1, failure x0.95, kept in [0.1, 5].
  goals.json      [{"id", "interest", "text", "status": open|done|dropped, "tries", "created"}]
  history.jsonl   one line per session: interest, activity, goal, claimed vs verified outcome, evidence, summary.

pick() = weighted random over interests that have an activity, weight x novelty x open-goal bonus; novelty falls
with each session of that interest in the last 24 h and halves right after one. budget_ok() bounds compute:
sessions per day and the pause between sessions (config.json).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import random

MIN_WEIGHT, MAX_WEIGHT = 0.1, 5.0
SEED_INTERESTS = {
    "game_making": {"weight": 1.5, "about": "make small games (Roblox/Luau, Godot, web) and play-test them"},
    "drawing": {"weight": 1.2, "about": "draw and animate: sketches, sprites, short animations"},
    "music": {"weight": 1.0, "about": "make music and listen to music"},
    "research": {"weight": 1.0, "about": "read about a topic she is curious about and write notes"},
    "practice": {"weight": 1.2, "about": "practice skills she failed at before (curiosity queue)"},
    "play_games": {"weight": 0.8, "about": "play games on her own accounts"},
    "chat_with_friends": {"weight": 0.6, "about": "talk with friends who opted in"},
    "watch_videos": {"weight": 1.0, "about": "watch, react to and learn from videos she picks"},
    "use_apps": {"weight": 0.5, "about": "use any app on her PC with her own mouse and keyboard"},
}
SEED_GOALS = [
    ("game_making", "Make a one-screen game with a win condition and play it until it works"),
    ("drawing", "Draw a self-portrait of the STAR mascot and save it in the gallery"),
    ("music", "Compose a 30-second loop and save it as an audio file"),
    ("research", "Pick a topic you do not know well and write a one-page note with sources"),
]
_STAMP = "%Y-%m-%dT%H:%M:%SZ"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(stamp: str) -> datetime | None:
    try:
        return datetime.strptime(stamp, _STAMP).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def normalize_outcome(outcome, *, minutes: float = 0.0) -> dict:
    """Validate the activity contract before it affects history, goals or learning."""
    invalid = "result"
    if isinstance(outcome, dict):
        invalid = ""
        for key in ("ok", "verified", "paused", "goal_done"):
            if key in outcome and type(outcome[key]) is not bool:
                invalid = key
                break
        for key in ("evidence", "failures"):
            value = outcome.get(key, [])
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                invalid = invalid or key
        steps = outcome.get("steps", 0)
        duration = outcome.get("minutes", minutes)
        if type(steps) is not int or not 0 <= steps <= 2**63 - 1:
            invalid = invalid or "steps"
        try:
            valid_duration = type(duration) in (int, float) and math.isfinite(duration) and duration >= 0
        except OverflowError:
            valid_duration = False
        if not valid_duration:
            invalid = invalid or "minutes"
        if not isinstance(outcome.get("summary", ""), str):
            invalid = invalid or "summary"
        if not invalid:
            try:
                for value in [outcome.get("summary", ""), *outcome.get("evidence", []), *outcome.get("failures", [])]:
                    value.encode("utf-8")
            except UnicodeEncodeError:
                invalid = "text encoding"
        if outcome.get("paused") is True and not isinstance(outcome.get("resume_state", {}), dict):
            invalid = invalid or "resume_state"
        if not invalid:
            clean = dict(outcome)
            clean.update(ok=outcome.get("ok") is True,
                         verified=outcome.get("ok") is True and outcome.get("verified") is True,
                         steps=steps, minutes=duration)
            return clean
    return {"ok": False, "verified": False, "steps": 0, "minutes": minutes,
            "summary": f"activity returned invalid outcome ({invalid})", "evidence": [],
            "failures": [f"activity: invalid outcome ({invalid})"]}


class Life:
    def __init__(self, home: Path, *, rng: random.Random | None = None, clock=_now):
        self.dir = Path(home) / "life"
        self.rng = rng or random.Random()
        self.clock = clock
        self.dir.mkdir(parents=True, exist_ok=True)
        if not (self.dir / "interests.json").exists():
            self._write("interests.json", SEED_INTERESTS)
        if not (self.dir / "goals.json").exists():
            self._write("goals.json", [])
            for interest, text in SEED_GOALS:
                self.add_goal(interest, text)

    # ---- storage ------------------------------------------------------------------------------------------
    def _read(self, name: str, default):
        try:
            return json.loads((self.dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def _write(self, name: str, data) -> None:
        tmp = self.dir / (name + ".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.dir / name)

    def interests(self) -> dict:
        return self._read("interests.json", {})

    def goals(self, status: str | None = "open") -> list[dict]:
        rows = self._read("goals.json", [])
        return [g for g in rows if status is None or g.get("status") == status]

    def history(self, last: int = 200) -> list[dict]:
        try:
            lines = (self.dir / "history.jsonl").read_text(encoding="utf-8").splitlines()[-last:]
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out

    # ---- her choices --------------------------------------------------------------------------------------
    def set_interest(self, name: str, weight: float, about: str = "") -> dict:
        name = "_".join(str(name).lower().split())[:40]
        if not name:
            raise ValueError("interest name is empty")
        data = self.interests()
        entry = data.get(name, {"about": ""})
        entry["weight"] = round(min(MAX_WEIGHT, max(MIN_WEIGHT, float(weight))), 3)
        if about:
            entry["about"] = str(about)[:200]
        data[name] = entry
        self._write("interests.json", data)
        return entry

    def add_goal(self, interest: str, text: str) -> dict:
        rows = self._read("goals.json", [])
        goal = {"id": f"g{len(rows) + 1}", "interest": str(interest), "text": str(text)[:300], "status": "open",
                "tries": 0, "created": self.clock().strftime(_STAMP)}
        rows.append(goal)
        self._write("goals.json", rows)
        return goal

    def set_goal(self, goal_id: str, status: str) -> dict:
        if status not in ("open", "done", "dropped"):
            raise ValueError("status must be open, done or dropped")
        rows = self._read("goals.json", [])
        for goal in rows:
            if goal["id"] == goal_id:
                goal["status"] = status
                self._write("goals.json", rows)
                return goal
        raise ValueError(f"no goal {goal_id}")

    # ---- scheduling ---------------------------------------------------------------------------------------
    def scores(self, available: set[str]) -> dict[str, float]:
        recent = [h for h in self.history() if (_parse(h.get("ts", "")) or datetime.min.replace(tzinfo=timezone.utc))
                  > self.clock() - timedelta(hours=24)]
        last = recent[-1]["interest"] if recent else None
        open_by = {g["interest"] for g in self.goals()}
        out = {}
        for name, entry in self.interests().items():
            if name not in available:
                continue
            novelty = 1.0 / (1 + sum(1 for h in recent if h.get("interest") == name))
            if name == last:
                novelty *= 0.5
            out[name] = float(entry.get("weight", 1.0)) * novelty * (1.3 if name in open_by else 1.0)
        return out

    def pick(self, available: set[str]) -> str | None:
        scores = self.scores(available)
        if not scores:
            return None
        names = sorted(scores)
        return self.rng.choices(names, weights=[scores[n] for n in names], k=1)[0]

    def goal_for(self, interest: str) -> dict | None:
        open_goals = sorted((g for g in self.goals() if g["interest"] == interest), key=lambda g: g["tries"])
        return open_goals[0] if open_goals else None

    def budget_ok(self, config: dict) -> tuple[bool, str]:
        now = self.clock()
        rows = self.history()
        today = [h for h in rows if (_parse(h.get("ts", "")) or now - timedelta(days=2)) > now - timedelta(hours=24)]
        if len(today) >= int(config.get("sessions_per_day", 24)):
            return False, f"{len(today)} sessions in the last 24 h (limit {config.get('sessions_per_day')})"
        if rows:
            last = _parse(rows[-1].get("ts", ""))
            pause = timedelta(minutes=float(config.get("pause_minutes", 30)))
            if last and now - last < pause:
                return False, "pausing between sessions"
        return True, ""

    # ---- outcomes -----------------------------------------------------------------------------------------
    def record(self, interest: str, activity: str, outcome: dict, goal: dict | None = None) -> dict:
        outcome = normalize_outcome(outcome)
        row = {"ts": self.clock().strftime(_STAMP), "interest": interest, "activity": activity,
               "goal": goal["id"] if goal else "", "claimed": bool(outcome.get("ok")),
               "verified": bool(outcome.get("verified")), "evidence": outcome.get("evidence", [])[:10],
               "summary": str(outcome.get("summary", ""))[:600], "steps": int(outcome.get("steps", 0)),
               "minutes": round(float(outcome.get("minutes") or 0.0), 1)}
        with (self.dir / "history.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        entry = self.interests().get(interest)
        if entry is not None:
            factor = 1.1 if row["verified"] else 0.95
            self.set_interest(interest, float(entry.get("weight", 1.0)) * factor)
        if goal:
            rows = self._read("goals.json", [])
            for g in rows:
                if g["id"] == goal["id"]:
                    g["tries"] = int(g.get("tries", 0)) + 1
                    if row["verified"] and outcome.get("goal_done") is True:
                        g["status"] = "done"
            self._write("goals.json", rows)
        return row
