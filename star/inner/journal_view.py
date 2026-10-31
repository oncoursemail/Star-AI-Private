"""The owner's view of her inner life: one JSON snapshot and a static page <app data>/inner/journal.html.

    python -m star.inner brain      # the snapshot as JSON
    python -m star.inner page       # (re)write journal.html and print its path

Shows today's plan (current block marked), energy, mood timeline (emotion events of the last 24 h), recent memories
(private ones and the people keys left out; names shown), insights with evidence ids, dreams, lessons, skills with
calibrated confidence, the monologue, the action-log lines of the mind, the settings, and whether STOP is on.
The page is written by the background tick (every 10 minutes at most) and is read-only: the stop is the owner's
STOP file (`python -m star.home stop`, the desktop button or Ctrl+Alt+Shift+F12).
"""
from __future__ import annotations

import html
import json
import time

from . import planner


def _when(ts: float) -> str:
    return time.strftime("%m-%d %H:%M", time.localtime(ts)) if ts else ""


def snapshot(mind, *, life=None, now: float | None = None) -> dict:
    now = mind.clock() if now is None else now
    s = mind.settings
    stream = mind.stream
    day = planner.day_of(now, int(s["wake_hour"]))
    plan = planner.load_plan(stream, day) or {"day": day, "blocks": []}
    current = planner.block_at(plan, now)
    mood = []
    try:
        if mind.emotion is not None and hasattr(mind.emotion, "default_engine"):
            mood = [{"at": _when(r["at"]), "kind": r["kind"], "strength": r["strength"]}
                    for r in mind.emotion.default_engine().history(200) if r["at"] >= now - 86400]
    except Exception:
        mood = []
    recent = [m for m in stream.all(since=now - 2 * 86400) if not m.private and m.kind != "thought"][-40:]
    view = mind.self_view(life, now)
    log = []
    if mind.life_home is not None:
        from ..home import control
        log = [r for r in control.read_log(mind.life_home, 200) if r.get("action") == "inner"][-20:]
    return {
        "now": _when(now), "stopped": mind.stopped(), "settings": s,
        "plan": {**plan, "current": current}, "energy": mind.energy.level(now),
        "summary": mind.summary(life, now) if s.get("self_summary") else "",
        "mood_timeline": mood,
        "memories": [{"id": m.id, "when": _when(m.ts), "kind": m.kind, "source": m.source, "text": m.text,
                      "people": m.names, "importance": round(m.importance, 2), "valence": round(m.valence, 2)}
                     for m in reversed(recent)],
        "insights": view["insights"],
        "dreams": [{"when": _when(m.ts), "text": m.text} for m in stream.all(kind="dream")[-7:]][::-1],
        "lessons": [m.text for m in stream.all(kind="semantic") if m.fact_key.startswith("lesson:") and not m.invalid_at],
        "skills": view["skills"], "timeline": view["timeline"][-15:],
        "monologue": [{"when": _when(t.get("ts", 0)), "thought": t.get("thought"), "why": t.get("why")}
                      for t in mind.monologue(30)][::-1],
        "actions": log, "memory_count": stream.count(),
    }


def _list(rows, render) -> str:
    return "<ul>" + "".join(f"<li>{render(r)}</li>" for r in rows) + "</ul>" if rows else "<p class=dim>nothing yet</p>"


def page(snap: dict) -> str:
    e = html.escape
    blocks = "".join(
        f"<tr class='{'now' if snap['plan'].get('current') == b else ''}'><td>{b['start']:02d}-{b['end']:02d}</td>"
        f"<td>{e(b['category'])}</td><td class=dim>{e(b['why'])}</td></tr>" for b in snap["plan"].get("blocks", []))
    sections = [
        ("Who she is right now", f"<p>{e(snap['summary']) or '<span class=dim>(summary off)</span>'}</p>"),
        ("Today's plan", f"<table>{blocks}</table><p>energy {snap['energy']:.2f}</p>" if blocks else
         "<p class=dim>no plan yet (made at her first pick after waking)</p>"),
        ("Inner monologue", _list(snap["monologue"], lambda t: f"<b>{e(t['when'])}</b> {e(t['thought'] or '')} "
                                                            f"<span class=dim>{e(t['why'] or '')}</span>")),
        ("Dreams (not real)", _list(snap["dreams"], lambda d: f"<b>{e(d['when'])}</b> {e(d['text'])}")),
        ("Insights", _list(snap["insights"], lambda i: f"{e(i['text'])} <span class=dim>evidence "
                                                         f"{e(', '.join(map(str, i['evidence'])))}</span>")),
        ("Lessons", _list(snap["lessons"], e)),
        ("Skills (calibrated from real outcomes)", _list(snap["skills"], lambda k: (
            f"{e(k['skill'])}: {k['confidence']:.2f} ({k['successes']}/{k['attempts']}"
            + (f", Brier {k['brier']}" if k.get("brier") is not None else "") + ")"))),
        ("Mood timeline (24 h)", _list(snap["mood_timeline"], lambda m: f"{e(m['at'])} {e(m['kind'])} "
                                                                       f"{m['strength']}")),
        ("Recent memories", _list(snap["memories"], lambda m: f"<b>{e(m['when'])}</b> [{e(m['kind'])}] "
                                                              f"{e(m['text'])}")),
        ("Timeline", _list(snap["timeline"], lambda t: f"{e(t['day'])} {e(t['text'])}")),
        ("Action log (inner)", _list(snap["actions"], lambda a: e(json.dumps(a, ensure_ascii=False)))),
    ]
    body = "".join(f"<section><h2>{e(t)}</h2>{c}</section>" for t, c in sections)
    stop = ("<p class=stop>STOPPED by the owner's STOP file</p>" if snap["stopped"] else
            "<p class=dim>Stop: <code>python -m star.home stop</code>, the STAR STOP desktop button or "
            "Ctrl+Alt+Shift+F12.</p>")
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>STAR journal</title><style>
:root{{--bg:#fafaf8;--fg:#1d1d1f;--dim:#6b6b70;--line:#e3e3e0;--hi:#fff4d6}}
@media (prefers-color-scheme:dark){{:root{{--bg:#141416;--fg:#ececef;--dim:#9a9aa2;--line:#2c2c30;--hi:#3a3220}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0 auto;max-width:860px;padding:16px}}
h1{{font-size:22px}}h2{{font-size:16px;margin:22px 0 6px;border-bottom:1px solid var(--line)}}
.dim{{color:var(--dim)}}.stop{{color:#c0392b;font-weight:600}}tr.now{{background:var(--hi)}}td{{padding:2px 10px 2px 0}}
ul{{padding-left:18px}}li{{margin:2px 0;overflow-wrap:anywhere}}</style></head><body>
<h1>STAR journal <span class=dim>{e(snap['now'])}, {snap['memory_count']} memories</span></h1>{stop}
<p class=dim>Her emotions, self-model and dreams are a designed simulation that shapes her behaviour.</p>{body}
</body></html>"""


def write_page(mind, *, life=None, now: float | None = None):
    path = mind.home / "inner" / "journal.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(page(snapshot(mind, life=life, now=now)), encoding="utf-8")
    tmp.replace(path)
    return path
