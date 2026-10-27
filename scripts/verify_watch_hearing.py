"""Offline watch-hearing checks with fake capture, ASR, VAD and host hooks.

Run from any directory with the project Python environment.
"""

import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star.home import voicestack, plugins, control
from star.watch.hearing import HubHearing, FallbackHearing
from star.watch.model import Line, AudioState
from star.senses.hearing import HeardLine


def main():
    checks = []

    def check(name, ok):
        if not ok:
            raise AssertionError(name)
        checks.append(name)

    class Source:
        made = []

        def __init__(self):
            self._stop = threading.Event()
            self.closed = False
            self.made.append(self)

        def frames(self):
            while not self._stop.wait(0.005):
                yield b"\0\0" * 512

        def close(self):
            self.closed = True
            self._stop.set()

    class VAD:
        def probability(self, frame):
            return 0.0

    class ASR:
        def transcribe(self, *args):
            return ""

    settings = SimpleNamespace(hear_pc_audio=True, vad="energy")
    with (
        patch.object(voicestack, "_settings", return_value=settings),
        patch.object(voicestack, "_engines", return_value=SimpleNamespace(asr=ASR())) as engines,
        patch("star.senses.capture.LoopbackSource", Source),
        patch("star.voice.engines.make_vad", return_value=VAD()),
    ):
        with voicestack.watch_hearing({}) as view:
            check("managed live hearing starts", view is not None and view.available())
            actual = view.hub
            check("shared playback reference", actual.reference is voicestack._reference())
        check("owned capture closes", Source.made[-1].closed and not view.thread.is_alive())
        check("owned hub stops", actual._stop.is_set())
        check("voice engines reused", engines.call_count == 1)
        borrowed = SimpleNamespace(lines=[])
        with voicestack.watch_hearing({}, hub=borrowed) as view2:
            check("external hub borrowed by identity", view2 is borrowed)
        check("borrow does not load voice engines", engines.call_count == 1)
    with (
        patch.object(voicestack, "_settings", return_value=settings),
        patch.object(voicestack, "_engines", side_effect=RuntimeError("model missing")),
        patch("star.senses.capture.LoopbackSource", Source),
    ):
        errors = []
        with voicestack.watch_hearing({}, on_unavailable=errors.append) as missing:
            check("missing engines permit caption fallback", missing is None and errors == ["RuntimeError"])
        check("partial construction capture closes", Source.made[-1].closed)

        def broken_report(kind):
            raise RuntimeError("reporting failed")

        with voicestack.watch_hearing({}, on_unavailable=broken_report) as missing:
            check("reporter failure preserves fallback", missing is None)
        check("reporter failure still closes capture", Source.made[-1].closed)

    with (
        patch.object(voicestack, "_settings", return_value=settings),
        patch.object(voicestack, "_engines", return_value=SimpleNamespace(asr=ASR())),
        patch("star.senses.capture.LoopbackSource", Source),
        patch("star.voice.engines.make_vad", return_value=VAD()),
    ):
        try:
            with voicestack.watch_hearing({}) as view:
                raise ValueError("activity failed")
        except ValueError:
            pass
        check("activity exception closes capture and hub", Source.made[-1].closed and view.hub._stop.is_set())

    shared_engines = SimpleNamespace(asr=ASR())

    def load_engines(settings):
        time.sleep(0.02)
        return shared_engines

    with (
        patch.dict(voicestack._engines_cache, {}, clear=True),
        patch("star.voice.runtime.Engines.load", side_effect=load_engines) as loader,
        ThreadPoolExecutor(max_workers=4) as pool,
    ):
        loaded = list(pool.map(voicestack._engines, [settings] * 4))
        check("concurrent first use loads engines once", loader.call_count == 1)
        check("concurrent consumers share engine identity", all(value is shared_engines for value in loaded))

    class Hub:
        def __init__(self):
            self.lines = [HeardLine("loopback", "old video", 8.0, 9.0), HeardLine("mic", "room", 10.0, 11.0)]
            self.up = True

        def clock(self):
            return 15.0

        def snapshot(self):
            return {"loopback": {"label": "speech", "level_db": -20, "partial": ""}}

        def available(self):
            return self.up

    hub = Hub()
    heard = HubHearing(hub, since=10.0)
    hub.lines += [
        HeardLine("loopback", "overlapping old utterance", 9.0, 12.0),
        HeardLine("loopback", "new video", 11.0, 13.0),
    ]
    check("prior video and room audio excluded", heard.poll(20.0) == [Line(16.0, "new video", "heard")])

    class Captions:
        def __init__(self):
            self.last = -1

        def poll(self, p):
            out = [Line(t, s, "caption") for t, s in [(1, "old caption"), (22, "new caption")] if self.last < t <= p]
            self.last = p
            return out

        def state(self, p):
            return AudioState("speech", -20, True)

    made = []

    def captions():
        made.append(1)
        return Captions()

    fallback = FallbackHearing(hub, captions, since=14.0)
    check("live source starts without fetching captions", fallback.poll(20.0) == [] and not made)
    hub.up = False
    check(
        "capture failure switches once without replay",
        fallback.poll(23.0) == [Line(22, "new caption", "caption")] and fallback.mode == "captions",
    )
    fallback.poll(24.0)
    fallback.state(24.0)
    check("captions loaded only once", len(made) == 1)
    fallback2 = FallbackHearing(hub, lambda: None, since=0)
    check("absent fallback reports picture only", fallback2.poll(1) == [] and fallback2.mode == "picture only")

    from star import watch

    oldparts = dict(vars(watch.configure()))
    try:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            record = []

            @contextmanager
            def factory(config, **kw):
                record.append("open")
                try:
                    yield hub
                finally:
                    record.append("close")

            rt = SimpleNamespace(
                home=home,
                config={},
                life=SimpleNamespace(interests=lambda: {"watch_videos": {}}, set_interest=lambda *a: None),
                voice=SimpleNamespace(speak=lambda *a: True),
                hooks={"watch_hearing": factory},
            )

            def inner(ctx):
                check("watch activity receives live hub", watch.configure().hub is hub)
                return {"ok": True, "verified": False, "summary": "watched", "evidence": []}

            activity = SimpleNamespace(run=inner)
            registry = SimpleNamespace(runtime=rt, items={"watch_videos": activity}, plugin_errors={})
            watch.configure(hub=None)
            plugins.wire_watch(registry)
            ctx = SimpleNamespace(interrupt=SimpleNamespace(is_set=lambda: False))
            activity.run(ctx)
            check(
                "normal activity restores parts and capture",
                watch.configure().hub is None and record == ["open", "close"],
            )
            control.stop(home)
            out = activity.run(ctx)
            check("STOP prevents capture and activity", out.get("stopped") is True and record == ["open", "close"])
    finally:
        watch.configure(**oldparts)
    print(str(len(checks)) + " standalone watch-hearing checks passed")
    for name in checks:
        print("  " + name)


if __name__ == "__main__":
    main()
