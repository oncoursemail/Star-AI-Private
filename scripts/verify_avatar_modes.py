"""Exercise live mode changes on a CPU fixture, with no camera, sound or user settings."""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from star.vtuber import control
from star.vtuber.camera import StarCamera
from star.vtuber.model import load_model, starface_spec
from star.vtuber.placeholder import build_placeholder
from star.vtuber.sinks import MemorySink


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="star-mode-check-") as temp:
        base = Path(temp)
        folder = base / "home/vtuber"
        with patch.dict(os.environ, {"STAR_ROOT": str(base)}):
            with patch.dict(os.environ):
                os.environ.pop("STAR_VTUBER_DIR", None)
                assert control.data_dir() == folder
            with patch.dict(os.environ, {"STAR_VTUBER_DIR": str(base / "explicit")}):
                assert control.data_dir() == base / "explicit"
        control.set_mode("dog", folder)
        assert control.load_config(folder).mode == "puppy"
        raw = json.loads((folder / "config.json").read_text())
        raw.update({"width": 640, "owner_extra": "preserved"})
        (folder / "config.json").write_text(json.dumps(raw))
        control.set_mode("cat", folder)
        assert json.loads((folder / "config.json").read_text())["owner_extra"] == "preserved"
        assert control.load_config(folder).width == 640
        for bad in ("arbitrary", "CAT", "../cat"):
            try:
                control.set_mode(bad, folder)
                raise AssertionError("invalid mode accepted")
            except ValueError:
                pass
        assert control.load_config(folder).mode == "cat"
        (folder / "config.json").write_text('{"mode":"invalid"}')
        assert control.load_config(folder).mode == "normal"
        model = load_model(build_placeholder(base / "fixture"), size=(640, 360))
        sink = MemorySink()
        camera = StarCamera(model, [sink], adaptive=False)
        normal = camera.tick(1.0)
        assert normal.tail_sway == 0
        camera.set_mode("cat")
        assert camera.rig.mode == "normal"  # pending changes apply on the frame thread
        cat = camera.tick(1.1)
        assert camera.rig.mode == "cat" and cat.tail_sway != 0
        camera.set_mode("puppy")
        puppy = camera.tick(1.2)
        assert camera.stats()["mode"] == "puppy" and puppy.tail_sway != cat.tail_sway
        camera.set_mode("normal")
        assert camera.tick(1.3).tail_sway == 0
        assert sink.count == 4
        camera.stop()
        assert sink.closed
        # The existing approved mascot is honestly reported as lacking animal layers.
        spec, _ = starface_spec()
        bindings = {rule["param"] for layer in spec["layers"] for rule in layer.get("bind", {}).values()}
        assert not {"ear_left", "ear_right", "tail_sway"}.intersection(bindings)
    print("Avatar modes verified: rooted storage, aliases, config preservation, live frame changes, honest art limits")


if __name__ == "__main__":
    main()
