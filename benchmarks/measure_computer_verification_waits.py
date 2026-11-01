"""Compare verification waits using the real Driver and deterministic fake time.

Run from any directory:
    python benchmarks/measure_computer_verification_waits.py

Stdlib-only, offline, no native desktop or model access. The script executes
Driver.run with an in-memory application and injected clock. All reported time
is SIMULATED. Observation costs are explicit hypothetical inputs, not measured
UI Automation, screenshot, network, inference, or Windows performance.

The same persistent postconditions, dispatches, retry budget, and application
readiness schedule are used for fixed-wait and polling variants. The script
reports the observation cost as well as saved sleep, including the existing
extended settling phase. It is a developer experiment, not a promotion gate or
a claim of end-to-end production speedup.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from star.computer import identity, settings  # noqa: E402
from star.computer.driver import Driver, Expect, Step  # noqa: E402
from star.computer.limits import RateLimits  # noqa: E402
from star.computer.screen import Element, Screen  # noqa: E402


class SimulatedClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleep_s = 0.0
        self.observation_s = 0.0
        self.sleep_calls = 0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise AssertionError("negative simulated sleep")
        self.sleep_calls += 1
        self.sleep_s += seconds
        self.now += seconds

    def observe_for(self, seconds: float) -> None:
        self.observation_s += seconds
        self.now += seconds


class MemoryLog:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def shot(self, image, label: str) -> str:
        if image is not None:
            raise AssertionError("the simulation must not capture images")
        return ""

    def step(self, **record) -> None:
        self.records.append(record)


class SimulatedApplication:
    """A refresh operation is dispatched once and changes Busy to persistent Ready.

    Readiness uses time since dispatch. A missing readiness time means the
    application never becomes ready. Observation delay is charged before the
    returned snapshot, so it can affect when readiness is observed.
    """

    def __init__(self, clock: SimulatedClock, case: dict, observation_cost_s: float) -> None:
        self.clock = clock
        self.case = case
        self.observation_cost_s = observation_cost_s
        self.cfg = {"settle_s": 0.5}
        self.eye = None
        self.dispatches: list[dict] = []
        self.observations: list[dict] = []
        self.focus_calls: list[int] = []
        self.hands = SimpleNamespace(key=self.dispatch, _stopped=lambda: False)
        self.windows = SimpleNamespace(windows=lambda: [], focus=self.focus)

    def sleep(self, seconds: float) -> None:
        self.clock.sleep(seconds)

    def dispatch(self, keys: str) -> None:
        self.dispatches.append({"operation": "refresh", "keys": keys, "at_s": self.clock()})

    def focus(self, hwnd: int) -> bool:
        self.focus_calls.append(hwnd)
        return True

    def ready(self) -> bool:
        if self.case.get("preexisting", False):
            return True
        delay = self.case["ready_after_dispatch_s"]
        return bool(self.dispatches and delay is not None
                    and self.clock() - self.dispatches[0]["at_s"] >= delay)

    def see(self) -> Screen:
        self.clock.observe_for(self.observation_cost_s)
        is_ready = self.ready()
        if is_ready:
            label = "Ready"
        elif self.dispatches or self.case["predicate"] in ("negative", "mixed"):
            label = "Busy"
        else:
            label = "Idle"
        self.observations.append({"at_s": self.clock(), "ready": is_ready, "label": label})
        return Screen(
            [Element(1, label, "text", (20, 20, 160, 60))],
            window="Verification fixture", process="fixture.exe", hwnd=1,
            size=(640, 480), taken=self.clock(),
        )

    def ask_owner(self, *args) -> None:
        raise AssertionError("this harmless fixture should never request a gated action")


class PhaseRecordingDriver(Driver):
    """Record real verification phases without changing their implementation."""

    def __init__(self, *args, **kwargs) -> None:
        self.phases: list[dict] = []
        super().__init__(*args, **kwargs)

    def _verify_after(self, step, before, el, delay_s):
        start = self.clock()
        sleeps_before = self.c.clock.sleep_s
        observations_before = len(self.c.observations)
        after, ok, why = super()._verify_after(step, before, el, delay_s)
        self.phases.append({
            "scheduled_wait_budget_s": rounded(delay_s),
            "simulated_elapsed_s": rounded(self.clock() - start),
            "simulated_sleep_s": rounded(self.c.clock.sleep_s - sleeps_before),
            "observation_count": len(self.c.observations) - observations_before,
            "postcondition_met": ok,
        })
        return after, ok, why


def rounded(value: float) -> float:
    return round(value, 9)


def expectation(case: dict) -> Expect:
    if case["predicate"] == "negative":
        return Expect(gone="Busy")
    if case["predicate"] == "mixed":
        return Expect(text="Ready", gone="Busy")
    if case["predicate"] == "generic":
        return Expect()
    return Expect(text="Ready")


def run_variant(case: dict, observation_cost_s: float, poll_s: float | None) -> dict:
    clock = SimulatedClock()
    app = SimulatedApplication(clock, case, observation_cost_s)
    log = MemoryLog()
    with tempfile.TemporaryDirectory(prefix="litha-verification-simulation-") as directory:
        home = Path(directory)
        fixture_guid = "deterministic-offline-fixture-not-a-real-machine"
        identity.enroll(home, lambda: fixture_guid)
        driver = PhaseRecordingDriver(
            app, home=home, read_guid=lambda: fixture_guid,
            log=log, limits=RateLimits(clock=clock),
            switch=SimpleNamespace(is_set=lambda: False),
            verification_poll_s=poll_s,
        )
        result = driver.run(Step("key", keys="F8", expect=expectation(case), retries=0))
    if len(app.dispatches) != 1:
        raise AssertionError(f"{case['id']}: expected one simulated operation, got {len(app.dispatches)}")
    if not driver.phases or any(p["observation_count"] > 32 for p in driver.phases):
        raise AssertionError(f"{case['id']}: invalid verification observation bound")
    return {
        "verification_poll_s": driver.verification_poll_s,
        "ok": result.ok,
        "outcome_uncertain": result.outcome_uncertain,
        "attempts": result.attempts,
        "final_ready": app.ready(),
        "dispatch_count": len(app.dispatches),
        "dispatch_operations": [{"operation": d["operation"], "keys": d["keys"]} for d in app.dispatches],
        "focus_calls": app.focus_calls,
        "total_observation_count": len(app.observations),
        "verification_observation_count": sum(p["observation_count"] for p in driver.phases),
        "simulated_total_elapsed_s": rounded(clock()),
        "simulated_after_dispatch_elapsed_s": rounded(clock() - app.dispatches[0]["at_s"]),
        "simulated_sleep_s": rounded(clock.sleep_s),
        "simulated_observation_s": rounded(clock.observation_s),
        "phases": driver.phases,
        "observation_times_s": [rounded(o["at_s"]) for o in app.observations],
    }


CASES = [
    {"id": "ready_immediately", "predicate": "positive", "ready_after_dispatch_s": 0.0},
    {"id": "ready_070ms", "predicate": "positive", "ready_after_dispatch_s": 0.07},
    {"id": "ready_230ms", "predicate": "positive", "ready_after_dispatch_s": 0.23},
    {"id": "ready_490ms", "predicate": "positive", "ready_after_dispatch_s": 0.49},
    {"id": "ready_750ms_extended_phase", "predicate": "positive", "ready_after_dispatch_s": 0.75},
    {"id": "ready_2100ms_sample_cap", "predicate": "positive", "ready_after_dispatch_s": 2.1},
    {"id": "never_ready", "predicate": "positive", "ready_after_dispatch_s": None},
    {"id": "preexisting_positive", "predicate": "positive", "ready_after_dispatch_s": 0.0,
     "preexisting": True},
    {"id": "negative_predicate", "predicate": "negative", "ready_after_dispatch_s": 0.07},
    {"id": "mixed_positive_and_negative", "predicate": "mixed", "ready_after_dispatch_s": 0.07},
    {"id": "generic_visible_change", "predicate": "generic", "ready_after_dispatch_s": None},
]


def run_experiment() -> dict:
    source = ROOT / "star" / "computer" / "driver.py"
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    comparisons = []
    equivalent_fields = ("ok", "outcome_uncertain", "attempts", "final_ready", "dispatch_count",
                         "dispatch_operations", "focus_calls")
    for observation_cost_s in (0.0, 0.02, 0.1):
        for case in CASES:
            fixed = run_variant(case, observation_cost_s, None)
            polling = run_variant(case, observation_cost_s, 0.05)
            equivalent = all(fixed[k] == polling[k] for k in equivalent_fields)
            if not equivalent:
                raise AssertionError(f"non-equivalent simulated outcomes: {case['id']} at {observation_cost_s}")
            comparisons.append({
                "case": case,
                "hypothetical_observation_cost_s": observation_cost_s,
                "outcomes_and_effects_match": equivalent,
                "fixed": fixed,
                "polling": polling,
                "simulated_elapsed_reduction_s": rounded(
                    fixed["simulated_total_elapsed_s"] - polling["simulated_total_elapsed_s"]),
                "additional_observations": polling["total_observation_count"] - fixed["total_observation_count"],
            })
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
        raise RuntimeError("driver.py changed during the experiment; rerun against a stable source")
    default_poll = settings.DEFAULTS.get("verification_poll_s")
    return {
        "schema_version": 1,
        "experiment": "deterministic_driver_verification_wait_simulation",
        "time_basis": "SIMULATED; no wall-clock/native performance was measured",
        "driver_sha256": source_hash,
        "configuration": {
            "repository_default_settle_s": settings.DEFAULTS.get("settle_s"),
            "repository_default_verification_poll_s": default_poll,
            "repository_polling_default_off": default_poll == 0.0,
            "driver_fallback_default_off": all(c["fixed"]["verification_poll_s"] == 0.0
                                               for c in comparisons),
            "experiment_settle_s": 0.5,
            "experiment_poll_s": 0.05,
            "experiment_retries": 0,
        },
        "assumptions": [
            "Ready is persistent after the scripted readiness time; transient predicates are outside this experiment.",
            "Action dispatch has zero simulated duration and causes one identical in-memory refresh operation.",
            "Observation costs 0, 0.02, or 0.1 seconds are hypothetical inputs, not hardware measurements.",
            "The initial observation and both possible settling phases are included in reported elapsed time.",
            "The production deadline bounds waits; it cannot cancel a blocking native observation call.",
            "Preexisting, negative, mixed positive/negative, and generic predicates retain fixed-wait behavior.",
            "No model calls, screenshots, UI Automation calls, network, or native input are executed.",
        ],
        "comparison_count": len(comparisons),
        "driver_run_count": 2 * len(comparisons),
        "all_outcomes_and_effects_match": all(c["outcomes_and_effects_match"] for c in comparisons),
        "comparisons": comparisons,
    }


if __name__ == "__main__":
    print(json.dumps(run_experiment(), indent=2, sort_keys=True, allow_nan=False))
