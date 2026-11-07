"""Check audio worker COM ownership and failure reporting without opening audio."""
from contextlib import contextmanager
import queue
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star.home.voicelink import VoiceCall
from star.senses import capture


class NativeCall:
    def __init__(self, result, events, label):
        self.result, self.events, self.label = result, events, label

    def __call__(self, *args):
        self.events.append((self.label, threading.get_ident()))
        return self.result


def main():
    checks = 0
    for result, expected in ((0, ['init', 'body', 'uninit']), (1, ['init', 'body', 'uninit']),
                             (-2147417850, ['init', 'body']), (-2147467259, ['init'])):
        events = []
        native = SimpleNamespace(CoInitializeEx=NativeCall(result, events, 'init'),
                                 CoUninitialize=NativeCall(None, events, 'uninit'))
        with patch.object(capture.ctypes, 'WinDLL', return_value=native, create=True):
            try:
                with capture._audio_apartment():
                    events.append(('body', threading.get_ident()))
                    if result in (0, 1):
                        raise ValueError('device construction failed')
            except (ValueError, RuntimeError):
                pass
        assert [label for label, ident in events] == expected
        assert all(ident == threading.get_ident() for label, ident in events)
        checks += 1

    order = []
    @contextmanager
    def apartment():
        order.append('init')
        try:
            yield
        finally:
            order.append('uninit')

    @contextmanager
    def recorder(**kwargs):
        order.append('open')
        try:
            yield SimpleNamespace(record=lambda **kwargs: (_ for _ in ()).throw(ValueError('device lost')))
        finally:
            order.append('close')

    source = capture.LoopbackSource.__new__(capture.LoopbackSource)
    source._mic = SimpleNamespace(recorder=recorder)
    source.rate, source.block = 48000, 960
    source._stop, source._error, source._blocks = threading.Event(), None, queue.Queue()
    source._thread = threading.Thread(target=source._read)
    with patch.object(capture, '_audio_apartment', apartment):
        try:
            list(source.frames())
        except RuntimeError as error:
            assert isinstance(error.__cause__, ValueError)
        else:
            raise AssertionError('Device failure became a successful empty stream')
    source._thread.join(1)
    assert not source._thread.is_alive() and order == ['init', 'open', 'close', 'uninit']
    checks += 1

    stopped = []
    session = SimpleNamespace(start=lambda: None, stop=lambda: stopped.append(True))
    def failed_frames():
        raise RuntimeError('private device details')
        yield b''
    call = VoiceCall(session, failed_frames()).start()
    call._thread.join(1)
    assert not call.alive() and call.error_type == 'RuntimeError' and stopped
    checks += 1
    print(f'Audio capture apartment: {checks} ownership, cleanup and failure-visibility checks passed')


if __name__ == '__main__':
    main()
