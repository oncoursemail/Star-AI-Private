"""Offline metric-ingestion and actual API-encoding checks; only temporary SQLite files are used."""
from __future__ import annotations

from contextlib import contextmanager
import json
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "metallic"))
from metallic.control.server import App  # noqa: E402
from metallic.control.store import Store  # noqa: E402

checks = 0


def check(condition, label):
    global checks
    assert condition, label
    checks += 1


@contextmanager
def opened(path=":memory:", now=10000):
    store = Store(path, clock=lambda: now)
    try:
        yield store
    finally:
        store.db.close()


def strict_wire(store, rng="hour", keys=None):
    app = object.__new__(App)  # Exercise the actual encoder without tokens, services or sockets.
    status, headers, body = app._json(200, store.series(store.keys() if keys is None else keys, rng))

    def invalid_constant(value):
        raise ValueError(f"nonstandard JSON number: {value}")

    payload = json.loads(body, parse_constant=invalid_constant)
    check(status == 200 and headers["Content-Type"] == "application/json", "actual API encoder contract retained")
    return payload["series"]


def main():
    rejected = {"plus_inf": math.inf, "minus_inf": -math.inf, "nan": math.nan,
                "true": True, "false": False, "overflow": 10 ** 1000,
                "negative_overflow": -(10 ** 1000), "text": "7", "missing": None}
    with opened() as store:
        store.add(9990, {**rejected, "zero": 0, "negative": -12.34567, "integer": 17, "large_finite": 1e300})
        check(store.keys() == ["integer", "large_finite", "negative", "zero"], "only real finite metrics create series")
        rows = strict_wire(store)
        check(rows["zero"] == [[9990, 0.0, 0.0, 0.0]], "zero is preserved rather than treated as missing")
        check(rows["negative"] == [[9990, -12.346, -12.346, -12.346]], "finite rounding unchanged")
        check(rows["integer"] == [[9990, 17.0, 17.0, 17.0]], "integer metrics remain supported")
        check(rows["large_finite"][0][1] == 1e300, "representable large finite values remain supported")
        check(not store.db.in_transaction, "mixed invalid input leaves no open transaction")
        for label, value in rejected.items():
            store.add(9990, {"integer": value})
            check(strict_wire(store)["integer"][0][1] == 17.0, f"invalid {label} cannot replace a real reading")
        store.add(9991, {"integer": 23.0})
        check([row[1] for row in strict_wire(store)["integer"]] == [17.0, 23.0], "valid next sample survives rejected inputs")

    with opened() as store:
        store.add(9990, rejected)
        check(store.keys() == [], "invalid-only sample creates no empty series")
        check(not store.db.in_transaction, "invalid-only sample opens no transaction")
        check(strict_wire(store, keys=["absent"]) == {"absent": []}, "unknown series remains an honest empty state")

    with TemporaryDirectory() as temporary:
        path = Path(temporary) / "metrics.sqlite3"
        with opened(path) as store:
            store.add(9901, {"finite": 12.25})
            with store.lock:
                sid = store._sid("legacy_inf")
                store.db.execute("INSERT INTO raw VALUES (?, ?, ?)", (sid, 9902, math.inf))
                store.db.execute("INSERT INTO m1 VALUES (?, ?, ?, ?, ?)", (sid, 9840, -math.inf, -math.inf, -math.inf))
                store.db.execute("INSERT INTO m10 VALUES (?, ?, ?, ?, ?)", (sid, 9600, math.inf, math.inf, math.inf))
            before = store.db.execute("SELECT count(*) FROM raw").fetchone()[0]
            for rng in ("hour", "day", "week"):
                rows = strict_wire(store, rng)
                check(rows["legacy_inf"][0][1:] == [None, None, None], f"legacy {rng} nonfinite fields become JSON null")
            check(store.db.execute("SELECT count(*) FROM raw").fetchone()[0] == before, "read sanitization deletes no history")
            check(math.isinf(store.db.execute("SELECT v FROM raw WHERE sid = ?", (sid,)).fetchone()[0]),
                  "legacy stored value remains intact for inspection")
        with opened(path) as reopened:
            check(strict_wire(reopened)["finite"] == [[9901, 12.25, 12.25, 12.25]], "finite history survives restart")
            check(strict_wire(reopened)["legacy_inf"][0][1:] == [None, None, None], "legacy protection survives restart")
            reopened.add(9990, {"legacy_inf": 9.75, "fresh_invalid": math.inf})
            rows = strict_wire(reopened)
            check(rows["legacy_inf"][-1][1] == 9.75 and "fresh_invalid" not in rows, "real readings recover after restart")

    with opened(now=7801) as store:
        store.add(7201, {"finite": 2, "overflowing_average": 1e308})
        store.add(7202, {"finite": 4, "overflowing_average": 1e308})
        store.add(7203, {"finite": math.inf})
        store.rollup()
        for rng in ("day", "week"):
            rows = strict_wire(store, rng)
            check(rows["finite"] == [[7200, 3.0, 2.0, 4.0]], f"finite {rng} aggregates unchanged")
            check(rows["overflowing_average"][0][1] is None, f"arithmetic overflow in {rng} average cannot break JSON")
            check(rows["overflowing_average"][0][2:] == [1e308, 1e308], "finite aggregate extrema remain real values")
        check(store.db.execute("SELECT count(*) FROM raw").fetchone()[0] == 4, "invalid samples never enter rollups")
    print(f"{checks} Metallic metric checks passed; no endpoints, native actions, accounts or persistent user state accessed.")


if __name__ == "__main__":
    main()
