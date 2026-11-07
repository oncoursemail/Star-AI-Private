"""Windows-only, allowlisted one-action game input worker.

A *separate* short-lived process owns each synthetic key-down and its bounded
key-up, so a parent AI/OBS/TTS stall cannot prolong a key hold. Nothing is
injected on import, and this module never finds or focuses a window itself.
This is a conservative pilot backend, not an anti-cheat bypass or hardware
watchdog: a worker crash, OS suspend, UIPI denial or Windows API failure
still requires a separately supervised owner kill switch.

No game or broadcast is launched. Do not use in competitive titles whose
terms prohibit automation.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
import sys
from threading import Event, Thread
from typing import Any
import time

# Scan codes are from the Windows Set 1 keyboard table. No system shortcuts,
# shell keys, text entry, modifiers, or mouse input are available.
@dataclass(frozen=True)
class Key:
    scan: int
    vk: int
    extended: bool = False


KEYS = {
    "move_up": Key(0x11, ord("W")),
    "move_left": Key(0x1E, ord("A")),
    "move_down": Key(0x1F, ord("S")),
    "move_right": Key(0x20, ord("D")),
    "jump": Key(0x39, 0x20),
    "arrow_up": Key(0x48, 0x26, True),
    "arrow_left": Key(0x4B, 0x25, True),
    "arrow_down": Key(0x50, 0x28, True),
    "arrow_right": Key(0x4D, 0x27, True),
}

_UINTPTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else wintypes.DWORD
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_EXTENDEDKEY = 0x0001
INPUT_KEYBOARD = 1


class _Keyboard(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", _UINTPTR),
    ]


class _Mouse(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG), ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", _UINTPTR),
    ]


class _Hardware(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class _Union(ctypes.Union):
    _fields_ = [("ki", _Keyboard), ("mi", _Mouse), ("hi", _Hardware)]


class _Input(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("data", _Union)]


class WindowsKeyboard:
    """Win32 session-local adapter; only works in an interactive desktop."""

    # ctypes.windll is OS-specific and dynamically typed. Declaring the
    # runtime handle here also keeps Linux CI type checking meaningful.
    _api: Any

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Windows interactive session required")
        api = ctypes.windll.user32
        api.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_Input), ctypes.c_int]
        api.SendInput.restype = wintypes.UINT
        api.GetAsyncKeyState.argtypes = [ctypes.c_int]
        api.GetAsyncKeyState.restype = ctypes.c_short
        api.GetForegroundWindow.restype = wintypes.HWND
        api.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
        ]
        api.GetWindowThreadProcessId.restype = wintypes.DWORD
        api.IsWindow.argtypes = [wintypes.HWND]
        api.IsWindow.restype = wintypes.BOOL
        api.IsWindowVisible.argtypes = [wintypes.HWND]
        api.IsWindowVisible.restype = wintypes.BOOL
        self._api = api

    def foreground_is(self, hwnd: int, pid: int) -> bool:
        if not self._api.IsWindow(hwnd) or not self._api.IsWindowVisible(hwnd):
            return False
        if self._api.GetForegroundWindow() != hwnd:
            return False
        actual = wintypes.DWORD()
        return bool(
            self._api.GetWindowThreadProcessId(hwnd, ctypes.byref(actual))
            and actual.value == pid
        )

    def up(self, key: Key) -> bool:
        return self._api.GetAsyncKeyState(key.vk) >= 0

    def send(self, key: Key, *, release: bool) -> bool:
        flags = KEYEVENTF_SCANCODE
        if key.extended:
            flags |= KEYEVENTF_EXTENDEDKEY
        if release:
            flags |= KEYEVENTF_KEYUP
        event = _Input(type=INPUT_KEYBOARD)
        event.data.ki = _Keyboard(0, key.scan, flags, 0, 0)
        return self._api.SendInput(1, ctypes.byref(event), ctypes.sizeof(_Input)) == 1


def bounded_press(
    device: WindowsKeyboard, *, action: str, hwnd: int, pid: int,
    hold_ms: int, stop: Event, clock=time.monotonic,
) -> bool:
    """Enforce key-up from the worker even when its parent stops communicating.

    This is a *synthetic* key event with independent OS-state polling, not
    proof the target game consumed the input or that a physical key is up.
    """
    if (type(action) is not str or action not in KEYS or type(hwnd) is not int
            or hwnd <= 0 or type(pid) is not int or pid <= 0
            or type(hold_ms) is not int or not 1 <= hold_ms <= 180):
        return False
    key = KEYS[action]
    if stop.is_set() or not device.foreground_is(hwnd, pid) or not device.up(key):
        return False
    # One injection edge. Recheck cancellation and window before injecting.
    if stop.is_set() or not device.foreground_is(hwnd, pid):
        return False
    pressed = False
    finished = False
    try:
        pressed = device.send(key, release=False)
        if not pressed:
            return False
        deadline = clock() + hold_ms / 1000.0
        while True:
            remaining = deadline - clock()
            if remaining <= 0:
                finished = True
                break
            if stop.is_set() or not device.foreground_is(hwnd, pid):
                break
            stop.wait(min(0.01, remaining))
    finally:
        # Never condition release on current game focus or cancellation.
        if pressed:
            released = device.send(key, release=True)
            if not released:
                finished = False
    return finished and not stop.is_set() and device.foreground_is(hwnd, pid) and device.up(key)


def _watch_stdin(stop: Event) -> None:
    # EOF when the parent exits is an emergency request for immediate key-up.
    try:
        for _line in sys.stdin:
            stop.set()
            return
    finally:
        stop.set()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="internal one-key guardian process")
    p.add_argument("--worker", action="store_true")
    p.add_argument("--action", choices=sorted(KEYS))
    p.add_argument("--hwnd", type=int)
    p.add_argument("--pid", type=int)
    p.add_argument("--hold-ms", type=int)
    args = p.parse_args(argv)
    if (not args.worker or args.action is None or args.hwnd is None
            or args.pid is None or args.hold_ms is None
            or os.name != "nt"):
        return 2
    stop = Event()
    Thread(target=_watch_stdin, args=(stop,), daemon=True).start()
    try:
        successful = bounded_press(
            WindowsKeyboard(), action=args.action, hwnd=args.hwnd,
            pid=args.pid, hold_ms=args.hold_ms, stop=stop,
        )
    except Exception:
        successful = False
    # stdout contains only a one-bit release result; no game/player data.
    sys.stdout.write("RELEASED" if successful else "REJECTED")
    sys.stdout.flush()
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
