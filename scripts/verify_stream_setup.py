"""Stateful fake-OBS verification; no OBS connection, device, model or account access."""
from __future__ import annotations

from copy import deepcopy
import io
import json
import logging
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from star.stream_setup import (CAMERA, GAME, KINDS, MARKER, MICROPHONE, PLAN_PATH, SCENES,
                               StreamSetup, StreamSetupError, connect_local, load_plan, local_path, prepare)


class FakeOBS:
    def __init__(self):
        self.current = "Owner collection"
        self.collections = {self.current: self._collection()}
        self.original = deepcopy(self.collections[self.current])
        self.marker = None
        self.calls = []
        self.active = set()
        self.fail = None
        self.video = {"baseWidth": 1280, "baseHeight": 720, "fpsNumerator": 60, "fpsDenominator": 1}
        self.devices = {
            CAMERA: [{"itemName": "STAR Camera (Unity Video Capture)", "itemValue": "star-camera", "itemEnabled": True},
                     {"itemName": "Room webcam", "itemValue": "room-camera", "itemEnabled": True},
                     {"itemName": "OBS Virtual Camera", "itemValue": "recursive-camera", "itemEnabled": True}],
            MICROPHONE: [{"itemName": "STAR Microphone", "itemValue": "star-microphone", "itemEnabled": True},
                         {"itemName": "Room microphone", "itemValue": "room-microphone", "itemEnabled": True}],
            GAME: [{"itemName": "Test game", "itemValue": "Test game:GameClass:game.exe", "itemEnabled": True}],
        }

    @staticmethod
    def _collection():
        return {"scenes": {}, "inputs": {
            "Desktop Audio": {"inputKind": "wasapi_output_capture", "settings": {}, "muted": False, "filters": {}},
            "Mic/Aux": {"inputKind": "wasapi_input_capture", "settings": {}, "muted": False, "filters": {}}}}

    @property
    def state(self):
        return self.collections[self.current]

    def send(self, request, data=None, raw=False):
        assert raw is True
        data = data or {}
        self.calls.append((request, deepcopy(data)))
        if self.fail == request:
            self.fail = None
            raise RuntimeError("sensitive upstream diagnostic")
        if request == "GetVersion":
            return {"obsWebSocketVersion": "5.5.0"}
        if request == "GetVideoSettings":
            return self.video
        if request in {"GetStreamStatus", "GetRecordStatus", "GetReplayBufferStatus", "GetVirtualCamStatus"}:
            return {"outputActive": request in self.active}
        if request == "GetInputKindList":
            return {"inputKinds": ["browser_source", *KINDS.values()]}
        if request == "GetSceneCollectionList":
            return {"currentSceneCollectionName": self.current, "sceneCollections": list(self.collections)}
        if request == "GetPersistentData":
            assert data["slotName"] == MARKER
            return {"slotValue": self.marker}
        if request == "SetPersistentData":
            self.marker = data["slotValue"]
        elif request == "CreateSceneCollection":
            self.current = data["sceneCollectionName"]
            assert self.current not in self.collections
            self.collections[self.current] = self._collection()
        elif request == "SetCurrentSceneCollection":
            self.current = data["sceneCollectionName"]
        elif request == "GetSpecialInputs":
            return {"desktop1": "Desktop Audio", "desktop2": None, "mic1": "Mic/Aux", "mic2": None}
        elif request == "GetSceneList":
            return {"scenes": [{"sceneName": name} for name in self.state["scenes"]]}
        elif request == "CreateScene":
            assert data["sceneName"] not in self.state["scenes"]
            self.state["scenes"][data["sceneName"]] = []
        elif request == "GetInputList":
            return {"inputs": [{"inputName": name, "inputKind": value["inputKind"],
                                "unversionedInputKind": value["inputKind"]} for name, value in self.state["inputs"].items()]}
        elif request in {"CreateInput", "CreateSceneItem"}:
            if request == "CreateInput":
                name = data["inputName"]
                assert name not in self.state["inputs"]
                self.state["inputs"][name] = {"inputKind": data["inputKind"], "settings": deepcopy(data["inputSettings"]),
                                              "muted": False, "filters": {}}
                if data["inputKind"] == "dshow_input":
                    assert data["inputSettings"]["active"] is False
                if data["inputKind"] == "wasapi_input_capture":
                    assert data["inputSettings"]["device_id"] != "default"
            else:
                name = data["sourceName"]
            items = self.state["scenes"][data["sceneName"]]
            identifier = max([item["sceneItemId"] for item in items], default=0) + 1
            items.append({"sourceName": name, "sceneItemId": identifier, "enabled": data["sceneItemEnabled"]})
            return {"sceneItemId": identifier}
        elif request == "GetSceneItemList":
            return {"sceneItems": deepcopy(self.state["scenes"][data["sceneName"]])}
        elif request == "GetInputSettings":
            return {"inputSettings": deepcopy(self.state["inputs"][data["inputName"]]["settings"])}
        elif request == "SetInputSettings":
            assert data["overlay"] is False
            self.state["inputs"][data["inputName"]]["settings"] = deepcopy(data["inputSettings"])
        elif request == "GetInputPropertiesListPropertyItems":
            return {"propertyItems": deepcopy(self.devices[data["inputName"]])}
        elif request == "SetInputMute":
            self.state["inputs"][data["inputName"]]["muted"] = data["inputMuted"]
        elif request in {"SetInputAudioMonitorType", "SetInputAudioTracks", "SetInputVolume"}:
            self.state["inputs"][data["inputName"]][request] = deepcopy(data)
        elif request == "PressInputPropertiesButton":
            assert data == {"inputName": CAMERA, "propertyName": "activate"}
            settings = self.state["inputs"][CAMERA]["settings"]
            settings["active"] = not settings["active"]
        elif request == "GetSourceFilterKindList":
            return {"sourceFilterKinds": ["limiter_filter"]}
        elif request == "GetSourceFilterList":
            filters = self.state["inputs"][data["sourceName"]]["filters"]
            return {"filters": [{"filterName": name, **value} for name, value in filters.items()]}
        elif request in {"CreateSourceFilter", "SetSourceFilterSettings"}:
            filters = self.state["inputs"][data["sourceName"]]["filters"]
            if request == "CreateSourceFilter":
                assert data["filterName"] not in filters
                filters[data["filterName"]] = {"filterKind": data["filterKind"], "settings": data["filterSettings"]}
            else:
                filters[data["filterName"]]["settings"] = data["filterSettings"]
        elif request in {"SetSceneItemEnabled", "SetSceneItemTransform", "SetSceneItemIndex"}:
            items = self.state["scenes"][data["sceneName"]]
            item = next(item for item in items if item["sceneItemId"] == data["sceneItemId"])
            if request == "SetSceneItemEnabled":
                item["enabled"] = data["sceneItemEnabled"]
            elif request == "SetSceneItemTransform":
                item["transform"] = data["sceneItemTransform"]
            else:
                items.remove(item)
                items.insert(data["sceneItemIndex"], item)
        elif request == "SetCurrentProgramScene":
            assert data["sceneName"] in self.state["scenes"]
            self.state["program"] = data["sceneName"]
        else:
            raise AssertionError(f"Unexpected RPC {request}")
        return {}


class StreamSetupChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="star-stream-verifier-")
        self.root = Path(self.temporary.name) / "installation"
        prepare(self.root, art=None)
        self.obs = FakeOBS()
        self.setup = StreamSetup(self.obs)

    def tearDown(self):
        self.temporary.cleanup()

    def configure(self, **updates):
        plan = load_plan(self.root)
        plan.update(updates)
        (self.root / PLAN_PATH).write_text(json.dumps(plan), encoding="utf-8")

    def opt_in(self):
        self.configure(enable_camera=True, camera_device_id="star-camera", enable_microphone=True,
                       microphone_device_id="star-microphone", enable_game=True, game_window="Test game:GameClass:game.exe")

    def captures_hidden(self):
        for items in self.obs.state["scenes"].values():
            self.assertTrue(all(not item["enabled"] for item in items if item["sourceName"] in KINDS))

    def test_prepare_is_portable_static_and_does_not_reset_owner_choices(self):
        plan = load_plan(self.root)
        self.assertNotIn(str(self.root), json.dumps(plan))
        for relative in plan["overlays"].values():
            source = (self.root / relative).read_text(encoding="utf-8")
            self.assertNotIn("<script", source)
            self.assertNotIn("https://", source)
            self.assertIn("Content-Security-Policy", source)
            self.assertIn("img-src 'self' file:;", source)
        self.configure(enable_game=True, game_window="Test game:GameClass:game.exe")
        prepare(self.root, art=None)
        self.assertTrue(load_plan(self.root)["enable_game"])

    def test_paths_and_unrecognized_plan_fields_are_rejected(self):
        for path in ("../outside", "C:/outside", "https://outside", "/outside", "folder\\outside"):
            with self.assertRaises(ValueError):
                local_path(self.root, path)
        self.configure(unrecognized_setting=True)
        with self.assertRaises(ValueError):
            load_plan(self.root)

    def test_confirmation_and_idle_checks_happen_before_any_mutation(self):
        with self.assertRaises(PermissionError):
            self.setup.apply(self.root)
        self.assertEqual(self.obs.calls, [])
        for active in ("GetStreamStatus", "GetRecordStatus", "GetReplayBufferStatus", "GetVirtualCamStatus"):
            self.obs.calls.clear()
            self.obs.active = {active}
            with self.assertRaises(PermissionError):
                self.setup.apply(self.root, confirmed=True)
            self.assertTrue(all(name.startswith("Get") for name, _ in self.obs.calls))

    def test_default_setup_is_silent_hidden_and_leaves_owner_collection_unchanged(self):
        result = self.setup.apply(self.root, confirmed=True)
        self.assertFalse(result["streaming_started"])
        self.assertFalse(result["desktop_capture"])
        self.assertEqual(self.obs.collections["Owner collection"], self.obs.original)
        self.assertEqual(set(self.obs.state["scenes"]), set(SCENES.values()))
        self.captures_hidden()
        self.assertTrue(self.obs.state["inputs"][MICROPHONE]["muted"])
        self.assertFalse(self.obs.state["inputs"][CAMERA]["settings"]["active"])
        self.assertTrue(self.obs.state["inputs"]["Desktop Audio"]["muted"])
        self.assertTrue(self.obs.state["inputs"]["Mic/Aux"]["muted"])
        kinds = {row["inputKind"] for row in self.obs.state["inputs"].values()}
        self.assertNotIn("monitor_capture", kinds)
        self.assertEqual(self.obs.state["program"], SCENES["starting"])

    def test_apply_is_idempotent_and_uses_existing_canvas_dimensions(self):
        self.setup.apply(self.root, confirmed=True)
        before = deepcopy(self.obs.state)
        self.setup.apply(self.root, confirmed=True)
        self.assertEqual(self.obs.state, before)
        for items in self.obs.state["scenes"].values():
            self.assertEqual(len(items), len({row["sourceName"] for row in items}))
            for item in items:
                if "overlay" in item["sourceName"]:
                    self.assertEqual(item["transform"]["boundsWidth"], 1280.0)
                    self.assertEqual(item["transform"]["boundsHeight"], 720.0)
        browser_inputs = [row for row in self.obs.state["inputs"].values() if row["inputKind"] == "browser_source"]
        self.assertTrue(all(row["settings"].get("fps_custom") is True and row["settings"]["fps"] == 30
                            for row in browser_inputs))

    def test_explicit_virtual_devices_and_selected_game_route_only_where_expected(self):
        self.opt_in()
        self.setup.apply(self.root, confirmed=True)
        inputs = self.obs.state["inputs"]
        self.assertEqual(inputs[CAMERA]["settings"]["video_device_id"], "star-camera")
        self.assertTrue(inputs[CAMERA]["settings"]["active"])
        self.assertTrue(inputs[CAMERA]["muted"])
        self.assertFalse(any(inputs[CAMERA]["SetInputAudioTracks"]["inputAudioTracks"].values()))
        self.assertFalse(inputs[MICROPHONE]["muted"])
        self.assertEqual(inputs[MICROPHONE]["SetInputAudioMonitorType"]["monitorType"], "OBS_MONITORING_TYPE_NONE")
        self.assertEqual(inputs[GAME]["settings"]["capture_mode"], "window")
        self.assertEqual(inputs[GAME]["settings"]["priority"], 1)
        for slug, scene in SCENES.items():
            enabled = {row["sourceName"] for row in self.obs.state["scenes"][scene] if row["enabled"]}
            if slug in {"starting", "brb", "ending"}:
                self.assertFalse(enabled & set(KINDS))
            if slug == "chatting":
                self.assertNotIn(GAME, enabled)
            if slug == "gameplay":
                self.assertIn(GAME, enabled)

    def test_room_devices_and_missing_windows_never_fall_back_to_defaults(self):
        for changes in ({"enable_camera": True, "camera_device_id": "room-camera"},
                        {"enable_camera": True, "camera_device_id": "recursive-camera"},
                        {"enable_microphone": True, "microphone_device_id": "room-microphone"},
                        {"enable_microphone": True, "microphone_device_id": "default"},
                        {"enable_game": True, "game_window": "missing"}):
            prepare(self.root, art=None)
            self.configure(**{"enable_camera": False, "enable_microphone": False, "enable_game": False, **changes})
            with self.assertRaises(PermissionError):
                self.setup.apply(self.root, confirmed=True)
            self.captures_hidden()
            self.assertTrue(self.obs.state["inputs"][MICROPHONE]["muted"])

    def test_duplicate_game_titles_and_unknown_collection_ownership_are_rejected(self):
        self.opt_in()
        self.obs.devices[GAME].append({"itemName": "Impersonated title", "itemValue": "Test game:OtherClass:other.exe", "itemEnabled": True})
        with self.assertRaises(PermissionError):
            self.setup.apply(self.root, confirmed=True)
        self.obs.marker = None
        self.obs.calls.clear()
        with self.assertRaises(PermissionError):
            self.setup.apply(self.root, confirmed=True)
        self.assertTrue(all(name.startswith("Get") for name, _ in self.obs.calls))

    def test_partial_failure_attempts_to_mute_and_hide_captures_without_leaking_errors(self):
        self.opt_in()
        self.setup.apply(self.root, confirmed=True)
        self.obs.fail = "SetCurrentProgramScene"
        with self.assertRaises(StreamSetupError) as caught:
            self.setup.apply(self.root, confirmed=True)
        self.assertNotIn("sensitive upstream", str(caught.exception))
        self.captures_hidden()
        self.assertTrue(self.obs.state["inputs"][MICROPHONE]["muted"])
        self.assertFalse(self.obs.state["inputs"][CAMERA]["settings"]["active"])

    def test_no_broadcast_recording_keys_or_virtual_camera_start_operations_exist(self):
        self.setup.apply(self.root, confirmed=True)
        for request in ("StartStream", "ToggleStream", "GetStreamServiceSettings", "SetStreamServiceSettings",
                        "StartRecord", "StartVirtualCam", "StartReplayBuffer"):
            before = len(self.obs.calls)
            with self.assertRaises(PermissionError):
                self.setup._rpc(request)
            self.assertEqual(len(self.obs.calls), before)

    def test_sdk_constructor_and_lifetime_logs_cannot_reveal_the_password(self):
        captured = io.StringIO()
        handler = logging.StreamHandler(captured)
        root = logging.getLogger()
        old_level = root.level
        known = logging.getLogger("obsws_python.reqs.KnownClient")
        known.setLevel(logging.INFO)
        known.addHandler(handler)
        logging.getLogger("obsws_python")
        states = {logger: (logger.level, logger.disabled, logger.propagate, list(logger.handlers))
                  for name, logger in tuple(logging.Logger.manager.loggerDict.items())
                  if (name == "obsws_python" or name.startswith("obsws_python.")) and isinstance(logger, logging.Logger)}
        dummy_secret = "dummy-local-obs-only"

        class LoggingClient:
            def __init__(self, **kwargs):
                self.secret = kwargs["password"]
                known.info("constructor connection secret=%s", self.secret)
                logging.getLogger("obsws_python.baseclient.NewClient").info("constructor secret=%s", self.secret)

            def later(self):
                known.error("later connection secret=%s", self.secret)

        root.addHandler(handler)
        root.setLevel(logging.INFO)
        try:
            with patch.dict(sys.modules, {"obsws_python": SimpleNamespace(ReqClient=LoggingClient)}):
                client = connect_local(dummy_secret)
                client.later()
            root.info("ordinary application diagnostic still works")
            self.assertNotIn(dummy_secret, captured.getvalue())
            self.assertIn("ordinary application diagnostic still works", captured.getvalue())
        finally:
            root.removeHandler(handler)
            root.setLevel(old_level)
            for logger, (level, disabled, propagate, handlers) in states.items():
                logger.setLevel(level)
                logger.disabled, logger.propagate, logger.handlers = disabled, propagate, handlers
            known.removeHandler(handler)
            handler.close()

    def test_stale_cleanup_item_does_not_skip_microphone_camera_or_other_items(self):
        self.opt_in()
        self.setup.apply(self.root, confirmed=True)
        original = self.obs.send
        cleanup, failed_item = [False], [False]

        def flaky(request, data=None, raw=False):
            if request == "SetCurrentProgramScene":
                cleanup[0] = True
                raise RuntimeError("setup failure before cleanup")
            if cleanup[0] and request == "SetSceneItemEnabled" and not failed_item[0]:
                failed_item[0] = True
                items = self.obs.state["scenes"][data["sceneName"]]
                items[:] = [item for item in items if item["sceneItemId"] != data["sceneItemId"]]
                raise RuntimeError("scene item disappeared")
            return original(request, data, raw)

        with patch.object(self.obs, "send", side_effect=flaky):
            with self.assertRaises(StreamSetupError):
                self.setup.apply(self.root, confirmed=True)
        self.assertTrue(failed_item[0])
        self.assertTrue(self.obs.state["inputs"][MICROPHONE]["muted"])
        self.assertFalse(self.obs.state["inputs"][CAMERA]["settings"]["active"])
        self.captures_hidden()

    def test_relocated_installation_resolves_browser_sources_from_its_new_root(self):
        relocated = Path(self.temporary.name) / "relocated"
        shutil.copytree(self.root, relocated)
        self.setup.apply(relocated, confirmed=True)
        paths = [row["settings"]["local_file"] for row in self.obs.state["inputs"].values()
                 if row["inputKind"] == "browser_source"]
        self.assertEqual(len(paths), 5)
        self.assertTrue(all(Path(path).is_relative_to(relocated) for path in paths))

    def test_status_and_selection_reads_do_not_modify_configuration(self):
        self.setup.apply(self.root, confirmed=True)
        before = deepcopy(self.obs.collections)
        self.obs.calls.clear()
        self.assertFalse(self.setup.status()["streaming"])
        self.assertIn(CAMERA, self.setup.selections())
        self.assertEqual(self.obs.collections, before)
        self.assertTrue(all(name.startswith("Get") for name, _ in self.obs.calls))


if __name__ == "__main__":
    unittest.main(verbosity=2)
