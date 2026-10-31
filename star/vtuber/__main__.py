"""python -m star.vtuber  run | on | off | status | mode | preview

run      the camera process itself (what `on` starts): model -> "STAR Camera" virtual camera, mouth frames on UDP 39541
on/off   start or stop that process (hidden, below-normal priority)
status   one line of JSON: alive, frames, fps, dropped, quality, device
mode     normal | cat | puppy (dog accepted); motion mode, requires matching avatar art for visible ears/tail
expression  a bounded facial cue; neutral releases it; does not start the camera
preview  render frames of the avatar speaking a spoken test sentence to PNG files (no camera, no audio device)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import control


def _set_below_normal() -> None:                                       # pragma: no cover - Windows only
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)
    except Exception:
        pass


def _mood_source(cfg: control.Config):
    if not cfg.use_emotion:
        return None

    def source():
        from .. import emotion
        if not emotion.enabled():
            return None
        state = emotion.current()
        return state.get("avatar") if state else None
    return source


def run(args) -> int:
    from .camera import StarCamera
    from .lipsync import UdpListener
    from .model import ModelError, load_model
    from .rig import LiveRig
    from .sinks import MemorySink, PngSink, PyVirtualCamSink, SinkError
    from .vmc import VmcSink

    folder = control.data_dir()
    cfg = control.load_config(folder)
    _set_below_normal()
    try:
        model = load_model(args.model or cfg.model, size=(cfg.width, cfg.height))
        if args.sink == "virtualcam":
            sink = PyVirtualCamSink(cfg.width, cfg.height, cfg.fps, name=cfg.device_name, backend=cfg.backend or None)
        elif args.sink.startswith("png:"):
            sink = PngSink(args.sink[4:], every=max(1, int(cfg.fps // 5)))
        else:
            sink = MemorySink()
    except (ModelError, SinkError) as why:
        control.write_status(folder, error=str(why), frames=0)
        print(f"star.vtuber: {why}", file=sys.stderr)
        return 3
    pose_sinks = [VmcSink(port=cfg.vmc_port)] if cfg.vmc_port else []
    camera = StarCamera(model, [sink], rig=LiveRig(mode=cfg.mode, reduced_motion=cfg.reduced_motion), fps=cfg.fps,
                        pose_sinks=pose_sinks, mood_source=_mood_source(cfg))
    listener = UdpListener(camera.feed, cfg.feed_port)
    listener.start()
    camera.start()
    try:
        while not control.stop_requested(folder):
            camera.set_mode(control.load_config(folder).mode)
            control.write_status(folder, model=model.name, device=getattr(sink, "device", type(sink).__name__),
                                 feed_port=listener.port, **camera.stats())
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        listener.close()
        camera.stop()
        try:
            (folder / "stop.flag").unlink()
        except OSError:
            pass
        control.write_status(folder, stopped=True, frames=camera.frames)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m star.vtuber")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--model", default="")
    p.add_argument("--sink", default="virtualcam", help="virtualcam | png:<folder> | memory")
    sub.add_parser("on")
    sub.add_parser("off")
    sub.add_parser("status")
    p = sub.add_parser("mode")
    p.add_argument("value", choices=("normal", "cat", "puppy", "dog"))
    from .expressions import EXPRESSION_NAMES
    p = sub.add_parser("expression")
    p.add_argument("name", choices=EXPRESSION_NAMES)
    p.add_argument("--seconds", type=float, default=None)
    p.add_argument("--strength", type=float, default=1.0)
    p = sub.add_parser("preview")
    p.add_argument("--out", required=True)
    p.add_argument("--model", default="placeholder")
    p.add_argument("--wav", default="", help="a speech WAV; default: Windows' own voice says a test sentence")
    p.add_argument("--fps", type=int, default=15)
    args = parser.parse_args(argv)
    if args.cmd == "run":
        return run(args)
    if args.cmd == "on":
        status = control.start()
        print(json.dumps(status))
        return 0 if status.get("alive") and not status.get("error") else 1
    if args.cmd == "off":
        print(json.dumps(control.stop()))
        return 0
    if args.cmd == "status":
        print(json.dumps(control.read_status()))
        return 0
    if args.cmd == "mode":
        print(json.dumps(control.set_mode(args.value)))
        return 0
    if args.cmd == "expression":
        from . import emit_expression
        try:
            emit_expression(args.name, duration_s=args.seconds, strength=args.strength)
        except ValueError as error:
            parser.error(str(error))
        print(json.dumps({"expression_requested": args.name, "camera_started": False, "delivery_verified": False}))
        return 0
    from .sample import render_sample
    print(json.dumps(render_sample(args.out, model_source=args.model, wav=args.wav or None, fps=args.fps)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
