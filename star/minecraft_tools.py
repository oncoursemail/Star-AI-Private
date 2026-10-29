"""Opt-in Minecraft asset tools for STAR's agent loop (Settings: minecraft_tools_enabled).

Offline and workspace-confined: no network, no server connection or scan, no Java or JAR
execution, no downloads. Inspection covers only the folder the user names; the two write tools
also need workspace editing to be on. Output may quote file names and plugin metadata, so the
agent treats the read tools as untrusted-source tools.
"""
from __future__ import annotations

from pathlib import Path
import re

from . import minecraft_assets, minecraft_server_inventory
from .blockbench import spec as bb_spec

_VERSIONS = sorted(minecraft_assets.RESOURCE_FORMATS, key=lambda v: [int(p) for p in v.split(".")])
_PATH = {"type": "string", "minLength": 1, "maxLength": 500}
_REQUEST = re.compile(
    r"minecraft|blockbench|\.bbmodel|pack\.mcmeta|resource[- ]?pack|(?:paper|spigot|bukkit|folia|purpur)\s+"
    r"(?:server|plugin)|fabric\s+mod|neoforge|\bnexo\b|\boraxen\b|itemsadder|geyser", re.I)


def _tool(name, description, properties, required):
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties,
                            "required": required, "additionalProperties": False}}


TOOLS = [
    _tool("workspace_minecraft_audit",
          "Offline read-only check of a Minecraft Java resource-pack folder or ZIP, or a Blockbench .bbmodel, "
          "inside the selected workspace: manifest, models, references, textures, unsafe ZIP entries. "
          "Launches nothing and installs nothing.",
          {"path": _PATH, "target_version": {"type": "string", "enum": _VERSIONS, "default": "26.3"}},
          ["path"]),
    _tool("workspace_minecraft_inspect",
          "Static, read-only inventory of ONE Minecraft server or project folder that the user named (plugin and mod "
          "JAR metadata, server family hints, pack managers, a short allowlist of server.properties). Never "
          "contacts a server, scans a network, runs a JAR or returns credentials; do not guess folders.",
          {"path": _PATH}, ["path"]),
    _tool("workspace_minecraft_package",
          "Build a deterministic ZIP from a validated Minecraft Java resource-pack folder. Needs workspace editing "
          "switched on. Never deploys, and refuses to replace an existing ZIP unless replace is true.",
          {"path": _PATH, "output": _PATH, "target_version": {"type": "string", "enum": _VERSIONS},
           "replace": {"type": "boolean", "default": False}},
          ["path", "output", "target_version"]),
    _tool("workspace_minecraft_item_scaffold",
          "Create a version-pinned Java custom 2D item resource pack from the user's own PNG texture. Needs "
          "workspace editing switched on; the output folder must be new. No placeholder art, no deployment.",
          {"output_dir": _PATH, "namespace": {"type": "string", "maxLength": 64},
           "item_id": {"type": "string", "maxLength": 64}, "texture_path": _PATH,
           "target_version": {"type": "string", "enum": _VERSIONS},
           "description": {"type": "string", "minLength": 1, "maxLength": 140}},
          ["output_dir", "namespace", "item_id", "texture_path", "target_version"]),
]
_VEC = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
_SPEC = {
    "type": "object", "required": ["name", "category", "materials", "parts"],
    "description": "Model plan. 16 units = 1 block; x/z centred on 0, y=0 is the ground; the front faces north (-z).",
    "properties": {
        "name": {"type": "string", "maxLength": 48},
        "category": {"type": "string", "enum": list(bb_spec.CATEGORIES),
                     "description": "block/item/furniture -> Java model; mob/entity/armor -> Bedrock + animations"},
        "density": {"type": "integer", "enum": [1, 2], "description": "texels per unit (1 = vanilla 16x)"},
        "materials": {"type": "object", "maxProperties": 12, "additionalProperties": {
            "type": "object", "required": ["kind", "color"],
            "properties": {"kind": {"type": "string", "enum": list(bb_spec.KINDS)},
                           "color": {"type": "string", "pattern": "^#?[0-9a-fA-F]{6}$"}}}},
        "parts": {"type": "array", "minItems": 1, "maxItems": 160, "items": {
            "type": "object", "required": ["name", "from", "to", "material"],
            "properties": {"name": {"type": "string"}, "from": _VEC, "to": _VEC, "material": {"type": "string"},
                           "parent": {"type": "string"}, "pivot": _VEC, "rotation": _VEC,
                           "mirror_of": {"type": "string"}, "inflate": {"type": "number"},
                           "decals": {"type": "array", "maxItems": 8, "items": {
                               "type": "object", "required": ["face", "kind"],
                               "properties": {"face": {"type": "string", "enum": list(bb_spec.FACES)},
                                              "kind": {"type": "string", "enum": list(bb_spec.DECALS)},
                                              "color": {"type": "string"}}}}}}},
        "animations": {"type": "array", "maxItems": 8, "description":
                       "[{name, length, loop, bones: {part: {rotation|position|scale: {time: [x,y,z]}}}}]",
                       "items": {"type": "object"}},
    },
}
TOOLS += [
    _tool("workspace_minecraft_model_build",
          "Build a Minecraft model from a cuboid plan into a NEW workspace folder: Blockbench .bbmodel, Java model "
          "+ resource pack (block/item/furniture) or Bedrock geometry + animations (mob/entity/armor), a pixel-art "
          "texture, preview renders and quality checks (texel density, palette, z-fighting, floating parts). "
          "Fix what the checks report and build again. Needs workspace editing switched on.",
          {"output_dir": _PATH, "spec": _SPEC,
           "target_version": {"type": "string", "enum": _VERSIONS, "default": "26.3"}},
          ["output_dir", "spec"]),
    _tool("workspace_minecraft_model_check",
          "Read-only quality check of a Blockbench .bbmodel in the workspace: texel density, palette size, "
          "noise, partial alpha, UV bounds/overlap, z-fighting, floating parts, Java/Bedrock limits.",
          {"path": _PATH}, ["path"]),
]
TOOL_NAMES = frozenset(t["name"] for t in TOOLS)
WRITE_TOOLS = frozenset({"workspace_minecraft_package", "workspace_minecraft_item_scaffold",
                         "workspace_minecraft_model_build"})
READ_TOOLS = TOOL_NAMES - WRITE_TOOLS


def wants_minecraft(prompt: str) -> bool:
    return isinstance(prompt, str) and bool(_REQUEST.search(prompt[:20000]))


class MinecraftTools:
    def __init__(self, workspace, *, enabled=False, allow_write=False):
        self.workspace = workspace
        self.enabled = enabled is True
        self.allow_write = allow_write is True

    @staticmethod
    def owns(name):
        return name in TOOL_NAMES

    def definitions(self, prompt):
        if not self.enabled or self.workspace is None or not wants_minecraft(prompt):
            return []
        return [t for t in TOOLS if self.allow_write or t["name"] not in WRITE_TOOLS]

    def call(self, name, args, *, enabled):
        if not self.enabled or self.workspace is None or name not in TOOL_NAMES or name not in enabled:
            raise PermissionError("Minecraft tools are not enabled for this task")
        if name in WRITE_TOOLS and not self.allow_write:
            raise PermissionError("Workspace editing is switched off")
        from jsonschema import Draft202012Validator, ValidationError
        schema = next(t["inputSchema"] for t in TOOLS if t["name"] == name)
        try:
            Draft202012Validator(schema).validate(args)
        except ValidationError as exc:
            raise ValueError("Invalid Minecraft tool arguments") from exc
        if name == "workspace_minecraft_audit":
            return minecraft_assets.audit(self.workspace, args["path"],
                                          target_version=args.get("target_version", "26.3"))
        if name == "workspace_minecraft_inspect":
            return minecraft_server_inventory.inspect(self.workspace, args["path"])
        if name == "workspace_minecraft_model_build":
            return _model_build(self.workspace, args)
        if name == "workspace_minecraft_model_check":
            return _model_check(self.workspace, args["path"])
        if name == "workspace_minecraft_package":
            return minecraft_assets.package(self.workspace, args["path"], args["output"],
                                            target_version=args["target_version"],
                                            replace=args.get("replace", False))
        return minecraft_assets.scaffold_item(
            self.workspace, args["output_dir"], namespace=args["namespace"], item_id=args["item_id"],
            texture_path=args["texture_path"], target_version=args["target_version"],
            description=args.get("description", "Minecraft custom items"))


def _model_build(workspace, args):
    from .blockbench import build, checks, render
    out = workspace.resolve(args["output_dir"], allow_missing=True)
    if out.exists():
        raise FileExistsError("output_dir must be a new folder")
    spec, fixes = bb_spec.normalize(args["spec"])
    built = build.build(spec)
    paths = build.write_outputs(spec, built, out, pack_version=args.get("target_version", "26.3"))
    report = checks.check(built["bbmodel"])
    views = render.previews(built["bbmodel"], size=320)
    sheet = out / f"{spec['name']}_views.png"
    render.sheet(list(views.values()), list(views), title=spec["name"]).save(sheet)
    root = Path(workspace.root).resolve()
    rel = {k: Path(v).resolve().relative_to(root).as_posix() for k, v in paths.items()}
    return {"name": spec["name"], "format": built["format"], "files": rel, "previews": str(sheet.name),
            "auto_fixes": fixes, "checks": report, "tested_in_game": False}


def _model_check(workspace, relative):
    import json
    from .blockbench import checks
    path = workspace.resolve(relative)
    if path.suffix.lower() != ".bbmodel" or not path.is_file():
        raise ValueError("Choose a Blockbench .bbmodel file")
    if path.stat().st_size > minecraft_assets.MAX_BBMODEL_BYTES:
        raise ValueError("Blockbench model exceeds 8 MiB")
    model = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(model, dict):
        raise ValueError("Not a Blockbench model")
    return {"path": relative, **checks.check(model)}
