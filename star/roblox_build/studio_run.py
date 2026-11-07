"""Apply a compiled build in STAR's Studio (STAR Studio server, STAR Test Place only, guarded + pinned), set the
lighting, take the camera shots, remove the draft. Builds sit far from the place's own content (origin offset).

Uses the existing guarded path: star.studio_remote.connect/open_server (place pin, own-account check, undo
recording per edit). Nothing is saved or published.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import time
from pathlib import Path

from . import luau

ORIGIN = (6000.0, 200.0, 6000.0)


def _text(result) -> str:
    from ..studio_loop import result_text
    return result_text(result)


def _result(text: str) -> str:
    """The Luau return value out of the guarded tool's text ('STAR_EDIT {..."result": "..."}'), else the text."""
    start = text.find("{")
    try:
        return str(json.loads(text[start:]).get("result", text)) if start >= 0 else text
    except ValueError:
        return text


def _images(result) -> list[tuple[bytes, str]]:
    data = result.model_dump(by_alias=True, exclude_none=True) if hasattr(result, "model_dump") else result
    found = []
    for item in (data.get("content", []) if isinstance(data, dict) else []):
        if isinstance(item, dict) and item.get("type") == "image" and item.get("data"):
            try:
                found.append((base64.b64decode(item["data"]), str(item.get("mimeType") or "image/jpeg")))
            except ValueError:
                continue
    return found


class StudioBuilder:
    def __init__(self, guarded, log=print):
        self.guarded, self.log = guarded, log

    async def luau(self, code: str) -> tuple[bool, str]:
        result = await self.guarded.call_tool("execute_luau", {"studio_id": self.guarded.studio_id,
                                                               "datamodel_type": "Edit", "code": code})
        text = _text(result)
        return (luau.MARK in text), text

    async def apply(self, name: str, compiled: dict, origin=ORIGIN) -> dict:
        started = time.monotonic()
        made = 0
        for chunk in luau.build_chunks(name, compiled["parts"], origin):
            ok, text = await self.luau(chunk)
            if not ok:
                return {"ok": False, "made": made, "detail": text[-400:]}
            try:
                made += int(text.split(luau.MARK, 1)[1].split('"')[0].split("}")[0].split(",")[0].strip())
            except (ValueError, IndexError):
                pass
        if compiled.get("preset"):   # one of the measured presets (star.roblox_lighting_presets)
            from .. import roblox_lighting_presets as presets
            code = presets.lighting_luau(compiled["preset"]).replace("return string.format(", 'return "RB_DONE " .. string.format(')
            ok, text = await self.luau(code)
            await self.luau('pcall(function() game:GetService("StarterGui").ShowDevelopmentGui = false end) return "RB_DONE gui"')
        else:
            ok, text = await self.luau(luau.lighting_luau(compiled["lighting"]))
        return {"ok": ok, "made": made, "seconds": round(time.monotonic() - started, 1),
                "detail": "" if ok else text[-300:]}

    async def pick(self, name: str, compiled: dict, origin=ORIGIN) -> list[dict]:
        """Replace the compiled cameras by the clearest candidate per shot (Studio raycasts)."""
        cands = compiled.get("candidates") or {}
        if not cands:
            return compiled["cameras"]
        ok, text = await self.luau(luau.pick_cameras_luau(name, cands, origin))
        try:
            picked = json.loads(_result(text).split(luau.MARK, 1)[1])
        except (IndexError, ValueError):
            picked = {}
        out = []
        for cam in compiled["cameras"]:
            got = picked.get(cam["id"])
            if ok and got and cands.get(cam["id"]):
                c = cands[cam["id"]][int(got[0])]
                cam = dict(cam, position=c["position"], look_at=c["look_at"], pick={"score": got[1], "near": got[2],
                                                                                    "content": got[3], "sky": got[4]})
            out.append(cam)
        return out

    async def _capture(self, cid: str, pos, look) -> list:
        result = await self.guarded.call_tool("screen_capture", {"studio_id": self.guarded.studio_id,
                                                                 "capture_id": f"{cid}_{time.time_ns() % 10 ** 9}",
                                                                 "camera_position": pos, "look_at_position": look})
        return _images(result)

    async def shoot(self, compiled: dict, folder: Path, label: str, origin=ORIGIN, name: str = "") -> list[dict]:
        folder.mkdir(parents=True, exist_ok=True)
        shots = []
        cut = any(p.get("roof") for p in compiled["parts"])
        cams = await self.pick(name, compiled, origin) if name and compiled.get("candidates") else compiled["cameras"]
        await asyncio.sleep(2.5)   # textures stream in after a rebuild; the first frame is untextured otherwise
        for cam in cams:
            if cam["id"] == "overview" and cut and name:
                await self.luau(luau.roofs_luau(name, True))
            pos = [cam["position"][i] + origin[i] for i in range(3)]
            look = [cam["look_at"][i] + origin[i] for i in range(3)]
            images = await self._capture(f"RB_{label}_{cam['id']}", pos, look)
            if not images:
                shots.append({"camera": cam["id"], "ok": False, "detail": "no image"})
                continue
            data, mime = images[0]
            path = folder / f"{label}-{cam['id']}.{'jpg' if 'jpeg' in mime else 'png'}"
            path.write_bytes(data)
            shots.append({"camera": cam["id"], "ok": True, "file": str(path), "bytes": len(data), "pick": cam.get("pick"),
                          "position": cam["position"], "look_at": cam["look_at"]})
        return shots

    async def remove(self, name: str) -> bool:
        ok, _ = await self.luau(luau.remove_luau(name))
        return ok


@contextlib.asynccontextmanager
async def session(home: Path, log=print):
    """Guarded session on the STAR Studio server; refuses unless the open place is STAR Test Place and editable."""
    from .. import studio, studio_remote
    async with studio_remote.connect(home) as raw:
        discovered = await studio.list_tools(raw)
        guarded, facts = await studio_remote.open_server(raw, discovered, home=home, opted_in=True)
        if guarded is None or not (guarded.verdict.editable and facts.get("is_test_place")):
            raise RuntimeError("Studio not usable for builds: " + str(facts.get("problem") or facts.get("verdict")))
        yield StudioBuilder(guarded, log=log)


OWNER = "roblox_build"


async def render(home: Path, name: str, compiled: dict, folder: Path, label: str, *, keep: bool = False,
                 wait_s: float = 600.0) -> dict:
    async with session(home) as sb:
        deadline = time.monotonic() + wait_s
        while True:   # shared capture lock with the other lanes on this Studio
            ok, text = await sb.luau(luau.lock_luau(OWNER))
            if ok and "taken" in text:
                break
            if time.monotonic() > deadline:
                return {"apply": {"ok": False, "detail": "Studio capture lock busy: " + text[-120:]}, "shots": []}
            await asyncio.sleep(5)
        try:
            await sb.luau(luau.save_lighting_luau())
            applied = await sb.apply(name, compiled)
            shots = await sb.shoot(compiled, folder, label, name=name) if applied["ok"] else []
            if not keep:
                await sb.remove(name)
        finally:
            if compiled.get("preset"):
                from .. import roblox_lighting_presets as presets
                await sb.luau(presets.restore_luau().replace('return "STAR lighting', 'return "RB_DONE STAR lighting'))
            await sb.luau(luau.restore_lighting_luau())
            await sb.luau(luau.unlock_luau(OWNER))
        return {"apply": applied, "shots": shots}


def render_sync(home: Path, name: str, compiled: dict, folder: Path, label: str, **kw) -> dict:
    return asyncio.run(render(home, name, compiled, folder, label, **kw))
