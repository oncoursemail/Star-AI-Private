"""Render critique (vision model vs a written rubric) and deterministic QA notes from the builder metrics."""
from __future__ import annotations

from . import llm
from .spec import budget

RUBRIC = """You are a strict senior 3D art director reviewing a game-ready prop for a portfolio.
Four studio renders of ONE asset: top-left 3/4 front, top-right side, bottom-left 3/4 back, bottom-right from above.
Brief: {brief}
Style asked: {style}. Parts (ids): {parts}
Score 1-10 each (10 = AAA portfolio, 5 = acceptable indie, 2 = broken):
- silhouette: reads instantly as the brief from the side and 3/4 views
- proportion: real-world proportions and scale between parts
- edges: bevels/edge quality, no blobby or melted geometry, no floating or intersecting junk
- detail: secondary/tertiary detail density where it belongs (not uniform, not noisy)
- materials: believable materials and colours for the style, no noise slop
- style: consistent with the asked style
Then list the 3-6 most important problems, each with the part id (or area) and a concrete geometric fix
(move/resize/add/remove which part, by how much, in metres).
Answer JSON only: {{"scores": {{"silhouette": n, "proportion": n, "edges": n, "detail": n, "materials": n,
"style": n}}, "overall": n, "issues": [{{"part": "...", "problem": "...", "fix": "..."}}]}}"""


def critique(sheet_path: str, brief: dict, part_ids: list[str], model: str = "star-fast") -> tuple[dict, dict]:
    prompt = RUBRIC.format(brief=brief["brief"], style=brief["style"], parts=", ".join(part_ids[:60]))
    msgs = [{"role": "user", "content": [{"type": "text", "text": prompt}, llm.image_part(sheet_path)]}]
    text, meta = llm.chat(model, msgs, max_tokens=900, temperature=0.1, json_mode=True)
    try:
        data = llm.extract_json(text)
    except ValueError:
        data = {"overall": None, "issues": [], "raw": text[:500]}
    ov = data.get("overall")
    sc = data.get("scores") if isinstance(data.get("scores"), dict) else {}
    nums = [v for v in sc.values() if isinstance(v, (int, float))]
    if not isinstance(ov, (int, float)) and nums:
        data["overall"] = round(sum(nums) / len(nums), 1)
    return data, meta


def qa_notes(metrics: dict, spec: dict) -> tuple[list[str], int]:
    """Deterministic problems the model should fix, plus a penalty count used when picking the best round."""
    notes, pen = [], 0
    b = budget(spec)
    for e in metrics.get("part_errors", [])[:5]:
        notes.append(f"part failed to build: {e}")
        pen += 1
    fl = metrics.get("contact", {}).get("floating_parts", [])
    if fl:
        notes.append("floating parts (touch nothing; move them so they overlap a neighbour): " + ", ".join(fl[:10]))
        pen += min(3, len(fl))
    qa = metrics.get("qa", {})
    tris = qa.get("tris", 0)
    if tris > b["tris"] * 1.15:
        notes.append(f"too many triangles: {tris} > budget {b['tris']} (fewer round parts, fewer cuts)")
        pen += 1
    if spec["style"] == "roblox" and tris > b["mesh_tris"]:
        notes.append(f"Roblox mesh limit exceeded: {tris} > {b['mesh_tris']}")
        pen += 2
    dims = metrics.get("dims") or [0, 0, 0]
    lo, hi = b["size_range"]
    longest = max(dims)
    if not lo <= longest <= hi:
        notes.append(f"overall size {longest:.2f} m is outside the real range {lo}-{hi} m for a {spec['category']}")
        pen += 1
    sd = spec.get("dims")
    if sd and longest > 0 and not 0.7 <= longest / max(sd) <= 1.4:
        notes.append(f"built size {[round(d, 2) for d in dims]} differs from your dims {sd}")
        pen += 1
    nm = qa.get("non_manifold_edges", 0)
    if tris and nm > 0.05 * tris:
        notes.append(f"{nm} non-manifold edges (overlapping cuts or thin walls)")
        pen += 1
    uv = qa.get("uv") or {}
    if uv.get("overlap_ratio", 0) > 0.03:
        notes.append(f"UV overlap {uv['overlap_ratio']:.1%}")
        pen += 1
    return notes, pen


def deterministic_pass(metrics: dict, spec: dict, tex_expected: int) -> dict:
    """Pass/fail table for the report (game-readiness checks)."""
    qa = metrics.get("qa", {})
    uv = qa.get("uv") or {}
    b = budget(spec)
    checks = {
        "built_all_parts": not metrics.get("part_errors"),
        "no_floating_parts": not metrics.get("contact", {}).get("floating_parts"),
        "tri_budget": qa.get("tris", 0) <= b["tris"] * 1.15,
        "roblox_mesh_limit": qa.get("tris", 0) <= b["mesh_tris"] if spec["style"] == "roblox" else True,
        "uv_overlap_below_3pct": uv.get("overlap_ratio", 1) <= 0.03,
        "uv_in_bounds": uv.get("out_of_bounds_tris", 1) == 0,
        "texel_density_even": uv.get("texel_p90_over_p10", 99) <= 1.5,
        "map_resolution": metrics.get("tex") == tex_expected,
        "real_world_size": b["size_range"][0] <= max(metrics.get("dims") or [0]) <= b["size_range"][1],
        "zero_area_faces": qa.get("zero_area_faces", 1) == 0,
    }
    return checks
