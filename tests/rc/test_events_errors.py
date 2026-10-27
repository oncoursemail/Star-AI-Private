import json
import threading

import pytest

from launcher.rc.errors import ACTIONS, CATALOG, Cancelled, RcError, from_rc
from launcher.rc.events import EventBus, TaskManager


def test_every_catalog_action_has_a_label_and_no_code_is_silent():
    for code, (title, message, actions) in CATALOG.items():
        assert title and message, code
        for a in actions:
            assert a in ACTIONS, (code, a)


def test_error_to_dict_is_json_and_carries_actions():
    err = RcError("files_changed", detail="x")
    d = json.loads(json.dumps(err.to_dict()))
    assert d["code"] == "files_changed" and d["detail"] == "x"
    assert [a["id"] for a in d["actions"]] == ["rebaseline", "locate_client", "view_log"]
    assert all(a["label"] for a in d["actions"])


def test_error_is_hashable_and_raisable():
    with pytest.raises(RcError) as info:
        raise RcError("tools_missing")
    assert {info.value}  # eq=False keeps exceptions hashable for the traceback machinery
    assert isinstance(Cancelled(), RcError)


def test_from_rc_maps_known_codes_and_keeps_rc_words_for_unknown():
    assert from_rc("verification_failed", "A file changed").code == "files_changed"
    other = from_rc("catalog_busy", "Another process is updating the catalog. Retry after it finishes.")
    assert other.code == "rc_error" and "Retry after it finishes" in other.message


def run_task(tm, job, **kw):
    snap = tm.start("t", "Title", [("a", "A"), ("b", "B"), ("c", "C")], job, **kw)
    return tm.wait(snap["id"])


def test_task_stages_progress_and_events():
    bus, events = EventBus(), []
    bus.subscribe(events.append)
    tm = TaskManager(bus, spawn=lambda fn: fn())

    def job(rep):
        rep.stage("a", "first")
        rep.progress(0.5, "half")
        rep.stage("c", "third")
        return {"ok": 1}
    done = run_task(tm, job)
    assert done["state"] == "done" and done["result"] == {"ok": 1} and done["fraction"] == 1.0
    assert [s["state"] for s in done["stages"]] == ["done", "done", "done"]  # b was passed over: done, not left pending
    states = [e["task"]["state"] for e in events]
    assert states[0] == "queued" and states[-1] == "done"
    mid = [e["task"] for e in events if e["task"]["fraction"] == 0.5]
    assert mid and mid[0]["stages"][0]["state"] == "active"


def test_task_failure_marks_active_stage_failed_and_keeps_the_error_readable():
    tm = TaskManager(EventBus(), spawn=lambda fn: fn())

    def job(rep):
        rep.stage("b")
        raise RcError("hash_mismatch", detail="d")
    done = run_task(tm, job)
    assert done["state"] == "failed" and done["error"]["code"] == "hash_mismatch"
    assert [s["state"] for s in done["stages"]] == ["done", "failed", "pending"]


def test_unexpected_exception_becomes_a_plain_failure():
    tm = TaskManager(EventBus(), spawn=lambda fn: fn())

    def job(rep):
        raise ZeroDivisionError("boom")
    done = run_task(tm, job)
    assert done["state"] == "failed" and done["error"]["code"] == "rc_error"
    assert "ZeroDivisionError" in done["error"]["detail"]


def test_cancel_stops_at_the_next_checkpoint():
    tm = TaskManager(EventBus())
    started, release = threading.Event(), threading.Event()

    def job(rep):
        rep.stage("a")
        started.set()
        release.wait(5)
        rep.progress(0.1)  # checkpoint: raises Cancelled
        return {}
    snap = tm.start("t", "T", [("a", "A")], job)
    assert started.wait(5)
    assert tm.cancel(snap["id"]) is True
    release.set()
    done = tm.wait(snap["id"])
    assert done["state"] == "cancelled" and done["error"]["code"] == "cancelled"
    assert done["stages"][0]["state"] == "skipped"


def test_same_kind_or_excluded_kind_cannot_run_twice():
    tm = TaskManager(EventBus())
    gate = threading.Event()
    first = tm.start("tools", "T", [("a", "A")], lambda rep: gate.wait(5) and {})
    with pytest.raises(RcError) as e:
        tm.start("tools", "T2", [("a", "A")], lambda rep: {})
    assert e.value.code == "busy"
    with pytest.raises(RcError):
        tm.start("launch", "L", [("a", "A")], lambda rep: {}, exclusive=("tools",))
    tm.start("backend", "B", [("a", "A")], lambda rep: {})  # unrelated kinds run alongside
    gate.set()
    tm.wait(first["id"])


def test_broken_listener_does_not_break_the_task():
    bus = EventBus()
    bus.subscribe(lambda e: 1 / 0)
    tm = TaskManager(bus, spawn=lambda fn: fn())
    assert run_task(tm, lambda rep: {})["state"] == "done"
