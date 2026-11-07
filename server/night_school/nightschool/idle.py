"""Polite scheduling: night school works only while nobody else uses the brain.

The brain is a llama.cpp router. `GET /v1/models` lists the loaded models and `GET /slots?model=<id>` lists each
model's slots with `is_processing` and `id_task` (the number of the last request the slot served). Somebody else is
using the brain when a slot is processing, or when a slot's `id_task` changed since the last look, and the change
is not night school's own request (night school only ever uses one slot, never slot 0).

Limits, stated plainly: activity is sampled (every `poll_s` seconds while waiting, every `watch_s` seconds during a
request); a request from somebody else that is pinned to night school's own slot while night school is generating
waits in the server's queue until night school's request ends and cannot be seen before that.
"""
from __future__ import annotations

import json
from pathlib import Path
import time
import urllib.error
import urllib.request

HELPERS = ("embed", "rerank")       # models the knowledge service calls for night school's own searches
LOCK_STALE_S = 1200


class BrainUnreachable(OSError):
    pass


def read_key(key_file: str) -> str:
    """The first key in the file, in memory only. Never printed or logged."""
    try:
        for line in Path(key_file).read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.strip().startswith("#"):
                return line.strip()
    except OSError:
        pass
    return ""


class BrainWatch:
    """Reads the brain's slot table. `fetch(path) -> parsed JSON` exists for tests."""

    def __init__(self, url: str, key: str = "", fetch=None, timeout: float = 6.0):
        self._url, self._key, self._timeout = url.rstrip("/"), key, timeout
        self._fetch = fetch or self._http

    def _http(self, path: str):
        request = urllib.request.Request(self._url + path)
        if self._key:
            request.add_header("Authorization", "Bearer " + self._key)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as reply:
                return json.loads(reply.read(4 * 1024 * 1024).decode("utf-8", "replace"))
        except (OSError, ValueError, urllib.error.URLError) as exc:
            raise BrainUnreachable(type(exc).__name__) from None      # the text may hold the address

    def models(self) -> dict[str, list[str]]:
        """{loaded model id: its other names}."""
        data = self._fetch("/v1/models")
        found = {}
        for row in (data.get("data") or []) if isinstance(data, dict) else []:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                continue
            status = row.get("status")
            if isinstance(status, dict) and status.get("value") not in (None, "loaded"):
                continue
            found[row["id"]] = [a for a in (row.get("aliases") or []) if isinstance(a, str)]
        return found

    def snapshot(self) -> dict[tuple[str, int], tuple[bool, int]]:
        """{(model, slot id): (is processing, last task number)} for every loaded model."""
        table = {}
        for model in self.models():
            slots = self._fetch("/slots?model=" + model)
            if not isinstance(slots, list):
                raise BrainUnreachable("slots")
            for slot in slots:
                if isinstance(slot, dict) and type(slot.get("id")) is int:
                    task = slot.get("id_task")
                    table[(model, slot["id"])] = (bool(slot.get("is_processing")), task if type(task) is int else -1)
        return table

    def slot_for(self, wanted: int) -> dict[str, int]:
        """{model or alias: the slot night school may use}: `wanted` when the model has it, else its highest slot.
        A model with a single slot maps to 0, which callers must refuse."""
        names = self.models()
        highest: dict[str, int] = {}
        for (model, slot) in self.snapshot():
            highest[model] = max(highest.get(model, 0), slot)
        chosen = {}
        for model, top in highest.items():
            slot = wanted if 0 < wanted <= top else top
            for name in (model, *names.get(model, [])):
                chosen[name] = slot
        return chosen


def activity(before: dict, after: dict, *, own_slot: int | None = None, skip_helpers: bool = False) -> list[str]:
    """Signs of another client between two snapshots, as "model/slot" strings. With `own_slot` set, that slot of
    every model is night school's own and is ignored (as are the helper models when `skip_helpers`)."""
    seen = []
    for (model, slot), (busy, task) in after.items():
        if own_slot is not None and slot == own_slot:
            continue
        if skip_helpers and any(word in model for word in HELPERS):
            continue
        old = before.get((model, slot))
        if busy or (old is not None and old[1] != task):
            seen.append(f"{model}/{slot}")
    return seen


class IdleGate:
    """`wait()` returns only after `idle_s` seconds with no sign of another client, no HOLD file and no quiet lock."""

    def __init__(self, settings, watch: BrainWatch, *, log=print, clock=time.monotonic, sleep=time.sleep):
        self.settings, self.watch, self._log, self._clock, self._sleep = settings, watch, log, clock, sleep
        self._last: dict | None = None          # the newest snapshot
        self._quiet_since: float | None = None  # start of the current quiet period
        self.signs: list[str] = []              # the busy "model/slot"s of the newest look
        self._said = ""
        self._said_at = -1e9

    def _say(self, text: str, every: float = 900.0) -> None:
        now = self._clock()
        if text != self._said or now - self._said_at >= every:
            self._log(text)
            self._said, self._said_at = text, now

    def lock_held(self) -> bool:
        try:
            newest = Path(self.settings.lock_dir).stat().st_mtime
        except OSError:
            return False
        return time.time() - newest < LOCK_STALE_S          # an older lock is stale and ignored, never removed

    def look(self) -> str:
        """One look. "" when nothing speaks against working now, else the reason. Updates the quiet timer."""
        now = self._clock()
        self.signs = []
        if Path(self.settings.hold_file).exists():
            self._quiet_since = None
            return "HOLD file present, paused"
        if self.lock_held():
            self._quiet_since = None
            return "quiet lock held, waiting"
        try:
            table = self.watch.snapshot()
        except OSError:
            self._last, self._quiet_since = None, None
            return "brain not reachable, waiting"
        # Helper models alone (embeddings, rerank: a documentation search, an index job, another night-school
        # worker's checks) are not somebody using the brain; every chat turn also shows on a chat model's slot.
        signs = activity(self._last if self._last is not None else {}, table, skip_helpers=True)
        self._last = table
        self.signs = sorted(signs)[:4]         # who made the brain busy, for a log line that names it
        if signs:
            self._quiet_since = None
            return "brain busy, waiting"
        if self._quiet_since is None:
            self._quiet_since = now
        if now - self._quiet_since < self.settings.idle_s:
            return f"brain quiet, waiting until it has been quiet for {int(self.settings.idle_s)} s"
        return ""

    def wait(self, stop=lambda: False) -> bool:
        """Block until the brain has been idle long enough. False when asked to stop."""
        while not stop():
            reason = self.look()
            if not reason:
                self._say("brain idle, working")
                return True
            self._say(reason)
            self._sleep(self.settings.poll_s)
        return False

    def intruder(self, own_slot: int) -> str:
        """During night school's own request: "" or the sign of another client. Resets the quiet timer on a sign."""
        if Path(self.settings.hold_file).exists():
            return "HOLD file"
        if self.lock_held():
            return "quiet lock"
        try:
            table = self.watch.snapshot()
        except OSError:
            return ""            # one failed look does not stop a running request; the next look decides
        signs = activity(self._last if self._last is not None else table, table, own_slot=own_slot, skip_helpers=True)
        self._last = table
        if signs:
            self._quiet_since = None
            return "another client on " + ", ".join(sorted(signs)[:4])
        return ""

    def own_work_done(self) -> None:
        """Night school's own request ended: take a fresh snapshot so its task numbers are not read as a stranger's."""
        try:
            self._last = self.watch.snapshot()
        except OSError:
            self._last, self._quiet_since = None, None


class PlannedGate(IdleGate):
    """The idle gate with STAR's resource planner (star/resource_planner_service.py) in front of it.

    With the planner up, night school holds a "nightschool" lease for its slot: it starts as soon as the planner
    admits it (no 10-minute wait: the planner knows which busy slots belong to leased batch work such as an eval, and
    which are chat) and backs off when a renewal says "yield" (chat active, a timing window, a higher-priority job
    that needs the slot). The HOLD file and the quiet lock are still checked here first, every time.
    With the planner down, slow, or without fresh data ("fallback"), every call is exactly the old IdleGate.
    """

    def __init__(self, settings, watch: BrainWatch, *, planner=None, holder: str = "nightschool",
                 slot: int | None = None, extra_lane: bool = False, **kwargs):
        super().__init__(settings, watch, **kwargs)
        self.planner, self.holder = planner, holder
        self.slot = int(settings.slot if slot is None else slot)
        self.extra_lane = extra_lane         # lanes 2..N exist only by the planner's leave: no idle-gate fallback
        self.grant = None
        self.mode = "idle-gate"

    def _local_stop(self) -> str:
        if Path(self.settings.hold_file).exists():
            return "HOLD file present, paused"
        if self.lock_held():
            return "quiet lock held, waiting"
        return ""

    def _ask(self):
        """Renew the lease, or ask for one. A Grant (see star/planner_client.py)."""
        if self.grant is not None and self.grant.planned:
            grant = self.planner.renew(self.grant)
            if grant.action != "refuse":
                return grant
        extra = {}
        drafts = getattr(self.settings, "diagnose_model", "")
        if drafts and drafts != getattr(self.settings, "model", ""):
            extra["extra_models"] = [drafts]       # its lesson drafts on that model are not "chat"
        return self.planner.admit("nightschool", self.holder, "practice", slot=self.slot, **extra)

    def look(self) -> str:
        if self.planner is None or not getattr(self.planner, "enabled", False):
            return "extra lanes run only with the resource planner" if self.extra_lane else super().look()
        local = self._local_stop()
        if local:
            self._quiet_since = None
            self._drop()
            return local
        grant = self._ask()
        if grant.action == "run":
            self.grant, self.mode = grant, "planner"
            return ""
        if grant.action == "fallback":
            self.grant = grant if grant.lease_id else None
            if self.extra_lane:
                self.grant, self.mode = None, "planner"
                return "extra lanes run only with the resource planner (" + (grant.reason or "fallback") + ")"
            self.mode = "idle-gate"
            return super().look()
        self.grant, self.mode = None, "planner"
        self._quiet_since = None
        return "planner: " + (grant.reason or grant.action)

    def wait(self, stop=lambda: False) -> bool:
        while not stop():
            reason = self.look()
            if not reason:
                self._say("planner admitted, working" if self.mode == "planner" else "brain idle, working")
                return True
            self._say(reason)
            self._sleep(self.settings.poll_s)
        return False

    def intruder(self, own_slot: int) -> str:
        if self.mode != "planner" or self.grant is None or not self.grant.planned:
            return super().intruder(own_slot)
        local = self._local_stop()
        if local:
            return local.split(",")[0]
        grant = self.planner.renew(self.grant)
        if grant.action == "run":
            self.grant = grant
            return ""
        if grant.action == "fallback":          # the planner went away mid-request: the old watch decides
            if self.extra_lane:
                self.grant = None
                return "planner gone (extra lane stops)"
            self.mode = "idle-gate"
            return super().intruder(own_slot)
        self.grant = None
        self._quiet_since = None
        return "planner: " + (grant.reason or grant.action)

    def _drop(self) -> None:
        if self.grant is not None and self.planner is not None:
            self.planner.release(self.grant)
        self.grant = None

    def close(self) -> None:
        self._drop()


class PriorityGate(IdleGate):
    """For a brain URL behind STAR's priority proxy: the proxy pauses night school's generation when the owner needs
    the slot and resumes it afterwards, so other clients are no reason to wait or to cancel. HOLD and the quiet lock
    still are. When the proxy does not answer /priority/v1/status (looked at once a minute), this is the idle gate."""

    def __init__(self, settings, watch: BrainWatch, *, recheck_s: float = 60.0, **kwargs):
        super().__init__(settings, watch, **kwargs)
        self._recheck_s, self._proxy_at, self._proxy = recheck_s, -1e18, False

    def proxied(self) -> bool:
        now = self._clock()
        if now - self._proxy_at >= self._recheck_s:
            self._proxy_at = now
            try:
                status = self.watch._fetch("/priority/v1/status")
                self._proxy = isinstance(status, dict) and "classes" in status
            except OSError:
                self._proxy = False
        return self._proxy

    def look(self) -> str:
        if Path(self.settings.hold_file).exists():
            return "HOLD file present, paused"
        if self.lock_held():
            return "quiet lock held, waiting"
        return "" if self.proxied() else super().look()

    def intruder(self, own_slot: int) -> str:
        if Path(self.settings.hold_file).exists():
            return "HOLD file"
        if self.lock_held():
            return "quiet lock"
        return "" if self.proxied() else super().intruder(own_slot)

    def close(self) -> None:
        return


def make_planner(settings, key: str):
    """The planner client for night school, or None when switched off (STAR_NS_PLANNER_URL=off) or not importable."""
    url = getattr(settings, "planner_url", "")
    if not url or url.lower() in ("off", "0", "none"):
        return None
    try:
        from star.planner_client import PlannerClient
    except ImportError:
        return None
    return PlannerClient(url, key=key, timeout=2.0, down_for=30.0)
