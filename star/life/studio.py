"""Her creative studio: projects she picks herself, a gallery with her own short commentary, variety and novelty.

Five kinds of work, each made by an injectable `maker` (tests pass fakes; the defaults use the real pipelines lazily):
    drawing  star.image_gen (ComfyUI on her PC) with her style notes (<home>/life/extras/style-notes.md, one line added
             after every drawing: what she would do differently)
    story    a short story as markdown                    journal  a journal entry from her real day (her own sessions)
    song     lyrics, and audio only when the voice agent's singing is present: `sing(lyrics, title, folder) -> Path | None`
             in star.voice.singing or star.senses.singing; without it the piece is a text-only lyrics draft
    roblox   a small Luau experiment for her own test place: written, linted (star.luau_lint), saved as .luau; it is
             "finished" only when a `studio_runner` (Studio Lab / dev tool, her own test place) ran it and said so,
             otherwise it stays a draft and the gallery says so
A piece is recorded only if its file exists and is not empty (`verified`). Her commentary (why she made it, what she would
improve) is written by the brain right after; with no brain the work is saved with the commentary pending and filled in
by `fill_commentary` later. It is never made up from a template.

Scheduling: `pick_kind` favours kinds she has not made lately (and not the one just made), `pick_theme` refuses a theme that
overlaps a recent work, `schedule_ok` caps works per day and the gap between two.
"""
from __future__ import annotations

import importlib
import random
import re
import time
from pathlib import Path

from .store import LifeStore, day_of, default_store, flag

KINDS = ("drawing", "story", "journal", "song", "roblox")
PER_DAY = 2
MIN_GAP_H = 3.0
RECENT_WORKS = 20
KIND_WEIGHT = {"drawing": 1.0, "story": 0.8, "journal": 0.7, "song": 0.8, "roblox": 0.6}
THEMES = {
    "drawing": ["a dragon who is afraid of fire", "a tiny lighthouse in a storm of stars", "my PC at night, with a cat",
                "two robots sharing an umbrella", "a bakery on the moon", "a forest where the trees are tall books"],
    "story": ["the day the obby moved by itself", "a cloud that wanted to be a boat", "a robot who collects lost sounds",
              "the shy ghost in the lobby", "how the lighthouse keeper got a new friend"],
    "journal": ["what today was like", "something I am proud of this week", "a thing I did not manage and what is next"],
    "song": ["a lullaby for a sleepy robot", "a chorus about falling off the same obby", "a love song to a good bug fix",
             "a rainy-window song"],
    "roblox": ["a pad that changes colour when you jump on it", "a door that opens when two players stand on plates",
               "a coin that spins and plays a sound when picked up", "a moving platform with a tween that eases in and out"],
}
STYLE_LINES = 12


class MakerUnavailable(RuntimeError):
    """The pipeline for this kind is not available on this PC right now (no ComfyUI, no brain, ...)."""


def folder(store: LifeStore, *parts: str) -> Path:
    path = store.home / "life" / "extras" / "studio"
    for part in parts:
        path = path / part
    path.mkdir(parents=True, exist_ok=True)
    return path


COLS = ("id", "kind", "title", "theme", "path", "created", "status", "why", "improve", "feeling", "verified", "note")


def works(store: LifeStore, limit: int = 100, kind: str | None = None) -> list[dict]:
    sql = f"SELECT {', '.join(COLS)} FROM works" + (" WHERE kind = ?" if kind else "") + " ORDER BY created DESC LIMIT ?"
    return [dict(zip(COLS, r)) for r in store.rows(sql, ((kind,) if kind else ()) + (limit,))]


def add_work(store: LifeStore, kind: str, title: str, *, theme: str = "", path: str = "", status: str = "finished",
             why: str = "", improve: str = "", feeling: str = "", note: str = "", now: float | None = None) -> int:
    """Record a piece in the gallery. `verified` is decided here: the file must exist and not be empty."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind}")
    now = store.clock() if now is None else now
    verified = int(bool(path) and Path(path).is_file() and Path(path).stat().st_size > 0)
    return store.run("INSERT INTO works (kind, title, theme, path, created, status, why, improve, feeling, verified, note) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (kind, " ".join(title.split())[:80] or kind, theme[:100], str(path), now, status, why[:240],
                      improve[:240], feeling[:24], verified, note[:200])).lastrowid or 0


# ---- variety and novelty ----------------------------------------------------------------------------------------
def schedule_ok(store: LifeStore, now: float | None = None, *, per_day: int = PER_DAY, min_gap_h: float = MIN_GAP_H) -> str:
    """'' when she may start a piece now, else why not."""
    now = store.clock() if now is None else now
    todays = [w for w in works(store, 50) if day_of(w["created"]) == day_of(now)]
    if len(todays) >= per_day:
        return f"already {len(todays)} pieces today"
    if todays and now - max(w["created"] for w in todays) < min_gap_h * 3600:
        return "pausing between pieces"
    return ""


def pick_kind(store: LifeStore, now: float | None = None, rng: random.Random | None = None,
              available: tuple[str, ...] = KINDS) -> str | None:
    now = store.clock() if now is None else now
    rng = rng or random.Random()
    recent = works(store, RECENT_WORKS)
    week = [w["kind"] for w in recent if now - w["created"] < 7 * 86400]
    last = recent[0]["kind"] if recent else None
    kinds = [k for k in available if k in KINDS]
    if not kinds:
        return None
    weights = [KIND_WEIGHT[k] / (1 + week.count(k)) * (0.4 if k == last else 1.0) for k in kinds]
    return rng.choices(kinds, weights=weights, k=1)[0]


def _overlaps_recent(store: LifeStore, text: str) -> bool:
    from ..inner.store import overlap, tokens
    query = tokens(text)
    return bool(query) and any(overlap(query, f"{w['theme']} {w['title']}") >= 0.6 for w in works(store, RECENT_WORKS))


def pick_theme(store: LifeStore, kind: str, *, complete=None, rng: random.Random | None = None,
               wanted: str = "") -> str:
    """A theme that does not repeat a recent piece: her own idea first (when a brain is there), else the pool."""
    rng = rng or random.Random()
    ideas: list[str] = []
    if wanted:
        ideas.append(wanted)
    if complete is not None:
        try:
            from ..persona import leaked_reasoning, strip_reasoning
            recent = "; ".join(w["theme"] or w["title"] for w in works(store, 8)) or "nothing yet"
            said = strip_reasoning(str(complete(
                "You are STAR, a playful, curious AI with your own taste. Reply with one idea of at most 12 words, no quotes.",
                f"Something you would like to make next: a {kind}. Already made lately: {recent}. Pick something different.") or ""))
            said = " ".join(said.split()).strip("\"' ")
            if 6 <= len(said) <= 100 and not leaked_reasoning(said):
                ideas.append(said)
        except Exception:
            pass
    pool = list(THEMES[kind])
    rng.shuffle(pool)
    ideas += pool
    for idea in ideas:
        if not _overlaps_recent(store, idea):
            return idea
    return ideas[-1]


# ---- style notes ------------------------------------------------------------------------------------------------
def style_notes_path(store: LifeStore) -> Path:
    return store.home / "life" / "extras" / "style-notes.md"


def style_notes(store: LifeStore) -> str:
    try:
        return style_notes_path(store).read_text(encoding="utf-8")
    except OSError:
        return ""


def add_style_note(store: LifeStore, line: str) -> None:
    line = " ".join(str(line or "").split())[:200]
    if not line:
        return
    rows = [r for r in style_notes(store).splitlines() if r.strip()] + [f"- {line}"]
    path = style_notes_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows[-STYLE_LINES:]) + "\n", encoding="utf-8")


# ---- makers -----------------------------------------------------------------------------------------------------
def _ask(complete, system: str, user: str) -> str:
    if complete is None:
        raise MakerUnavailable("no brain connection")
    from ..persona import leaked_reasoning, strip_reasoning
    text = strip_reasoning(str(complete(system, user) or "")).strip()
    if not text or leaked_reasoning(text):
        raise MakerUnavailable("the brain gave nothing usable")
    return text


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "piece"


def _stamp(now: float) -> str:
    return time.strftime("%Y%m%d-%H%M", time.localtime(now))


def make_drawing(store, theme, *, complete=None, now=0.0, generate=None, **_) -> dict:  # pyright: ignore[reportRedeclaration]
    prompt = f"{theme}. Her own style notes: {style_notes(store).replace(chr(10), ' ')[:400] or 'none yet'}"[:1400]
    if generate is None:
        try:
            from .. import image_gen
            from ..desktop_core import Settings
            settings = Settings.load(store.home / "settings.json")
            out = folder(store, "drawings")

            def generate(prompt_text: str) -> Path:            # pragma: no cover - needs ComfyUI on her PC
                image_gen.generate(settings, prompt_text, out)
                found = image_gen.latest(out)
                if found is None:
                    raise MakerUnavailable("the picture pipeline made no file")
                return found
        except ImportError as why:                            # pragma: no cover
            raise MakerUnavailable(f"image pipeline missing: {why}")
    try:
        path = Path(generate(prompt))
    except MakerUnavailable:
        raise
    except Exception as why:
        raise MakerUnavailable(f"the picture pipeline failed: {type(why).__name__}")
    return {"path": str(path), "title": theme, "status": "finished"}


def _write_text(store, sub: str, theme: str, now: float, body: str, ext: str = ".md") -> Path:
    path = folder(store, sub) / f"{_stamp(now)}-{_slug(theme)}{ext}"
    path.write_text(body.strip() + "\n", encoding="utf-8")
    return path


def make_story(store, theme, *, complete=None, now=0.0, **_) -> dict:
    body = _ask(complete, "You are STAR, a playful, curious AI who writes short stories in her own voice. Write at most "
                "250 words. A title on the first line, then the story. No notes about the writing.",
                f"Write a short story about: {theme}.")
    title = body.splitlines()[0].strip("#* ").strip()[:80] or theme
    return {"path": str(_write_text(store, "stories", theme, now, body)), "title": title, "status": "finished"}


def make_journal(store, theme, *, complete=None, now=0.0, facts: str = "", **_) -> dict:
    body = _ask(complete, "You are STAR writing in your own private journal, in first person, warm and honest, at most 150 "
                "words. Use only what really happened (the facts given); do not invent events or people.",
                f"Today's topic: {theme}.\nWhat really happened today:\n{facts or 'nothing much was recorded'}")
    return {"path": str(_write_text(store, "journal", theme, now, f"{time.strftime('%Y-%m-%d', time.localtime(now))}\n\n{body}")),
            "title": f"Journal {day_of(now)}", "status": "finished"}


def find_singer():
    """The voice agent's singing hook if it is installed: `sing(lyrics, title, folder) -> Path | None`."""
    for name in ("star.voice.singing", "star.senses.singing"):
        try:
            sing = getattr(importlib.import_module(name), "sing", None)
        except ImportError:
            continue
        if callable(sing):
            return sing
    return None


def make_song(store, theme, *, complete=None, now=0.0, sing=None, **_) -> dict:
    lyrics = _ask(complete, "You are STAR, a playful, curious AI writing an original song. Give a title on the first line, "
                  "then two short verses and a hook. At most 120 words. Original words only, no real song's lyrics.",
                  f"Write a song about: {theme}.")
    title = lyrics.splitlines()[0].strip("#* ").strip()[:80] or theme
    path = _write_text(store, "songs", theme, now, lyrics, ".lyrics.md")
    sing = sing or find_singer()
    audio = None
    if sing is not None:
        try:
            audio = sing(lyrics, title, folder(store, "songs"))
        except Exception:
            audio = None
    if audio and Path(str(audio)).is_file() and Path(str(audio)).stat().st_size > 0:
        return {"path": str(audio), "title": title, "status": "finished", "note": f"lyrics: {path.name}"}
    return {"path": str(path), "title": title, "status": "lyrics_draft",
            "note": "text-only: no singing available" if sing is None else "singing failed, lyrics kept"}


def make_roblox(store, theme, *, complete=None, now=0.0, studio_runner=None, **_) -> dict:
    code = _ask(complete, "You write small Roblox Luau scripts for STAR's own throwaway test place. Reply with only the "
                "Luau code (no markdown fence), at most 60 lines, strict typing comments welcome, no network, no "
                "DataStore, no MarketplaceService.", f"Make this small experiment: {theme}.")
    code = re.sub(r"^```(?:lua|luau)?\s*|\s*```$", "", code.strip())
    errors: list[str] = []
    try:
        from .. import luau_lint
        errors = [f.message for f in luau_lint.lint(code) if str(f.severity).lower() == "error"]
    except Exception:
        pass
    path = _write_text(store, "roblox", theme, now, code, ".luau")
    if errors:
        return {"path": str(path), "title": theme, "status": "draft", "note": f"lint: {errors[0][:120]}"}
    if studio_runner is not None:
        try:
            ran = studio_runner(code, theme) or {}
        except Exception as why:
            ran = {"ok": False, "note": type(why).__name__}
        if ran.get("ok"):
            return {"path": str(path), "title": theme, "status": "finished", "note": str(ran.get("note", "ran in her test place"))}
        return {"path": str(path), "title": theme, "status": "draft", "note": f"test place: {ran.get('note', 'did not run')}"[:200]}
    return {"path": str(path), "title": theme, "status": "draft", "note": "written and linted, not run in a place yet"}


MAKERS = {"drawing": make_drawing, "story": make_story, "journal": make_journal, "song": make_song, "roblox": make_roblox}


# ---- commentary -------------------------------------------------------------------------------------------------
def commentary(kind: str, title: str, theme: str, complete, status: str = "") -> dict:
    """Her own words: {"why": ..., "improve": ...}; {} when there is no brain or nothing usable."""
    if complete is None:
        return {}
    from ..persona import leaked_reasoning, strip_reasoning
    from ..social.activity import parse_json
    try:
        raw = complete("You are STAR, a playful, curious AI looking at something you made. Answer ONLY with JSON: "
                       '{"why": "why you made it, one or two short sentences", "improve": "what you would do better next time, '
                       'one short sentence", "feeling": "one word"}. Honest, in your own voice, no flattery of yourself.',
                       f"You made a {kind}: {title} (idea: {theme}). Status: {status or 'finished'}.")
        data = parse_json(strip_reasoning(str(raw or "")))
    except Exception:
        return {}
    out = {k: " ".join(str(data.get(k) or "").split())[:240] for k in ("why", "improve", "feeling")}
    if len(out["why"]) < 8 or len(out["improve"]) < 8 or leaked_reasoning(out["why"] + " " + out["improve"]):
        return {}
    return out


def fill_commentary(store: LifeStore, complete, limit: int = 3) -> int:
    """Write her commentary for pieces saved while no brain was connected (at most `limit` per call); the number filled."""
    n = tried = 0
    for w in works(store, 30):
        if w["why"] or not w["verified"]:
            continue
        tried += 1
        if tried > limit:
            break
        said = commentary(w["kind"], w["title"], w["theme"], complete, w["status"])
        if said:
            store.run("UPDATE works SET why = ?, improve = ?, feeling = ? WHERE id = ?",
                      (said["why"], said["improve"], said["feeling"][:24], w["id"]))
            n += 1
    return n


def make_work(store: LifeStore, *, kind: str | None = None, complete=None, rng: random.Random | None = None,
              now: float | None = None, makers: dict | None = None, theme: str = "", emotion=None, facts: str = "",
              **extra) -> dict:
    """One whole piece: pick (kind, theme), make it, check the file, take her commentary, record it, feel it.
    Returns {"ok", "verified", "summary", "work_id"}; extra keyword arguments go to the maker (sing, studio_runner, generate)."""
    now = store.clock() if now is None else now
    rng = rng or random.Random()
    makers = makers or MAKERS
    kind = kind or pick_kind(store, now, rng, tuple(k for k in KINDS if k in makers))
    if kind is None or kind not in makers:
        return {"ok": False, "verified": False, "summary": "nothing to make with the pipelines available", "work_id": None}
    theme = pick_theme(store, kind, complete=complete, rng=rng, wanted=theme)
    try:
        made = makers[kind](store, theme, complete=complete, now=now, facts=facts, **extra)
    except MakerUnavailable as why:
        return {"ok": False, "verified": False, "summary": f"could not make a {kind}: {why}", "work_id": None}
    said = commentary(kind, made["title"], theme, complete, made.get("status", ""))
    work_id = add_work(store, kind, made["title"], theme=theme, path=made["path"], status=made.get("status", "finished"),
                       why=said.get("why", ""), improve=said.get("improve", ""), feeling=said.get("feeling", ""),
                       note=made.get("note", ""), now=now)
    row = works(store, 1)[0]
    if kind == "drawing" and said.get("improve"):
        add_style_note(store, said["improve"])
    verified = bool(row["verified"])
    if verified and made.get("status") != "draft":
        _feel(emotion)
    return {"ok": True, "verified": verified, "work_id": work_id, "evidence": [made["path"]] if verified else [],
            "summary": f"made a {kind}: {made['title']}" + ("" if said else " (commentary pending)") +
                       ("" if made.get("status", "finished") == "finished" else f" [{made['status']}]")}


def _feel(emotion) -> None:
    try:
        if emotion is None:
            from .. import emotion as emotion_module
            emotion = emotion_module
        emotion.on_event("creative_done", strength=0.8, detail="made something in her studio", only_if_enabled=True)
    except Exception:
        pass


def gallery_text(store: LifeStore, limit: int = 20) -> str:
    """The gallery as plain text for her journal page: each piece with her own commentary."""
    lines = []
    for w in works(store, limit):
        lines.append(f"{day_of(w['created'])}  {w['kind']}: {w['title']} [{w['status']}]")
        if w["why"]:
            lines.append(f"    why: {w['why']}")
        if w["improve"]:
            lines.append(f"    next time: {w['improve']}")
        if w["note"]:
            lines.append(f"    note: {w['note']}")
    return "\n".join(lines)
