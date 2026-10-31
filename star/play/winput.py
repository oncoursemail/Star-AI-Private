"""The real Windows InputSink: SendInput with hardware scan codes (games that read raw/DirectInput see them too).

Ordinary input first checks that the game window is in front (`window_guard`); a refused event raises and is
counted. Cleanup-only UP methods let trusted callers release their own held inputs after focus changes.
Ordinary input only: no driver, no
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


class InputDeliveryError(OSError):
    """Windows did not confirm input delivery. Failed actions are never replayed automatically."""

    def __init__(self, message: str, *, accepted: int | None = None):
        super().__init__(message)
        self.accepted = accepted  # None means unknown; zero means the owned press was not inserted.


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
    user32 = ctypes.windll.user32  # pyright: ignore[reportAttributeAccessIssue]
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
        self.accepted_events = 0
        self.failed_events = 0
        self.confirmed_moves = 0
        self._user32 = ctypes.windll.user32  # pyright: ignore[reportAttributeAccessIssue]

    def _send(self, inp: INPUT, *, release: bool = False) -> None:
        if not release and not self.guard():
            self.dropped += 1
            raise InputDeliveryError("foreground guard refused input", accepted=0)
        try:
            accepted = self._user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        except OSError:
            self.dropped += 1
            self.failed_events += 1
            raise InputDeliveryError("Windows input delivery was not confirmed") from None
        if type(accepted) is not int or accepted != 1:
            self.dropped += 1
            self.failed_events += 1
            raise InputDeliveryError("Windows did not accept the requested input event", accepted=0 if type(accepted) is int and accepted == 0 else None)
        self.accepted_events += 1

    def move_to(self, x: int, y: int) -> None:
        if self.guard():
            if not self._user32.SetCursorPos(int(x), int(y)):
                self.dropped += 1
                self.failed_events += 1
                raise InputDeliveryError("Windows did not confirm cursor placement", accepted=0)
            self.confirmed_moves += 1
        else:
            self.dropped += 1
            raise InputDeliveryError("foreground guard refused cursor placement", accepted=0)

    def move_rel(self, dx: int, dy: int) -> None:
        self._send(INPUT(INPUT_MOUSE, _U(mi=MOUSEINPUT(int(dx), int(dy), 0, MOUSEEVENTF_MOVE, 0, None))))

    def button(self, name: str, down: bool) -> None:
        flag = _BUTTON_FLAGS[name][0 if down else 1]
        self._send(INPUT(INPUT_MOUSE, _U(mi=MOUSEINPUT(0, 0, 0, flag, 0, None))))

    def release_button(self, name: str) -> None:
        """Cleanup of a button owned by the caller; never presses or moves across a changed foreground."""
        self._send(INPUT(INPUT_MOUSE, _U(mi=MOUSEINPUT(0, 0, 0, _BUTTON_FLAGS[name][1], 0, None))), release=True)

    def key(self, name: str, down: bool) -> None:
        vk = vk_of(name)
        scan = self._user32.MapVirtualKeyW(vk, 0)
        flags = KEYEVENTF_SCANCODE | (0 if down else KEYEVENTF_KEYUP) | (KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0)
        self._send(INPUT(INPUT_KEYBOARD, _U(ki=KEYBDINPUT(0, scan, flags, 0, None))))

    def release_key(self, name: str) -> None:
        scan = self._user32.MapVirtualKeyW(vk_of(name), 0)
        flags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP | (KEYEVENTF_EXTENDEDKEY if vk_of(name) in _EXTENDED else 0)
        self._send(INPUT(INPUT_KEYBOARD, _U(ki=KEYBDINPUT(0, scan, flags, 0, None))), release=True)
