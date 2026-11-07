"""Opt-in 3D asset tools for STAR's agent loop (Settings: asset3d_tools_enabled).

The model picks a parametric template (star.shapes.a3d) and fills parameters, colours and material kinds; trusted
code builds the spec and validates it. The model never sends geometry, Blender code, file paths outside the
workspace, hosts or commands.

  workspace_asset3d_build  writes a NEW workspace folder with spec.json (+ job.json for the builder). Needs
                           workspace editing on. Rendering/exporting (GLB/FBX/OBJ, PBR textures, preview sheet) runs
                           only when the OPERATOR configured a builder with STAR_ASSET3D_BUILD=local|remote; the
                           fixed entry point is star/asset3d/build_bpy.py run headless on that job and nothing else.
  workspace_asset3d_check  read-only validation of a spec.json in the workspace (budgets, size, parts).

Default: no builder (offline): the result says the asset was planned but not built.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import spec as A

_PATH = {"type": "string", "minLength": 1, "maxLength": 500}
_REQUEST_WORDS = ("3d", "model", "mesh", "asset", "prop", "blender", "glb", "fbx", "obj", "low poly", "low-poly",
                  "high poly", "high-poly", "pbr", "stylized", "render", "sculpt")
MAX_SPEC_BYTES = 512_000


def _tool(name, description, properties, required):
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties,
                            "required": required, "additionalProperties": False}}


def _tools():
    from star.shapes import a3d, styles
    lines = "; ".join(f"{n} ({t.summary})" for n, t in a3d.TEMPLATES.items())
    style_doc = "; ".join(f"{k}: {v['doc']}" for k, v in styles.STYLE_PACKS.items())
    return [
        _tool("workspace_asset3d_build",
              "Build a 3D asset from a parametric template into a NEW workspace folder (spec.json; with the "
              "operator's Blender builder also GLB/FBX/OBJ with LODs, PBR textures and a 4-view preview sheet). Pick "
              "the template whose SHAPE fits and set only the parameters/colours the request needs: code builds exact, "
              "attached, symmetric parts in real-world metres, never coordinates. The result lists the template's "
              "parameters and colour roles: adjust and build again into another folder. Needs workspace editing. "
              "Styles: " + style_doc + ". Templates: " + lines,
              {"output_dir": _PATH, "template": {"type": "string", "enum": list(a3d.TEMPLATES)},
               "style": {"type": "string", "enum": list(A.STYLES),
                         "description": "omit to pick from the brief (default pbr)"},
               "brief": {"type": "string", "maxLength": 400, "description": "the request, used to pick the style"},
               "category": {"type": "string", "enum": list(A.CATEGORIES)},
               "name": {"type": "string", "maxLength": 60},
               "params": {"type": "object", "maxProperties": 24,
                          "description": "template parameters (unknown ones are ignored, values are clamped)"},
               "colors": {"type": "object", "maxProperties": 12, "description": "colour role -> #rrggbb",
                          "additionalProperties": {"type": "string", "pattern": "^#?[0-9a-fA-F]{6}$"}},
               "kinds": {"type": "object", "maxProperties": 12, "description": "colour role -> material kind",
                         "additionalProperties": {"type": "string", "enum": list(A.MATERIALS)}},
               "render": {"type": "boolean", "default": True,
                          "description": "build meshes/textures/previews when a builder is configured"}},
              ["output_dir", "template"]),
        _tool("workspace_asset3d_check",
              "Read-only check of a 3D asset spec.json in the workspace: validation, part count, size against the "
              "category's real-world range, triangle and texture budgets for its style.",
              {"path": _PATH}, ["path"]),
    ]


TOOLS = _tools()
TOOL_NAMES = frozenset(t["name"] for t in TOOLS)
WRITE_TOOLS = frozenset({"workspace_asset3d_build"})


def wants_asset3d(prompt: str) -> bool:
    text = prompt[:20000].lower() if isinstance(prompt, str) else ""
    return any(w in text for w in _REQUEST_WORDS)


def builder_mode() -> str:
    """Operator setting (environment), never the model: off (default), local or remote."""
    mode = os.environ.get("STAR_ASSET3D_BUILD", "off").strip().lower()
    return mode if mode in ("local", "remote") else "off"


class Asset3DTools:
    def __init__(self, workspace, *, enabled=False, allow_write=False):
        self.workspace = workspace
        self.enabled = enabled is True
        self.allow_write = allow_write is True

    @staticmethod
    def owns(name):
        return name in TOOL_NAMES

    def definitions(self, prompt):
        if not self.enabled or self.workspace is None or not wants_asset3d(prompt):
            return []
        return [t for t in TOOLS if self.allow_write or t["name"] not in WRITE_TOOLS]

    def call(self, name, args, *, enabled):
        if not self.enabled or self.workspace is None or name not in TOOL_NAMES or name not in enabled:
            raise PermissionError("3D asset tools are not enabled for this task")
        if name in WRITE_TOOLS and not self.allow_write:
            raise PermissionError("Workspace editing is switched off")
        from jsonschema import Draft202012Validator, ValidationError
        schema = next(t["inputSchema"] for t in TOOLS if t["name"] == name)
        try:
            Draft202012Validator(schema).validate(args)
        except ValidationError as exc:
            raise ValueError("Invalid 3D asset tool arguments") from exc
        if name == "workspace_asset3d_build":
            return build(self.workspace, args)
        return check(self.workspace, args["path"])


def _summary(spec: dict) -> dict:
    from star.shapes import a3d
    lo, hi = a3d.bounds(spec)
    b = A.budget(spec)
    dims = [round(hi[i] - lo[i], 3) for i in range(3)]
    lo_s, hi_s = b["size_range"]
    notes = []
    if not lo_s <= max(dims) <= hi_s:
        notes.append(f"longest side {max(dims)} m is outside the {spec['category']} range {lo_s}-{hi_s} m")
    return {"style": spec["style"], "category": spec["category"], "parts": len(spec["parts"]), "dims_m": dims,
            "tri_budget": b["tris"], "texture_px": b["tex"], "notes": notes}


def build(workspace, args, *, runner_build=None) -> dict:
    from star.shapes import a3d, styles
    out = workspace.resolve(args["output_dir"], allow_missing=True)
    if out.exists():
        raise FileExistsError("output_dir must be a new folder")
    style = args.get("style") or styles.style_from_brief(args.get("brief", ""))
    answer = {k: args[k] for k in ("params", "colors", "kinds", "name") if k in args}
    raw, notes = a3d.build_spec(args["template"], answer, style, args.get("category"))
    raw["style"] = style
    spec = A.ground(A.prepare(raw))  # validates every part; raises SpecError on anything malformed
    out.mkdir(parents=True)
    (out / "spec.json").write_text(json.dumps(raw, indent=1), encoding="utf-8")
    t = a3d.TEMPLATES[args["template"]]
    root = Path(workspace.root).resolve()
    res = {"name": raw["name"], "template": t.name, **_summary(raw), "clamped": notes,
           "files": {"spec": (out / "spec.json").resolve().relative_to(root).as_posix()},
           "parameters": {k: p.describe() for k, p in t.params.items()},
           "colour_roles": {k: f"{r.color} {r.kind}" for k, r in t.roles.items()}}
    mode = builder_mode()
    if not args.get("render", True) or mode == "off":
        res["built"] = False
        res["build_note"] = ("planned only: no Blender builder is configured (operator setting STAR_ASSET3D_BUILD)"
                             if mode == "off" else "planned only (render=false)")
        return res
    from . import pipeline as AP, runner
    job = AP._job("pipeline", spec, 3, tex=A.STYLE[style]["tex"], bake_samples=16, render=AP.EVAL_RENDER, final=True)
    m = (runner_build or runner.build)(job, out / "build", mode)
    res["built"] = bool(m.get("ok"))
    if not m.get("ok"):
        res["build_note"] = "builder failed: " + str(m.get("error", "unknown"))[:300]
        return res
    sheet = runner.contact_sheet(m["views"], out / "preview.jpg", tile=512)
    res["files"]["preview"] = sheet.resolve().relative_to(root).as_posix()
    for k, v in (m.get("exports") or {}).items():
        p = out / "build" / Path(str(v[0] if isinstance(v, (list, tuple)) else v)).name
        if p.exists():
            res["files"][k] = p.resolve().relative_to(root).as_posix()
    qa = m.get("qa") or {}
    res["mesh"] = {"tris": qa.get("tris"), "lod_tris": m.get("lod_tris"), "non_manifold_edges":
                   qa.get("non_manifold_edges"), "floating_parts": (m.get("contact") or {}).get("floating_parts")}
    return res


def check(workspace, relative) -> dict:
    path = workspace.resolve(relative)
    if path.suffix.lower() != ".json" or not path.is_file():
        raise ValueError("Choose a spec .json file")
    if path.stat().st_size > MAX_SPEC_BYTES:
        raise ValueError("Spec file is too large")
    raw = json.loads(path.read_text(encoding="utf-8"))
    try:
        spec = A.prepare(raw)
    except A.SpecError as exc:
        return {"path": relative, "valid": False, "error": str(exc)[:300]}
    return {"path": relative, "valid": True, **_summary(spec)}
