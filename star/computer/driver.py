"""The computer-use driver: observe -> ground -> act -> verify, with retries, for one concrete step at a time.

The planner (agent.Computer.act, or a skill in skills.py) says WHAT: a `Step` ("click the Send button, expect the
text to appear"). The driver does it reliably and safely:
  observe  screenshot + UI Automation tree of the front window + the list of open windows (`Observation`)
  ground   ground.GroundingChain: UIA name match first, then the GPU grounder, then STAR's remote vision
  act      human-paced mouse and keyboard (hands.py)
  verify   look again and check the step's `Expect` (text appears / disappears, window in front / opened / closed,
           a switch is on or off, or at least something changed). Mismatch: wait longer and look again (slow apps),
           then the next alternative target, then re-focus and retry; never a blind repeat of a click that DID change
           something (a second click on a toggle undoes the first).
Before anything: the machine must be STAR's enrolled PC (identity.py), the owner's stop must be off (stopswitch.py),
the pace and messaging limits must allow it (limits.py) and the gates must pass (gates.py: money, accounts, passwords,
mass messaging; never CAPTCHAs or cheat tools). Every attempt is written to the action log with before/after
screenshots (actionlog.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from . import gates, identity
from .actionlog import ActionLog
from .eye import changed_fraction
from .gates import Gated
from .ground import GroundingChain, UiaFinder
from .hands import Stopped
from .limits import Limited, RateLimits
from .screen import Element, Screen
from .stopswitch import StopSwitch

URI_SCHEMES = ("http", "https", "roblox", "discord", "ms-settings", "steam")
KINDS = ("click", "double", "right", "type", "key", "scroll", "open", "uri", "focus", "wait")


@dataclass
class Observation:
    screen: Screen
    image: object = None
    windows: list = field(default_factory=list)

    def window(self, part: str):
        part = part.lower()
        return next((w for w in self.windows if part in (w.title + " " + w.exe).lower()), None)


@dataclass(frozen=True)
class Expect:
    text: str = ""            # on screen afterwards (control names/values or the window title)
    gone: str = ""            # no longer on screen
    window: str = ""          # the window in front has this in its title or program name
    window_open: str = ""     # some window has it
    window_closed: str = ""   # no window has it
    toggle: int = -1          # the grounded switch is now 1 (on) or 0 (off)
    focused: str = ""         # the focused control's role or name contains this (e.g. "edit" after Ctrl+L)

    def specific(self) -> bool:
        return any((self.text, self.gone, self.window, self.window_open, self.window_closed, self.focused)) or             self.toggle >= 0


@dataclass
class Step:
    do: str
    target: str | tuple = ""     # a control's name; a tuple = alternatives, one per attempt
    role: str = ""
    text: str = ""
    keys: str = ""
    amount: int = 3              # scroll notches (positive = down)
    expect: Expect = field(default_factory=Expect)
    retries: int = 2
    message_to: str = ""         # this step sends a message to this person (messaging limits and gates)


@dataclass
class StepResult:
    ok: bool
    detail: str
    source: str = ""
    attempts: int = 0
    gated: str = ""

    @property
    def verified(self) -> bool:
        return self.ok


class Driver:
    def __init__(self, computer, *, home, chain: GroundingChain | None = None, limits: RateLimits | None = None,
                 log: ActionLog | None = None, switch: StopSwitch | None = None,
                 read_guid: Callable[[], str] = identity.machine_guid, settle_s: float | None = None,
                 sleep: Callable[[float], None] | None = None) -> None:
        identity.require(home, read_guid)                  # never on the owner's PC: raises WrongMachine
        self.c, self.home = computer, home
        self.switch = switch or StopSwitch(home)
        self.c.hands._stopped = self.switch.is_set
        self.chain = chain or GroundingChain([UiaFinder()])
        self.limits = limits or RateLimits(computer.cfg.get("limits") if isinstance(computer.cfg, dict) else None)
        self.log = log or ActionLog(home)
        self.settle_s = float(computer.cfg.get("settle_s", 0.5)) if settle_s is None else settle_s
        self.sleep = sleep or computer.sleep

    # ---- observe ------------------------------------------------------------------------------------------
    def observe(self) -> Observation:
        screen = self.c.see()
        image = self.c.eye.grab() if self.c.eye is not None else None
        return Observation(screen, image, list(self.c.windows.windows()))

    # ---- verify -------------------------------------------------------------------------------------------
    @staticmethod
    def _changed(before: Observation, after: Observation) -> bool:
        if before.screen.difference(after.screen) >= 0.02:
            return True
        if before.image is not None and after.image is not None:
            return changed_fraction(before.image, after.image) >= 0.002
        return False

    def verify(self, expect: Expect, before: Observation, after: Observation, el: Element | None,
               typed: str = "") -> tuple[bool, str]:
        misses = []
        if expect.text and not after.screen.has_text(expect.text):
            misses.append(f"{expect.text!r} not on screen")
        if expect.gone and after.screen.has_text(expect.gone):
            misses.append(f"{expect.gone!r} still on screen")
        if expect.window and expect.window.lower() not in (after.screen.window + " " + after.screen.process).lower():
            misses.append(f"front window is {after.screen.window!r}, not {expect.window!r}")
        if expect.window_open and after.window(expect.window_open) is None:
            misses.append(f"no window {expect.window_open!r}")
        if expect.window_closed and after.window(expect.window_closed) is not None:
            misses.append(f"window {expect.window_closed!r} is still open")
        if expect.toggle >= 0:
            now = after.screen.find(el.name, role=el.role, limit=1) if el is not None else []
            state = now[0][1].toggle if now and now[0][0] >= 0.85 else -1
            if state != expect.toggle:
                misses.append(f"switch {el.name if el else '?'!r} is {('off', 'on')[state] if state in (0, 1) else 'unknown'}")
        if expect.focused:
            focus = next((e for e in after.screen.elements if e.focused), None)
            if focus is None or expect.focused.lower() not in f"{focus.role} {focus.name}".lower():
                misses.append(f"focus is on {focus.name if focus else 'nothing'!r}, not {expect.focused!r}")
        if not expect.specific() and not self._changed(before, after) and not (
                typed and after.screen.has_text(typed[-40:])):
            misses.append("no visible effect")
        return (not misses), ("; ".join(misses) or "as expected")

    # ---- act ----------------------------------------------------------------------------------------------
    def _aim(self, el: Element) -> tuple[int, int]:
        return self.c.aim_point(el) if el.source == "uia" or el.width > 8 else el.center

    def _perform(self, step: Step, obs: Observation, el: Element | None) -> str:
        hands, kind = self.c.hands, step.do
        if kind in ("click", "double", "right"):
            if el is None:
                raise RuntimeError(f"{kind} without a target")
            x, y = self._aim(el)
            hands.click(x, y, width=min(el.width, el.height) or 20, button="right" if kind == "right" else "left",
                        clicks=2 if kind == "double" else 1)
            return f"{kind} {el.name!r}"
        if kind == "type":
            if el is not None and not el.focused:
                x, y = self._aim(el)
                hands.click(x, y, width=min(el.width, el.height) or 20)
                self.sleep(0.25)
            hands.type_text(step.text)
            return f"typed {len(step.text)} characters"
        if kind == "key":
            hands.key(step.keys)
            return f"pressed {step.keys}"
        if kind == "scroll":
            at = el.center if el is not None else (obs.screen.size[0] // 2, obs.screen.size[1] // 2)
            hands.scroll(-int(step.amount), at=at)
            return f"scrolled {step.amount}"
        if kind == "open":
            info, message = self.c.open_app(str(step.target), match=step.expect.window_open)
            if info is None:
                raise RuntimeError(message)
            return message
        if kind == "uri":
            result = self.c.executor.do("launch", {"target": str(step.target)})
            if not result.ok:
                raise RuntimeError(result.text)
            return f"opened {str(step.target)[:80]}"
        if kind == "focus":
            hit = obs.window(str(step.target))
            if hit is None or not self.c.windows.focus(hit.hwnd):
                raise RuntimeError(f"no window {step.target!r} to bring to the front")
            return f"focused {hit.title!r}"
        if kind == "wait":
            hands.wait(min(30.0, max(0.0, float(step.amount))))
            return "waited"
        raise ValueError(f"unknown step {kind!r}")

    def _gate(self, step: Step, obs: Observation, el: Element | None, target: str) -> None:
        gates.check_screen(obs.screen)
        if step.do in ("click", "double", "right"):
            gates.check_click(el, target)
        elif step.do == "type":
            focused = el or next((e for e in obs.screen.elements if e.focused), None)
            gates.check_type(focused, step.text)
        elif step.do in ("open", "uri"):
            gates.check_open(target)
            if step.do == "uri":
                scheme = target.split(":", 1)[0].lower()
                if scheme not in URI_SCHEMES:
                    raise Gated(f"links of the kind {scheme!r}: are not opened by her driver")

    def _needs_element(self, step: Step) -> bool:
        return step.do in ("click", "double", "right") or (step.do in ("type", "scroll") and bool(step.target))

    def run(self, step: Step) -> StepResult:
        """One step with up to `retries` more attempts. Raises Stopped on the owner's stop."""
        if step.do not in KINDS:
            return StepResult(False, f"unknown step {step.do!r}")
        targets = step.target if isinstance(step.target, tuple) else (step.target,)
        if self.switch.is_set():
            raise Stopped("the owner's stop is on")
        try:
            if step.message_to:
                gates.check_type(None, step.text)
                self.limits.message(step.message_to, step.text)
        except Gated as why:
            return self._refused(step, why, str(targets[0]))
        detail, source, index = "not tried", "", 0
        attempt = 0
        for attempt in range(1, step.retries + 2):
            if self.switch.is_set():
                raise Stopped("the owner's stop is on")
            target = str(targets[min(index, len(targets) - 1)])
            before = self.observe()
            el, tried = None, []
            try:
                self._pace()
                if self._needs_element(step):
                    found = self.chain.ground(before, target, step.role)
                    tried = found.tried
                    if found.hit is None:
                        detail = f"{target!r} not found ({', '.join(f'{n}: {s}' for n, s in tried)})"
                        self._record(step, attempt, target, "", tried, False, detail, before, None)
                        index += 1 if index + 1 < len(targets) else 0
                        self.sleep(self.settle_s * attempt)
                        continue
                    el, source = found.hit.element, found.hit.source
                self._gate(step, before, el, target)
                did = self._perform(step, before, el)
            except Gated as why:
                return self._refused(step, why, target, before)
            except Limited as why:
                detail = str(why)
                self._record(step, attempt, target, source, tried, False, detail, before, None)
                if why.retry_after > 10:
                    break
                self.sleep(why.retry_after)
                continue
            except Stopped:
                raise
            except (RuntimeError, ValueError, TypeError) as why:
                detail = str(why)
                self._record(step, attempt, target, source, tried, False, detail, before, None)
                self.sleep(self.settle_s * attempt)
                continue
            self.sleep(self.settle_s * attempt)
            after = self.observe()
            ok, why = self.verify(step.expect, before, after, el, step.text if step.do == "type" else "")
            if not ok and step.expect.specific() and self._changed(before, after):
                self.sleep(self.settle_s * 3 + 0.5)                     # it did something: maybe just slow
                after = self.observe()
                ok, why = self.verify(step.expect, before, after, el, step.text if step.do == "type" else "")
            detail = f"{did}: {why}"
            self._record(step, attempt, target, source, tried, ok, detail, before, after)
            if ok:
                return StepResult(True, detail, source, attempt)
            changed = self._changed(before, after)
            if index + 1 < len(targets):
                index += 1                                              # replan: the next alternative target
            elif changed and step.do in ("click", "double", "right", "key"):
                break                                                   # never repeat a click that changed something
            elif before.screen.hwnd:
                self.c.windows.focus(before.screen.hwnd)                # recover: her window back in front
        return StepResult(False, detail, source, attempt)

    def _pace(self) -> None:
        self.limits.action()

    def _refused(self, step: Step, why: Gated, target: str, obs: Observation | None = None) -> StepResult:
        self.c.ask_owner(f"{step.do} {target!r}" + (f" -> {step.message_to}" if step.message_to else ""), why.reason)
        self._record(step, 0, target, "", [], False, f"GATED: {why.reason}", obs, None)
        return StepResult(False, f"refused: {why.reason}", gated=why.reason)

    def _record(self, step: Step, attempt: int, target: str, source: str, tried, ok: bool, detail: str,
                before: Observation | None, after: Observation | None) -> None:
        self.log.step(do=step.do, target=target, keys=step.keys, text=step.text[:30], attempt=attempt, source=source,
                      tried=[f"{n}: {s}" for n, s in tried], ok=ok, detail=detail,
                      window=before.screen.window if before else "",
                      before=self.log.shot(before.image, "before") if before else "",
                      after=self.log.shot(after.image, "after") if after else "")

    def run_all(self, steps: list[Step]) -> tuple[bool, list[StepResult]]:
        """Steps in order; stops at the first one that fails."""
        done: list[StepResult] = []
        for step in steps:
            result = self.run(step)
            done.append(result)
            if not result.ok:
                return False, done
        return True, done
