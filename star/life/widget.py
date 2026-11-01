"""The mood weather widget for the OWNER's PC: a small window that shows her mood as weather with a one-line why.

Opt-in: it only starts when the owner's settings.json has `life_widget_enabled: true`. It reads nothing from her PC directly:
every number comes from her status API (star/life/api.py: GET /life/mood), with the token from a file the owner copied over.
Click the window and her journal opens (GET /life/journal, saved as a local HTML page and opened in the browser). Right
click: always-on-top on/off, refresh, close. The window is plain tkinter (standard library), 220x74, no taskbar clutter.

<owner app data>/life/widget.json:
    {"url": "http://<her pc>:8765", "token_file": "C:/.../api_token", "poll_s": 60, "always_on_top": false}
`state_of()` and `Widget.refresh()` are the testable parts; the window code is thin on purpose.
"""
from __future__ import annotations

import html
import json
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .store import base, flag

COLORS = {"sunny": ("#fff3c4", "#7a5b00"), "cloudy": ("#e3e8ee", "#3d4852"), "stormy": ("#c9ced8", "#2b2f3a"),
          "starry": ("#1e2340", "#e8e9ff"), "off": ("#eeeeee", "#555555"), "offline": ("#eeeeee", "#555555")}
ICONS = {"sunny": "\u2600", "cloudy": "\u2601", "stormy": "\u26c8", "starry": "\u2728", "off": "\u00b7", "offline": "\u00b7"}
MIN_POLL_S = 15


@dataclass
class WidgetConfig:
    url: str = ""
    token_file: str = ""
    poll_s: int = 60
    always_on_top: bool = False

    @classmethod
    def load(cls, home=None) -> "WidgetConfig":
        try:
            raw = json.loads((base(home) / "life" / "widget.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        raw = raw if isinstance(raw, dict) else {}
        return cls(str(raw.get("url") or "").rstrip("/"), str(raw.get("token_file") or ""),
                   max(MIN_POLL_S, int(raw.get("poll_s") or 60)), raw.get("always_on_top") is True)

    def token(self) -> str:
        try:
            return Path(self.token_file).read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def save(self, home=None) -> None:
        path = base(home) / "life" / "widget.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"url": self.url, "token_file": self.token_file, "poll_s": self.poll_s,
                                    "always_on_top": self.always_on_top}, indent=1), encoding="utf-8")


def state_of(payload: dict | None, error: str = "") -> dict:
    """The widget's picture from the API's answer: {"kind", "icon", "label", "why", "bg", "fg"}. No answer is shown as
    offline (never as a guess about her mood)."""
    if not isinstance(payload, dict) or payload.get("kind") not in COLORS:
        kind, why = "offline", error or "can't reach her PC right now"
    else:
        kind, why = payload["kind"], str(payload.get("why") or "")[:80]
    bg, fg = COLORS[kind]
    return {"kind": kind, "icon": ICONS[kind], "label": kind if kind != "off" else "no mood", "why": why, "bg": bg, "fg": fg}


def http_get(url: str, token: str, timeout: float = 6.0, opener=urllib.request.urlopen) -> str:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")
    with opener(request, timeout=timeout) as response:
        return response.read(2_000_000).decode("utf-8", "replace")


class Widget:
    def __init__(self, config: WidgetConfig, *, get=http_get) -> None:
        self.config, self.get = config, get
        self.state = state_of(None, "not connected yet")

    def refresh(self) -> dict:
        if not self.config.url or not self.config.token():
            self.state = state_of(None, "set url and token_file in widget.json")
            return self.state
        try:
            self.state = state_of(json.loads(self.get(self.config.url + "/life/mood", self.config.token())))
        except (OSError, ValueError, urllib.error.URLError):
            self.state = state_of(None)
        return self.state

    def journal_page(self) -> Path | None:
        """Fetch her journal and save it as a local page; None when she cannot be reached."""
        try:
            text = self.get(self.config.url + "/life/journal", self.config.token())
        except (OSError, ValueError, urllib.error.URLError):
            return None
        page = ("<!doctype html><meta charset='utf-8'><title>STAR's journal</title><body style='font-family:Segoe UI,sans-serif;"
                "max-width:42em;margin:2em auto;line-height:1.5'><pre style='white-space:pre-wrap;font:inherit'>"
                + html.escape(text) + "</pre></body>")
        path = Path(tempfile.gettempdir()) / "star-journal.html"
        path.write_text(page, encoding="utf-8")
        return path

    def open_journal(self, opener=None) -> bool:
        path = self.journal_page()
        if path is None:
            return False
        if opener is None:                                   # pragma: no cover - opens the real browser
            import webbrowser
            opener = webbrowser.open
        opener(path.as_uri())
        return True


def run(home=None) -> int:  # pragma: no cover - the window itself
    import tkinter as tk
    if not flag("life_widget_enabled", home):
        print("life_widget_enabled is off in settings.json: the widget is opt-in.")
        return 2
    config = WidgetConfig.load(home)
    widget = Widget(config)
    root = tk.Tk()
    root.title("STAR mood")
    root.overrideredirect(True)
    root.attributes("-topmost", config.always_on_top)
    root.geometry("220x74+40+40")
    icon, line = tk.Label(root, font=("Segoe UI Emoji", 26)), tk.Label(root, font=("Segoe UI", 9), wraplength=150, justify="left")
    icon.pack(side="left", padx=8)
    line.pack(side="left", fill="both", expand=True)

    def paint() -> None:
        s = widget.state
        root.configure(bg=s["bg"])
        icon.configure(text=s["icon"], bg=s["bg"], fg=s["fg"])
        line.configure(text=f"{s['label']}\n{s['why']}", bg=s["bg"], fg=s["fg"])

    def poll() -> None:
        widget.refresh()
        paint()
        root.after(config.poll_s * 1000, poll)

    def toggle_top() -> None:
        config.always_on_top = not config.always_on_top
        root.attributes("-topmost", config.always_on_top)
        config.save(home)

    menu = tk.Menu(root, tearoff=0)
    menu.add_command(label="Always on top", command=toggle_top)
    menu.add_command(label="Refresh", command=lambda: (widget.refresh(), paint()))
    menu.add_command(label="Close", command=root.destroy)
    moved = [False]

    def drag(event) -> None:
        moved[0] = True
        root.geometry(f"+{event.x_root - 100}+{event.y_root - 30}")

    def release(_event) -> None:
        if not moved[0]:
            widget.open_journal()                       # a click, not a drag
        moved[0] = False

    for item in (root, icon, line):
        item.bind("<B1-Motion>", drag)
        item.bind("<ButtonRelease-1>", release)
        item.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))
    poll()
    root.mainloop()
    return 0
