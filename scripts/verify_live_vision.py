"""Hardware-free retained checks. No screenshots, model calls, files, or native devices."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np

from star.computer.eye import ScreenEye
from star.computer.live_vision import LatestFrameCapture
from star.play.capture import DxcamCapture, Frame, MssCapture

checks = 0


def check(ok, label):
    global checks
    assert ok, label
    checks += 1


def until(predicate, timeout=2):
    deadline = time.perf_counter() + timeout
    while not predicate():
        if time.perf_counter() >= deadline:
            raise AssertionError('bounded wait expired')
        time.sleep(.002)


class Source:
    name = 'fake'

    def __init__(self, *, gate=None, fail=False, close_fail=False, stale=False):
        self.owner = threading.get_ident()
        self.grab_threads, self.close_threads = [], []
        self.index = 0
        self.pixels = np.zeros((8, 8, 3), dtype=np.uint8)
        self.gate, self.fail, self.close_fail, self.stale = gate, fail, close_fail, stale
        self.entered = threading.Event()
        self.closed = threading.Event()

    def grab(self):
        self.grab_threads.append(threading.get_ident())
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(3)
        if self.fail:
            raise RuntimeError('private window text must not be logged')
        self.index += 1
        self.pixels[:] = self.index % 255
        return Frame(self.index, time.perf_counter() - (10 if self.stale else 0), self.pixels)

    def close(self):
        self.close_threads.append(threading.get_ident())
        self.closed.set()
        if self.close_fail:
            raise RuntimeError('private native detail')


def make_capture(**kwargs):
    sources = []

    def factory():
        item = Source(**kwargs)
        sources.append(item)
        return item

    capture = LatestFrameCapture(factory, hz=60, max_age_s=.2)
    capture.start()
    until(lambda: bool(sources))
    return capture, sources


def integration_checks():
    import star.computer as computer_module
    from star.computer.agent import Computer
    from star.computer.screen import Screen, Element
    from star.computer.hands import Hands as RealHands, Stopped
    from star.computer.__main__ import main as computer_cli
    from contextlib import ExitStack, redirect_stdout
    import io

    native_sources = []
    pending_gate = None

    def source_factory(region):
        source = Source(gate=pending_gate)
        native_sources.append(source)
        return source

    def eye_factory(**kwargs):
        return ScreenEye(source_factory, hz=60, **kwargs)

    with TemporaryDirectory() as temporary, ExitStack() as stack:
        home = Path(temporary) / 'home'
        ctx = SimpleNamespace(home=home, executor=SimpleNamespace(dry_run=False), interrupt=threading.Event(),
                              config={}, chat=lambda *args: {}, goal={'text': 'a bounded task'}, practice_topic='')
        stack.enter_context(patch('star.computer.winapi.ensure_dpi_aware'))
        stack.enter_context(patch('star.computer.winapi.Windows', return_value=SimpleNamespace()))
        stack.enter_context(patch('star.computer.winapi.DesktopSink', return_value=object()))
        stack.enter_context(patch('star.computer.uia.ComtypesUia', return_value=object()))
        stack.enter_context(patch('star.computer.hands.Hands', side_effect=lambda *args, **kw:
                                  SimpleNamespace(dry_run=kw.get('dry_run', False))))
        stack.enter_context(patch('star.computer.eye.ScreenEye', side_effect=eye_factory))
        stack.enter_context(patch('star.home.control.stopped', return_value=False))
        stack.enter_context(patch('star.computer.settings.make_grounder', return_value=None))

        computer = computer_module.build_computer(ctx)
        assert computer.eye is not None
        check(computer.eye.grab_frame() is not None, 'real builder starts continuous fake capture')
        alias = SimpleNamespace(**vars(ctx))
        alias.home = home / '..' / 'home'
        try:
            computer_module.build_computer(alias)
        except RuntimeError:
            check(True, 'canonical home aliases cannot duplicate active capture')
        else:
            raise AssertionError('duplicate canonical owner admitted')
        check(computer._shot() is not None, 'externally built Computer reusable before explicit close')
        check(computer.close(), 'Computer.close releases its capture ownership')
        check(computer._shot() is None, 'closed Computer cannot take screenshots')

        ctx.executor.dry_run = True
        count = len(native_sources)
        computer = computer_module.build_computer(ctx)
        check(computer._shot() is None and len(native_sources) == count, 'preview builder never opens capture')
        calls = []
        computer.grounder = SimpleNamespace(locate=lambda *args: calls.append(True))
        screen = Screen([], 'synthetic', 'fake.exe', 1, (8, 8), 'fake', time.monotonic())
        check(computer.resolve(screen, {'target': 'unlisted'})[0] is None and not calls,
              'preview refuses vision network fallback')
        computer.close()
        ctx.executor.dry_run = False

        ctx.executor.dry_run = True
        planned = []
        sink_events = []
        fake_sink = SimpleNamespace(move=lambda *args: sink_events.append('move'),
                                    button=lambda *args: sink_events.append('button'))
        with patch('star.computer.hands.Hands', RealHands), patch('star.computer.winapi.DesktopSink',
                                                                return_value=fake_sink), patch(
                'star.home.control.log_action', side_effect=lambda *args, **kwargs: planned.append((args, kwargs))):
            computer = computer_module.build_computer(ctx)
            button = Element(1, 'safe synthetic control', 'button', (0, 0, 8, 8))
            uia_screen = Screen([button], 'synthetic', 'fake.exe', 1, (8, 8), 'fake', time.monotonic())
            check(computer.do_click(uia_screen, {'id': 1})[0] and not sink_events,
                  'preview UIA action can be planned without native input')
            check(len(planned) == 2 and all(item[1]['dry_run'] for item in planned),
                  'preview Hands preserves start and done planning logs')
            computer.close()
        ctx.executor.dry_run = False

        computer = computer_module.build_computer(ctx)
        assert computer.eye is not None
        computer.eye.grab_frame()

        def preview_during_vision(*args):
            ctx.executor.dry_run = True
            return SimpleNamespace(x=4, y=4)

        computer.grounder = SimpleNamespace(locate=preview_during_vision)
        check(computer.resolve(screen, {'target': 'unlisted'})[0] is None,
              'preview flip during vision discards returned coordinates')
        computer.close()
        ctx.executor.dry_run = False

        computer = computer_module.build_computer(ctx)
        assert computer.eye is not None
        computer.eye.grab_frame()
        ctx.interrupt.set()
        check(computer._shot() is None, 'context interrupt blocks capture consumption')
        check(computer.close(), 'interrupted activity releases resources')
        ctx.interrupt.clear()

        sink_events = []
        fake_sink = SimpleNamespace(move=lambda *args: sink_events.append('move'),
                                    button=lambda *args: sink_events.append('button'))
        ctx.interrupt.set()
        with patch('star.computer.hands.Hands', RealHands), patch('star.computer.winapi.DesktopSink',
                                                                return_value=fake_sink):
            computer = computer_module.build_computer(ctx)
            button = Element(1, 'safe synthetic control', 'button', (0, 0, 8, 8))
            uia_screen = Screen([button], 'synthetic', 'fake.exe', 1, (8, 8), 'fake', time.monotonic())
            try:
                computer.do_click(uia_screen, {'id': 1})
            except Stopped:
                check(not sink_events, 'context interrupt blocks actual Hands even for a successful UIA target')
            else:
                raise AssertionError('interrupted UIA target reached sink')
            computer.close()
        ctx.interrupt.clear()

        count = len(native_sources)
        with patch('star.home.control.stopped', return_value=True):
            computer = computer_module.build_computer(ctx)
            check(computer._shot() is None and len(native_sources) == count, 'initial owner STOP opens no capture')
            computer.close()
        with patch('star.computer.winapi.Windows', side_effect=RuntimeError('synthetic constructor failure')):
            try:
                computer_module.build_computer(ctx)
            except RuntimeError:
                check(computer_module._ownership_key(home) not in computer_module._CAPTURE_OWNERS,
                      'native constructor failure releases unstarted ownership reservation')

        pending_gate = threading.Event()
        computer = computer_module.build_computer(ctx)
        until(lambda: bool(native_sources) and native_sources[-1].entered.is_set())
        check(not computer.close(.02), 'Computer does not launder incomplete native cleanup')
        try:
            computer_module.build_computer(ctx)
        except RuntimeError:
            check(True, 'pending cleanup blocks next activity for same home')
        else:
            raise AssertionError('new capture admitted before previous cleanup')
        pending_gate.set()
        pending_eye = computer.eye
        assert pending_eye is not None
        until(lambda: pending_eye.status()['cleanup_complete'])
        pending_gate = None
        replacement = computer_module.build_computer(ctx)
        check(replacement is not computer, 'completed pending cleanup allows a fresh owner')
        replacement.close()

        stack.enter_context(patch('star.computer.sys.platform', 'win32'))
        with patch.object(Computer, 'act', return_value={'ok': True, 'verified': True, 'summary': 'fake',
                                                       'failures': [], 'evidence': []}):
            result = computer_module.use_app_activity(ctx)
        check(result['verified'] and computer_module._ownership_key(home) not in computer_module._CAPTURE_OWNERS,
              'Home use_app finally closes its privately built Computer')

        plan = SimpleNamespace(strokes=[])
        with patch('star.computer.draw.plan_drawing', return_value=(plan, '')), patch(
                'star.computer.draw.draw_session', return_value={'ok': True, 'verified': True, 'summary': 'fake',
                                                               'failures': [], 'evidence': []}):
            result = computer_module.draw_activity(ctx)
        check(result['verified'] and computer_module._ownership_key(home) not in computer_module._CAPTURE_OWNERS,
              'Home draw finally closes its privately built Computer')

        with patch('star.computer.draw.plan_drawing', return_value=(plan, '')), patch(
                'star.computer.draw.draw_session', side_effect=RuntimeError('synthetic drawing failure')):
            try:
                computer_module.draw_activity(ctx)
            except RuntimeError:
                check(computer_module._ownership_key(home) not in computer_module._CAPTURE_OWNERS,
                      'drawing exception still releases capture ownership')

        with patch.object(Computer, 'act', side_effect=RuntimeError('synthetic failure')):
            try:
                computer_module.use_app_activity(ctx)
            except RuntimeError:
                check(computer_module._ownership_key(home) not in computer_module._CAPTURE_OWNERS,
                      'Home use_app exception still releases capture')

        pending_gate = threading.Event()

        def quick_act(self, *args, **kwargs):
            until(lambda: native_sources[-1].entered.is_set())
            return {'ok': True, 'verified': True, 'goal_done': True, 'summary': 'fake', 'failures': []}

        with patch.object(Computer, 'act', quick_act):
            result = computer_module.use_app_activity(ctx)
        check(not result['ok'] and not result['verified'] and not result['goal_done'],
              'incomplete cleanup downgrades all Home completion fields')
        key = computer_module._ownership_key(home)
        check(key in computer_module._CAPTURE_OWNERS and computer_module._CAPTURE_OWNERS[key].computer is not None,
              'pending cleanup keeps a strong owner reference')
        pending_gate.set()
        pending = computer_module._CAPTURE_OWNERS[key].computer
        until(lambda: pending.eye.status()['cleanup_complete'])
        pending.close(0)
        pending_gate = None

        with redirect_stdout(io.StringIO()):
            check(computer_cli(['calibrate', '--dry-run', '--home', str(home)]) == 3,
                  'CLI preview calibrate makes no model request')

        result = {'ok': True, 'verified': True, 'goal_done': True}
        broken = SimpleNamespace(close=lambda **kwargs: (_ for _ in ()).throw(RuntimeError('synthetic close failure')))
        computer_module._close_result(broken, result)
        check(not result['ok'] and not result['verified'] and not result['goal_done'],
              'close exception produces unverified result without masking activity exception')

    regions = []
    with patch('star.computer.eye.open_capture', side_effect=lambda region, **kwargs:
               regions.append((region, kwargs)) or Source()):
        eye = ScreenEye()
        check(eye.grab_frame((-8, 0, 0, 8)) is not None, 'global negative-origin rectangle supported')
        eye.close()
    check(regions[0][1]['prefer'] == ('mss', 'gdi'), 'global ROI never passed to output-relative DXcam')


def main():
    for bad in (0, -1, 61, float('nan'), float('inf')):
        try:
            LatestFrameCapture(lambda: Source(), hz=bad)
        except ValueError:
            check(True, 'invalid rate rejected')
        else:
            raise AssertionError('invalid rate accepted')
    for bad in (0, -1, float('nan'), 11):
        try:
            LatestFrameCapture(lambda: Source(), max_age_s=bad)
        except ValueError:
            check(True, 'invalid freshness rejected')
        else:
            raise AssertionError('invalid age accepted')

    capture, sources = make_capture()
    try:
        first = capture.grab(timeout=1)
        check(first is not None, 'first frame delivered')
        assert first is not None
        first_index = first.index
        saved = first.image.copy()
        until(lambda: capture.status()['new_frames'] >= first_index + 5)
        newest = capture.grab()
        assert newest is not None
        check(newest.index >= first.index + 5, 'slow reader skips queued old frames')
        check(capture.status()['buffered_frames'] == 1, 'single bounded slot')
        check(capture.status()['overwritten_unread'] >= 3, 'unread overwrites observable')
        check(np.array_equal(first.image, saved), 'native buffer reuse cannot mutate published pixels')
        check(not first.image.flags.writeable, 'published pixels read only')
        try:
            first.image.setflags(write=True)
        except ValueError:
            check(True, 'consumer cannot re-enable writes on shared slot')
        else:
            raise AssertionError('published image can be made writable')
        check(not capture.status()['perception_connected'], 'capture never claims model vision')
        check(capture.status()['capture_new_frame_hz'] <= 85, 'capture pacing bounded')
    finally:
        check(capture.close(), 'normal close completes')
    source = sources[0]
    check(source.owner == source.grab_threads[0] == source.close_threads[0], 'native owner thread consistent')
    check(capture.grab() is None, 'closed frame invalidated')
    check(capture.close(), 'close idempotent')

    gate = threading.Event()
    capture, sources = make_capture(gate=gate)
    check(sources[0].entered.wait(1), 'blocked native grab entered')
    began = time.perf_counter()
    check(not capture.close(.02), 'blocked capture reports incomplete cleanup')
    check(time.perf_counter() - began < .3, 'close bounded while native call stalls')
    check(capture.grab() is None, 'close rejects late native frame immediately')
    gate.set()
    until(lambda: capture.status()['cleanup_complete'])
    check(capture.status()['new_frames'] == 0, 'late frame after close never publishes')
    check(len(sources[0].close_threads) == 1, 'late native source closed once')

    copy_entered, release_copy = threading.Event(), threading.Event()

    class SlowPixels(np.ndarray):
        def tobytes(self, *args, **kwargs):
            copy_entered.set()
            release_copy.wait(3)
            return super().tobytes(*args, **kwargs)

    def slow_pixels_source():
        item = Source()
        item.pixels = item.pixels.view(SlowPixels)
        return item

    capture = LatestFrameCapture(slow_pixels_source)
    capture.start()
    check(copy_entered.wait(1), 'pixel conversion stall entered')
    began = time.perf_counter()
    check(not capture.close(.02), 'copy stall reports pending cleanup')
    check(time.perf_counter() - began < .3, 'close deadline excludes blocked pixel conversion')
    release_copy.set()
    until(lambda: capture.status()['cleanup_complete'])
    check(capture.status()['new_frames'] == 0, 'late copied pixels never publish after close')

    start_entered, release_start = threading.Event(), threading.Event()
    real_start = threading.Thread.start

    def delayed_start(thread):
        if thread.name == 'desktop-capture':
            start_entered.set()
            release_start.wait(3)
        return real_start(thread)

    made = []
    capture = LatestFrameCapture(lambda: made.append(Source()) or made[-1])
    with patch('threading.Thread.start', delayed_start):
        launcher = threading.Thread(target=capture.start, name='owner-starter')
        launcher.start()
        check(start_entered.wait(1), 'native worker launch stall entered')
        began = time.perf_counter()
        check(not capture.close(.02), 'unstarted pending worker not joined or claimed closed')
        check(time.perf_counter() - began < .3, 'close bounded while OS thread startup pending')
        release_start.set()
        launcher.join(1)
    until(lambda: capture.status()['cleanup_complete'])
    check(not made, 'late worker launch after close cannot open source')

    factory_entered, release_factory = threading.Event(), threading.Event()

    def interrupted_factory():
        factory_entered.set()
        release_factory.wait(3)
        return Source()

    def interrupted_start(thread):
        real_start(thread)
        if thread.name == 'desktop-capture':
            assert factory_entered.wait(1)
            raise KeyboardInterrupt()

    capture = LatestFrameCapture(interrupted_factory)
    with patch('threading.Thread.start', interrupted_start):
        try:
            capture.start()
        except KeyboardInterrupt:
            check(not capture.close(.02), 'interrupt after OS launch retains pending native worker')
        else:
            raise AssertionError('interrupted launch hidden')
    release_factory.set()
    until(lambda: capture.status()['cleanup_complete'])
    check(capture.grab() is None, 'interrupted startup cannot publish pixels')

    stopped = threading.Event()
    made = []
    capture = LatestFrameCapture(lambda: made.append(Source()) or made[-1], stopped=stopped.is_set)
    stopped.set()
    capture.start()
    check(not made and capture.grab() is None, 'initial STOP prevents source creation')
    capture.close()
    stopped.clear()
    capture = LatestFrameCapture(lambda: Source(), hz=60, stopped=stopped.is_set)
    capture.start()
    check(capture.grab(timeout=1) is not None, 'running source delivered')
    stopped.set()
    check(capture.grab() is None, 'STOP invalidates already captured pixels')
    until(lambda: capture.status()['closed'])
    check(capture.close(), 'STOP releases source')

    capture, _ = make_capture(stale=True)
    check(capture.grab(timeout=.05) is None, 'stale backend pixels never delivered')
    check(not capture.status()['available'], 'stale state unavailable')
    capture.close()
    capture, _ = make_capture(fail=True)
    until(lambda: capture.status()['closed'])
    check(capture.status()['error_type'] == 'RuntimeError', 'error reports type only')
    check('private' not in str(capture.status()), 'exception text absent from metadata')
    check(capture.close(), 'failed grab releases source')
    capture, _ = make_capture(close_fail=True)
    check(not capture.close(), 'failed native close not claimed complete')

    made = []
    capture = LatestFrameCapture(lambda: made.append(Source()) or made[-1])
    with patch('threading.Thread.start', side_effect=RuntimeError('private native detail')):
        try:
            capture.start()
        except RuntimeError:
            check(capture.close() and not made, 'thread startup failure closes without joining unstarted thread')
            check(capture.status()['error_type'] == 'RuntimeError', 'thread startup failure metadata only')
        else:
            raise AssertionError('thread startup failure hidden')

    calls = []
    eye = ScreenEye(lambda region: calls.append((region, Source())) or calls[-1][1], hz=60)
    first = eye.grab((0, 0, 8, 8))
    check(first.size == (8, 8), 'ScreenEye existing PIL grab interface')
    before = eye.status()['new_frames']
    until(lambda: eye.status()['new_frames'] >= before + 3)
    check(len(calls) == 1, 'capture continues between caller snapshots with one source')
    eye.grab((8, 8, 16, 16))
    check(calls[0][1].closed.is_set() and len(calls) == 2, 'region handoff closes old source first')
    check(eye.close(), 'eye explicit lifecycle closes source')
    try:
        eye.grab()
    except RuntimeError:
        check(True, 'closed eye cannot silently restart')

    start_entered, release_start = threading.Event(), threading.Event()
    eye = ScreenEye(lambda region: Source())
    errors = []

    def eye_start():
        try:
            eye.start()
        except Exception as exc:
            errors.append(type(exc).__name__)

    with patch('threading.Thread.start', delayed_start):
        launcher = threading.Thread(target=eye_start, name='eye-owner-starter')
        launcher.start()
        check(start_entered.wait(1), 'Eye native launch stall entered')
        began = time.perf_counter()
        check(not eye.close(.02), 'Eye keeps stalled launch cleanup pending')
        check(time.perf_counter() - began < .3, 'Eye close deadline not held by startup owner lock')
        release_start.set()
        launcher.join(1)
    until(lambda: eye.status()['cleanup_complete'])
    check(not errors and not eye.status()['available'], 'late Eye startup remains closed')

    eye = ScreenEye(lambda region: Source(), hz=60)
    original_start = eye.start
    region_entered, release_region = threading.Event(), threading.Event()
    region_a, region_b = (0, 0, 8, 8), (8, 8, 16, 16)
    region_results = []

    def paused_start(region=None):
        owned = original_start(region)
        if region == region_a:
            region_entered.set()
            release_region.wait(3)
        return owned

    with patch.object(eye, 'start', paused_start):
        reader = threading.Thread(target=lambda: region_results.append(eye.grab_frame(region_a)))
        reader.start()
        check(region_entered.wait(1), 'region A reader paused after own source start')
        check(eye.grab_frame(region_b) is not None, 'region B source replaced A successfully')
        release_region.set()
        reader.join(1)
    check(region_results == [None], 'region A caller cannot receive region B pixels')
    eye.close()

    pixels = np.zeros((2, 2, 3), dtype=np.uint8)
    results = iter((pixels, None))
    camera = DxcamCapture.__new__(DxcamCapture)
    released = []
    camera._cam = SimpleNamespace(grab=lambda **kwargs: next(results), release=lambda: released.append(True))
    camera.region, camera.index = None, 0
    check(camera.grab() is not None and camera.grab() is None, 'DXcam no-update pixels not restamped')
    check(camera.index == 1, 'DXcam genuine updates alone increment sequence')
    camera.close()
    camera.close()
    check(len(released) == 1, 'DXcam release explicit and idempotent')

    confirmations = []
    static = DxcamCapture.__new__(DxcamCapture)
    static.region, static.index, static._fresh_snapshot = None, 0, True
    static._cam = SimpleNamespace(grab=lambda **kwargs: confirmations.append(kwargs) or pixels,
                                  release=lambda: None)
    first, second = static.grab(), static.grab()
    check(first is not None and second is not None and second.t >= first.t,
          'unchanged desktop freshly confirmed by backend')
    check(all(c['new_frame_only'] is False for c in confirmations), 'fresh snapshot explicit API contract')
    static._cam.grab = lambda **kwargs: None
    check(static.grab() is None, 'missing confirmation never reuses static pixels')
    static._cam.grab = lambda **kwargs: (_ for _ in ()).throw(RuntimeError('access lost private detail'))
    capture = LatestFrameCapture(lambda: static)
    capture.start()
    until(lambda: capture.status()['closed'])
    check(capture.grab() is None and capture.status()['error_type'] == 'RuntimeError',
          'DXGI access lost closes without stale pixels or physical fallback')

    entered, release_factory = threading.Event(), threading.Event()
    late_source = []

    def delayed_factory():
        entered.set()
        release_factory.wait(3)
        item = Source()
        late_source.append(item)
        return item

    capture = LatestFrameCapture(delayed_factory)
    capture.start()
    check(entered.wait(1), 'delayed factory entered')
    check(not capture.close(.02), 'factory startup race has bounded close')
    release_factory.set()
    until(lambda: capture.status()['cleanup_complete'])
    check(late_source[0].closed.is_set() and not late_source[0].grab_threads,
          'STOP during source creation closes it without first capture')

    capture, _ = make_capture()
    readers = []
    try:
        until(lambda: capture.status()['new_frames'] >= 2)
        threads = [threading.Thread(target=lambda: readers.append(capture.grab())) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(1)
        check(len(readers) == 8 and all(f is not None for f in readers), 'parallel readers share latest safely')
        check(capture.status()['buffered_frames'] == 1, 'parallel consumers do not create frame queues')
    finally:
        capture.close()

    created, native_released = [], []

    def create(**kwargs):
        item = SimpleNamespace(grab=lambda **kw: pixels, release=lambda: native_released.append(True))
        created.append(item)
        return item

    with patch.dict(sys.modules, {'dxcam': SimpleNamespace(create=create)}):
        first_owner = DxcamCapture()
        try:
            DxcamCapture()
        except RuntimeError:
            check(len(created) == 1, 'independent source cannot borrow DXcam singleton')
        else:
            raise AssertionError('DXcam singleton silently shared')
        first_owner.close()
        second_owner = DxcamCapture()
        check(len(created) == 2 and len(native_released) == 1, 'new owner admitted only after release')
        second_owner.close()
        check(len(native_released) == 2, 'each native owner released once')

    mss_closed = []
    monitor = {'left': -640, 'top': 0, 'width': 640, 'height': 480}
    with patch.dict(sys.modules, {'mss': SimpleNamespace(mss=lambda: SimpleNamespace(
            monitors=[{}, monitor], close=lambda: mss_closed.append(True)))}):
        source = MssCapture()
        check(source._box == {'left': -640, 'top': 0, 'width': 640, 'height': 480},
              'MSS default uses actual monitor geometry')
        source.close()
        try:
            MssCapture((2, 2, 1, 1))
        except ValueError:
            check(len(mss_closed) == 2, 'MSS failed setup closes native allocation')
    integration_checks()
    print(f'{checks} live capture checks passed; no native capture, model, or owner-state writes.')


if __name__ == '__main__':
    main()
