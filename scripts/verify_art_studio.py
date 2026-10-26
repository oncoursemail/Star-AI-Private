"""Offline art-studio regressions; tiny raster fixtures are not artwork samples.

Run ``python scripts/verify_art_studio.py``. No model, GPU, UI, app, network or
approved user image is used. Every project lives in a disposable temp folder.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
from unittest.mock import patch
import xml.etree.ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from star import art_studio as art  # noqa: E402
from star.home.activities import Registry  # noqa: E402


class Checks:
    def __init__(self):
        self.count = 0

    def check(self, condition):
        if not condition:
            raise AssertionError(f"Art studio check {self.count + 1} failed")
        self.count += 1

    def refused(self, operation, errors=(ValueError, TypeError, PermissionError)):
        try:
            operation()
        except errors:
            self.count += 1
        else:
            raise AssertionError(f"Art studio check {self.count + 1}: expected refusal")


def png(size=(32, 24), color=(255, 255, 255, 255)):
    stream = BytesIO()
    art.Image.new("RGBA", size, color).save(stream, format="PNG")
    return stream.getvalue()


def rehash(folder, name):
    path = folder / "receipt.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["files"][name] = sha256((folder / name).read_bytes()).hexdigest()
    path.write_text(json.dumps(receipt), encoding="utf-8")


def alter_archive(folder, change):
    target = folder / "painting.ora"
    with ZipFile(target) as archive:
        files = [(entry, archive.read(entry.filename)) for entry in archive.infolist()]
    with ZipFile(target, "w") as archive:
        for entry, raw in files:
            archive.writestr(entry, change(entry.filename, raw))
    rehash(folder, "painting.ora")


def verify(folder, checks):
    check, refused = checks.check, checks.refused
    stroke = art.Stroke("Sketch", "#ff0000ff", 4, ((0.2, 0.5, 0.8), (0.8, 0.5, 1.0)))
    refused(lambda: art.Stroke("../outside", "#ff0000ff", 4, stroke.points))
    refused(lambda: art.Stroke("Sketch", "red", 4, stroke.points))
    refused(lambda: art.Stroke("Sketch", "#ff0000ff", float("nan"), stroke.points))
    refused(lambda: art.Stroke("Sketch", "#ff0000ff", True, stroke.points))
    refused(lambda: art.Stroke("Sketch", "#ff0000ff", 129, stroke.points))
    refused(lambda: art.Stroke("Sketch", "#ff0000ff", 4, ((-0.1, 0.5, 1),)))
    refused(lambda: art.Stroke("Sketch", "#ff0000ff", 4, ((0.5, 0.5, 2),)))
    refused(lambda: art.Stroke("Sketch", "#ff0000ff", 4, ((0.5, 0.5, True),)))
    refused(lambda: art.Stroke("Sketch", "#ff0000ff", 4, tuple((0.5, 0.5, 1) for _ in range(65))))
    refused(lambda: art.parse_strokes({"strokes": [], "execute": "unused"}, "Sketch"))
    refused(lambda: art.parse_strokes({"strokes": [{"color": "#ff0000ff", "width": 1, "points": [], "code": "unused"}]}, "Sketch"))
    refused(lambda: art._decode(b"not an image"), Exception)
    check(art.parse_strokes({"strokes": []}, "Sketch") == [])
    metadata_image = art.Image.new("RGB", (12, 10), "white")
    exif = art.Image.Exif()
    exif[270] = "offline-private-metadata-fixture"
    encoded = BytesIO()
    metadata_image.save(encoded, format="JPEG", exif=exif)
    scrubbed = art._png(art._decode(encoded.getvalue()))
    with art.Image.open(BytesIO(scrubbed)) as image:
        check(not image.getexif())

    base, reference = png(), png((20, 36), (32, 64, 128, 255))
    blue = art.Stroke("Details", "#0000ff80", 3, ((0.5, 0.1, 1.0), (0.5, 0.9, 1.0)))
    layers, merged = art.paint_layers(art._decode(base), [stroke, blue])
    check(list(layers) == list(art.PASSES))
    check(merged.getpixel((15, 12)) != (255, 255, 255, 255))
    check(layers["Color"].getbbox() is None)
    check(layers["Sketch"].getbbox() is not None and layers["Details"].getbbox() is not None)
    refused(lambda: art.paint_layers(art._decode(base), [stroke] * 257))
    refused(lambda: art.paint_layers(art._decode(base), [stroke], stopped=lambda: True), art.Stopped)

    gallery = folder / "gallery"
    project = art.create_project(gallery, title="Raster verification fixture", base=base,
                                 reference=reference, strokes=[stroke, blue])
    result = art.verify_project(project)
    check(result["verified"] and result["quality_assessed"] is False)
    check(result["stroke_count"] == 2 and result["layers"] == 5)
    check((project / "base.original").read_bytes() == base)
    check((project / "reference.original").read_bytes() == reference)
    check(art._decode((project / "preview.png").read_bytes()).tobytes() == merged.tobytes())
    with ZipFile(project / "painting.ora") as archive:
        check(archive.infolist()[0].filename == "mimetype" and archive.infolist()[0].compress_type == 0)
        stack = ET.fromstring(archive.read("stack.xml")).find("stack")
        check([row.get("name") for row in stack][:2] == ["Details", "Shadows"])
        check(list(stack)[-1].get("visibility") == "hidden")
        check(archive.read("mimetype") == b"image/openraster")
    times = {p.name: p.stat().st_mtime_ns for p in project.iterdir()}
    cli = subprocess.run([sys.executable, "-m", "star.art_studio", str(project)], cwd=ROOT,
                         text=True, capture_output=True, timeout=15, check=True)
    check(json.loads(cli.stdout)["verified"])
    check(times == {p.name: p.stat().st_mtime_ns for p in project.iterdir()})
    refused(lambda: art.create_project(gallery, title="bad\ntitle", base=base, strokes=[stroke]))
    refused(lambda: art.create_project(gallery, title="stopped", base=base, strokes=[stroke], stopped=lambda: True), art.Stopped)
    with patch.object(art, "_archive", side_effect=art.Stopped("offline stop fixture")):
        refused(lambda: art.create_project(gallery, title="mid-export stop", base=base, strokes=[stroke]), art.Stopped)
    check(not list(gallery.glob(".art-stage-*")))
    check(len(list(gallery.glob("art-*"))) == 1)

    corrupt = folder / "corrupt"
    shutil.copytree(project, corrupt)
    (corrupt / "preview.png").write_bytes(png(color=(0, 0, 0, 255)))
    refused(lambda: art.verify_project(corrupt))
    rehash(corrupt, "preview.png")
    refused(lambda: art.verify_project(corrupt))
    (corrupt / "preview.png").write_bytes((project / "preview.png").read_bytes())
    rehash(corrupt, "preview.png")
    alter_archive(corrupt, lambda name, raw: raw.replace(b'opacity="1.0"', b'opacity="0.0"') if name == "stack.xml" else raw)
    refused(lambda: art.verify_project(corrupt))

    home, workspace = folder / "home", folder / "workspace"
    workspace.mkdir()
    (workspace / "art-input").mkdir()
    (workspace / "art-input" / "approved.png").write_bytes(reference)
    (workspace / "outside-input.png").write_bytes(reference)
    ctx = SimpleNamespace(home=home, executor=SimpleNamespace(workspace=workspace, dry_run=False),
                          config={"vision": True, "art_studio": {"enabled": True, "mode": "paint"}},
                          interrupt=threading.Event(), goal={"text": "Offline raster fixture"}, chat=None)
    passes = []

    def planner(_chat, _goal, layer, preview, approved):
        passes.append(layer)
        check(art._decode(preview).size == (768, 1024))
        return [art.Stroke(layer, "#102030ff", 6, ((0.1, 0.2, 0.8), (0.2, 0.3, 0.9)))]

    outcome = art.run_activity(ctx, planner=planner)
    check(outcome["ok"] and outcome["verified"] and outcome["goal_done"] is False)
    check(passes == list(art.PASSES) and len(outcome["evidence"]) == 4)
    check(all(Path(path).is_file() for path in outcome["evidence"]))
    ctx.executor.dry_run = True
    count = len(passes)
    check(not art.run_activity(ctx, planner=planner)["ok"] and len(passes) == count)
    ctx.executor.dry_run = False
    ctx.config["art_studio"]["enabled"] = False
    check(not art.run_activity(ctx, planner=planner)["ok"] and len(passes) == count)
    ctx.config["art_studio"]["enabled"] = True
    ctx.interrupt.set()
    check(art.run_activity(ctx, planner=planner)["paused"])
    ctx.interrupt.clear()
    (home / "STOP").write_text("offline owner-stop fixture", encoding="utf-8")
    check(not art.run_activity(ctx, planner=planner)["ok"])
    (home / "STOP").unlink()
    ctx.config["art_studio"]["reference"] = "outside-input.png"
    check(not art.run_activity(ctx, planner=planner)["ok"] and len(passes) == count)
    ctx.config["art_studio"]["reference"] = "../gallery/anything.png"
    check(not art.run_activity(ctx, planner=planner)["ok"] and len(passes) == count)
    ctx.config["art_studio"].update(mode="reference", reference="art-input/approved.png")
    reference_outcome = art.run_activity(ctx, planner=lambda _c, _g, layer, _p, _r: [art.Stroke(layer, "#ff0000ff", 4, stroke.points)])
    check(reference_outcome["ok"])
    folder_ref = Path(reference_outcome["evidence"][0]).parent
    check((folder_ref / "base.original").read_bytes() == reference)
    check((folder_ref / "reference.original").read_bytes() == reference)
    check(not art.run_activity(ctx, planner=lambda *args: [])["ok"])
    check(not art.run_activity(ctx, planner=lambda _c, _g, layer, _p, _r: [art.Stroke(layer, "#ff000000", 4, stroke.points)])["ok"])
    registry = Registry(runtime=SimpleNamespace(config={}))
    art.register_home_activities(registry)
    check("art studio" not in registry.items)
    registry.runtime.config = {"art_studio": {"enabled": True}}
    art.register_home_activities(registry)
    check("art studio" not in registry.items and "star.art_studio" in registry.plugin_errors)
    registry.runtime.config = ctx.config
    art.register_home_activities(registry)
    check(registry.items["art studio"].interest == "drawing" and registry.items["art studio"].gpu_mb == 0)

    messages = []

    def fake_chat(sent, tools):
        messages.extend(sent)
        check(tools == [])
        return {"content": '{"strokes": [{"color":"#ff0000ff","width":4,"points":[[0.1,0.2,1]]}]}'}

    check(len(art._ask_pass(fake_chat, "offline fixture", "Sketch", base, reference)) == 1)
    check(sum(part.get("type") == "image_url" for part in messages[-1]["content"]) == 2)

    # Mock the existing ComfyUI client and GPU probe; no sockets or GPU probes run.
    class Probe:
        free = 8000
        game = ""

        def free_mb(self):
            return self.free

        def game_running(self, _names):
            return self.game

    class Client:
        missing = []
        queue = {"queue_running": [], "queue_pending": []}
        runs = 0

        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def missing_models(self, _engine):
            return self.missing

        def _call(self, method, path):
            check(method == "GET" and path == "/queue")
            return SimpleNamespace(json=lambda: self.queue)

        def upload(self, raw, _name):
            check(art._decode(raw).size == (20, 36))
            return "star/fixture.png"

        def run(self, flow, **_kwargs):
            check(flow["unet"]["class_type"] == "UNETLoader" and flow["out"]["class_type"] == "PreviewImage")
            Client.runs += 1
            return [base]

    config = {"allow_generation": True}
    cancel = SimpleNamespace(is_set=lambda: False)
    with patch("star.comfy.ComfyClient", Client), patch("star.home.activities.GpuProbe", Probe):
        refused(lambda: art._comfy_base({}, "fixture", None, cancel))
        Probe.free = 1000
        refused(lambda: art._comfy_base(config, "fixture", None, cancel))
        Probe.free, Probe.game = 8000, "Minecraft"
        refused(lambda: art._comfy_base(config, "fixture", None, cancel))
        Probe.game, Client.missing = "", ["missing-model"]
        refused(lambda: art._comfy_base(config, "fixture", None, cancel), RuntimeError)
        Client.missing, Client.queue = [], {"queue_running": ["another-job"]}
        refused(lambda: art._comfy_base(config, "fixture", None, cancel), RuntimeError)
        Client.queue = {"queue_running": [], "queue_pending": []}
        check(art._comfy_base(config, "fixture", reference, cancel) == base and Client.runs == 1)
        refused(lambda: art._comfy_base({**config, "width": 257}, "fixture", None, cancel))
        refused(lambda: art._comfy_base(config, "fixture", None, SimpleNamespace(is_set=lambda: True)), art.Stopped)
        check(Client.runs == 1)


def main():
    checks = Checks()
    with TemporaryDirectory(prefix="star-art-verification-") as folder:
        verify(Path(folder), checks)
    print(f"Art studio verification: {checks.count} checks passed; synthetic rasters only, no model/GPU/UI/network.")


if __name__ == "__main__":
    main()
