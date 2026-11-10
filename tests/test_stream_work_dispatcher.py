import threading

import pytest

from star.stream_brain_governor import BrainAdmission, BrainLease
from star.stream_qos import InferenceJob
from star.stream_work_dispatcher import DispatchPolicy, StreamWorkDispatcher


class FakeGovernor:
    def __init__(self, outcomes=None):
        self.outcomes = list(outcomes or [])
        self.calls = []
        self.ticket = 0

    def admit(self, job):
        self.calls.append(job.job_id)
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            if isinstance(outcome, str):
                return BrainAdmission(False, outcome)
            if outcome is not None:
                return outcome
        self.ticket += 1
        lease = BrainLease(1, self.ticket, "cpu" if job.kind == "speech" else "gpu",
                           job.kind, job.deadline_ms)
        return BrainAdmission(True, "measured_p95_with_headroom", lease, 25.0)


def make_job(job_id, kind, created=1000, deadline=5000):
    return InferenceJob(job_id, kind, created, deadline, 128, 256,
                        "cpu" if kind == "speech" else "auto")


def make_dispatcher(governor=None, **kwargs):
    g = governor or FakeGovernor()
    return StreamWorkDispatcher(admit=g.admit, clock_ms=lambda: 1000, **kwargs), g


def test_priority_order_preserves_voice_then_vision_then_commentary_then_background():
    dispatcher, governor = make_dispatcher()
    for job in [
        make_job("r", "research"),
        make_job("c", "commentary"),
        make_job("v", "vision"),
        make_job("s", "speech"),
    ]:
        assert dispatcher.submit(job, now_ms=1000).accepted
    expected = ["s", "v", "c", "r"]
    for job_id in expected:
        result = dispatcher.dispatch(now_ms=1000)
        assert result.status == "admitted"
        assert result.job.job_id == job_id
        assert isinstance(result.admission.lease, BrainLease)
    assert governor.calls == expected


def test_earliest_deadline_breaks_ties_with_fifo_after_deadline():
    dispatcher, _ = make_dispatcher()
    dispatcher.submit(make_job("late", "commentary", deadline=4900), now_ms=1000)
    dispatcher.submit(make_job("early", "commentary", deadline=3000), now_ms=1000)
    dispatcher.submit(make_job("fifo", "commentary", deadline=3000), now_ms=1000)
    assert dispatcher.dispatch(now_ms=1000).job.job_id == "early"
    assert dispatcher.dispatch(now_ms=1000).job.job_id == "fifo"


def test_background_aging_prevents_idle_starvation_but_never_overtakes_commentary():
    dispatcher, _ = make_dispatcher()
    dispatcher.submit(make_job("research", "research", created=1000, deadline=120000), now_ms=1000)
    dispatcher.submit(make_job("comment", "commentary", created=11000, deadline=120000), now_ms=11000)
    # Research gets at most +30, so commentary remains ahead.
    assert dispatcher.dispatch(now_ms=11000).job.job_id == "comment"
    assert dispatcher.dispatch(now_ms=11000).job.job_id == "research"


def test_latest_wins_coalescing_for_queued_vision_and_old_id_cannot_replay():
    dispatcher, governor = make_dispatcher()
    assert dispatcher.submit(make_job("frame-1", "vision", created=1000), now_ms=1000,
                              coalesce_key="game-main").accepted
    result = dispatcher.submit(make_job("frame-2", "vision", created=1100), now_ms=1100,
                                coalesce_key="game-main")
    assert result.accepted and result.replaced_queued_work
    assert dispatcher.submit(make_job("frame-1", "vision", created=1000), now_ms=1100,
                              coalesce_key="game-main").reason == "duplicate_job_id"
    dispatched = dispatcher.dispatch(now_ms=1100)
    assert dispatched.job.job_id == "frame-2"
    assert governor.calls == ["frame-2"]


def test_speech_cannot_be_coalesced():
    dispatcher, _ = make_dispatcher()
    with pytest.raises(ValueError, match="cannot be coalesced"):
        dispatcher.submit(make_job("s", "speech"), now_ms=1000, coalesce_key="same")


def test_transient_admission_failure_keeps_item_and_tries_lower_priority_candidate():
    governor = FakeGovernor(["no_calibrated_deadline_safe_route_or_headroom", None])
    dispatcher, _ = make_dispatcher(governor)
    dispatcher.submit(make_job("speech", "speech"), now_ms=1000)
    dispatcher.submit(make_job("vision", "vision"), now_ms=1000)
    result = dispatcher.dispatch(now_ms=1000)
    assert result.status == "admitted"
    assert result.job.job_id == "vision"
    assert dispatcher.status(now_ms=1000)["queued"] == 1
    assert dispatcher.dispatch(now_ms=1000).reason == "retry_backoff"
    assert dispatcher.dispatch(now_ms=1050).job.job_id == "speech"


def test_transient_denial_is_retryable_without_reusing_or_replaying_job_id():
    governor = FakeGovernor(["telemetry_unavailable", None])
    dispatcher, _ = make_dispatcher(governor)
    dispatcher.submit(make_job("s", "speech"), now_ms=1000)
    first = dispatcher.dispatch(now_ms=1000)
    assert first.status == "deferred"
    assert dispatcher.status(now_ms=1000)["queued"] == 1
    second = dispatcher.dispatch(now_ms=1050)
    assert second.status == "admitted"
    assert governor.calls == ["s", "s"]


def test_permanent_governor_rejection_is_removed():
    governor = FakeGovernor(["job_stale"])
    dispatcher, _ = make_dispatcher(governor)
    dispatcher.submit(make_job("s", "speech"), now_ms=1000)
    result = dispatcher.dispatch(now_ms=1000)
    assert result.status == "idle"
    assert dispatcher.status(now_ms=1000)["queued"] == 0
    assert dispatcher.status(now_ms=1000)["permanent_reject"] == 1


def test_expired_and_overaged_jobs_are_removed_before_admission():
    dispatcher, governor = make_dispatcher()
    dispatcher.submit(make_job("expired", "speech", deadline=1001), now_ms=1000)
    result = dispatcher.dispatch(now_ms=1001)
    assert result.status == "idle"
    assert result.expired == 1
    assert governor.calls == []


def test_cancel_only_removes_queued_work_and_never_releases_a_lease():
    dispatcher, governor = make_dispatcher()
    dispatcher.submit(make_job("s", "speech"), now_ms=1000)
    assert dispatcher.cancel_queued("s")
    assert not dispatcher.cancel_queued("s")
    assert dispatcher.dispatch(now_ms=1000).status == "idle"
    assert governor.calls == []


def test_queue_and_seen_id_limits_are_bounded():
    policy = DispatchPolicy(max_queue=2, max_seen_ids=64, max_per_kind=2)
    dispatcher, _ = make_dispatcher(policy=policy)
    assert dispatcher.submit(make_job("a", "speech"), now_ms=1000).accepted
    assert dispatcher.submit(make_job("b", "vision"), now_ms=1000).accepted
    assert dispatcher.submit(make_job("c", "commentary"), now_ms=1000).reason == "queue_full"
    assert dispatcher.status(now_ms=1000)["queued"] == 2


def test_status_contains_aggregate_counts_but_no_job_ids_or_keys():
    dispatcher, _ = make_dispatcher()
    dispatcher.submit(make_job("private-job-id", "vision"), now_ms=1000, coalesce_key="private-key")
    report = repr(dispatcher.status(now_ms=1000))
    assert "private-job-id" not in report
    assert "private-key" not in report
    assert "queued_by_kind" in report


def test_invalid_key_kind_and_clock_regression_rejected():
    dispatcher, _ = make_dispatcher()
    with pytest.raises(ValueError, match="opaque"):
        dispatcher.submit(make_job("v", "vision"), now_ms=1000, coalesce_key="../private")
    with pytest.raises(ValueError, match="cannot be coalesced"):
        dispatcher.submit(make_job("s", "speech"), now_ms=1000, coalesce_key="voice")
    dispatcher.status(now_ms=1100)
    with pytest.raises(ValueError, match="regressed"):
        dispatcher.status(now_ms=1099)


def test_adapter_exception_does_not_lose_queued_work():
    governor = FakeGovernor([RuntimeError("private exception")])
    dispatcher, _ = make_dispatcher(governor)
    dispatcher.submit(make_job("s", "speech"), now_ms=1000)
    result = dispatcher.dispatch(now_ms=1000)
    assert result.status == "deferred"
    assert result.reason == "admission_adapter_error"
    assert dispatcher.status(now_ms=1000)["queued"] == 1
    assert dispatcher.status(now_ms=1000)["adapter_errors"] == 1


def test_concurrent_dispatch_is_single_flight_and_cannot_cancel_inflight():
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def admit(job):
        calls.append(job.job_id)
        entered.set()
        assert release.wait(2)
        return BrainAdmission(True, "ok", BrainLease(1, 1, "cpu", "speech", 5000))

    dispatcher = StreamWorkDispatcher(admit=admit, clock_ms=lambda: 1000)
    dispatcher.submit(make_job("s", "speech"), now_ms=1000)
    output = []
    thread = threading.Thread(target=lambda: output.append(dispatcher.dispatch(now_ms=1000)))
    thread.start()
    assert entered.wait(2)
    assert dispatcher.dispatch(now_ms=1000).status == "busy"
    assert not dispatcher.cancel_queued("s")
    release.set()
    thread.join(2)
    assert not thread.is_alive()
    assert output[0].status == "admitted"
    assert calls == ["s"]


def test_newer_coalesced_item_survives_if_inflight_admission_is_deferred():
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def admit(job):
        calls.append(job.job_id)
        if job.job_id == "old":
            entered.set()
            assert release.wait(2)
            return BrainAdmission(False, "temporary_pressure")
        return BrainAdmission(True, "ok", BrainLease(1, 2, "gpu", "vision", 6000))

    dispatcher = StreamWorkDispatcher(admit=admit, clock_ms=lambda: 1000)
    dispatcher.submit(make_job("old", "vision", created=1000), now_ms=1000, coalesce_key="scene")
    output = []
    thread = threading.Thread(target=lambda: output.append(dispatcher.dispatch(now_ms=1000)))
    thread.start()
    assert entered.wait(2)
    assert dispatcher.submit(make_job("new", "vision", created=1100), now_ms=1100,
                              coalesce_key="scene").accepted
    release.set()
    thread.join(2)
    # The same bounded dispatch pass may continue to the newer replacement
    # after the old candidate is deferred.
    assert output[0].status == "admitted"
    assert output[0].job.job_id == "new"
    assert dispatcher.status(now_ms=1100)["queued"] == 0
    assert calls == ["old", "new"]


def test_admitted_result_requires_real_lease():
    governor = FakeGovernor([BrainAdmission(True, "broken", None)])
    dispatcher, _ = make_dispatcher(governor)
    dispatcher.submit(make_job("s", "speech"), now_ms=1000)
    result = dispatcher.dispatch(now_ms=1000)
    assert result.status == "deferred"
    assert result.reason == "admission_adapter_error"
    assert dispatcher.status(now_ms=1000)["queued"] == 1


def test_newer_coalesced_item_survives_if_inflight_admission_raises():
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def admit(job):
        calls.append(job.job_id)
        if job.job_id == "old":
            entered.set()
            assert release.wait(2)
            raise RuntimeError("temporary adapter failure")
        return BrainAdmission(True, "ok", BrainLease(1, 3, "gpu", "vision", 6000))

    dispatcher = StreamWorkDispatcher(admit=admit, clock_ms=lambda: 1000)
    dispatcher.submit(make_job("old", "vision", created=1000), now_ms=1000, coalesce_key="scene")
    output = []
    thread = threading.Thread(target=lambda: output.append(dispatcher.dispatch(now_ms=1000)))
    thread.start()
    assert entered.wait(2)
    assert dispatcher.submit(make_job("new", "vision", created=1100), now_ms=1100,
                              coalesce_key="scene").accepted
    release.set()
    thread.join(2)
    assert output[0].status == "deferred"
    assert dispatcher.status(now_ms=1100)["queued"] == 1
    assert dispatcher.dispatch(now_ms=1100).job.job_id == "new"
    assert calls == ["old", "new"]


def test_backoff_prevents_head_of_line_starvation_beyond_attempt_budget():
    policy = DispatchPolicy(max_queue=16, max_seen_ids=64, max_admission_attempts=4)
    governor = FakeGovernor(["temporary_pressure"] * 5 + [None])
    dispatcher, _ = make_dispatcher(governor, policy=policy)
    for index in range(5):
        dispatcher.submit(make_job(f"speech-{index}", "speech"), now_ms=1000)
    dispatcher.submit(make_job("vision", "vision"), now_ms=1000)

    first = dispatcher.dispatch(now_ms=1000)
    assert first.status == "deferred"
    assert first.attempted == 4
    assert dispatcher.status(now_ms=1000)["backoff_queued"] == 4

    # The four denied speech jobs are in a short retry backoff. The fifth
    # speech job is tried once, deferred, then the vision job can use the slot.
    second = dispatcher.dispatch(now_ms=1000)
    assert second.status == "admitted"
    assert second.job.job_id == "vision"


def test_transient_backoff_expires_and_job_is_retried():
    governor = FakeGovernor(["temporary_pressure", None])
    dispatcher, _ = make_dispatcher(governor)
    dispatcher.submit(make_job("s", "speech"), now_ms=1000)
    assert dispatcher.dispatch(now_ms=1000).status == "deferred"
    assert dispatcher.dispatch(now_ms=1049).reason == "retry_backoff"
    assert dispatcher.status(now_ms=1049)["backoff_queued"] == 1
    assert dispatcher.dispatch(now_ms=1050).status == "admitted"
