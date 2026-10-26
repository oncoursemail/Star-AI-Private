"""Recording play for behaviour cloning: game-window frames + game keys/mouse, in compact per-session shards.

Who plays:
  * the owner (or a friend): `RawInputSource` reads the real keyboard and mouse through Windows Raw Input on a hidden
    message-only window (no visible window, no hook DLL); `Recorder.run()` grabs frames itself at `hz`;
  * STAR herself: `SinkTap` wraps her InputSink (it records exactly what her actuator sends) and `TeeSource` hands
    every frame the fast loop grabs to the recorder, so recording costs no second screen grab.
Consent and visibility (binding): a Recorder refuses to start without a non-empty `consent` note (who agreed); it
prints a "[STAR rec]" line when it starts, every few minutes while it runs, and when it stops; it records only the
game window's region and only while that window is in front (`guard`); only the game's own keys are labelled, and
the chat box (opened with "/", Enter or T) pauses recording until it closes, so typed text is never stored.

On disk (default <STAR home>/play/recordings/<game>/<session>/):
  session.json        spec, who, consent, window, hz, steps, shards, markers (game moments at their step), stats
  shard_00000.npz     frames (N,H,W,3) uint8 (resized), keys (N,K) u1, buttons (N,B) u1, mouse (N,2) u1 bins,
                      delta (N,2) f4 raw pixels, t (N,) f8, gap (N,) u1 (1 = the step after a pause or a drop)
At 128x72 and 20 Hz one hour is 72,000 frames (2.0 GB raw before compression; see the notes for measured sizes).
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from .actions import GameSpec, InputState

SHARD_STEPS = 2000                                   # 100 s at 20 Hz per shard


def data_root() -> Path:
    override = os.environ.get("STAR_PLAY_DIR")
    if override:
        return Path(override)
    from ...home.control import home_dir
    return home_dir() / "play"


def shrink(image, size: tuple[int, int]):
    """Area-average down to (width, height) with numpy only: block means by the integer factor, then nearest pick
    for the remainder. Plenty for 1280x720 -> 128x72 (factor 10 exactly)."""
    import numpy as np
    w, h = size
    src_h, src_w = image.shape[:2]
    fy, fx = max(1, src_h // h), max(1, src_w // w)
    if fy > 1 or fx > 1:
        hh, ww = (src_h // fy) * fy, (src_w // fx) * fx
        image = image[:hh, :ww, :3].reshape(hh // fy, fy, ww // fx, fx, 3).mean(axis=(1, 3))
    rows = (np.arange(h) * image.shape[0] / h).astype(np.intp)
    cols = (np.arange(w) * image.shape[1] / w).astype(np.intp)
    return np.ascontiguousarray(image[rows][:, cols, :3]).astype(np.uint8)


def _log(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


class SinkTap:
    """An InputSink that forwards to the real one and labels what it sent (STAR's own play)."""

    def __init__(self, inner, state: InputState) -> None:
        self.inner, self.state = inner, state

    def move_to(self, x: int, y: int) -> None:
        self.inner.move_to(x, y)
        self.state.move_to(x, y)

    def move_rel(self, dx: int, dy: int) -> None:
        self.inner.move_rel(dx, dy)
        self.state.move(dx, dy)

    def button(self, name: str, down: bool) -> None:
        self.inner.button(name, down)
        self.state.button(name, down)

    def key(self, name: str, down: bool) -> None:
        self.inner.key(name, down)
        self.state.key(name, down)


class TeeSource:
    """A FrameSource that hands each grabbed frame to the recorder too (one grab serves play and recording)."""

    def __init__(self, inner, recorder: Recorder) -> None:
        self.inner, self.recorder, self.name = inner, recorder, f"tee:{getattr(inner, 'name', '?')}"

    def grab(self):
        frame = self.inner.grab()
        if frame is not None:
            self.recorder.step(frame.image, frame.t)
        return frame

    def close(self) -> None:
        self.inner.close()


class Recorder:
    def __init__(self, spec: GameSpec, *, consent: str, who: str, state: InputState | None = None,
                 root: Path | None = None, guard: Callable[[], bool] | None = None, source=None,
                 notify: Callable[[str], None] = _log, remind_s: float = 300.0, shard_steps: int = SHARD_STEPS,
                 clock: Callable[[], float] = time.perf_counter, session_id: str = "") -> None:
        if not consent.strip():
            raise PermissionError("recording needs a consent note (who agreed to be recorded)")
        self.spec, self.consent, self.who = spec, consent.strip(), who
        self.state = state or InputState(spec)
        self.guard, self.source, self.notify, self.remind_s = guard, source, notify, remind_s
        self.shard_steps, self.clock = shard_steps, clock
        self.session_id = session_id or time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.dir = Path(root or data_root() / "recordings") / spec.game / self.session_id
        self.steps = 0
        self.paused = 0
        self.markers: list[dict] = []
        self.shards: list[str] = []
        self._buf: dict[str, list] = self._empty()
        self._gap = True
        self._pending = None
        self.write_error = ""
        self._writer: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._last_note = -1e9
        self._abs_dx: list[float] = []
        self.started = False

    @staticmethod
    def _empty() -> dict[str, list]:
        return {k: [] for k in ("frames", "keys", "buttons", "mouse", "delta", "t", "gap")}

    # ---- lifecycle -------------------------------------------------------------------------------------------
    def start(self) -> Recorder:
        self.dir.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._write_loop, name="play-rec-writer", daemon=True)
        self._thread.start()
        self.started = True
        self._save_meta()
        self._announce("recording")
        return self

    def _announce(self, what: str) -> None:
        w, h = self.spec.frame_size
        self.notify(f"[STAR rec] {what} {self.spec.game}: game window '{self.spec.window or 'region'}' only, "
                    f"{w}x{h} frames + {len(self.spec.keys)} game keys at {self.spec.hz:g} Hz, who={self.who}, "
                    f"{self.steps} steps -> {self.dir} (stop: close the session or Ctrl-C)")
        self._last_note = self.clock()

    def stop(self) -> Path:
        self._stop.set()
        with self._lock:
            self._flush()
        self._writer.put(None)
        if self._thread is not None:
            self._thread.join(30)
        self._save_meta()
        self._announce("stopped")
        if self.write_error:
            raise OSError(f"recording shard not written: {self.write_error}")
        return self.dir

    # ---- data ------------------------------------------------------------------------------------------------
    def step(self, image, t: float | None = None) -> bool:
        """One recording step. The input made since the previous step is the answer to the PREVIOUS frame, so
        that frame is stored with it, and this frame waits for the next step's input. False when paused (window
        not in front, chat open): the waiting frame is dropped and the next stored step is marked as a gap."""
        if not self.started or self._stop.is_set():
            return False
        t = self.clock() if t is None else t
        if t - self._last_note >= self.remind_s:
            self._announce("still recording")
        label = self.state.take()
        if label is None or (self.guard is not None and not self.guard()):
            self.paused += 1
            self._gap = True
            self._pending = None
            return False
        previous, self._pending = self._pending, (shrink(image, self.spec.frame_size), t)
        if previous is None:
            return True
        small, t = previous
        with self._lock:
            b = self._buf
            b["frames"].append(small)
            b["keys"].append(label.keys)
            b["buttons"].append(label.buttons)
            b["mouse"].append((label.mx, label.my))
            b["delta"].append((label.dx, label.dy))
            b["t"].append(t)
            b["gap"].append(1 if self._gap else 0)
            self._gap = False
            self._abs_dx.append(abs(label.dx))
            self.steps += 1
            if len(b["t"]) >= self.shard_steps:
                self._flush()
        return True

    def cut(self) -> None:
        """A jump in the picture (respawn, teleport, loading screen): drop the waiting frame, start a new run."""
        self._pending = None
        self._gap = True
        self.state.take()

    def mark(self, kind: str, now: float | None = None) -> None:
        """A game moment (FastLoop.on_moment listener signature): success/failure markers cut episodes for
        filtered behaviour cloning and evaluation."""
        with self._lock:
            self.markers.append({"step": self.steps, "kind": kind, "t": now})

    def _flush(self) -> None:
        if not self._buf["t"]:
            return
        name = f"shard_{len(self.shards):05d}.npz"
        self.shards.append(name)
        self._writer.put((self.dir / name, self._buf))
        self._buf = self._empty()

    def _write_loop(self) -> None:
        while True:
            item = self._writer.get()
            if item is None:
                return
            path, b = item
            tmp = path.with_suffix(".tmp.npz")
            try:
                self._save_shard(tmp, b)
                os.replace(tmp, path)
            except Exception as exc:                       # surfaced by stop(): a lost shard must not be silent
                self.write_error = f"{path.name}: {type(exc).__name__}: {exc}"

    def _save_shard(self, path: Path, b: dict) -> None:
        import numpy as np
        n, u1 = len(b["t"]), np.uint8
        np.savez_compressed(path, frames=np.stack(b["frames"]),
                            keys=np.asarray(b["keys"], dtype=u1).reshape(n, len(self.spec.keys)),
                            buttons=np.asarray(b["buttons"], dtype=u1).reshape(n, len(self.spec.buttons)),
                            mouse=np.asarray(b["mouse"], dtype=u1), delta=np.asarray(b["delta"], dtype=np.float32),
                            t=np.asarray(b["t"], dtype=np.float64), gap=np.asarray(b["gap"], dtype=u1))

    def _save_meta(self) -> None:
        ordered = sorted(self._abs_dx)
        p99 = ordered[int(0.99 * (len(ordered) - 1))] if ordered else 0.0
        meta = {"session": self.session_id, "spec": self.spec.to_dict(), "who": self.who, "consent": self.consent,
                "steps": self.steps, "paused_steps": self.paused, "shards": list(self.shards),
                "markers": list(self.markers), "stats": {"abs_dx_p99": p99},
                "written": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        tmp = self.dir / "session.json.tmp"
        tmp.write_text(json.dumps(meta, indent=1), encoding="utf-8")
        os.replace(tmp, self.dir / "session.json")

    # ---- owner mode: grab frames ourselves -------------------------------------------------------------------
    def run(self, seconds: float | None = None, sleep: Callable[[float], None] = time.sleep) -> None:
        if self.source is None:
            raise RuntimeError("run() needs a frame source; STAR's own play feeds frames through TeeSource")
        period, end = 1.0 / self.spec.hz, None if seconds is None else self.clock() + seconds
        next_at = self.clock()
        while not self._stop.is_set() and (end is None or self.clock() < end):
            frame = self.source.grab()
            if frame is not None:
                self.step(frame.image, frame.t)
            next_at += period
            wait = next_at - self.clock()
            if wait > 0:
                sleep(wait)
            else:
                next_at = self.clock()


def load_session(path: Path) -> dict:
    """session.json plus all shards concatenated (numpy arrays)."""
    import numpy as np
    path = Path(path)
    meta = json.loads((path / "session.json").read_text(encoding="utf-8"))
    parts: dict[str, list] = {}
    for name in meta["shards"]:
        with np.load(path / name) as shard:
            for key in shard.files:
                parts.setdefault(key, []).append(shard[key])
    data = {k: np.concatenate(v) for k, v in parts.items()}
    return {"meta": meta, "dir": str(path), **data}


def sessions(root: Path, game: str) -> list[Path]:
    base = Path(root) / game
    return sorted(p.parent for p in base.glob("*/session.json")) if base.exists() else []


# ---- owner's real keyboard and mouse ---------------------------------------------------------------------------
_VK_NAMES = {0x20: "space", 0x0D: "enter", 0x1B: "escape", 0x09: "tab", 0x10: "shift", 0xA0: "shift", 0xA1: "shift",
             0x11: "ctrl", 0xA2: "ctrl", 0xA3: "ctrl", 0x12: "alt", 0x08: "backspace", 0x25: "left", 0x26: "up",
             0x27: "right", 0x28: "down", 0xBF: "slash"}


def vk_name(vk: int) -> str:
    if vk in _VK_NAMES:
        return _VK_NAMES[vk]
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk).lower()
    return f"vk{vk}"


class RawInputSource:  # pragma: no cover - needs a Windows desktop and real devices
    """Windows Raw Input on a message-only window (HWND_MESSAGE: never shown) with RIDEV_INPUTSINK, so input is
    seen while the game has focus. Feeds an InputState: relative mouse deltas (works with games that lock the
    cursor) and key/button transitions. Only the InputState decides what is kept (game keys only)."""

    def __init__(self, state: InputState) -> None:
        self.state = state
        self._thread: threading.Thread | None = None
        self._tid = 0
        self.error = ""
        self.ready = threading.Event()

    def start(self) -> RawInputSource:
        self._thread = threading.Thread(target=self._run, name="play-rawinput", daemon=True)
        self._thread.start()
        self.ready.wait(5)
        if self.error:
            raise OSError(self.error)
        return self

    def stop(self) -> None:
        import ctypes
        if self._tid:
            ctypes.windll.user32.PostThreadMessageW(self._tid, 0x0012, 0, 0)     # WM_QUIT
        if self._thread is not None:
            self._thread.join(3)

    def _run(self) -> None:
        import ctypes
        import ctypes.wintypes as wt
        user32, kernel32 = ctypes.WinDLL("user32", use_last_error=True), ctypes.windll.kernel32
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                        ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                        ("lpszClassName", wt.LPCWSTR)]

        class RAWINPUTDEVICE(ctypes.Structure):
            _fields_ = [("usUsagePage", wt.USHORT), ("usUsage", wt.USHORT), ("dwFlags", wt.DWORD),
                        ("hwndTarget", wt.HWND)]

        class RAWINPUTHEADER(ctypes.Structure):
            _fields_ = [("dwType", wt.DWORD), ("dwSize", wt.DWORD), ("hDevice", wt.HANDLE), ("wParam", wt.WPARAM)]

        class RAWMOUSE(ctypes.Structure):
            _fields_ = [("usFlags", wt.USHORT), ("usButtonFlags", wt.USHORT), ("usButtonData", wt.USHORT),
                        ("ulRawButtons", wt.ULONG), ("lLastX", wt.LONG), ("lLastY", wt.LONG),
                        ("ulExtraInformation", wt.ULONG)]

        class RAWKEYBOARD(ctypes.Structure):
            _fields_ = [("MakeCode", wt.USHORT), ("Flags", wt.USHORT), ("Reserved", wt.USHORT),
                        ("VKey", wt.USHORT), ("Message", wt.UINT), ("ExtraInformation", wt.ULONG)]

        class _DATA(ctypes.Union):
            _fields_ = [("mouse", RAWMOUSE), ("keyboard", RAWKEYBOARD)]

        class RAWINPUT(ctypes.Structure):
            _fields_ = [("header", RAWINPUTHEADER), ("data", _DATA)]

        user32.DefWindowProcW.restype = LRESULT
        user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        user32.CreateWindowExW.restype = wt.HWND
        user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
        user32.GetRawInputData.argtypes = [wt.HANDLE, wt.UINT, wt.LPVOID, ctypes.POINTER(wt.UINT), wt.UINT]
        state, buttons = self.state, {0x0001: ("left", True), 0x0002: ("left", False), 0x0004: ("right", True),
                                      0x0008: ("right", False), 0x0010: ("middle", True), 0x0020: ("middle", False)}

        def proc(hwnd, msg, wparam, lparam):
            if msg == 0x00FF:                                       # WM_INPUT
                raw, size = RAWINPUT(), wt.UINT(ctypes.sizeof(RAWINPUT))
                if user32.GetRawInputData(lparam, 0x10000003, ctypes.byref(raw), ctypes.byref(size),
                                          ctypes.sizeof(RAWINPUTHEADER)) not in (0, 0xFFFFFFFF):
                    if raw.header.dwType == 0:                      # mouse
                        m = raw.data.mouse
                        if not m.usFlags & 0x01:                    # relative (absolute = tablets/remote desktop)
                            state.move(m.lLastX, m.lLastY)
                        for flag, (name, down) in buttons.items():
                            if m.usButtonFlags & flag:
                                state.button(name, down)
                    elif raw.header.dwType == 1:                    # keyboard
                        k = raw.data.keyboard
                        state.key(vk_name(k.VKey), not k.Flags & 0x01)
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._proc = WNDPROC(proc)                                  # keep a reference for the window's lifetime
        hinst = kernel32.GetModuleHandleW(None)
        cls = WNDCLASSW(lpfnWndProc=self._proc, hInstance=hinst, lpszClassName="STARPlayRawInput")
        user32.RegisterClassW(ctypes.byref(cls))
        hwnd = user32.CreateWindowExW(0, "STARPlayRawInput", "", 0, 0, 0, 0, 0, wt.HWND(-3), None, hinst, None)
        devices = (RAWINPUTDEVICE * 2)(RAWINPUTDEVICE(0x01, 0x02, 0x00000100, hwnd),
                                       RAWINPUTDEVICE(0x01, 0x06, 0x00000100, hwnd))
        if not hwnd or not user32.RegisterRawInputDevices(devices, 2, ctypes.sizeof(RAWINPUTDEVICE)):
            self.error = f"raw input registration failed (error {ctypes.get_last_error()})"
            self.ready.set()
            return
        self._tid = kernel32.GetCurrentThreadId()
        self.ready.set()
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        devices[0].dwFlags = devices[1].dwFlags = 0x00000001             # RIDEV_REMOVE
        devices[0].hwndTarget = devices[1].hwndTarget = None
        user32.RegisterRawInputDevices(devices, 2, ctypes.sizeof(RAWINPUTDEVICE))
        user32.DestroyWindow(hwnd)
