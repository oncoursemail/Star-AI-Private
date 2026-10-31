"""Synthetic-only visual grounding regressions. No endpoints, devices, or account actions."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import redirect_stdout
from typing import Any, Callable, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image

from star.computer import grounding, settings
from star.computer.agent import Computer
from star.computer.hands import Stopped
from star.computer.hands import Hands as GuiHands
from star.computer.screen import Screen
from star.play.capture import Frame
from star.play.humanlike import Actuator, Event, HumanProfile

checks = 0


def check(value, label):
    global checks
    assert value, label
    checks += 1


def rejected(function, label, exceptions=(ValueError, RuntimeError)):
    try:
        function()
    except exceptions:
        check(True, label)
    else:
        raise AssertionError(label)


def candidate(replies=None, *, fmt='auto'):
    grounder = grounding.VlmGrounder('http://127.0.0.1:8081/v1', 'synthetic-only', fmt=fmt, max_side=640)
    _, truth = grounding.synthetic_screen()
    lookup = dict(truth)
    calls = []

    def ask(image, query):
        calls.append(query)
        x, y = lookup[query.rsplit(' ', 1)[-1]]
        text = json.dumps({'coordinate': [round(x / 1280 * 1000), round(y / 720 * 1000)]})
        return (next(replies) if replies is not None else text), (640, 360), 0.01

    grounder.ask = ask
    return grounder, calls


class Eye:
    def __init__(self):
        self.image = Image.new('RGB', (128, 96), 'navy')
        self.reads = 0
        self.region: tuple[int,int,int,int] | None = None

    def grab(self):
        self.reads += 1
        return self.image.copy()


class FramedEye(Eye):
    def __init__(self, stale=False):
        super().__init__()
        self._capture = object()
        self.stale = stale

    def grab_frame(self):
        self.reads += 1
        return Frame(self.reads, time.perf_counter() - (10 if self.stale else 0), np.asarray(self.image))


class Sink:
    def __init__(self):
        self.events = []
        self.position = (0, 0)
        self.allowed = True

    def move_to(self, x, y):
        self.position = x, y
        self.events.append(('move', x, y))

    def button(self, name, down):
        if not self.allowed:
            class Declined(RuntimeError):
                accepted = 0
            raise Declined('synthetic original sink guard refused')
        self.events.append(('button', name, down, self.position))

    def release_button(self, name):
        self.events.append(('release', name))


class Hands:
    dry_run = False

    def __init__(self, sink):
        self.sink = sink
        self.before_down: Callable[[], None] | None = None
        self.calls = []

    def click(self, x, y, *, width, button, clicks):
        self.calls.append((x, y, width, clicks))
        player = Actuator(self.sink, clock=lambda: 0)
        player.submit([Event(0, 'move_to', x, y), Event(1, 'button_down', button), Event(2, 'button_up', button)])
        try:
            player.pump(0)
            if self.before_down is not None:
                self.before_down()
            player.pump(1)
            player.pump(2)
        finally:
            player.release_all()


def desktop(*, eye=None, infer=None):
    window = SimpleNamespace(hwnd=1, pid=10, exe='synthetic.exe', rect=(0, 0, 128, 96), title='Synthetic')
    windows = SimpleNamespace(front=window)
    windows.foreground = lambda: windows.front
    windows.screen_size = lambda: (128, 96)
    sink = Sink()
    hands = Hands(sink)
    eye = eye or Eye()
    calls = []

    def locate(image, query):
        calls.append(query)
        if infer is not None:
            infer()
        return grounding.Grounded(60, 40)

    computer = Computer(cast(Any, hands), windows=windows, eye=eye, grounder=SimpleNamespace(locate=locate),
                        executor=SimpleNamespace(dry_run=False), settings={'frame_max_age_s': .05})
    screen = Screen([], window.title, window.exe, window.hwnd, (128, 96), 'synthetic', 0)
    return computer, screen, windows, eye, hands, sink, calls


def main():
    for text in ('I cannot locate it. The screenshot is 1280 by 720.', 'Maybe (12, 20)', '(1, 2]','[1, 2, 3]',
                 '{"coordinate":[true,2]}', '{"x":NaN,"y":1}', '{"x":1e999,"y":2}',
                 '{"found":false,"x":1,"y":2}', '{"point":[1,2],"x":3,"y":4}',
                 '(1,2) (3,4)', '{"box":[10,10,1,1]}'):
        check(grounding.parse_point(text) is None, 'unrecognized or ambiguous coordinate rejected')

    grounder, calls = candidate()
    rejected(lambda: grounder.locate(Image.new('RGB', (128, 96)), 'Alpha'), 'auto mode refuses uncalibrated locate')
    check(not calls, 'uncalibrated auto mode sends no model request')
    fmt, _ = grounder.calibrate()
    check(fmt == 'unit1000' and len(calls) == 6, 'six measured points select their actual convention')
    check(grounder.calibration['points'] == 6 and grounder.calibration['max_error_px'] <= 20,
          'accepted calibration carries bounded synthetic provenance')

    missing, _ = candidate(iter(['no coordinate available']))
    rejected(missing.calibrate, 'missing answers cannot become fabricated zero points')
    check(not missing.calibration and missing._requires_calibration, 'failed calibration cannot enable locate')
    native = [(183,202),(687,153),(435,453),(136,751),(788,603),(536,851)]
    shifted, _ = candidate(iter(json.dumps({'coordinate': list(point)}) for point in native))
    rejected(shifted.calibrate, 'all-inside native label-start points still fail the predeclared center gate')
    check(not shifted.calibration, 'native failed center metrics cannot be persisted as accepted')
    repeated, _ = candidate(iter(['(500,500)'] * 6))
    rejected(repeated.calibrate, 'least-bad convention does not pass wrong-button calibration')

    for fmt, raw in (('pixels','(128,20)'), ('pixels','(-1,20)'), ('pixels','(0,0,200,40)'),
                     ('unit1000','(1001,500)'), ('unit1','(1.1,0.2)'), ('pixels','(1e999,10)')):
        bounded = grounding.VlmGrounder('http://127.0.0.1:8081/v1', 'synthetic', fmt=fmt)
        bounded.ask = lambda image, query, raw=raw: (raw, image.size, 0)
        check(bounded.locate(Image.new('RGB',(128,96)), 'synthetic') is None, 'out-of-range data never clamps into click')

    cancelled = threading.Event()
    interrupted, interrupted_calls = candidate()
    ask = interrupted.ask

    def interrupt_ask(image, query):
        reply = ask(image, query)
        cancelled.set()
        return reply

    interrupted.ask = interrupt_ask
    rejected(lambda: interrupted.calibrate(cancelled=cancelled.is_set), 'STOP interrupts synthetic calibration')
    check(len(interrupted_calls) == 1 and not interrupted.calibration, 'STOP prevents remaining requests and acceptance')

    with TemporaryDirectory() as temporary:
        home = Path(temporary)
        path = home / settings.NAME
        original_document = {'grounder': {'kind':'none', 'url':grounder.url, 'model':grounder.model,
                                          'format':'auto', 'max_side':640, 'owner_extra':'keep'},
                             'capture_hz':60, 'owner_setting':{'nested':[1,2,3]}}
        original = json.dumps(original_document).encode()
        path.write_bytes(original)
        settings.save_calibration(home, settings.calibration_snapshot(home), grounder.calibration)
        saved = json.loads(path.read_text())
        check(saved['capture_hz'] == 60 and saved['owner_setting'] == original_document['owner_setting'],
              'calibration preserves unrelated owner configuration')
        check(saved['grounder']['kind'] == 'none' and saved['grounder']['owner_extra'] == 'keep',
              'saving candidate calibration never enables it or removes unknown keys')
        check(saved['grounder']['format'] == 'unit1000' and settings.make_grounder(settings.load(home)) is None,
              'format survives reload while runtime remains disabled')
        path.write_bytes(original)
        owner_edit = original + b'\n '
        path.write_bytes(owner_edit)
        rejected(lambda: settings.save_calibration(home, original, grounder.calibration), 'concurrent owner edit blocks save')
        check(path.read_bytes() == owner_edit, 'owner edit remains byte-for-byte unchanged')
        path.write_bytes(original)
        phases = iter((False, True))
        rejected(lambda: settings.save_calibration(home, original, grounder.calibration,
                                                   cancelled=lambda: next(phases)), 'STOP during commit rolls back')
        check(path.read_bytes() == original, 'STOP rollback restores original bytes')
        with patch('star.computer.settings.os.fsync', side_effect=[OSError('synthetic disk failure'), None]):
            rejected(lambda: settings.save_calibration(home, original, grounder.calibration),
                     'failed commit rolls back', exceptions=(OSError,))
        check(path.read_bytes() == original and len(list(home.iterdir())) == 1, 'write failure creates no retained extra config')
        if os.name == 'nt':
            conflicts = []

            def conflicting_owner_write():
                try:
                    with path.open('r+b') as other:
                        other.write(b'owner edit')
                except OSError:
                    conflicts.append('write blocked')
                try:
                    path.rename(home / 'moved-owner-config.json')
                except OSError:
                    conflicts.append('replace blocked')
                return False

            settings.save_calibration(home, original, grounder.calibration, cancelled=conflicting_owner_write)
            check(conflicts == ['write blocked', 'replace blocked'] * 2,
                  'Windows lock prevents other-handle writes and replacement throughout commit')
            path.write_bytes(original)
        from star.computer.__main__ import main as cli
        with redirect_stdout(io.StringIO()), patch('star.computer.settings.make_grounder') as factory:
            check(cli(['calibrate','--home',str(home),'--dry-run']) == 3, 'preview CLI refuses calibration')
            check(not factory.called and path.read_bytes() == original, 'preview touches neither model nor config')

    computer, screen, _, _, hands, sink, calls = desktop()
    check(computer.do_click(screen, {'target':'synthetic target'})[0], 'unchanged visual target delivers click')
    check(hands.calls == [(60,40,1,1)], 'grounded point and one-pixel precision are never jittered')
    check(sink.events[-2:] == [('button','left',True,(60,40)),('button','left',False,(60,40))],
          'accepted click retains matching press and release')
    check(GuiHands(sink).profile.miss_p == 0, 'default GUI hands never deliberately miss')
    explicit_profile = HumanProfile(miss_p=.25)
    check(GuiHands(sink, profile=explicit_profile).profile is explicit_profile,
          'an explicitly supplied GUI profile is preserved')
    check(HumanProfile().miss_p > 0, 'game profile default remains separate from GUI accuracy default')

    computer, screen, windows, eye, _, sink, calls = desktop()
    windows.front.hwnd = 2
    check(not computer.do_click(screen, {'target':'synthetic'})[0] and not calls and eye.reads == 0,
          'wrong initial foreground prevents even picture submission')
    for mode in ('preview', 'STOP'):
        computer, screen, _, _, _, sink, calls = desktop()
        stop = threading.Event()
        computer._stopped = stop.is_set

        def interrupt_model(image, query):
            calls.append(query)
            if mode == 'preview':
                executor = computer.executor
                assert executor is not None
                executor.dry_run = True
            else:
                stop.set()
            return grounding.Grounded(60,40)

        computer.grounder = SimpleNamespace(locate=interrupt_model)
        check(not computer.do_click(screen, {'target':'synthetic'})[0] and len(calls) == 1 and not sink.events,
              'admission flip inside actual model invocation discards coordinate')

    computer, screen, _, _, hands, sink, _ = desktop()
    stop = threading.Event()
    computer._stopped = stop.is_set
    hands.before_down = stop.set
    rejected(lambda: computer.do_click(screen, {'target':'synthetic'}), 'STOP during pointer movement prevents press',
             exceptions=(Stopped,))
    check(not any(event[0] in ('button','release') for event in sink.events),
          'STOP before native press preserves owner-held buttons')

    for stage in ('conversion', 'comparison'):
        stop = threading.Event()
        armed = threading.Event()

        class ConversionImage:
            size = (128, 96)

            def convert(self, mode):
                if armed.is_set() and stage == 'conversion':
                    stop.set()
                return Image.new('RGB', self.size, 'navy')

        converting_eye = SimpleNamespace(grab=lambda: ConversionImage())
        computer, screen, _, _, hands, sink, _ = desktop(eye=converting_eye)
        computer._stopped = stop.is_set
        hands.before_down = armed.set
        from PIL import ImageChops
        real_difference = ImageChops.difference

        def compare_then_stop(*args):
            result = real_difference(*args)
            if armed.is_set() and stage == 'comparison':
                stop.set()
            return result

        with patch('PIL.ImageChops.difference', side_effect=compare_then_stop):
            rejected(lambda: computer.do_click(screen, {'target':'synthetic'}),
                     'STOP inside expensive image operation is rechecked before native press', exceptions=(Stopped,))
        check(not any(event[0] in ('button','release') for event in sink.events),
              'late image-operation admission failure emits neither press nor cleanup release')

    for attribute, value in (('hwnd',2),('pid',11),('rect',(1,0,129,96)),('title','Changed')):
        computer, screen, windows, _, _, sink, _ = desktop()
        assert computer.grounder is not None
        computer.grounder.locate = lambda image, query, attribute=attribute, value=value: (
            setattr(windows.front, attribute, value) or grounding.Grounded(60,40))
        check(not computer.do_click(screen, {'target':'synthetic'})[0] and not sink.events,
              'foreground identity change during inference cancels click')

    computer, screen, windows, _, _, sink, _ = desktop()
    windows.front.rect = (0,0,40,40)
    check(not computer.do_click(screen, {'target':'synthetic'})[0] and not sink.events,
          'desktop-valid point outside bound foreground can never click a background app')
    computer, screen, _, eye, _, sink, calls = desktop()
    eye.region = (100,100,228,196)
    check(not computer.do_click(screen, {'target':'synthetic'})[0] and not calls and not sink.events,
          'nonzero image ROI never guessed as global desktop coordinates')
    computer, screen, _, eye, _, sink, calls = desktop()
    eye.image = Image.new('RGB',(64,48),'navy')
    check(not computer.do_click(screen, {'target':'synthetic'})[0] and not calls and not sink.events,
          'cropped image with undeclared origin is refused')

    computer, screen, _, eye, _, sink, _ = desktop()
    assert computer.grounder is not None
    computer.grounder.locate = lambda image, query: (eye.image.putpixel((0,0),(255,255,255)) or grounding.Grounded(60,40))
    check(not computer.do_click(screen, {'target':'synthetic'})[0] and not sink.events,
          'even a one-pixel content change after model invalidates target')

    computer, screen, windows, _, hands, sink, _ = desktop()
    hands.before_down = lambda: setattr(windows.front, 'hwnd', 2)
    rejected(lambda: computer.do_click(screen, {'target':'synthetic'}), 'window changed during mouse movement blocks down',
             exceptions=(Stopped,))
    check(not any(event[0] in ('button','release') for event in sink.events),
          'known zero emitted presses never release an owner-held button')
    check(hands.sink is sink, 'declined visual click restores original guarded sink')

    framed = FramedEye()
    computer, screen, _, _, _, sink, _ = desktop(eye=framed, infer=lambda: time.sleep(.55))
    check(computer.do_click(screen, {'target':'synthetic'})[0],
          'slow inference can click only after fresh unchanged scene confirmation, not original-frame-age rejection')
    framed = FramedEye()
    computer, screen, _, _, _, sink, _ = desktop(eye=framed)
    assert computer.grounder is not None
    computer.grounder.locate = lambda image, query: (setattr(framed, '_capture', object()) or grounding.Grounded(60,40))
    check(not computer.do_click(screen, {'target':'synthetic'})[0] and not sink.events,
          'source generation replacement invalidates otherwise identical pixels')
    computer, screen, _, _, _, sink, calls = desktop(eye=FramedEye(stale=True))
    check(not computer.do_click(screen, {'target':'synthetic'})[0] and not calls and not sink.events,
          'stale source frame cannot reach model or mouse')
    computer, screen, _, _, hands, sink, _ = desktop()
    hands.before_down = lambda: setattr(sink, 'allowed', False)
    rejected(lambda: computer.do_click(screen, {'target':'synthetic'}), 'original native sink guard remains enforced',
             exceptions=(RuntimeError,))
    check(not any(event[0] in ('button','release') for event in sink.events), 'original guard rejection emits no press or cleanup release')
    print(f'{checks} synthetic visual grounding checks passed; no endpoint, native input, or owner-state access.')


if __name__ == '__main__':
    main()
