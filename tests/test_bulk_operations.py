"""Failure and concurrency contracts for the opt-in bulk-operation ledger.

These tests use synthetic adapters and disposable databases. The crash test
actually terminates a child process after a visible effect, before a receipt
can be committed; none of the tests contacts a brain or changes a real project.
"""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading

import pytest

from star.bulk_operations import (
    BulkAdapter,
    BulkConflictError,
    BulkNotFoundError,
    BulkOperationEngine,
    BulkValidationError,
    OperationCancelled,
    OperationFailed,
    OperationPartial,
    OutcomeUnknown,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def make_engine(tmp_path, run, *, targets=("a", "b", "c", "d"), mutating=True, **options):
    return BulkOperationEngine(tmp_path / "bulk.sqlite3", {
        "edit": BulkAdapter(run, lambda: targets, mutating=mutating),
    }, **options)


def prepare(engine, targets=("a", "b"), *, key="intent-1", payload=None, **options):
    return engine.submit("edit", list(targets), payload if payload is not None else {"text": "example"},
                         idempotency_key=key, **options)


def statuses(batch):
    return {operation["target_id"]: operation["status"] for operation in batch["operations"]}


@pytest.mark.parametrize("targets", [[], "a", ["a", "unknown"], ["*"], ["all"], [""]])
def test_selection_fails_closed_before_any_callback(tmp_path, targets):
    calls = []
    with make_engine(tmp_path, lambda context: calls.append(context.target_id)) as engine:
        with pytest.raises(BulkValidationError):
            engine.submit("edit", targets, {}, idempotency_key="bad")
        assert calls == []
        assert engine.list_batches() == []


def test_unknown_action_is_not_an_arbitrary_command(tmp_path):
    with make_engine(tmp_path, lambda context: None) as engine:
        with pytest.raises(BulkValidationError, match="Unknown bulk action"):
            engine.submit("shell", ["a"], {"command": "anything"}, idempotency_key="bad")


def test_deduplicated_intent_and_payload_are_independent_snapshots(tmp_path):
    seen = []

    def edit(context):
        seen.append((context.target_id, context.payload["nested"]["text"]))
        context.payload["nested"]["text"] = "changed inside callback"
        return {"target": context.target_id}

    payload = {"nested": {"text": "original"}}
    with make_engine(tmp_path, edit) as engine:
        batch = prepare(engine, ["a", "a", "b"], payload=payload, concurrency=1)
        assert batch["status"] == "prepared"
        assert batch["targets"] == ["a", "b"]
        assert seen == []
        ids = [operation["operation_id"] for operation in batch["operations"]]
        assert len(set(ids)) == 2
        payload["nested"]["text"] = "changed by caller"
        engine.get_payload(batch["batch_id"])["nested"]["text"] = "changed by preview"
        batch["targets"].append("unknown")
        result = engine.run_batch(batch["batch_id"], expected_intent_sha256=batch["intent_sha256"])
        assert result["status"] == "succeeded"
        assert seen == [("a", "original"), ("b", "original")]
        assert [operation["operation_id"] for operation in result["operations"]] == ids
        assert "payload" not in result and "payload_json" not in result
        assert "operations" not in engine.list_batches()[0]


def test_idempotency_matches_canonical_intent_and_rejects_changed_scope(tmp_path):
    calls = []
    with make_engine(tmp_path, lambda context: calls.append(context.operation_id)) as engine:
        first = prepare(engine, payload={"x": 1, "y": 2})
        same = prepare(engine, ["a", "a", "b"], payload={"y": 2, "x": 1})
        assert same["batch_id"] == first["batch_id"]
        with pytest.raises(BulkConflictError):
            prepare(engine, ["b", "a"], payload={"x": 1, "y": 2})
        with pytest.raises(BulkConflictError):
            prepare(engine, payload={"x": 9, "y": 2})
        engine.run_batch(first["batch_id"])
        engine.run_batch(first["batch_id"])
        assert len(calls) == 2
        assert len(engine.list_batches()) == 1


def test_simultaneous_submitters_share_one_durable_idempotent_batch(tmp_path):
    with make_engine(tmp_path, lambda context: None) as engine:
        with ThreadPoolExecutor(max_workers=8) as callers:
            batches = list(callers.map(lambda _: prepare(engine), range(20)))
        assert len({batch["batch_id"] for batch in batches}) == 1
        assert len(engine.list_batches()) == 1


def test_wrong_preview_digest_leaves_prepared_batch_unexecuted(tmp_path):
    calls = []
    with make_engine(tmp_path, lambda context: calls.append(context.target_id)) as engine:
        batch = prepare(engine)
        with pytest.raises(BulkConflictError, match="digest"):
            engine.run_batch(batch["batch_id"], expected_intent_sha256="0" * 64)
        assert engine.get_batch(batch["batch_id"])["status"] == "prepared"
        assert calls == []


def test_explicit_target_catalog_is_revalidated_at_run(tmp_path):
    catalog = ["a", "b"]
    calls = []
    with make_engine(tmp_path, lambda context: calls.append(context.target_id), targets=catalog) as engine:
        batch = prepare(engine)
        catalog.remove("b")
        result = engine.run_batch(batch["batch_id"])
        assert result["status"] == "failed"
        assert statuses(result) == {"a": "skipped", "b": "conflict"}
        assert calls == []


def test_changed_adapter_version_cannot_execute_old_preview(tmp_path):
    with make_engine(tmp_path, lambda context: None) as engine:
        batch = prepare(engine)
    with BulkOperationEngine(tmp_path / "bulk.sqlite3", {
        "edit": BulkAdapter(lambda context: pytest.fail("old preview executed"), lambda: ["a", "b"], version="2"),
    }) as reopened:
        with pytest.raises(BulkConflictError, match="version"):
            reopened.run_batch(batch["batch_id"])


def test_canary_finishes_before_any_wider_target_begins(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def edit(context):
        calls.append(context.target_id)
        if context.target_id == "a":
            entered.set()
            assert release.wait(5)
        return "done"

    with make_engine(tmp_path, edit) as engine:
        batch = prepare(engine, ["a", "b", "c", "d"], canary_size=1, concurrency=4)
        with ThreadPoolExecutor(max_workers=1) as coordinator:
            future = coordinator.submit(engine.run_batch, batch["batch_id"])
            try:
                assert entered.wait(3)
                assert calls == ["a"]
                assert statuses(engine.get_batch(batch["batch_id"])) == {
                    "a": "running", "b": "pending", "c": "pending", "d": "pending",
                }
            finally:
                release.set()
            assert future.result(timeout=5)["status"] == "succeeded"
        assert set(calls) == {"a", "b", "c", "d"}


def test_failed_canary_blocks_expansion_even_below_failure_cutoff(tmp_path):
    calls = []

    def edit(context):
        calls.append(context.target_id)
        raise OperationFailed("Nothing was changed")

    with make_engine(tmp_path, edit) as engine:
        batch = prepare(engine, failure_cutoff=3)
        result = engine.run_batch(batch["batch_id"])
        assert calls == ["a"]
        assert statuses(result) == {"a": "failed", "b": "skipped"}


def test_failure_cutoff_stops_new_dispatch_after_successful_canary(tmp_path):
    calls = []

    def edit(context):
        calls.append(context.target_id)
        if context.target_id == "b":
            raise OperationFailed("Known failure before editing")
        return "done"

    with make_engine(tmp_path, edit) as engine:
        batch = prepare(engine, ["a", "b", "c", "d"], concurrency=1)
        result = engine.run_batch(batch["batch_id"])
        assert calls == ["a", "b"]
        assert statuses(result) == {"a": "succeeded", "b": "failed", "c": "skipped", "d": "skipped"}
        assert result["status"] == "partial"
        assert result["stop_reason"] == "failure_cutoff"


def test_unknown_outcome_stops_dispatch_without_waiting_for_failure_cutoff(tmp_path):
    calls = []

    def edit(context):
        calls.append(context.target_id)
        if context.target_id == "b":
            raise OutcomeUnknown("Connection closed after acceptance")
        return "done"

    with make_engine(tmp_path, edit) as engine:
        batch = prepare(engine, ["a", "b", "c"], concurrency=1, failure_cutoff=3)
        result = engine.run_batch(batch["batch_id"])
        assert result["status"] == "outcome_unknown"
        assert calls == ["a", "b"]
        assert statuses(result)["c"] == "skipped"
        engine.run_batch(batch["batch_id"])
        assert calls == ["a", "b"]


@pytest.mark.parametrize("error_type,expected", [
    (OperationFailed, "failed"),
    (OperationPartial, "partial"),
    (OperationCancelled, "cancelled"),
    (BulkConflictError, "conflict"),
    (OutcomeUnknown, "outcome_unknown"),
])
def test_non_success_outcomes_keep_verified_receipts_after_restart(tmp_path, error_type, expected):
    receipt = {"files": [{"path": "note.txt", "before_sha256": "a" * 64, "after_sha256": "b" * 64}],
               "pending": ["other.txt"]}

    def edit(context):
        raise error_type("Safe adapter explanation", result=receipt)

    with make_engine(tmp_path, edit) as engine:
        batch = prepare(engine)
        result = engine.run_batch(batch["batch_id"])
        first, second = result["operations"]
        assert first["status"] == expected
        assert first["result"] == receipt
        assert first["error"] == "Safe adapter explanation"
        assert second["status"] == "skipped"
        if expected == "partial":
            assert result["status"] == "partial"
    with make_engine(tmp_path, lambda context: pytest.fail("terminal operation replayed")) as reopened:
        restored = reopened.run_batch(batch["batch_id"])
        assert restored["operations"][0]["result"] == receipt
        assert restored["operations"][0]["status"] == expected


@pytest.mark.parametrize("error_type,failure_cutoff,expected_status,reason", [
    (OutcomeUnknown, 3, "outcome_unknown", "outcome_requires_review"),
    (OperationFailed, 1, "failed", "failure_cutoff"),
    (OperationPartial, 1, "partial", "failure_cutoff"),
])
def test_accepted_callback_in_shared_queue_rechecks_failure_gate(
        tmp_path, error_type, failure_cutoff, expected_status, reason):
    blocker_entered = threading.Event()
    failure_entered = threading.Event()
    release_blocker = threading.Event()
    release_failure = threading.Event()
    calls = []

    def edit(context):
        calls.append(context.target_id)
        if context.target_id == "a":
            blocker_entered.set()
            assert release_blocker.wait(5)
            return "blocker completed"
        if context.target_id == "b":
            failure_entered.set()
            assert release_failure.wait(5)
            raise error_type("Conclusive failure boundary")
        pytest.fail("An accepted callback started after the batch failure gate closed")

    with make_engine(tmp_path, edit, max_workers=2) as engine:
        blocker = prepare(engine, ["a"], key="occupy-one-worker")
        victim = prepare(engine, ["b", "c"], key="queued-victim", canary_size=2,
                         failure_cutoff=failure_cutoff, concurrency=2)
        with ThreadPoolExecutor(max_workers=2) as coordinators:
            blocker_future = coordinators.submit(engine.run_batch, blocker["batch_id"])
            try:
                assert blocker_entered.wait(3)
                victim_future = coordinators.submit(engine.run_batch, victim["batch_id"])
                assert failure_entered.wait(3)
                assert statuses(engine.get_batch(victim["batch_id"])) == {"b": "running", "c": "accepted"}
                release_failure.set()
                result = victim_future.result(timeout=3)
                assert statuses(result) == {"b": expected_status, "c": "skipped"}
                assert result["operations"][1]["error_code"] == reason
                assert "c" not in calls
            finally:
                release_failure.set()
                release_blocker.set()
            assert blocker_future.result(timeout=3)["status"] == "succeeded"


def test_unexpected_exception_messages_do_not_leak_into_public_status(tmp_path):
    def edit(context):
        raise RuntimeError("Provider failure at https://user:private-token@example.test/private-request")

    with make_engine(tmp_path, edit) as engine:
        result = engine.run_batch(prepare(engine, ["a"])["batch_id"])
        operation = result["operations"][0]
        assert operation["status"] == "outcome_unknown"
        assert operation["error_code"] == "adapter_exception"
        assert "private-token" not in str(result)
        assert "unexpected exception" in operation["error"]


@pytest.mark.parametrize("mutating,error,expected", [
    (True, RuntimeError("possibly after effect"), "outcome_unknown"),
    (False, RuntimeError("read failed"), "failed"),
    (False, OutcomeUnknown("provider accepted request"), "outcome_unknown"),
    (True, OperationFailed("known no-effect failure"), "failed"),
    (True, BulkConflictError("preview no longer matches"), "conflict"),
    (True, OperationCancelled("confirmed not applied"), "cancelled"),
    (True, SystemExit("abandoned callback"), "outcome_unknown"),
])
def test_adapter_failures_preserve_their_evidence_boundary(tmp_path, mutating, error, expected):
    def edit(context):
        raise error

    with make_engine(tmp_path, edit, mutating=mutating) as engine:
        result = engine.run_batch(prepare(engine, ["a"])["batch_id"])
        assert result["operations"][0]["status"] == expected


def test_combined_batches_share_one_bounded_executor(tmp_path):
    lock = threading.Lock()
    ready = threading.Event()
    release = threading.Event()
    active = 0
    peak = 0

    def edit(context):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 2:
                ready.set()
        try:
            assert release.wait(5)
            return context.target_id
        finally:
            with lock:
                active -= 1

    with make_engine(tmp_path, edit, max_workers=2) as engine:
        batches = [prepare(engine, ["a", "b"], key=f"key-{index}", canary_size=2, concurrency=2)
                   for index in range(2)]
        with ThreadPoolExecutor(max_workers=2) as coordinators:
            futures = [coordinators.submit(engine.run_batch, batch["batch_id"]) for batch in batches]
            try:
                assert ready.wait(3)
            finally:
                release.set()
            assert all(future.result(timeout=5)["status"] == "succeeded" for future in futures)
        assert peak == 2


def test_cancellation_is_per_batch_and_does_not_erase_completed_mutations(tmp_path):
    started = {"A": threading.Event(), "B": threading.Event()}
    release = threading.Event()
    contexts = {}
    calls = []

    def edit(context):
        name = context.payload["name"]
        calls.append((name, context.target_id))
        if context.target_id == "a":
            contexts[name] = context
            started[name].set()
            assert release.wait(5)
        # This synthetic adapter has completed an effect even if a request to
        # cancel arrived during it. A successful result must remain successful.
        return {"applied": True}

    with make_engine(tmp_path, edit, max_workers=2) as engine:
        a = prepare(engine, key="A", payload={"name": "A"}, concurrency=1)
        b = prepare(engine, key="B", payload={"name": "B"}, concurrency=1)
        with ThreadPoolExecutor(max_workers=2) as coordinators:
            fa = coordinators.submit(engine.run_batch, a["batch_id"])
            fb = coordinators.submit(engine.run_batch, b["batch_id"])
            try:
                assert started["A"].wait(3) and started["B"].wait(3)
                engine.cancel_batch(a["batch_id"])
                assert contexts["A"].cancel_event.is_set()
                assert not contexts["B"].cancel_event.is_set()
                assert contexts["A"].cancel_event is not contexts["B"].cancel_event
                with pytest.raises(BulkConflictError, match="active coordinator"):
                    engine.run_batch(a["batch_id"])
                with pytest.raises(BulkConflictError, match="before closing"):
                    engine.close()
                with pytest.raises(BulkConflictError, match="live owner"):
                    make_engine(tmp_path, edit)
            finally:
                release.set()
            ra, rb = fa.result(timeout=5), fb.result(timeout=5)
        assert ra["status"] == "partial" and ra["cancellation_requested"]
        assert statuses(ra) == {"a": "succeeded", "b": "cancelled"}
        assert ra["operations"][0]["result"] == {"applied": True}
        assert rb["status"] == "succeeded" and not rb["cancellation_requested"]
        assert ("A", "b") not in calls and ("B", "b") in calls


def test_cancel_prepared_batch_survives_restart_and_never_dispatches(tmp_path):
    calls = []
    with make_engine(tmp_path, lambda context: calls.append(context.target_id)) as engine:
        batch = prepare(engine)
        cancelled = engine.cancel_batch(batch["batch_id"])
        assert cancelled["status"] == "cancelled"
    with make_engine(tmp_path, lambda context: calls.append(context.target_id)) as reopened:
        assert reopened.list_batches()[0]["cancellation_requested"]
        assert reopened.run_batch(batch["batch_id"])["status"] == "cancelled"
        assert calls == []


def test_prepared_status_and_private_payload_survive_restart_without_execution(tmp_path):
    calls = []
    with make_engine(tmp_path, lambda context: calls.append(context.target_id)) as engine:
        batch = prepare(engine, payload={"nested": {"retained": True}})
    with make_engine(tmp_path, lambda context: calls.append(context.target_id)) as reopened:
        restored = reopened.get_batch(batch["batch_id"])
        assert restored["status"] == "prepared"
        assert restored["intent_sha256"] == batch["intent_sha256"]
        assert reopened.get_payload(batch["batch_id"]) == {"nested": {"retained": True}}
        assert restored["operations"] == batch["operations"]
        assert calls == []


def test_expiry_is_visible_in_status_and_blocks_admission(tmp_path):
    clock = Clock()
    calls = []
    with make_engine(tmp_path, lambda context: calls.append(context.target_id), clock=clock) as engine:
        batch = prepare(engine, expires_at=101)
        clock.now = 102
        assert engine.get_batch(batch["batch_id"])["status"] == "expired"
        assert engine.run_batch(batch["batch_id"])["status"] == "expired"
        same = prepare(engine, expires_at=101)
        assert same["batch_id"] == batch["batch_id"]
        assert same["status"] == "expired"
        assert calls == []
        with pytest.raises(BulkValidationError, match="expired"):
            prepare(engine, key="new-expired", expires_at=101)


def test_expiry_after_effect_retains_success_and_stops_remaining_targets(tmp_path):
    clock = Clock()
    calls = []

    def edit(context):
        calls.append(context.target_id)
        clock.now = 102
        return {"applied": True}

    with make_engine(tmp_path, edit, clock=clock) as engine:
        result = engine.run_batch(prepare(engine, expires_at=101, concurrency=1)["batch_id"])
        assert statuses(result) == {"a": "succeeded", "b": "expired"}
        assert result["status"] == "partial"
        assert calls == ["a"]


@pytest.mark.parametrize("payload", [{"x": float("nan")}, {1: "wrong key"}, {"x": object()}, {"x": (1, 2)}])
def test_non_json_payload_is_rejected(tmp_path, payload):
    with make_engine(tmp_path, lambda context: None) as engine:
        with pytest.raises(BulkValidationError):
            prepare(engine, payload=payload)


def test_payload_results_and_errors_have_byte_bounds(tmp_path):
    def edit(context):
        if context.target_id == "a":
            return {"answer": "🙂\\\n" * 10000}
        raise OperationFailed("🙂" * 10000)

    with make_engine(tmp_path, edit, payload_limit_bytes=256, result_limit_bytes=256) as engine:
        with pytest.raises(BulkValidationError, match="byte limit"):
            prepare(engine, payload={"large": "🙂" * 1000})
        batch = prepare(engine, concurrency=1)
        result = engine.run_batch(batch["batch_id"])
        first, second = result["operations"]
        assert first["status"] == "succeeded" and first["result_truncated"]
        assert first["result"]["_truncated"] is True
        assert len(second["error"].encode("utf-8")) <= 256
        with sqlite3.connect(engine.path) as connection:
            stored = connection.execute("SELECT result_json FROM operations WHERE target_id='a'").fetchone()[0]
            assert len(stored.encode("utf-8")) <= 256


def test_cannot_open_unrelated_database_or_ephemeral_ledger(tmp_path):
    unrelated = tmp_path / "other.sqlite3"
    with sqlite3.connect(unrelated) as connection:
        connection.execute("CREATE TABLE other_app (id INTEGER)")
    with pytest.raises(BulkConflictError, match="not a bulk"):
        BulkOperationEngine(unrelated, {})
    with pytest.raises(BulkValidationError, match="durable"):
        BulkOperationEngine(":memory:", {})


def run_child(script, *args):
    return subprocess.run([sys.executable, "-c", script, *map(str, args)], cwd=PROJECT_ROOT,
                          env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
                          capture_output=True, text=True, timeout=15)


def test_another_process_cannot_recover_a_live_owners_jobs(tmp_path):
    script = """
import sys
from star.bulk_operations import BulkOperationEngine, BulkConflictError
try:
    engine = BulkOperationEngine(sys.argv[1], {})
except BulkConflictError:
    print('ownership-blocked')
else:
    engine.close()
    raise SystemExit(10)
"""
    with make_engine(tmp_path, lambda context: None) as engine:
        batch = prepare(engine)
        child = run_child(script, engine.path)
        assert child.returncode == 0, child.stderr
        assert child.stdout.strip() == "ownership-blocked"
        assert engine.get_batch(batch["batch_id"])["status"] == "prepared"


def test_real_crash_after_effect_recovers_unknown_without_replaying(tmp_path):
    database = tmp_path / "bulk.sqlite3"
    effect = tmp_path / "visible-effect.txt"
    script = """
import os
from pathlib import Path
import sys
from star.bulk_operations import BulkAdapter, BulkOperationEngine
def apply(context):
    if context.target_id == 'effect':
        with open(sys.argv[2], 'w', encoding='utf-8') as output:
            output.write(context.operation_id)
            output.flush()
            os.fsync(output.fileno())
        os._exit(23)
    return {'applied': context.target_id}
engine = BulkOperationEngine(sys.argv[1], {'edit': BulkAdapter(apply, lambda: ['first', 'effect', 'last'])})
batch = engine.submit('edit', ['first', 'effect', 'last'], {'original': True},
                      idempotency_key='crashing-intent', concurrency=1)
engine.run_batch(batch['batch_id'])
"""
    child = run_child(script, database, effect)
    assert child.returncode == 23, child.stderr
    operation_id = effect.read_text(encoding="utf-8")
    calls = []
    with make_engine(tmp_path, lambda context: calls.append(context.target_id),
                     targets=["first", "effect", "last"]) as reopened:
        summary = reopened.list_batches()[0]
        recovered = reopened.get_batch(summary["batch_id"])
        assert recovered["status"] == "outcome_unknown"
        assert statuses(recovered) == {"first": "succeeded", "effect": "outcome_unknown", "last": "skipped"}
        assert recovered["operations"][1]["operation_id"] == operation_id
        assert recovered["operations"][0]["result"] == {"applied": "first"}
        reopened.run_batch(recovered["batch_id"])
        retry = reopened.submit("edit", ["first", "effect", "last"], {"original": True},
                                idempotency_key="crashing-intent", concurrency=1)
        assert retry["batch_id"] == recovered["batch_id"]
        assert retry["status"] == "outcome_unknown"
        assert calls == []
        assert effect.read_text(encoding="utf-8") == operation_id


def test_unknown_batch_and_closed_engine_fail_explicitly(tmp_path):
    engine = make_engine(tmp_path, lambda context: None)
    with pytest.raises(BulkNotFoundError):
        engine.get_batch("absent")
    engine.close()
    engine.close()
    with pytest.raises(BulkConflictError, match="closed"):
        engine.list_batches()
