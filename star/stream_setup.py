"""Local OBS WebSocket 5 scene setup. No broadcasting, credentials or desktop capture APIs.

Prepare writes portable local overlays and a plan. Apply is a separate, explicitly
confirmed operation against idle OBS on loopback. Never expose this adapter as a
model tool. Device identifiers must come from OBS's own selectable properties.
Standalone browser previews do not verify OBS's custom local-file origin or its
native source pacing; those still require target-PC OBS acceptance.
"""
from __future__ import annotations

import argparse
from getpass import getpass
from html import escape
import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Any, Protocol
from urllib.parse import quote

COLLECTION = "STAR AI"
MARKER = "star.stream_setup.v1"
SCENES = {"starting": "STAR - Starting", "chatting": "STAR - Chatting", "gameplay": "STAR - Gameplay",
          "brb": "STAR - BRB", "ending": "STAR - Ending"}
CAMERA, MICROPHONE, GAME = "STAR - Avatar camera", "STAR - Voice only", "STAR - Selected game"
KINDS = {CAMERA: "dshow_input", MICROPHONE: "wasapi_input_capture", GAME: "game_capture"}
PLAN_PATH = "home/stream/setup.json"
OVERLAYS = "home/stream/overlays"
ART = "app/assets/vtuber/star-streamer-concept-v2.png"
_REQUESTS = frozenset({
    "GetVersion", "GetVideoSettings", "GetStreamStatus", "GetRecordStatus", "GetReplayBufferStatus", "GetVirtualCamStatus",
    "GetSceneCollectionList", "CreateSceneCollection", "SetCurrentSceneCollection", "GetPersistentData",
    "SetPersistentData", "GetSceneList", "CreateScene", "GetInputList", "GetInputKindList", "CreateInput",
    "GetInputSettings", "SetInputSettings", "GetInputPropertiesListPropertyItems", "GetSpecialInputs",
    "SetInputMute", "SetInputAudioMonitorType", "SetInputAudioTracks", "SetInputVolume",
    "GetSourceFilterKindList", "GetSourceFilterList", "CreateSourceFilter", "SetSourceFilterSettings",
    "GetSceneItemList", "CreateSceneItem", "SetSceneItemEnabled", "SetSceneItemTransform", "SetSceneItemIndex",
    "SetCurrentProgramScene", "PressInputPropertiesButton",
})


class OBSClient(Protocol):
    def send(self, request: str, data: dict | None = None, raw: bool = False) -> Any: ...


class StreamSetupError(RuntimeError):
    pass


def local_path(root: Path, relative: str, *, exists: bool = False) -> Path:
    if (not isinstance(relative, str) or not relative or len(relative) > 1024 or ":" in relative
            or "\\" in relative or Path(relative).is_absolute() or ".." in Path(relative).parts):
        raise ValueError("Use a portable path relative to the STAR installation")
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or (exists and not path.is_file()):
        raise ValueError("Required local stream asset is missing or outside STAR")
    return path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(text)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(root: Path, *, art: str | None = ART) -> dict:
    """Create five original static HTML overlays; all media is local, with no scripts or remote fonts."""
    root = Path(root).resolve()
    artwork = local_path(root, art) if art else None
    if artwork is not None and (not artwork.is_file() or artwork.suffix.lower() not in {".png", ".webp", ".jpg"}):
        artwork = None
    titles = {"starting": ("Getting comfy", "Stream starting soon"), "chatting": ("Star", "Just chatting"),
              "gameplay": ("Star", "Let's play"), "brb": ("Back in a moment", "Taking a little break"),
              "ending": ("See you next time", "Thanks for hanging out")}
    for slug, (title, subtitle) in titles.items():
        transparent = slug in {"chatting", "gameplay"}
        image = ""
        if artwork and not transparent:
            relative = os.path.relpath(artwork, local_path(root, OVERLAYS)).replace("\\", "/")
            image = f'<img alt="Star" src="{escape(quote(relative, safe="/."), quote=True)}">'
        body = ("background:transparent" if transparent else "background:#15161d")
        style = "compact" if transparent else "full"
        # OBS serves local files through http://absolute/; same-origin images must remain allowed.
        html = f'''<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' file:; style-src 'unsafe-inline'">
<style>*{{box-sizing:border-box}}html,body{{margin:0;width:1920px;height:1080px;overflow:hidden;{body}}}
body{{font-family:Segoe UI,Arial,sans-serif;color:#f4ebd8}}main{{position:absolute;left:112px;top:310px;z-index:1}}
.brand{{font-size:25px;letter-spacing:8px;color:#d5ad62}}h1{{font-size:88px;line-height:1.08;max-width:870px;margin:32px 0 25px}}
p{{font-size:29px;margin:0;color:#c3bcaf}}img{{position:absolute;right:12px;bottom:0;height:1020px;max-width:920px;object-fit:contain}}
.compact main{{left:40px;top:24px;background:#15161df2;padding:14px 24px;border-left:4px solid #d5ad62}}
.compact .brand{{font-size:17px;letter-spacing:5px}}.compact h1{{display:none}}.compact p{{font-size:19px;margin-top:5px}}
</style></head><body class="{style}">{image}<main><div class="brand">STAR</div><h1>{escape(title)}</h1>
<p>{escape(subtitle)}</p></main></body></html>'''
        _write(local_path(root, f"{OVERLAYS}/{slug}.html"), html)
    plan = {"schema": 1, "collection": COLLECTION, "overlays": {slug: f"{OVERLAYS}/{slug}.html" for slug in SCENES},
            "camera_device_id": "", "microphone_device_id": "", "game_window": "",
            "enable_camera": False, "enable_microphone": False, "enable_game": False}
    destination = local_path(root, PLAN_PATH)
    if not destination.exists():
        _write(destination, json.dumps(plan, indent=2))
    return {"prepared": True, "plan": PLAN_PATH, "overlay_count": 5, "art_available": artwork is not None,
            "live_obs_changed": False, "streaming_started": False}


def load_plan(root: Path) -> dict:
    path = local_path(root, PLAN_PATH, exists=True)
    if path.stat().st_size > 32768:
        raise ValueError("Stream setup plan is too large")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    expected = {"schema", "collection", "overlays", "camera_device_id", "microphone_device_id", "game_window",
                "enable_camera", "enable_microphone", "enable_game"}
    if (not isinstance(value, dict) or set(value) != expected or type(value["schema"]) is not int
            or value["schema"] != 1 or value["collection"] != COLLECTION
            or not isinstance(value["overlays"], dict) or set(value["overlays"]) != set(SCENES)):
        raise ValueError("Unrecognized STAR stream setup plan")
    for path in value["overlays"].values():
        if not isinstance(path, str) or not path.endswith(".html"):
            raise ValueError("Stream overlays must be local HTML files")
        local_path(root, path, exists=True)
    for name in ("camera", "microphone", "game"):
        if type(value["enable_" + name]) is not bool:
            raise ValueError("Stream source switches must be booleans")
    for field in ("camera_device_id", "microphone_device_id", "game_window"):
        raw = value[field]
        if not isinstance(raw, str) or len(raw) > 2048 or any(ord(c) < 32 or ord(c) == 127 for c in raw):
            raise ValueError("OBS selections must be bounded property-list identifiers")
    return value


class StreamSetup:
    def __init__(self, client: OBSClient):
        self.client = client

    def _rpc(self, request: str, **data) -> dict:
        if request not in _REQUESTS:
            raise PermissionError("This adapter has no broadcast or stream-service operations")
        try:
            response = self.client.send(request, data or None, raw=True)
            if response is not None and not isinstance(response, dict):
                raise TypeError
            return response or {}
        except Exception:
            raise StreamSetupError(f"OBS could not complete {request}; check the local setup. No automatic retry occurred.") from None

    def _idle(self) -> None:
        version = self._rpc("GetVersion")
        if not str(version.get("obsWebSocketVersion", "")).startswith("5."):
            raise StreamSetupError("OBS WebSocket 5 is required")
        for request in ("GetStreamStatus", "GetRecordStatus", "GetReplayBufferStatus", "GetVirtualCamStatus"):
            if self._rpc(request).get("outputActive") is not False:
                raise PermissionError("OBS must be idle: stop streaming, recording, replay buffer and virtual camera first")

    def status(self) -> dict:
        """Read-only status: no scene changes and no stream-service settings or keys."""
        version = self._rpc("GetVersion")
        return {"websocket_version": version.get("obsWebSocketVersion"),
                "collection": self._rpc("GetSceneCollectionList").get("currentSceneCollectionName"),
                "streaming": self._rpc("GetStreamStatus").get("outputActive"),
                "recording": self._rpc("GetRecordStatus").get("outputActive")}

    def selections(self) -> dict:
        """Local owner-facing IDs only; first apply creates inactive selection placeholders."""
        if self._rpc("GetSceneCollectionList").get("currentSceneCollectionName") != COLLECTION:
            raise PermissionError("Select the STAR AI scene collection before listing its devices")
        inputs = {row["inputName"] for row in self._rpc("GetInputList").get("inputs", [])}
        result = {}
        for name, field in ((CAMERA, "video_device_id"), (MICROPHONE, "device_id"), (GAME, "window")):
            result[name] = (self._rpc("GetInputPropertiesListPropertyItems", inputName=name, propertyName=field)
                            .get("propertyItems", [])) if name in inputs else []
        return result

    def _selected(self, name: str, field: str, value: str, labels: tuple[str, ...] = ()) -> str:
        if not value or value == "default":
            raise PermissionError("Choose an explicit STAR virtual device or game window in the local setup plan")
        items = self._rpc("GetInputPropertiesListPropertyItems", inputName=name, propertyName=field).get("propertyItems", [])
        selected = [row for row in items if row.get("itemValue") == value and row.get("itemEnabled") is True]
        if len(selected) != 1 or (labels and not any(label in str(selected[0].get("itemName", "")).casefold() for label in labels)):
            raise PermissionError("The selected source is unavailable or is not a STAR virtual device")
        if field == "window":
            parts = value.split(":")
            if len(parts) != 3 or not all(parts):
                raise PermissionError("Choose an explicit OBS game window")
            if sum(str(row.get("itemValue", "")).split(":")[0].casefold() == parts[0].casefold()
                   and row.get("itemEnabled") is True for row in items) != 1:
                raise PermissionError("The selected game title is ambiguous; use a uniquely named window")
        return value

    def _input(self, scene: str, name: str, kind: str, settings: dict, inputs: dict) -> None:
        if name in inputs:
            existing = inputs[name].get("unversionedInputKind", inputs[name].get("inputKind"))
            if existing != kind:
                raise PermissionError("A managed source name belongs to another input kind; resolve it in OBS")
        else:
            self._rpc("CreateInput", sceneName=scene, inputName=name, inputKind=kind,
                      inputSettings=settings, sceneItemEnabled=False)
            inputs[name] = {"inputKind": kind}

    def _camera_active(self, enabled: bool) -> None:
        settings = self._rpc("GetInputSettings", inputName=CAMERA).get("inputSettings", {})
        if (settings.get("active") is True) != enabled:
            self._rpc("PressInputPropertiesButton", inputName=CAMERA, propertyName="activate")

    def apply(self, root: Path, *, confirmed: bool = False) -> dict:
        if confirmed is not True:
            raise PermissionError("Apply requires confirmation of this local OBS target")
        self._editing = False
        try:
            return self._apply(root)
        except Exception as error:
            if self._editing:
                self._safe_off()
            if isinstance(error, (PermissionError, ValueError, StreamSetupError)):
                raise
            raise StreamSetupError("OBS setup did not finish; inspect the managed collection before using it") from None

    def _safe_off(self) -> None:
        """Best-effort fail-closed cleanup, confined to the collection this operation owns."""
        try:
            if self._rpc("GetSceneCollectionList").get("currentSceneCollectionName") != COLLECTION:
                return
        except Exception:
            return  # Never mutate a collection when its identity cannot be verified.
        # Audio and device activation come first; a stale scene item must not skip either.
        for name in (MICROPHONE, CAMERA):
            try:
                self._rpc("SetInputMute", inputName=name, inputMuted=True)
            except Exception:
                pass
        try:
            self._camera_active(False)
        except Exception:
            pass
        for scene in SCENES.values():
            try:
                items = self._rpc("GetSceneItemList", sceneName=scene).get("sceneItems", [])
            except Exception:
                continue
            for item in items:
                if isinstance(item, dict) and item.get("sourceName") in KINDS:
                    try:
                        self._rpc("SetSceneItemEnabled", sceneName=scene, sceneItemId=item["sceneItemId"], sceneItemEnabled=False)
                    except Exception:
                        pass  # Continue with the other captures after an individual failure.

    def _apply(self, root: Path) -> dict:
        plan = load_plan(root)
        self._idle()
        video = self._rpc("GetVideoSettings")
        width, height = video.get("baseWidth"), video.get("baseHeight")
        if type(width) is not int or type(height) is not int or not 1 <= width <= 8192 or not 1 <= height <= 8192:
            raise StreamSetupError("OBS returned an unsupported canvas size")
        scale_x, scale_y = width / 1920, height / 1080
        kinds = self._rpc("GetInputKindList", unversioned=True).get("inputKinds", [])
        if not {"browser_source", *KINDS.values()}.issubset(kinds):
            raise StreamSetupError("Windows camera, WASAPI, game capture and browser sources are required")
        collections = self._rpc("GetSceneCollectionList").get("sceneCollections", [])
        marker = self._rpc("GetPersistentData", realm="OBS_WEBSOCKET_DATA_REALM_GLOBAL", slotName=MARKER).get("slotValue")
        if COLLECTION in collections:
            if marker != {"schema": 1, "collection": COLLECTION}:
                raise PermissionError("The STAR AI collection already exists without this adapter's ownership marker")
            self._rpc("SetCurrentSceneCollection", sceneCollectionName=COLLECTION)
            self._editing = True
        else:
            self._rpc("CreateSceneCollection", sceneCollectionName=COLLECTION)
            self._editing = True
            self._rpc("SetPersistentData", realm="OBS_WEBSOCKET_DATA_REALM_GLOBAL", slotName=MARKER,
                      slotValue={"schema": 1, "collection": COLLECTION})
        # Existing global desktop/room inputs in this collection never reach a scene's output.
        for name in self._rpc("GetSpecialInputs").values():
            if isinstance(name, str) and name:
                self._rpc("SetInputMute", inputName=name, inputMuted=True)
        scenes = {row["sceneName"] for row in self._rpc("GetSceneList").get("scenes", [])}
        for name in SCENES.values():
            if name not in scenes:
                self._rpc("CreateScene", sceneName=name)
        # Hide every existing item before changing any source; failures attempt capture cleanup again.
        for scene in SCENES.values():
            for item in self._rpc("GetSceneItemList", sceneName=scene).get("sceneItems", []):
                self._rpc("SetSceneItemEnabled", sceneName=scene, sceneItemId=item["sceneItemId"], sceneItemEnabled=False)
        inputs = {row["inputName"]: row for row in self._rpc("GetInputList").get("inputs", [])}
        staging = SCENES["starting"]
        self._input(staging, CAMERA, KINDS[CAMERA], {"active": False, "video_device_id": "", "deactivate_when_not_showing": True}, inputs)
        self._camera_active(False)
        self._rpc("SetInputMute", inputName=CAMERA, inputMuted=True)
        self._rpc("SetInputAudioMonitorType", inputName=CAMERA, monitorType="OBS_MONITORING_TYPE_NONE")
        self._rpc("SetInputAudioTracks", inputName=CAMERA, inputAudioTracks={str(n): False for n in range(1, 7)})
        self._input(staging, MICROPHONE, KINDS[MICROPHONE], {"device_id": "STAR_UNSELECTED_DEVICE"}, inputs)
        self._rpc("SetInputMute", inputName=MICROPHONE, inputMuted=True)
        self._input(staging, GAME, KINDS[GAME], {"capture_mode": "window", "window": "", "priority": 1}, inputs)
        camera = self._selected(CAMERA, "video_device_id", plan["camera_device_id"], ("star camera", "unity video capture")) if plan["enable_camera"] else ""
        microphone = self._selected(MICROPHONE, "device_id", plan["microphone_device_id"], ("star microphone", "cable output")) if plan["enable_microphone"] else "STAR_UNSELECTED_DEVICE"
        game = self._selected(GAME, "window", plan["game_window"]) if plan["enable_game"] else ""
        self._rpc("SetInputSettings", inputName=CAMERA, overlay=False, inputSettings={"active": False,
                  "video_device_id": camera, "deactivate_when_not_showing": True, "use_custom_audio_device": False})
        self._rpc("SetInputSettings", inputName=MICROPHONE, overlay=False, inputSettings={"device_id": microphone})
        self._rpc("SetInputSettings", inputName=GAME, overlay=False, inputSettings={"capture_mode": "window", "window": game,
                  "priority": 1, "capture_cursor": False, "capture_overlays": False, "limit_framerate": True})
        self._rpc("SetInputAudioMonitorType", inputName=MICROPHONE, monitorType="OBS_MONITORING_TYPE_NONE")
        self._rpc("SetInputAudioTracks", inputName=MICROPHONE, inputAudioTracks={str(n): n == 1 for n in range(1, 7)})
        self._rpc("SetInputVolume", inputName=MICROPHONE, inputVolumeMul=1.0)
        if "limiter_filter" in self._rpc("GetSourceFilterKindList").get("sourceFilterKinds", []):
            filters = {row["filterName"]: row for row in self._rpc("GetSourceFilterList", sourceName=MICROPHONE).get("filters", [])}
            if "STAR - Voice limiter" not in filters:
                self._rpc("CreateSourceFilter", sourceName=MICROPHONE, filterName="STAR - Voice limiter",
                          filterKind="limiter_filter", filterSettings={"threshold": -1.0, "release_time": 60})
            elif filters["STAR - Voice limiter"].get("filterKind") == "limiter_filter":
                self._rpc("SetSourceFilterSettings", sourceName=MICROPHONE, filterName="STAR - Voice limiter", overlay=False,
                          filterSettings={"threshold": -1.0, "release_time": 60})
            else:
                raise PermissionError("The managed voice limiter name belongs to another filter")
        for slug, scene in SCENES.items():
            overlay_name = f"STAR - {slug} overlay"
            settings = {"is_local_file": True, "local_file": str(local_path(root, plan["overlays"][slug], exists=True)),
                        "width": 1920, "height": 1080, "fps": 30, "fps_custom": True,
                        "shutdown": True, "restart_when_active": True}
            self._input(scene, overlay_name, "browser_source", settings, inputs)
            self._rpc("SetInputSettings", inputName=overlay_name, overlay=False, inputSettings=settings)
            desired = [(overlay_name, True, 0, 0, 1920, 1080)]
            if slug in {"chatting", "gameplay"}:
                desired = [(GAME, plan["enable_game"] and slug == "gameplay", 0, 0, 1920, 1080),
                           (CAMERA, plan["enable_camera"], 1450 if slug == "gameplay" else 1040,
                            430 if slug == "gameplay" else 100, 430 if slug == "gameplay" else 820,
                            650 if slug == "gameplay" else 980),
                           (MICROPHONE, plan["enable_microphone"], 0, 0, 1, 1), *desired]
            for index, (name, enabled, x, y, item_width, item_height) in enumerate(desired):
                items = [item for item in self._rpc("GetSceneItemList", sceneName=scene).get("sceneItems", []) if item["sourceName"] == name]
                if len(items) > 1:
                    raise PermissionError("A managed scene contains duplicate sources; resolve them in OBS")
                item_id = items[0]["sceneItemId"] if items else self._rpc("CreateSceneItem", sceneName=scene, sourceName=name, sceneItemEnabled=False)["sceneItemId"]
                if name != MICROPHONE:
                    self._rpc("SetSceneItemTransform", sceneName=scene, sceneItemId=item_id, sceneItemTransform={
                        "positionX": x * scale_x, "positionY": y * scale_y, "alignment": 5, "rotation": 0.0,
                        "boundsType": "OBS_BOUNDS_SCALE_INNER", "boundsAlignment": 5,
                        "boundsWidth": item_width * scale_x, "boundsHeight": item_height * scale_y})
                self._rpc("SetSceneItemIndex", sceneName=scene, sceneItemId=item_id, sceneItemIndex=index)
                self._rpc("SetSceneItemEnabled", sceneName=scene, sceneItemId=item_id, sceneItemEnabled=enabled)
        self._camera_active(plan["enable_camera"])
        self._rpc("SetInputMute", inputName=MICROPHONE, inputMuted=not plan["enable_microphone"])
        self._rpc("SetCurrentProgramScene", sceneName=SCENES["starting"])
        return {"configured": True, "collection": COLLECTION, "scene_count": 5, "desktop_capture": False,
                "canvas": {"width": width, "height": height},
                "camera_enabled": plan["enable_camera"], "microphone_enabled": plan["enable_microphone"],
                "selected_game_enabled": plan["enable_game"], "streaming_started": False,
                "native_acceptance_required": True}


def _disable_sdk_diagnostics() -> None:
    """The SDK logs plaintext connection passwords at INFO before its constructor connects.

    Suppress only its namespace, before import and construction. Existing child
    loggers may have their own levels/handlers; future children inherit the quiet
    namespace. Keep this in force for the connection's lifetime, not just startup.
    Adapter errors remain available without forwarding SDK messages.
    """
    namespace = logging.getLogger("obsws_python")
    namespace.setLevel(logging.CRITICAL + 1)
    namespace.disabled = True
    namespace.propagate = False
    if not namespace.handlers:
        namespace.addHandler(logging.NullHandler())
    for name, logger in tuple(logging.Logger.manager.loggerDict.items()):
        if name.startswith("obsws_python.") and isinstance(logger, logging.Logger):
            logger.setLevel(logging.CRITICAL + 1)
            logger.disabled = True


def connect_local(password: str):
    if not isinstance(password, str) or not 1 <= len(password) <= 256:
        raise ValueError("Enter the local OBS WebSocket password")
    _disable_sdk_diagnostics()
    try:
        from obsws_python import ReqClient
        return ReqClient(host="127.0.0.1", port=4455, password=password, timeout=5)
    except Exception:
        raise StreamSetupError("Could not connect to local authenticated OBS WebSocket 5 on port 4455") from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "status", "selections", "apply"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--art", default=ART)
    parser.add_argument("--confirm-this-pc", action="store_true")
    args = parser.parse_args()
    client = None
    try:
        if args.command == "prepare":
            result = prepare(args.root, art=args.art or None)
        else:
            if args.command == "apply" and not args.confirm_this_pc:
                raise PermissionError("Apply requires --confirm-this-pc after reviewing this PC and the local setup plan")
            client = connect_local(getpass("Local OBS WebSocket password: "))
            adapter = StreamSetup(client)
            result = (adapter.apply(args.root, confirmed=True) if args.command == "apply" else
                      adapter.selections() if args.command == "selections" else adapter.status())
        print(json.dumps(result, indent=2))
    except (StreamSetupError, PermissionError, ValueError, OSError):
        print(json.dumps({"ok": False, "message": "Stream setup could not complete; check the local plan, idle OBS and selected virtual devices.",
                          "streaming_started": False}))
        raise SystemExit(1) from None
    finally:
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass


if __name__ == "__main__":
    main()
