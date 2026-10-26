"""The real Windows InputSink: SendInput with hardware scan codes (games that read raw/DirectInput see them too).

Every call first checks that the game window is in front (`window_guard`), so nothing STAR plays ever lands in
another program; if it is not in front the event is dropped and counted. Ordinary input only: no driver, no
injection into the game process, nothing that hides from or works around anti-cheat.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from typing import Callable

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE = 0x0001
_BUTTON_FLAGS = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}
KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE, KEYEVENTF_EXTENDEDKEY = 0x0002, 0x0008, 0x0001
_VK = {"space": 0x20, "enter": 0x0D, "escape": 0x1B, "esc": 0x1B, "tab": 0x09, "shift": 0x10, "ctrl": 0x11,
       "alt": 0x12, "backspace": 0x08, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "slash": 0xBF,
       "/": 0xBF}
_EXTENDED = {0x25, 0x26, 0x27, 0x28}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_void_p)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _U)]


def vk_of(name: str) -> int:
    name = name.lower()
    if name in _VK:
        return _VK[name]
    if len(name) == 1 and (name.isalpha() or name.isdigit()):
        return ord(name.upper())
    raise ValueError(f"unknown key {name!r}")


def foreground_title() -> str:  # pragma: no cover - needs a Windows desktop
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def window_guard(title_part: str) -> Callable[[], bool]:
    part = title_part.lower()
    return lambda: part in foreground_title().lower()


class SendInputSink:  # pragma: no cover - sends real input on a Windows desktop
    def __init__(self, guard: Callable[[], bool]) -> None:
        self.guard = guard
        self.dropped = 0
        self._user32 = ctypes.windll.user32

    def _send(self, inp: INPUT) -> None:
        if not self.guard():
            self.dropped += 1
            return
        self._user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    def move_to(self, x: int, y: int) -> None:
        if self.guard():
            self._user32.SetCursorPos(int(x), int(y))
        else:
            self.dropped += 1

    def move_rel(self, dx: int, dy: int) -> None:
        self._send(INPUT(INPUT_MOUSE, _U(mi=MOUSEINPUT(int(dx), int(dy), 0, MOUSEEVENTF_MOVE, 0, None))))

    def button(self, name: str, down: bool) -> None:
        flag = _BUTTON_FLAGS[name][0 if down else 1]
        self._send(INPUT(INPUT_MOUSE, _U(mi=MOUSEINPUT(0, 0, 0, flag, 0, None))))

    def key(self, name: str, down: bool) -> None:
        vk = vk_of(name)
        scan = self._user32.MapVirtualKeyW(vk, 0)
        flags = KEYEVENTF_SCANCODE | (0 if down else KEYEVENTF_KEYUP) | (KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0)
        self._send(INPUT(INPUT_KEYBOARD, _U(ki=KEYBDINPUT(0, scan, flags, 0, None))))
