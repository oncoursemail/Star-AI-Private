"""Windows calls STAR needs for using any app: which window is in front, find/focus a window, and a SendInput sink
that can also scroll and type any character. ctypes only. Everything here needs a real desktop, so tests fake the
`Windows` class and the sink (the pure parts live in the other modules)."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass
import os

from ..play.winput import INPUT, INPUT_KEYBOARD, INPUT_MOUSE, KEYBDINPUT, MOUSEINPUT, _BUTTON_FLAGS, _U
from ..play.winput import KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE
from ..play.winput import InputDeliveryError
from ..play.winput import vk_of as _basic_vk

KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_MOVE, MOUSEEVENTF_WHEEL = 0x0001, 0x0800
MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_VIRTUALDESK = 0x8000, 0x4000
WHEEL_DELTA = 120
_EXTRA_VK = {"delete": 0x2E, "del": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23, "pageup": 0x21, "pgup": 0x21,
             "pagedown": 0x22, "pgdn": 0x22, "win": 0x5B, "capslock": 0x14, "menu": 0x5D, "return": 0x0D,
             "minus": 0xBD, "plus": 0xBB, "equals": 0xBB, "comma": 0xBC, "period": 0xBE, "-": 0xBD, "=": 0xBB,
             ",": 0xBC, ".": 0xBE, **{f"f{n}": 0x6F + n for n in range(1, 13)}}
_EXTENDED = {0x25, 0x26, 0x27, 0x28, 0x2E, 0x2D, 0x24, 0x23, 0x21, 0x22, 0x5B, 0x5D}


def vk_of(name: str) -> int:
    name = name.lower()
    return _EXTRA_VK[name] if name in _EXTRA_VK else _basic_vk(name)


def ensure_dpi_aware() -> None:  # pragma: no cover - Windows only
    """Without this, UI Automation rectangles, screenshots and the cursor can use different scales."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (OSError, AttributeError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (OSError, AttributeError):
            pass


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    pid: int
    exe: str                      # lower-case file name, e.g. mspaint.exe
    rect: tuple[int, int, int, int] = (0, 0, 0, 0)


class Windows:  # pragma: no cover - needs a Windows desktop
    def __init__(self) -> None:
        self.u = ctypes.WinDLL("user32", use_last_error=True)
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k.OpenProcess.restype = wt.HANDLE
        self.k.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
        self.k.CloseHandle.argtypes = [wt.HANDLE]
        self.u.GetForegroundWindow.restype = ctypes.c_void_p
        self.u.GetWindowTextW.argtypes = [ctypes.c_void_p, wt.LPWSTR, ctypes.c_int]
        self.u.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
        self.u.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.DWORD)]
        self.u.IsWindowVisible.argtypes = [ctypes.c_void_p]
        self.u.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.RECT)]
        self.u.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        self.u.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.u.IsIconic.argtypes = [ctypes.c_void_p]
        self.u.BringWindowToTop.argtypes = [ctypes.c_void_p]
        self.u.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
        self.k.GetCurrentThreadId.restype = wt.DWORD
        self._exe_cache: dict[int, str] = {}

    def screen_size(self) -> tuple[int, int]:
        return self.u.GetSystemMetrics(0), self.u.GetSystemMetrics(1)

    def cursor(self) -> tuple[int, int]:
        pt = wt.POINT()
        self.u.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def _exe(self, pid: int) -> str:
        if pid not in self._exe_cache:
            handle = self.k.OpenProcess(0x1000, False, pid)       # PROCESS_QUERY_LIMITED_INFORMATION
            name = ""
            if handle:
                buf, size = ctypes.create_unicode_buffer(1024), wt.DWORD(1024)
                if self.k.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    name = os.path.basename(buf.value).lower()
                self.k.CloseHandle(handle)
            self._exe_cache[pid] = name
        return self._exe_cache[pid]

    def info(self, hwnd: int) -> WindowInfo:
        buf, pid, rect = ctypes.create_unicode_buffer(512), wt.DWORD(0), wt.RECT()
        self.u.GetWindowTextW(hwnd, buf, 512)
        self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        self.u.GetWindowRect(hwnd, ctypes.byref(rect))
        return WindowInfo(int(hwnd), buf.value, pid.value, self._exe(pid.value),
                          (rect.left, rect.top, rect.right, rect.bottom))

    def foreground(self) -> WindowInfo | None:
        hwnd = self.u.GetForegroundWindow()
        return self.info(hwnd) if hwnd else None

    def windows(self) -> list[WindowInfo]:
        found: list[int] = []
        proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def visit(hwnd, _):
            if self.u.IsWindowVisible(hwnd) and self.u.GetWindowTextLengthW(hwnd) > 0:
                found.append(hwnd)
            return True

        self.u.EnumWindows(proc(visit), 0)
        return [self.info(h) for h in found]

    def focus(self, hwnd: int) -> bool:
        """Bring a window to the front and say whether it is there. Windows refuses SetForegroundWindow from a
        background program, so: an Alt tap, then the input queues of this thread, the front window and the target are
        joined for the call (the standard workaround; a plain call failed behind a system dialog, measured)."""
        if self.u.IsIconic(hwnd):
            self.u.ShowWindow(hwnd, 9)                            # SW_RESTORE
        self.u.keybd_event(0x12, 0, 0, 0)
        self.u.keybd_event(0x12, 0, KEYEVENTF_KEYUP, 0)
        front = self.u.GetForegroundWindow()
        mine = self.k.GetCurrentThreadId()
        theirs = self.u.GetWindowThreadProcessId(front, None) if front else 0
        target = self.u.GetWindowThreadProcessId(hwnd, None)
        joined = [t for t in {theirs, target} if t and t != mine and self.u.AttachThreadInput(mine, t, True)]
        try:
            self.u.BringWindowToTop(hwnd)
            self.u.SetForegroundWindow(hwnd)
        finally:
            for t in joined:
                self.u.AttachThreadInput(mine, t, False)
        return self.u.GetForegroundWindow() == hwnd


class DesktopSink:  # pragma: no cover - sends real input on a Windows desktop
    """Guarded desktop input plus cleanup-only UP methods for presses owned by the trusted caller.

    Ordinary events ask guard() first; refusal raises and counts the dropped event.
    """

    def __init__(self, guard=None) -> None:
        self.guard = guard or (lambda: True)
        self.dropped = 0
        self.accepted_events = 0
        self.failed_events = 0
        self.u = ctypes.WinDLL("user32")

    def _ok(self) -> bool:
        if self.guard():
            return True
        self.dropped += 1
        return False

    def _send(self, inp: INPUT, *, release: bool = False) -> None:
        if not release and not self._ok():
            raise InputDeliveryError("foreground guard refused input", accepted=0)
        try:
            accepted = self.u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        except OSError:
            self.dropped += 1
            self.failed_events += 1
            raise InputDeliveryError("Windows input delivery was not confirmed") from None
        if type(accepted) is not int or accepted != 1:
            self.dropped += 1
            self.failed_events += 1
            raise InputDeliveryError("Windows did not accept the requested input event", accepted=0 if type(accepted) is int and accepted == 0 else None)
        self.accepted_events += 1

    def position(self) -> tuple[int, int]:
        pt = wt.POINT()
        self.u.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def move_to(self, x: int, y: int) -> None:
        """An absolute move as real mouse input (SendInput). SetCursorPos only teleports the cursor: XAML apps such
        as Win11 Paint do not see it as a pointer move, so a drag drew a dot instead of a line (measured)."""
        vx, vy = self.u.GetSystemMetrics(76), self.u.GetSystemMetrics(77)                 # virtual desktop origin
        vw, vh = self.u.GetSystemMetrics(78), self.u.GetSystemMetrics(79)
        nx = int((int(x) - vx) * 65535 / max(1, vw - 1) + 0.5)
        ny = int((int(y) - vy) * 65535 / max(1, vh - 1) + 0.5)
        self._send(INPUT(INPUT_MOUSE, _U(mi=MOUSEINPUT(nx, ny, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE |
                                                       MOUSEEVENTF_VIRTUALDESK, 0, None))))

    def move_rel(self, dx: int, dy: int) -> None:
        self._send(INPUT(INPUT_MOUSE, _U(mi=MOUSEINPUT(int(dx), int(dy), 0, MOUSEEVENTF_MOVE, 0, None))))

    def button(self, name: str, down: bool) -> None:
        flag = _BUTTON_FLAGS[name][0 if down else 1]
        self._send(INPUT(INPUT_MOUSE, _U(mi=MOUSEINPUT(0, 0, 0, flag, 0, None))))

    def release_button(self, name: str) -> None:
        """Only caller-owned cleanup releases bypass a changed foreground; ordinary actions remain guarded."""
        self._send(INPUT(INPUT_MOUSE, _U(mi=MOUSEINPUT(0, 0, 0, _BUTTON_FLAGS[name][1], 0, None))), release=True)

    def wheel(self, notches: int) -> None:
        """Positive = away from the user (scroll up)."""
        data = (int(notches) * WHEEL_DELTA) & 0xFFFFFFFF
        self._send(INPUT(INPUT_MOUSE, _U(mi=MOUSEINPUT(0, 0, data, MOUSEEVENTF_WHEEL, 0, None))))

    def key(self, name: str, down: bool) -> None:
        vk = vk_of(name)
        scan = self.u.MapVirtualKeyW(vk, 0)
        flags = KEYEVENTF_SCANCODE | (0 if down else KEYEVENTF_KEYUP) | (KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0)
        self._send(INPUT(INPUT_KEYBOARD, _U(ki=KEYBDINPUT(0, scan, flags, 0, None))))

    def release_key(self, name: str) -> None:
        vk = vk_of(name)
        scan = self.u.MapVirtualKeyW(vk, 0)
        flags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP | (KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0)
        self._send(INPUT(INPUT_KEYBOARD, _U(ki=KEYBDINPUT(0, scan, flags, 0, None))), release=True)

    def type_char(self, ch: str) -> None:
        """Any Unicode character, the way an input method sends it (works in text boxes of every app)."""
        raw = ch.encode("utf-16-le")
        for i in range(0, len(raw), 2):
            unit = int.from_bytes(raw[i:i + 2], "little")
            pressed = True
            try:
                self._send(INPUT(INPUT_KEYBOARD, _U(ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE, 0, None))))
            except InputDeliveryError as error:
                pressed = error.accepted is None
                raise
            finally:
                if pressed:
                    self._send(INPUT(INPUT_KEYBOARD, _U(ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None))),
                               release=True)
