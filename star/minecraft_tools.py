"""Opt-in Minecraft asset tools for STAR's agent loop (Settings: minecraft_tools_enabled).

Offline and workspace-confined: no network, no server connection or scan, no Java or JAR
execution, no downloads. Inspection covers only the folder the user names; the two write tools
also need workspace editing to be on. Output may quote file names and plugin metadata, so the
agent treats the read tools as untrusted-source tools.
"""
from __future__ import annotations

import re

from . import minecraft_assets, minecraft_server_inventory

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
TOOL_NAMES = frozenset(t["name"] for t in TOOLS)
WRITE_TOOLS = frozenset({"workspace_minecraft_package", "workspace_minecraft_item_scaffold"})
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
        if name == "workspace_minecraft_package":
            return minecraft_assets.package(self.workspace, args["path"], args["output"],
                                            target_version=args["target_version"],
                                            replace=args.get("replace", False))
        return minecraft_assets.scaffold_item(
            self.workspace, args["output_dir"], namespace=args["namespace"], item_id=args["item_id"],
            texture_path=args["texture_path"], target_version=args["target_version"],
            description=args.get("description", "Minecraft custom items"))
