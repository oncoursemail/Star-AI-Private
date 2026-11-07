"""Brain 2's first-party Blender MCP server and guarded in-process client.

The local desktop uses real MCP through an isolated SDK memory transport. An
operator may also run the same server on stdio with --settings. This never
connects to a third-party Blender addon or exposes Blender's Python console.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
import json
import os
from pathlib import Path
import re

from mcp import types
from mcp.server import Server
from mcp.shared.memory import create_connected_server_and_client_session

from .blender_bridge import BlenderController, SCENE_SCHEMA, status
from .blender_animation import ANIMATION_SCHEMA, analyze_animation

STATUS = "star_blender_status"
PROBE = "star_blender_probe"
INSPECT = "star_blender_inspect"
BUILD = "star_blender_build_scene"
ANIMATION_PREFLIGHT = "star_blender_animation_preflight"
ANIMATION_EXPORT = "star_blender_animation_export_r15_draft"
MOTION_QA = "star_blender_animation_motion_qa"
NAMES = frozenset({STATUS, PROBE, INSPECT, BUILD, ANIMATION_PREFLIGHT, ANIMATION_EXPORT, MOTION_QA})
MAX_ARGS = 25_000
MAX_PREVIEW = 1_800_000
CALL_SECONDS = 205
BLENDER_INTENT = re.compile(
    r"\b(?:blender|bpy|3d model(?:s|ling|ing)?|3d assets?|3d meshes?|glb|gltf|fbx|"
    r"procedural (?:mesh|tree|forest|architecture|model|asset)|mesh export)\b", re.IGNORECASE,
)

CATALOG = (
    {"name": STATUS, "description": "Read whether STAR's local Blender install and project-scoped MCP are ready; no Blender process starts.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": PROBE, "description": "Start the locally configured Blender once in factory-startup background mode to verify the installed Blender version. No changes to user projects.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": INSPECT, "description": "Inspect only a previous STAR-created Blender job in the currently selected project; does not open arbitrary .blend files.",
     "inputSchema": {"type": "object", "properties": {"job_id": {"type": "string", "pattern": "^[a-f0-9]{24}$"}},
                     "required": ["job_id"], "additionalProperties": False}},
    {"name": ANIMATION_PREFLIGHT,
     "description": ("Read-only preflight of bounded R15/R6 Blender animation keyframe plans: "
                     "rig-specific bone names, loops, motion-rate warnings, and native Studio import limits. "
                     "Does not launch Blender, upload, train or prove an animation is playable."),
     "inputSchema": ANIMATION_SCHEMA},
    {"name": MOTION_QA,
     "description": ("Read-only motion check of an R15/R6 animation keyframe plan: samples every frame, reports peak "
                     "and p95 joint speed, sharp accelerations and loop seams; with `reference` (an approved clip of "
                     "the same rig, fps and length) also the per-frame difference. Authored values only, not "
                     "rendered Blender or Studio frames; no Blender process starts."),
     "inputSchema": {"type": "object", "additionalProperties": False, "required": ["clip"],
                     "properties": {"clip": ANIMATION_SCHEMA, "reference": ANIMATION_SCHEMA,
                                    "tolerance_deg": {"type": "number", "minimum": 0, "maximum": 120}}}},
    {"name": ANIMATION_EXPORT,
     "description": ("EXPERIMENTAL: author editable Blender R15 proxy bone actions and export "
                     "one draft animation.fbx plus scene.blend into a private STAR job. "
                     "This is bone-only, not a Roblox avatar; native Studio import unverified. "
                     "Requires existing Blender edit permission AND "
                     "STAR_BLENDER_R15_ANIMATION_EXPERIMENT=on. Never supports R6 export, "
                     "arbitrary bpy, source assets, Roblox publishing or auto-install."),
     "inputSchema": ANIMATION_SCHEMA},
    {"name": BUILD, "description": (
        "Create an editable .blend scene and Roblox-compatible .glb in STAR's isolated Blender project folder. "
        "Only validated primitives, modular arches/roofs, low-poly trees/rocks, colors, camera and optional preview render. "
        "No arbitrary Python, external assets, network, publishing or modification of existing Blender files. "
        "Requires the owner's Blender scene creation switch; exports need manual Studio import and quality review."),
     "inputSchema": SCENE_SCHEMA},
)


def wants_blender(prompt: str) -> bool:
    return isinstance(prompt, str) and bool(BLENDER_INTENT.search(prompt[:20000]))


def _error(message: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=message)], isError=True)


def _image_preview(result: dict) -> types.CallToolResult | None:
    source = result.get("preview_file")
    if not source:
        return None
    file = Path(source)
    if file.is_symlink() or not file.is_file() or not 0 < file.stat().st_size <= MAX_PREVIEW:
        return None
    preview = file.read_bytes()
    if not preview.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    return types.CallToolResult(isError=False, content=[
        types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False)),
        types.ImageContent(type="image", mimeType="image/png", data=base64.b64encode(preview).decode("ascii")),
    ])


def make_server(controller: BlenderController):
    """Expose only host-approved capabilities; schema and runtime gates both enforce scope."""
    enabled = getattr(controller.settings, "blender_enabled", False) is True
    editing = enabled and getattr(controller.settings, "blender_edit", False) is True
    animation_export = editing and os.environ.get("STAR_BLENDER_R15_ANIMATION_EXPERIMENT") == "on"
    motion_qa = enabled and getattr(controller.settings, "blender_motion_qa", False) is True
    catalog = [tool for tool in CATALOG
               if (tool["name"] != BUILD or editing)
               and (tool["name"] != ANIMATION_EXPORT or animation_export)
               and (tool["name"] != MOTION_QA or motion_qa)]
    server = Server("STAR Blender MCP", version="1.0")

    @server.list_tools()
    async def list_tools():
        return [types.Tool.model_validate(item) for item in catalog]

    @server.call_tool(validate_input=False)
    async def call(name, arguments):
        if name not in {item["name"] for item in catalog}:
            return _error("STAR Blender MCP: tool not enabled for this session")
        try:
            if type(arguments) is not dict or len(json.dumps(arguments, allow_nan=False)) > MAX_ARGS:
                return _error("STAR Blender MCP: invalid or oversized tool arguments")
            if name in (STATUS, PROBE) and arguments:
                return _error("STAR Blender MCP: this tool takes no arguments")
            if name == STATUS:
                return status(controller.settings)
            if name == PROBE:
                return await controller.probe()
            if name == INSPECT:
                if set(arguments) != {"job_id"}:
                    return _error("STAR Blender MCP: inspect takes one job identifier")
                result = controller.inspect(arguments["job_id"])
            elif name == ANIMATION_PREFLIGHT:
                result = analyze_animation(arguments)
            elif name == MOTION_QA:
                from .animation_regression import compare_clip_to_reference, motion_quality_report
                if "clip" not in arguments or not set(arguments) <= {"clip", "reference", "tolerance_deg"}:
                    return _error("STAR Blender MCP: motion check takes clip, optional reference and tolerance_deg")
                result = motion_quality_report(arguments["clip"])
                if "reference" in arguments:
                    result["reference_comparison"] = compare_clip_to_reference(
                        arguments["reference"], arguments["clip"], tolerance_deg=arguments.get("tolerance_deg", 5.0))
            elif name == ANIMATION_EXPORT:
                if not animation_export:
                    return _error("STAR Blender MCP: experimental R15 animation permission required")
                result = await controller.animate(arguments)
            else:
                if not editing:
                    return _error("STAR Blender MCP: owner approval required")
                result = await controller.build(arguments)
            return _image_preview(result) or result
        except asyncio.CancelledError:
            raise
        except (ValueError, PermissionError) as exc:
            # Only known local validation outcomes, not arbitrary shell output.
            return _error(f"STAR Blender MCP: {type(exc).__name__}: {str(exc)[:180]}")
        except Exception as exc:
            return _error(f"STAR Blender MCP: {type(exc).__name__}; check local Blender job diagnostics")

    return server, catalog


@dataclass
class BlenderClient:
    client: object
    catalog: list[dict]

    @staticmethod
    def owns(name: str) -> bool:
        return name in NAMES

    def definitions(self, prompt: str) -> list[dict]:
        return list(self.catalog) if wants_blender(prompt) else []

    async def call(self, name: str, arguments: dict):
        if name not in {tool["name"] for tool in self.catalog}:
            raise PermissionError("Blender tool was not enabled for this session")
        result = await self.client.call_tool(name, arguments=arguments)
        return result.model_dump(by_alias=True, exclude_none=True)


@asynccontextmanager
async def connect_blender(settings, home: Path):
    """Brain 2 uses this only for an explicitly Blender-related tool turn."""
    controller = BlenderController(settings=settings, home=home)
    server, catalog = make_server(controller)
    async with create_connected_server_and_client_session(
            server, read_timeout_seconds=timedelta(seconds=CALL_SECONDS)) as client:
        listed = await client.list_tools()
        if {tool.name for tool in listed.tools} != {tool["name"] for tool in catalog}:
            raise RuntimeError("STAR Blender MCP catalog verification failed")
        yield BlenderClient(client, catalog)


async def _serve(settings_file: Path):
    from .desktop_core import Settings
    from mcp.server.stdio import stdio_server
    settings = Settings.load(settings_file)
    settings.validate()
    controller = BlenderController(settings=settings, home=settings_file.parent)
    server, _ = make_server(controller)
    async with stdio_server() as (incoming, outgoing):
        await server.run(incoming, outgoing, server.create_initialization_options())


def main():
    parser = argparse.ArgumentParser(description="STAR Blender MCP: locally configured and bounded stdio server")
    parser.add_argument("--settings", type=Path, required=True)
    args = parser.parse_args()
    if not args.settings.is_file():
        parser.error("Choose an existing STAR settings file")
    try:
        asyncio.run(_serve(args.settings))
    except Exception:
        import sys
        print("STAR Blender MCP could not start using the selected settings.", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
