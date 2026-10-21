"""Metallic Control's SQLite store: tiers, rollups, retention, request speed history, audit log."""
from __future__ import annotations

from metallic.control.store import Store


class Clock:
    def __init__(self, t: float):
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_hour_reads_raw_and_day_reads_minute_rollups_including_the_current_minute():
    clock = Clock(1_000_000_040.0)                      # 20 s into a minute
    store = Store(":memory:", clock=clock)
    base = 1_000_000_040 - 20 - 120                     # two full minutes back
    for i in range(0, 140, 5):                          # every 5 s up to now
        store.add(base + i, {"brain1.cpu": float(i), "brain1.mem_pct": 50.0})
    store.rollup()
    hour = store.series(["brain1.cpu", "missing"], "hour")
    assert hour["step"] == 5 and len(hour["series"]["brain1.cpu"]) == 28 and hour["series"]["missing"] == []
    day = store.series(["brain1.cpu"], "day")["series"]["brain1.cpu"]
    assert [row[0] % 60 for row in day] == [0, 0, 0]    # two finished minutes + the current one from raw
    first = day[0]
    assert first[1] == sum(range(0, 60, 5)) / 12 and first[2] == 0 and first[3] == 55
    assert day[-1][2] == 120 and day[-1][3] == 135      # current minute: min/max of its raw samples


def test_ten_minute_rollup_and_retention():
    clock = Clock(2_000_000_000.0 - 2_000_000_000 % 600)
    store = Store(":memory:", clock=clock)
    start = clock.t - 1200
    for i in range(0, 1200, 10):
        store.add(start + i, {"pc.gpu_util": 10.0 if i < 600 else 30.0})
    store.rollup()
    week = store.series(["pc.gpu_util"], "week")["series"]["pc.gpu_util"]
    assert [round(r[1]) for r in week] == [10, 30]
    clock.t += 4 * 3600                                 # raw older than 3 h is dropped, minute rollups stay
    store.rollup()
    assert store.series(["pc.gpu_util"], "hour")["series"]["pc.gpu_util"] == []
    assert len(store.series(["pc.gpu_util"], "day")["series"]["pc.gpu_util"]) == 20
    clock.t += 9 * 86400                                # and everything older than 8 days goes
    store.rollup()
    assert store.series(["pc.gpu_util"], "week")["series"]["pc.gpu_util"] == []


def test_non_numbers_are_not_stored():
    store = Store(":memory:", clock=Clock(100.0))
    store.add(100, {"a": None, "b": float("nan"), "c": "7", "d": 3})
    assert store.keys() == ["d"]


def test_speed_history_medians_per_hour_and_model():
    clock = Clock(10 * 3600 + 30.0)
    store = Store(":memory:", clock=clock)
    rows = [{"t": 10 * 3600 + i, "model": "star-fast", "slot": 1, "prompt_ms": 1000.0 * (i + 1), "prompt_tokens": 100,
             "eval_ms": 1000.0, "eval_tokens": 8 + i} for i in range(3)]
    store.add_requests("brain1", rows)
    hist = store.speed_history(1)
    assert hist == [{"t": 36000, "machine": "brain1", "model": "star-fast", "n": 3, "tps_median": 9.0,
                     "prompt_ms_median": 2000.0}]
    assert [r["eval_tokens"] for r in store.requests(0)] == [10, 9, 8]


def test_audit_entries_record_start_and_finish(tmp_path):
    clock = Clock(500.0)
    store = Store(tmp_path / "c.sqlite3", clock=clock)
    entry = store.audit_start("brain1/ns-pause", "Pause night school (Brain 1)", "brain1", "owner ab12cd", "192.0.2.5")
    clock.t = 503.0
    store.audit_finish(entry, "ok", 0, "night school paused (HOLD file)")
    row = store.audit()[0]
    assert row["state"] == "ok" and row["finished"] == 503.0 and row["actor"] == "owner ab12cd"
    reopened = Store(tmp_path / "c.sqlite3", clock=clock)       # persists across restarts
    assert reopened.audit()[0]["id"] == entry
