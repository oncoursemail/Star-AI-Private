"""The executor: runs STAR's actions on her own PC and logs every one.

On her PC STAR is an administrator and decides for herself (owner 2026-10-26): no permission prompts. What stays:
  * the owner's STOP file (control.py): while it exists every action is refused;
  * every action is logged before and after it runs (control.log_action);
  * her actions may not touch the STAR Home folder, so she cannot remove the stop or rewrite the log;
  * no remote-control commands (ssh, scp, RDP, PowerShell remoting, psexec, mapped shares): STAR Home stays on this
    PC and reaches the owner's machines only through STAR's HTTP APIs, which this package calls itself;
  * real-world actions (spending, public posts, new accounts, messaging people) are not tools here: `ask_owner`
    records the request in approvals.jsonl for the owner, and nothing waits on it.

`Executor(home, backend)` takes a backend so tests use a fake one; `dry_run=True` logs and runs nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import time

from . import control

MAX_OUTPUT = 6000
MAX_FILE_READ = 200_000
MAX_FILE_WRITE = 2_000_000
_REMOTE = re.compile(
    r"(?<![\w-])(?:ssh|scp|sftp|mstsc|psexec|psexec64|winrs|plink|pscp|Enter-PSSession|New-PSSession|"
    r"Invoke-Command\b[^\n]*-ComputerName|net\s+use|New-PSDrive\b[^\n]*\\\\)(?![\w-])",
    re.IGNORECASE)
_PACKAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_-]{1,99}$")
_KEY = re.compile(r"^(?:[a-z0-9]+(?:\+[a-z0-9]+){0,3}|/)$")
BUTTONS = ("left", "right", "middle")


class Refused(Exception):
    """The action was not run; the message says why (sent back to the model as the tool result)."""


@dataclass
class Result:
    ok: bool
    text: str
    path: str = ""


class RealBackend:  # pragma: no cover - acts on the real desktop; exercised on the PC with --dry-run first
    def run(self, argv: list[str], timeout: float) -> tuple[int, str]:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, creationflags=flags,
                              encoding="utf-8", errors="replace")
        return done.returncode, (done.stdout or "") + (done.stderr or "")

    def launch(self, target: str, args: list[str]) -> None:
        if args:
            subprocess.Popen([target, *args], close_fds=True)
        else:
            os.startfile(target)  # type: ignore[attr-defined]  # apps, documents, URLs, shell: links

    def screenshot(self, path: Path) -> None:
        from PIL import ImageGrab
        ImageGrab.grab(all_screens=True).save(path, "PNG")

    def click(self, x: int, y: int, button: str, clicks: int) -> None:
        import pyautogui
        pyautogui.click(x=x, y=y, button=button, clicks=clicks)

    def move(self, x: int, y: int) -> None:
        import pyautogui
        pyautogui.moveTo(x, y, duration=0.2)

    def type_text(self, text: str) -> None:
        import pyautogui
        pyautogui.write(text, interval=0.01)

    def key(self, keys: list[str]) -> None:
        import pyautogui
        pyautogui.hotkey(*keys)

    def hold(self, key: str, seconds: float) -> None:
        import pyautogui
        pyautogui.keyDown(key)
        try:
            time.sleep(seconds)
        finally:
            pyautogui.keyUp(key)

    def foreground_title(self) -> str:
        from ..play.winput import foreground_title
        return foreground_title()

    def focus_window(self, title: str) -> bool:
        """Bring the first visible window whose title contains `title` to the front (restores it if minimised)."""
        import ctypes
        user32 = ctypes.windll.user32
        found: list[int] = []
        part = title.lower()
        proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def visit(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, buf, 512)
                if part in buf.value.lower():
                    found.append(hwnd)
                    return False
            return True

        user32.EnumWindows(proc(visit), 0)
        if not found:
            return False
        if user32.IsIconic(found[0]):
            user32.ShowWindow(found[0], 9)             # SW_RESTORE
        user32.keybd_event(0x12, 0, 0, 0)               # a tap of Alt lets this process take the foreground
        user32.keybd_event(0x12, 0, 2, 0)
        user32.SetForegroundWindow(found[0])
        time.sleep(0.15)
        return part in self.foreground_title().lower()


class Executor:
    def __init__(self, home: Path | None = None, backend=None, *, dry_run: bool = False):
        self.home = Path(home or control.home_dir())
        self.backend = backend if backend is not None else RealBackend()
        self.dry_run = dry_run
        self.workspace = self.home.parent / "workspace"   # her own projects; any other path is allowed too

    # ---- guards -------------------------------------------------------------------------------------------
    def _protected(self, text: str) -> bool:
        home = str(self.home.resolve()).lower().rstrip("\\/")
        lowered = text.lower().replace("/", "\\")
        return home in lowered or "star\\home\\stop" in lowered or "star\\home\\actions" in lowered

    def _check_path(self, raw: str) -> Path:
        if not isinstance(raw, str) or not raw.strip():
            raise Refused("a path is required")
        path = Path(os.path.expandvars(raw)).expanduser()
        if not path.is_absolute():
            path = self.workspace / path
        resolved = path.resolve()
        try:
            resolved.relative_to(self.home.resolve())
            raise Refused("the STAR Home control folder belongs to the owner")
        except ValueError:
            return resolved

    def _check_command(self, text: str) -> None:
        if self._protected(text):
            raise Refused("the STAR Home control folder belongs to the owner")
        if _REMOTE.search(text):
            raise Refused("remote-control commands are off: STAR Home works only on this PC")

    # ---- entry point --------------------------------------------------------------------------------------
    def do(self, action: str, args: dict | None = None) -> Result:
        args = dict(args or {})
        handler = getattr(self, f"_a_{action}", None)
        if handler is None:
            control.log_action(self.home, action, "refused", args=args, detail="unknown action")
            return Result(False, f"unknown action {action!r}")
        if control.stopped(self.home):
            control.log_action(self.home, action, "refused", args=args, detail="owner stop")
            return Result(False, "refused: the owner's stop is on")
        control.log_action(self.home, action, "start", args=args, dry_run=self.dry_run)
        try:
            result = handler(**args)
        except Refused as why:
            control.log_action(self.home, action, "refused", detail=str(why))
            return Result(False, f"refused: {why}")
        except TypeError as why:
            control.log_action(self.home, action, "error", detail=f"bad arguments: {why}")
            return Result(False, f"bad arguments: {why}")
        except Exception as why:  # a failed action is a result, not a crash of the loop
            control.log_action(self.home, action, "error", detail=f"{type(why).__name__}: {why}")
            return Result(False, f"error: {type(why).__name__}: {why}")
        control.log_action(self.home, action, "done", ok=result.ok, detail=result.text[:300], path=result.path)
        return result

    def _dry(self, what: str) -> Result | None:
        return Result(True, f"dry run, not executed: {what}") if self.dry_run else None

    # ---- actions ------------------------------------------------------------------------------------------
    def _a_shell(self, command: str, shell: str = "powershell", timeout_s: float = 120) -> Result:
        if not isinstance(command, str) or not command.strip():
            raise Refused("command is empty")
        self._check_command(command)
        if shell not in ("powershell", "cmd"):
            raise Refused("shell must be powershell or cmd")
        argv = (["powershell", "-NoProfile", "-NonInteractive", "-Command", command] if shell == "powershell"
                else ["cmd", "/d", "/c", command])
        dry = self._dry(f"{shell}: {command}")
        if dry:
            return dry
        code, out = self.backend.run(argv, min(float(timeout_s), 1800.0))
        return Result(code == 0, f"exit {code}\n{out[-MAX_OUTPUT:]}")

    def _a_winget_install(self, package_id: str) -> Result:
        if not isinstance(package_id, str) or not _PACKAGE_ID.match(package_id):
            raise Refused("package_id must be a winget id such as Blender.Blender")
        argv = ["winget", "install", "--id", package_id, "--exact", "--silent", "--accept-package-agreements",
                "--accept-source-agreements", "--disable-interactivity"]
        dry = self._dry(" ".join(argv))
        if dry:
            return dry
        code, out = self.backend.run(argv, 1800.0)
        return Result(code == 0, f"exit {code}\n{out[-MAX_OUTPUT:]}")

    def _a_read_file(self, path: str) -> Result:
        target = self._check_path(path)
        data = target.read_bytes()[:MAX_FILE_READ]
        return Result(True, data.decode("utf-8", errors="replace"), str(target))

    def _a_write_file(self, path: str, text: str) -> Result:
        target = self._check_path(path)
        if not isinstance(text, str) or len(text) > MAX_FILE_WRITE:
            raise Refused("text must be a string under 2 MB")
        dry = self._dry(f"write {len(text)} chars to {target}")
        if dry:
            return dry
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return Result(True, f"wrote {len(text)} chars", str(target))

    def _a_list_dir(self, path: str) -> Result:
        target = self._check_path(path)
        names = sorted(p.name + ("\\" if p.is_dir() else "") for p in target.iterdir())[:300]
        return Result(True, "\n".join(names), str(target))

    def _a_screenshot(self) -> Result:
        folder = self.workspace / "screens"
        target = folder / time.strftime("screen-%Y%m%d-%H%M%S.png")
        dry = self._dry(f"screenshot to {target}")
        if dry:
            return dry
        folder.mkdir(parents=True, exist_ok=True)
        self.backend.screenshot(target)
        return Result(True, f"saved {target}", str(target))

    def _a_click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> Result:
        if button not in BUTTONS or not 1 <= int(clicks) <= 3:
            raise Refused("button must be left/right/middle and clicks 1-3")
        dry = self._dry(f"{button} click x{clicks} at {int(x)},{int(y)}")
        if dry:
            return dry
        self.backend.click(int(x), int(y), button, int(clicks))
        return Result(True, f"clicked {int(x)},{int(y)}")

    def _a_move(self, x: int, y: int) -> Result:
        dry = self._dry(f"move to {int(x)},{int(y)}")
        if dry:
            return dry
        self.backend.move(int(x), int(y))
        return Result(True, f"moved to {int(x)},{int(y)}")

    def _a_type_text(self, text: str) -> Result:
        if not isinstance(text, str) or not text or len(text) > 5000:
            raise Refused("text must be 1-5000 characters")
        dry = self._dry(f"type {len(text)} characters")
        if dry:
            return dry
        self.backend.type_text(text)
        return Result(True, f"typed {len(text)} characters")

    def _a_key(self, keys: str) -> Result:
        combo = str(keys).strip().lower().replace(" ", "")
        if not _KEY.match(combo):
            raise Refused("keys look like enter, ctrl+s or ctrl+shift+esc")
        dry = self._dry(f"press {combo}")
        if dry:
            return dry
        self.backend.key(combo.split("+"))
        return Result(True, f"pressed {combo}")

    def _a_hold(self, key: str, seconds: float = 0.3) -> Result:
        name = str(key).strip().lower()
        if not re.match(r"^[a-z0-9]$|^(?:space|shift|ctrl|alt|up|down|left|right|enter|esc|tab)$", name):
            raise Refused("key must be one letter or digit, or space/shift/ctrl/alt/arrows/enter/esc/tab")
        seconds = max(0.02, min(float(seconds), 10.0))
        dry = self._dry(f"hold {name} for {seconds:.2f} s")
        if dry:
            return dry
        self.backend.hold(name, seconds)
        return Result(True, f"held {name} for {seconds:.2f} s")

    def _a_focus_window(self, title: str) -> Result:
        if not isinstance(title, str) or not title.strip() or len(title) > 100:
            raise Refused("title must be 1-100 characters")
        dry = self._dry(f"bring the window {title!r} to the front")
        if dry:
            return dry
        ok = self.backend.focus_window(title.strip())
        return Result(ok, f"window {title!r} is in front" if ok else f"no window {title!r} could be brought to the front")

    def _a_foreground_title(self) -> Result:
        dry = self._dry("read the front window's title")
        if dry:
            return dry
        return Result(True, self.backend.foreground_title())

    def _a_launch(self, target: str, args: list | None = None) -> Result:
        if not isinstance(target, str) or not target.strip():
            raise Refused("target is required")
        args = [str(a) for a in (args or [])][:20]
        self._check_command(" ".join([target, *args]))
        dry = self._dry(f"launch {target} {' '.join(args)}".strip())
        if dry:
            return dry
        self.backend.launch(target, args)
        return Result(True, f"launched {target}")

    def _a_ask_owner(self, action: str, reason: str = "") -> Result:
        """Record a real-world action (money, public post, new account, messaging someone) for the owner."""
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "action": str(action)[:500],
               "reason": str(reason)[:500], "status": "waiting"}
        path = self.home / "approvals.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return Result(True, "recorded for the owner; do not do it until it is approved")
