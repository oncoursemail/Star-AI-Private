"""Skills: short, tested macros for the apps she uses most, built from driver Steps (so every one is grounded,
verified, gated, rate-limited, stoppable and logged with screenshots).

  open_app(app)                      open or bring to the front (aliases below + computer.json "apps")
  focus_window(part)                 bring a window whose title or program contains `part` to the front
  browser_go(url) / browser_search(q) address bar of her browser (Ctrl+L, type, Enter)
  discord_dm(user, text)             Ctrl+K quick switcher -> the person -> type -> Enter (messaging limits apply)
  discord_reply(text)                type into the open conversation -> Enter (messaging limits apply)
  roblox_join(place_id)              roblox://experiences/start?placeId=... (her own signed-in Roblox)
  roblox_leave()                     Esc, L, Enter (Roblox's own leave keys), or the Leave buttons
  settings_toggle(page, name, on)    ms-settings:<page>, read the switch, click only if it is not already right
  install(path)                      .msi silently (msiexec /qn); .exe: accept the licence, untick bundled offers,
                                     Next/Install/Finish until done; a serial/password/payment screen goes to the owner
`run_skill(driver, name, **args)` returns {"ok", "summary", "steps"}; the owner's stop ends any skill at once.
"""
from __future__ import annotations

import os
from pathlib import Path
import re

from . import gates
from .driver import Driver, Expect, Step, StepResult
from .gates import Gated
from .hands import Stopped

APPS = {"paint": "mspaint.exe", "notepad": "notepad.exe", "calculator": "calc.exe", "explorer": "explorer.exe",
        "file explorer": "explorer.exe", "settings": "ms-settings:", "edge": "msedge.exe",
        "browser": "msedge.exe", "chrome": "chrome.exe", "task manager": "taskmgr.exe",
        # the installer's shortcut: Discord with --force-renderer-accessibility, so UI Automation can read it
        "discord": r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Discord (STAR).lnk"}
WINDOW_OF = {"mspaint.exe": "paint", "notepad.exe": "notepad", "calc.exe": "calculator", "explorer.exe": "explorer",
             "ms-settings:": "settings", "msedge.exe": "edge", "chrome.exe": "chrome",
             "taskmgr.exe": "task manager"}
BROWSERS = ("msedge.exe", "chrome.exe", "firefox.exe", "brave.exe", "opera.exe")
NEXT_BUTTONS = ("Install", "Next", "Next >", "I Agree", "Agree", "Accept", "Continue", "Yes", "OK", "Finish", "Close",
                "Done")
FINISH = ("finish", "close", "done")
OFFER = re.compile(r"(toolbar|mcafee|norton|avast|avg |opera|yahoo|bing|search engine|home ?page|offer|recommended "
                   r"software|special offer|browser extension|set as default)", re.I)
ACCEPT = re.compile(r"\bi (?:accept|agree)\b", re.I)


def _result(ok: bool, summary: str, steps: list[StepResult]) -> dict:
    return {"ok": ok, "summary": summary[:600], "steps": [s.detail for s in steps]}


def _resolve(d: Driver, app: str) -> str:
    apps = dict(APPS)
    apps.update({str(k).lower(): str(v) for k, v in (d.c.cfg.get("apps") or {}).items()})
    return apps.get(app.strip().lower(), app.strip())


def open_app(d: Driver, app: str) -> dict:
    target = _resolve(d, app)
    match = WINDOW_OF.get(target.lower(), re.sub(r"\.exe$", "", Path(target).name, flags=re.I).lower() or app)
    if target.lower().endswith(".lnk"):
        match = app.strip().lower()
    target = os.path.expandvars(target)
    if d.observe().window(match) is not None:
        return focus_window(d, match)
    is_uri = re.match(r"^[a-z][a-z0-9+.-]+:", target) and not re.match(r"^[a-z]:\\", target, re.I)
    step = (Step("uri", target, expect=Expect(window_open=match), retries=1) if is_uri else
            Step("open", target, expect=Expect(window_open=match), retries=1))
    result = d.run(step)
    return _result(result.ok, f"open {app}: {result.detail}", [result])


def focus_window(d: Driver, part: str) -> dict:
    result = d.run(Step("focus", part, expect=Expect(window=part), retries=2))
    return _result(result.ok, f"focus {part}: {result.detail}", [result])


def _browser(d: Driver) -> str:
    obs = d.observe()
    if obs.screen.process in BROWSERS:
        return obs.screen.process
    hit = next((w for w in obs.windows if w.exe in BROWSERS), None)
    if hit is not None:
        return hit.exe
    opened = open_app(d, "browser")
    return d.observe().screen.process if opened["ok"] else ""


def _address_bar(d: Driver, text: str) -> dict:
    exe = _browser(d)
    if not exe:
        return _result(False, "no browser window", [])
    ok, steps = d.run_all([Step("focus", exe, expect=Expect(window=exe)),
                           Step("key", keys="ctrl+l", expect=Expect(focused="edit"), retries=1),
                           Step("type", text=text, retries=0),
                           Step("key", keys="enter", retries=0)])
    return _result(ok, f"browser: {steps[-1].detail}", steps)


def browser_go(d: Driver, url: str) -> dict:
    if not re.match(r"^https?://[^\s]+$", url.strip(), re.I):
        return _result(False, "browser_go takes an http(s) address", [])
    return _address_bar(d, url.strip())


def browser_search(d: Driver, query: str) -> dict:
    query = " ".join(str(query).split())
    if not query or re.match(r"^[a-z]+:", query, re.I):
        return _result(False, "a search is plain words", [])
    return _address_bar(d, query)


def discord_dm(d: Driver, user: str, text: str) -> dict:
    opened = open_app(d, "discord")
    if not opened["ok"]:
        return opened
    ok, steps = d.run_all([Step("key", keys="ctrl+k", retries=0),
                           Step("type", text=user, retries=0),
                           Step("key", keys="enter", expect=Expect(text=user), retries=0),
                           Step("type", text=text, message_to=user, retries=0),
                           Step("key", keys="enter", expect=Expect(text=text[:40]), retries=0)])
    return _result(ok, f"discord dm {user}: {steps[-1].detail}", steps)


def discord_reply(d: Driver, text: str) -> dict:
    focused = focus_window(d, "discord")
    if not focused["ok"]:
        return focused
    title = d.observe().screen.window
    who = re.sub(r"\s*[-|]\s*discord\s*$|^discord\s*[-|]\s*", "", title, flags=re.I).strip() or title
    ok, steps = d.run_all([Step("type", text=text, message_to=who, retries=0),
                           Step("key", keys="enter", expect=Expect(text=text[:40]), retries=0)])
    return _result(ok, f"discord reply in {who}: {steps[-1].detail}", steps)


def roblox_join(d: Driver, place_id: int) -> dict:
    place = int(place_id)
    if place <= 0:
        return _result(False, "a Roblox place id is a positive number", [])
    result = d.run(Step("uri", f"roblox://experiences/start?placeId={place}", expect=Expect(window_open="roblox"),
                        retries=0))
    if not result.ok:                                   # the player takes a while to start: one longer look
        d.c.hands.wait(15.0)
        if d.observe().window("roblox") is not None:
            result = StepResult(True, "Roblox window opened after a longer wait", result.source, result.attempts)
    return _result(result.ok, f"join {place}: {result.detail}", [result])


def roblox_leave(d: Driver) -> dict:
    focused = focus_window(d, "roblox")
    if not focused["ok"]:
        return focused
    ok, steps = d.run_all([Step("key", keys="escape", retries=0), Step("key", keys="l", retries=0),
                           Step("key", keys="enter", expect=Expect(window_closed="roblox"), retries=0)])
    if not ok and d.observe().window("roblox") is not None:
        ok, more = d.run_all([Step("click", ("Leave", "Leave Game"), expect=Expect(window_closed="roblox"))])
        steps += more
    return _result(ok, f"leave Roblox: {steps[-1].detail}", steps)


def settings_toggle(d: Driver, page: str, name: str, on: bool) -> dict:
    if not re.match(r"^[a-z0-9-]+$", page):
        return _result(False, "a settings page is like 'bluetooth' or 'nightlight'", [])
    opened = d.run(Step("uri", f"ms-settings:{page}", expect=Expect(window_open="settings"), retries=1))
    steps = [opened]
    if not opened.ok:
        return _result(False, f"settings {page}: {opened.detail}", steps)
    steps.append(d.run(Step("focus", "settings", expect=Expect(window="settings"))))
    want = 1 if on else 0
    found = d.observe().screen.find(name, limit=1)
    if found and found[0][0] >= 0.85 and found[0][1].toggle == want:
        return _result(True, f"{name} is already {'on' if on else 'off'}", steps)
    steps.append(d.run(Step("click", name, expect=Expect(toggle=want), retries=1)))
    return _result(steps[-1].ok, f"{name} {'on' if on else 'off'}: {steps[-1].detail}", steps)


def install(d: Driver, path: str, *, max_screens: int = 30) -> dict:
    file = Path(path)
    if file.suffix.lower() not in (".exe", ".msi") or not file.is_file():
        return _result(False, f"{path!r} is not a downloaded .exe or .msi installer", [])
    try:
        gates.check_open(file.name)
    except Gated as why:
        d.c.ask_owner(f"install {file.name}", why.reason)
        return _result(False, f"refused: {why.reason}", [])
    if file.suffix.lower() == ".msi":
        done = d.c.executor.do("shell", {"command": f'msiexec /i "{file}" /qn /norestart', "shell": "cmd",
                                         "timeout_s": 1800})
        return _result(done.ok, f"msiexec {file.name}: {done.text[:200]}", [])
    launched = d.c.executor.do("launch", {"target": str(file)})
    if not launched.ok:
        return _result(False, f"could not start {file.name}: {launched.text}", [])
    steps: list[StepResult] = []
    accepted, idle = False, 0
    for _ in range(max_screens):
        if d.switch.is_set():
            raise Stopped("the owner's stop is on")
        screen = d.observe().screen
        try:
            gates.check_screen(screen)
            for el in screen.elements:
                if el.role == "edit" and not el.value:
                    gates.check_type(el, "")
        except Gated as why:
            d.c.ask_owner(f"install {file.name}: screen {screen.window!r}", why.reason)
            return _result(False, f"refused: {why.reason}", steps)
        offer = next((e for e in screen.elements if e.role == "checkbox" and e.toggle == 1 and OFFER.search(e.name)),
                     None)
        if offer is not None:
            steps.append(d.run(Step("click", offer.name, role="checkbox", expect=Expect(toggle=0), retries=1)))
            continue
        agree = next((e for e in screen.elements if e.role in ("radio", "checkbox") and ACCEPT.search(e.name)
                      and e.toggle != 1), None)
        if agree is not None and not accepted:
            accepted = True
            steps.append(d.run(Step("click", agree.name, role=agree.role, retries=0)))
            continue
        button = next((e for name in NEXT_BUTTONS for e in screen.elements
                       if e.role == "button" and e.enabled and e.name.strip().lower() == name.lower()), None)
        if button is None:
            idle += 1
            if idle >= 10:
                return _result(False, f"{file.name}: no button to press on {screen.window!r} for a long time", steps)
            d.c.hands.wait(3.0)                                  # copying files: wait for the next screen
            continue
        idle = 0
        last = button.name.strip().lower() in FINISH
        steps.append(d.run(Step("click", button.name, role="button", retries=1)))
        if not steps[-1].ok and steps[-1].gated:
            return _result(False, steps[-1].detail, steps)
        if last and steps[-1].ok:
            return _result(True, f"installed {file.name}", steps)
    return _result(False, f"{file.name}: still not finished after {max_screens} screens", steps)


SKILLS = {"open_app": open_app, "focus_window": focus_window, "browser_go": browser_go,
          "browser_search": browser_search, "discord_dm": discord_dm, "discord_reply": discord_reply,
          "roblox_join": roblox_join, "roblox_leave": roblox_leave, "settings_toggle": settings_toggle,
          "install": install}


def run_skill(d: Driver, name: str, /, **args) -> dict:
    skill = SKILLS.get(name)
    if skill is None:
        return {"ok": False, "summary": f"no skill {name!r}; known: {', '.join(SKILLS)}", "steps": []}
    try:
        return skill(d, **args)
    except Stopped:
        return {"ok": False, "summary": "stopped by the owner", "steps": []}
    except TypeError as why:
        return {"ok": False, "summary": f"bad arguments for {name}: {why}", "steps": []}
