"""STAR's environment builder: brief + style -> layout plan -> detail pass -> checks + automatic fixes -> Studio
render -> vision critique -> revision -> final render. `baseline` is the single-pass arm used by the eval.

CLI:  python -m star.roblox_build.pipeline build --brief "..." --style lowpoly --out DIR [--arm pipeline|baseline]
      python -m star.roblox_build.pipeline check SPEC.json
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import sys
import threading
import time
from pathlib import Path

from . import checks, kits, llm, prompts, scene, sheet

STUDIO_LOCK = threading.Lock()
DEFAULT_HOME = Path.home() / ".star" / "roblox-lab-home"


# --------------------------------------------------------------------------- automatic (deterministic) fixes

def _inst_boxes(compiled: dict) -> dict:
    from .geom import aabb
    out = {}
    for p in compiled["parts"]:
        if p.get("prop") is None:
            continue
        key = (p["prop"], p.get("copy", 0))
        lo, hi = aabb(p)
        if key in out:
            a = out[key]
            out[key] = (tuple(min(a[0][k], lo[k]) for k in range(3)), tuple(max(a[1][k], hi[k]) for k in range(3)))
        else:
            out[key] = (lo, hi)
    return out


def _move_prop(spec: dict, index: int, dx: float, dz: float) -> None:
    p = spec["props"][index]
    w, d = spec["size"]
    p["at"] = [round(max(-w / 2 + 1, min(w / 2 - 1, p["at"][0] + dx)), 2),
               round(max(-d / 2 + 1, min(d / 2 - 1, p["at"][1] + dz)), 2)]


def autofix(spec: dict, rounds: int = 3) -> tuple[dict, dict, dict, list[str]]:
    """Compile, check, fix what code can fix; returns (spec, compiled, report, log)."""
    spec = copy.deepcopy(spec)
    spec["budget"] = True
    log: list[str] = []
    compiled = scene.compile_spec(spec)
    report = checks.run(spec, compiled)
    for _ in range(rounds):
        changed = False
        boxes = _inst_boxes(compiled)
        drop = set()
        for d in report["defects"]:
            code, idx = d["code"], d.get("prop")
            if code == "no_door":
                zone_id = d["detail"].split()[1]
                room = next((r for r in spec["rooms"] if r["zone"] == zone_id), None)
                zone = next((z for z in spec["zones"] if z["id"] == zone_id), None)
                if room and zone:
                    x0, z0, x1, z1 = zone["rect"]
                    sx, sz = spec["spawn"]
                    side = min((("N", abs(sz - z0)), ("S", abs(sz - z1)), ("W", abs(sx - x0)), ("E", abs(sx - x1))),
                               key=lambda s: s[1])[0]
                    room["openings"].append({"side": side, "at": 0.5, "w": 6, "h": 9, "kind": "door"})
                    log.append(f"added a door on {zone_id} {side}")
                    changed = True
            elif idx is None or idx >= len(spec["props"]):
                continue
            elif code == "floating" and "y" in spec["props"][idx]:
                spec["props"][idx].pop("y")
                log.append(f"prop {idx} put on the floor (was floating)")
                changed = True
            elif code == "floating" and spec["props"][idx]["kit"] in ("chandelier", "pendant_lamp", "string_lights"):
                drop.add(idx)
            elif code == "prop_overlap":
                a, b = boxes.get((d["other"], 0)), boxes.get((idx, d.get("copy", 0)))
                if a and b:
                    ox = min(a[1][0], b[1][0]) - max(a[0][0], b[0][0])
                    oz = min(a[1][2], b[1][2]) - max(a[0][2], b[0][2])
                    bc = ((b[0][0] + b[1][0]) / 2, (b[0][2] + b[1][2]) / 2)
                    ac = ((a[0][0] + a[1][0]) / 2, (a[0][2] + a[1][2]) / 2)
                    if ox < oz:
                        _move_prop(spec, idx, math.copysign(ox + 0.5, bc[0] - ac[0] or 1), 0)
                    else:
                        _move_prop(spec, idx, 0, math.copysign(oz + 0.5, bc[1] - ac[1] or 1))
                    log.append(f"prop {idx} moved off prop {d['other']}")
                    changed = True
            elif code == "wall_clip":
                b = boxes.get((idx, d.get("copy", 0)))
                zone = scene.zone_at(spec, *spec["props"][idx]["at"])
                if b and zone:
                    x0, z0, x1, z1 = zone["rect"]
                    cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
                    px, pz = spec["props"][idx]["at"]
                    dist = math.hypot(cx - px, cz - pz) or 1
                    _move_prop(spec, idx, (cx - px) / dist * 2, (cz - pz) / dist * 2)
                    log.append(f"prop {idx} moved away from the wall")
                    changed = True
            elif code == "through_roof":
                params = spec["props"][idx]["params"]
                room_h = float(d["detail"].rsplit(" ", 1)[-1])
                if "h" in params:
                    params["h"] = max(2.0, room_h - 3)
                    log.append(f"prop {idx} height cut to fit under the roof")
                else:
                    drop.add(idx)
                changed = True
        # blocked route: push props out of the spawn->focal corridor
        if any(d["code"] in ("unreachable", "spawn_blocked") for d in report["defects"]):
            sx, sz = spec["spawn"]
            for f in spec["focal"]:
                fx, fz = f["at"]
                length = math.hypot(fx - sx, fz - sz) or 1
                ux, uz = (fx - sx) / length, (fz - sz) / length
                for (i, _copy), b in boxes.items():
                    if i in drop or spec["props"][i].get("repeat") or b[1][1] - b[0][1] < 2:
                        continue
                    cx, cz = (b[0][0] + b[1][0]) / 2, (b[0][2] + b[1][2]) / 2
                    along = (cx - sx) * ux + (cz - sz) * uz
                    if not 0 < along < length - 4:
                        continue
                    across = -(cx - sx) * uz + (cz - sz) * ux
                    half = max(b[1][0] - b[0][0], b[1][2] - b[0][2]) / 2
                    if abs(across) < half + 3:
                        push = math.copysign(half + 3.5 - abs(across), across or 1)
                        _move_prop(spec, i, -uz * push, ux * push)
                        log.append(f"prop {i} moved out of the route to {f['id']}")
                        changed = True
        if drop:
            spec["props"] = [p for i, p in enumerate(spec["props"]) if i not in drop]
            log.append(f"removed props {sorted(drop)}")
            changed = True
        if not changed:
            break
        compiled = scene.compile_spec(spec)
        report = checks.run(spec, compiled)
    return spec, compiled, report, log


LIGHT_KITS = {name for name, info in kits.KITS.items() if "light" in info.get("tags", ())}


def dress(spec: dict) -> tuple[dict, list[str]]:
    """Art-direction rules STAR applies after the detail pass: a light pool at every focal point, and for abandoned
    rooms a little intentional decay in the corners (cobwebs) - never spread everywhere."""
    spec = copy.deepcopy(spec)
    log = []
    lights = [p for p in spec["props"] if p["kit"] in LIGHT_KITS]
    for f in spec["focal"]:
        fx, fz = f["at"]
        if any(math.hypot(p["at"][0] - fx, p["at"][1] - fz) < 12 for p in lights):
            continue
        room, _rect = scene._room_rect(spec, fx, fz)
        if room and room["roof"] != "none":
            kit_name = "candles" if spec["state"] == "abandoned" else "pendant_lamp"
            prop = {"kit": kit_name, "at": [fx + 2.5, fz + 2.5], "params": {"y": room["h"]} if kit_name == "pendant_lamp" else {}}
        else:
            prop = {"kit": "lamp_post", "at": [fx + 5, fz + 3], "params": {"color": "warm"}}
        spec["props"].append({**prop, "rot": 0, "why": f"light pool at {f['id']}"})
        log.append(f"added {prop['kit']} at focal {f['id']}")
    if spec["state"] == "abandoned":
        t = scene.WALL_T[spec["style"]]
        for room in spec["rooms"][:3]:
            if room["roof"] == "none":
                continue
            zone = next(z for z in spec["zones"] if z["id"] == room["zone"])
            x0, z0, x1, z1 = zone["rect"]
            for cx, cz in ((x0 + t + 1.5, z0 + t + 1.5), (x1 - t - 1.5, z0 + t + 1.5)):
                spec["props"].append({"kit": "cobweb", "at": [cx, cz], "rot": 0, "params": {"y": room["h"] - 1, "s": 4},
                                      "why": "decay in the corner"})
            log.append(f"cobwebs in {room['zone']}")
    norm, _notes = scene.normalize(spec)
    return norm, log


# --------------------------------------------------------------------------- model stages

def _ask(messages, **kw) -> tuple[dict | None, dict]:
    text, meta = llm.chat(messages, **kw)
    value = llm.parse_json(text)
    meta["chars"] = len(text)
    if value is None:
        meta["bad_text"] = text[:600] + " ... " + text[-400:]
    if value is None:
        text, meta2 = llm.chat(messages + [{"role": "assistant", "content": text[:2000]},
                                           {"role": "user", "content": "That was not valid JSON. Answer again with one valid JSON object only."}], **kw)
        value = llm.parse_json(text)
        meta["retry"] = meta2
    return value, meta


def plan_and_detail(brief: str, style: str) -> tuple[dict, dict]:
    """Layout plan first, then one detail call per zone (each fits the node's 4k context)."""
    plan, m1 = _ask(prompts.plan_messages(brief, style), max_tokens=1400)
    plan = plan or {}
    plan["style"] = style
    norm, _ = scene.normalize(dict(plan, props=[]))
    metas = {"plan": m1, "story": plan.get("story"), "detail": []}
    props: list = []
    zones = norm["zones"] or [None]
    for zone in zones[:6]:
        detail, m2 = _ask(prompts.detail_messages(brief, style, plan, zone), max_tokens=1800)
        got = (detail or {}).get("props") or []
        if zone:   # keep entries inside (or within 2 studs of) the zone they were asked for
            x0, z0, x1, z1 = zone["rect"]
            kept = []
            for row in got:
                p = scene.prop_from_list(row) if isinstance(row, list) else row
                at = p.get("at") if isinstance(p, dict) else None
                try:
                    if at and x0 - 2 <= float(at[0]) <= x1 + 2 and z0 - 2 <= float(at[1]) <= z1 + 2:
                        kept.append(p)
                except (TypeError, ValueError, IndexError):
                    continue
            got = kept
        props += got
        metas["detail"].append({"zone": zone["id"] if zone else None, "n": len(got), **m2})
    raw = dict(plan)
    raw["props"] = props
    return raw, metas


def baseline_spec(brief: str, style: str) -> tuple[dict, dict]:
    raw, meta = _ask(prompts.baseline_messages(brief, style), max_tokens=2400)
    raw = raw or {}
    raw["style"] = style
    return raw, {"single": meta}


def props_text(spec: dict, limit: int = 90) -> str:
    return "\n".join(f"{i}: {p['kit']} at {p['at']}" + (f" x{p['repeat']['n']}" if p.get("repeat") else "")
                     for i, p in enumerate(spec["props"][:limit]))


def critique(brief: str, style: str, spec: dict, report: dict, sheet_path: Path, shots: list[str] | None = None,
             vision_max_load: int = 4) -> tuple[dict | None, dict]:
    """Art-lead critique. Vision model (star-fast) when its host is not overloaded; otherwise a text critique by
    STAR's fast model from measured image facts (exposure, contrast, empty frame share) + scene metrics."""
    metrics = {k: report["metrics"].get(k) for k in ("parts", "lights", "props", "floating_parts", "prop_overlaps",
                                                     "z_fighting", "unreachable_focal", "density")}
    facts = {}
    for f in shots or []:
        try:
            m = sheet.shot_metrics(f)
            facts[Path(f).stem.split("-")[-1]] = {"facts": m, "notes": sheet.describe(m)}
        except Exception:
            continue
    load = llm.brain_load()
    if load is not None and load <= vision_max_load:
        msgs = prompts.critic_messages(brief, style, llm.image_part(sheet_path, 1024), props_text(spec), metrics)
        value, meta = _ask(msgs, model=llm.VISION_MODEL, max_tokens=1200, temperature=0.2, json_mode=False, timeout=900,
                           first_token_s=600)
        meta["critic"] = "vision"
    else:
        msgs = prompts.metric_critic_messages(brief, style, spec, props_text(spec), metrics, facts)
        value, meta = _ask(msgs, max_tokens=900, temperature=0.2)
        meta["critic"] = f"metrics (brain load {load})"
    if value is not None:
        value["shot_facts"] = facts
    return value, meta


def _op_from_keyed(op: dict) -> dict | None:
    """Model variants like {"move": 3, "x": 1, "z": 2}, {"remove": 4}, {"add": "table", "x": .., "z": .., "params": {}}."""
    def at():
        if "at" in op:
            return op["at"]
        return [op.get("x"), op.get("z")]
    try:
        if "add" in op:
            kit = op["add"] if isinstance(op["add"], str) else op.get("kit")
            prop = {"kit": kit, "at": at(), "rot": op.get("rot", 0), "params": dict(op.get("params") or {})}
            if "y" in op:
                prop["y"] = op["y"]
            return {"op": "add", "prop": prop}
        if "move" in op:
            return {"op": "move", "index": int(op["move"]), "at": at()}
        if "remove" in op:
            return {"op": "remove", "index": int(op["remove"])}
        if "rotate" in op:
            return {"op": "rotate", "index": int(op["rotate"]), "rot": op.get("rot", op.get("deg", 0))}
        if "params" in op and isinstance(op.get("index"), int):
            return {"op": "params", "index": op["index"], "params": op["params"]}
        for field in ("mood", "state", "ground"):
            if field in op:
                return {"op": "set", "field": field, "value": op[field]}
        if "door" in op:
            return {"op": "opening", "zone": op["door"], "opening": {"side": op.get("side", "S"), "at": 0.5, "w": 6, "h": 9,
                                                                    "kind": "door"}}
    except (TypeError, ValueError):
        return None
    return None


def _op_from_list(op: list) -> dict | None:
    kind, a = op[0], op[1:]
    try:
        if kind == "add":
            return {"op": "add", "prop": scene.prop_from_list(a)}
        if kind == "move":
            return {"op": "move", "index": int(a[0]), "at": [a[1], a[2]]}
        if kind in ("remove",):
            return {"op": "remove", "index": int(a[0])}
        if kind == "params":
            return {"op": "params", "index": int(a[0]), "params": a[1]}
        if kind == "rotate":
            return {"op": "rotate", "index": int(a[0]), "rot": a[1]}
        if kind in ("mood", "state", "ground"):
            return {"op": "set", "field": kind, "value": a[0]}
        if kind == "room":
            return {"op": "room", "zone": a[0], "field": a[1], "value": a[2]}
        if kind == "door":
            return {"op": "opening", "zone": a[0], "opening": {"side": a[1], "at": 0.5, "w": 6, "h": 9, "kind": "door"}}
    except (IndexError, TypeError, ValueError):
        return None
    return None


def apply_ops(spec: dict, ops: list) -> tuple[dict, list[str]]:
    spec = copy.deepcopy(spec)
    log: list[str] = []
    removed = set()
    added = []
    for op in ops if isinstance(ops, list) else []:
        if isinstance(op, list) and op and isinstance(op[0], str):
            op = _op_from_list(op)
        elif isinstance(op, dict) and "op" not in op:
            op = _op_from_keyed(op)
        if not isinstance(op, dict):
            continue
        kind, idx = op.get("op"), op.get("index")
        valid_idx = isinstance(idx, int) and 0 <= idx < len(spec["props"])
        try:
            if kind == "add" and isinstance(op.get("prop"), dict):
                added.append(op["prop"])
            elif kind == "move" and valid_idx:
                spec["props"][idx]["at"] = op["at"]
            elif kind == "rotate" and valid_idx:
                spec["props"][idx]["rot"] = float(op["rot"])
            elif kind == "remove" and valid_idx:
                removed.add(idx)
            elif kind == "params" and valid_idx and isinstance(op.get("params"), dict):
                spec["props"][idx]["params"] = {**spec["props"][idx]["params"], **op["params"]}
            elif kind == "set" and op.get("field") in ("mood", "state", "ground", "palette"):
                spec[op["field"]] = op.get("value")
            elif kind == "room":
                room = next((r for r in spec["rooms"] if r["zone"] == op.get("zone")), None)
                if room and op.get("field") in ("h", "roof", "windows", "wall"):
                    room[op["field"]] = op.get("value")
            elif kind == "opening":
                room = next((r for r in spec["rooms"] if r["zone"] == op.get("zone")), None)
                if room and isinstance(op.get("opening"), dict):
                    room["openings"].append(op["opening"])
            else:
                continue
            log.append(json.dumps(op)[:160])
        except (KeyError, TypeError, ValueError):
            continue
    spec["props"] = [p for i, p in enumerate(spec["props"]) if i not in removed] + added
    # re-normalise (clamps values, drops unknown kits)
    norm, notes = scene.normalize(spec)
    return norm, log + [f"note: {n}" for n in notes]


def redo_zone(brief: str, style: str, spec: dict, report: dict, crit: dict | None, defects: list[str]):
    """Revision step: re-dress the weakest zone (the one the critique names, else the emptiest) with the critique's
    problems and fixes as notes; the other zones stay as they are."""
    zones = spec["zones"]
    if not zones:
        return spec, [], {}
    text = json.dumps(crit or {}).lower()
    named = [z for z in zones if z["id"].lower() in text]
    density = report["metrics"].get("density", {})
    target = (named or sorted(zones, key=lambda z: density.get(z["id"], 0)))[0]
    notes = "; ".join([str(x) for x in ((crit or {}).get("problems") or [])[:4] + ((crit or {}).get("fixes") or [])[:4]]
                      + [d for d in defects if target["id"] in d][:3])[:900]
    plan = {k: spec.get(k) for k in ("size", "mood", "state", "zones", "rooms", "spawn", "focal", "paths")}
    detail, meta = _ask(prompts.detail_messages(brief, style, plan, target, notes), max_tokens=1800)
    rows = (detail or {}).get("props") or []
    new_props = []
    for row in rows:
        p = scene.prop_from_list(row) if isinstance(row, list) else row
        if isinstance(p, dict) and p.get("at") is not None:
            new_props.append(p)
    if not new_props:
        return spec, [], meta
    keep = [p for p in spec["props"] if (scene.zone_at(spec, *p["at"]) or {}).get("id") != target["id"]]
    new = copy.deepcopy(spec)
    new["props"] = keep + new_props
    norm, notes2 = scene.normalize(new)
    return norm, [f"re-dressed zone {target['id']}: {len(spec['props']) - len(keep)} -> {len(new_props)} props"], meta


# --------------------------------------------------------------------------- orchestration

def render(home: Path, spec: dict, compiled: dict, folder: Path, label: str) -> dict:
    from . import studio_run
    with STUDIO_LOCK:
        for attempt in range(4):   # the place pin can fail transiently while another client talks to Studio
            try:
                result = studio_run.render_sync(home, spec["name"].replace(" ", "_")[:30] or "Build", compiled, folder, label)
                break
            except RuntimeError:
                if attempt == 3:
                    raise
                time.sleep(20 + 20 * attempt)
    shots = [s["file"] for s in result["shots"] if s.get("ok")]
    order = {"hero": 0, "wide": 1, "detail": 2, "overview": 3}
    shots.sort(key=lambda f: order.get(Path(f).stem.split("-")[-1], 9))
    result["sheet"] = str(sheet.grid(shots, folder / f"{label}-sheet.jpg", cell=(726, 398))) if shots else None
    return result


def _record(folder: Path, name: str, data) -> None:
    (folder / name).write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")


def build(brief: str, style: str, out: Path, *, arm: str = "pipeline", home: Path = DEFAULT_HOME, rounds: int = 1,
          log=print) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    result: dict = {"brief": brief, "style": style, "arm": arm, "timings": {}}
    t = time.monotonic()
    raw, meta = baseline_spec(brief, style) if arm == "baseline" else plan_and_detail(brief, style)
    result["timings"]["generate"] = round(time.monotonic() - t, 1)
    result["gen_meta"] = meta
    _record(out, "raw.json", raw)
    spec, notes = scene.normalize(raw)
    result["normalize_notes"] = notes
    if arm == "baseline":
        compiled = scene.compile_spec(spec)
        report = checks.run(spec, compiled)
        fixlog: list[str] = []
    else:
        spec, dresslog = dress(spec)
        spec, compiled, report, fixlog = autofix(spec)
        fixlog = dresslog + fixlog
    result["autofix"] = fixlog
    _record(out, "spec-v1.json", spec)
    t = time.monotonic()
    rendered = render(home, spec, compiled, out, "v1")
    result["timings"]["render_v1"] = round(time.monotonic() - t, 1)
    result["v1"] = {"metrics": report["metrics"], "defects": [d["detail"] for d in report["defects"]][:20],
                    "severity": report["severity_sum"], "sheet": rendered.get("sheet"), "apply": rendered["apply"]}
    log(f"[{arm}] v1 rendered: {report['metrics']['parts']} parts, severity {report['severity_sum']}")
    final = {"spec": spec, "report": report, "sheet": rendered.get("sheet"), "label": "v1",
             "shots": [s["file"] for s in rendered["shots"] if s.get("ok")]}
    if arm == "pipeline":
        for r in range(rounds):
            t = time.monotonic()
            crit, cmeta = critique(brief, style, final["spec"], final["report"], Path(final["sheet"]),
                                   final.get("shots")) if final["sheet"] else (None, {})
            result[f"critic_meta_{r + 1}"] = cmeta
            result["timings"][f"critique_{r + 1}"] = round(time.monotonic() - t, 1)
            result[f"critique_{r + 1}"] = crit
            log(f"[{arm}] critique {r + 1}: overall {crit.get('overall') if crit else None}")
            t = time.monotonic()
            defects = [d["detail"] for d in final["report"]["defects"]][:15]
            new_spec, oplog, rmeta = redo_zone(brief, style, final["spec"], final["report"], crit, defects)
            new_spec, compiled2, report2, fixlog2 = autofix(new_spec)
            result["timings"][f"revise_{r + 1}"] = round(time.monotonic() - t, 1)
            result[f"revise_{r + 1}"] = {"ops": oplog, "autofix": fixlog2, "meta": rmeta}
            label = f"v{r + 2}"
            _record(out, f"spec-{label}.json", new_spec)
            try:
                rendered2 = render(home, new_spec, compiled2, out, label)
            except RuntimeError as error:   # Studio refused the revision render: keep the rendered v1
                result[label] = {"error": repr(error)[:300]}
                log(f"[{arm}] {label}: render failed, keeping {final['label']}")
                break
            result[label] = {"metrics": report2["metrics"], "defects": [d["detail"] for d in report2["defects"]][:20],
                             "severity": report2["severity_sum"], "sheet": rendered2.get("sheet")}
            # keep the revision when the same critic rates it at least as well and nothing measurable got worse
            shots2 = [s_["file"] for s_ in rendered2["shots"] if s_.get("ok")]
            crit2, _m = critique(brief, style, new_spec, report2, Path(rendered2["sheet"]), shots2) if rendered2.get("sheet")                 else (None, {})
            result[f"critique_{label}"] = crit2

            def _overall(c):
                try:
                    return float((c or {}).get("overall") or 0)
                except (TypeError, ValueError):
                    return 0.0
            better_eye = _overall(crit2) >= _overall(crit)
            if rendered2.get("sheet") and better_eye and report2["severity_sum"] <= final["report"]["severity_sum"] + 2:
                final = {"spec": new_spec, "report": report2, "sheet": rendered2.get("sheet"), "label": label,
                         "shots": [s["file"] for s in rendered2["shots"] if s.get("ok")]}
            log(f"[{arm}] {label}: {len(oplog)} ops, severity {report2['severity_sum']}, kept={final['label'] == label}")
    result["final"] = {"label": final["label"], "sheet": final["sheet"], "severity": final["report"]["severity_sum"],
                       "metrics": final["report"]["metrics"]}
    result["timings"]["total"] = round(time.monotonic() - started, 1)
    _record(out, "result.json", result)
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="STAR Roblox environment builder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--brief", required=True)
    b.add_argument("--style", required=True, choices=["stud", "lowpoly", "midpoly", "highpoly"])
    b.add_argument("--out", required=True)
    b.add_argument("--arm", default="pipeline", choices=["pipeline", "baseline"])
    b.add_argument("--rounds", type=int, default=1)
    b.add_argument("--home", default=str(DEFAULT_HOME))
    c = sub.add_parser("check")
    c.add_argument("spec")
    sub.add_parser("catalog")
    a = ap.parse_args(argv)
    if a.cmd == "catalog":
        print(kits.catalog())
        return 0
    if a.cmd == "check":
        spec, notes = scene.normalize(json.loads(Path(a.spec).read_text(encoding="utf-8")))
        compiled = scene.compile_spec(spec)
        report = checks.run(spec, compiled)
        print(json.dumps({"notes": notes, "metrics": report["metrics"], "defects": report["defects"][:30]}, indent=1))
        return 0 if report["ok"] else 1
    result = build(a.brief, a.style, Path(a.out), arm=a.arm, home=Path(a.home), rounds=a.rounds)
    print(json.dumps(result["final"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
