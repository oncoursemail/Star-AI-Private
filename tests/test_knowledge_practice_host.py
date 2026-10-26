"""Offline integration tests: model answer is never its own grading authority."""
from __future__ import annotations

import asyncio
from dataclasses import replace
import hmac

import pytest

from star.knowledge import KnowledgeStore
from star.knowledge_practice_host import KnowledgePracticeHost, PracticeQuestion
from star.knowledge_recall import GradedRecall, KnowledgeRecallPlanner, RecallCard, note_fingerprint
from star.stream_budget import StreamTelemetry

NOW = 1_800_000_000
KEY = b"separately-trusted-grader-signing-key-for-tests!"
READY = StreamTelemetry(
    live=False, game_active=False, total_vram_mib=8192,
    free_vram_mib=6000, game_fps=60, speech_backlog_ms=0,
)


@pytest.fixture
def env(tmp_path):
    store = KnowledgeStore(tmp_path)
    text = "The unit-test star is a fictional character."
    ident = store.add_note(project="STAR", kind="fact", text=text,
                           source="trusted-human-editor", revision="v1")
    store.review_note(project="STAR", note_id=ident, evidence="human checked")
    pin = note_fingerprint(text=text, source="trusted-human-editor", revision="v1")
    card = RecallCard("sample", "fictional_lore", ident, pin)
    planner = KnowledgeRecallPlanner(
        store, project="STAR", cards=(card,), verification_key=KEY)
    q = PracticeQuestion("sample", pin, "What does this unit-test record describe?")
    try:
        yield store, planner, q, ident
    finally:
        store.close()


def setup(env, *, model=None, grader=None, telemetry=None, **kw):
    _, planner, q, _ = env
    calls = {"model": [], "grade": []}
    state = {"telemetry": READY, "clock": NOW}

    async def infer(prompt):
        calls["model"].append(prompt)
        return "a fictional character" if model is None else await model(prompt)

    async def grade(qid, ticket, source, answer):
        calls["grade"].append((qid, ticket, source, answer))
        if grader is not None:
            return await grader(qid, ticket, source, answer)
        feedback = GradedRecall(qid, ticket, source, "correct", state["clock"],
                                "independent_grader_1", "0" * 64)
        return replace(feedback, receipt=hmac.new(
            KEY, feedback.canonical_bytes(), "sha256").hexdigest())

    host = KnowledgePracticeHost(
        planner, questions=(q,), infer_local=infer, grade_independently=grade,
        host_clock=lambda: state["clock"],
        host_telemetry=(lambda: state["telemetry"]) if telemetry is None else telemetry,
        **kw)
    return host, planner, calls, state


def run(host):
    return asyncio.run(host.run_once())


def test_default_off_and_dual_owner_approval(env):
    host, planner, calls, _ = setup(env)
    assert run(host).reason == "host_opt_in_missing"
    with pytest.raises(PermissionError):
        host.enable()
    with pytest.raises(PermissionError):
        host.enable(owner_approved=1)
    host.enable(owner_approved=True)
    with pytest.raises(RuntimeError):
        host.enable(owner_approved=True)
    assert run(host).reason == "offline_recall_opt_in_missing"
    assert calls == {"model": [], "grade": []}
    planner.enable(owner_approved=True)
    assert run(host).status == "verified"
    assert planner.metrics()["correct"] == 1


def test_signed_success_and_strict_prompt_separation(env):
    host, planner, calls, _ = setup(env)
    planner.enable(owner_approved=True)
    host.enable(owner_approved=True)
    report = run(host)
    assert report.reason == "authenticated_grade_accepted"
    assert report.inference_ms is not None and report.inference_ms >= 0
    assert calls["model"] == ["What does this unit-test record describe?"]
    assert calls["grade"][0][0] == "sample"
    assert calls["grade"][0][2] == env[2].source_sha256
    assert calls["grade"][0][3] == "a fictional character"
    assert "a fictional character" not in repr(report)
    assert "trusted-human-editor" not in repr(report)
    assert planner.metrics()["attempts"] == 1
    assert host.metrics()["verified"] == 1
    assert host.metrics()["busy"] is False
    assert run(host).reason == "no_practice_due"


def test_unsigned_grader_response_cannot_claim_progress(env):
    async def bogus(qid, ticket, source, answer):
        return GradedRecall(qid, ticket, source, "correct", NOW,
                            "independent_grader_1", "0" * 64)
    host, planner, calls, _ = setup(env, grader=bogus)
    planner.enable(owner_approved=True)
    host.enable(owner_approved=True)
    assert run(host).reason == "unsigned_or_stale_grade"
    assert planner.metrics()["attempts"] == 0
    assert planner.metrics()["pending"] is False
    assert len(calls["grade"]) == 1


@pytest.mark.parametrize("wrong", ["digest", "missing"])
def test_host_prompt_manifest_must_match_the_planner_pin(env, wrong):
    _, planner, q, _ = env
    async def model(prompt):
        pytest.fail("unapproved model prompt must never run")
    async def grader(*args):
        pytest.fail("unapproved grade must never run")
    questions = (PracticeQuestion(q.question_id, "f" * 64, q.prompt),) if wrong == "digest" else (
        PracticeQuestion("other", q.source_sha256, q.prompt),)
    host = KnowledgePracticeHost(
        planner, questions=questions, infer_local=model,
        grade_independently=grader, host_clock=lambda: NOW,
        host_telemetry=lambda: READY)
    planner.enable(owner_approved=True)
    host.enable(owner_approved=True)
    assert run(host).reason == "vetted_prompt_pin_missing"
    assert not planner.metrics()["pending"]
    assert planner.metrics()["attempts"] == 0


def test_revoked_review_fails_before_inference(env):
    store, planner, _, ident = env
    host, _, calls, _ = setup(env)
    store.db.execute("UPDATE notes SET reviewed=0 WHERE id=?", (ident,))
    store.db.commit()
    planner.enable(owner_approved=True)
    host.enable(owner_approved=True)
    assert run(host).reason == "no_current_reviewed_pinned_sources"
    assert calls["model"] == []


@pytest.mark.parametrize("out", [None, "", " " * 10, "z" * 4097, "okay\x00bad", 123])
def test_bad_model_output_cannot_be_graded(env, out):
    async def model(_):
        return out
    host, planner, calls, _ = setup(env, model=model)
    planner.enable(owner_approved=True)
    host.enable(owner_approved=True)
    assert run(host).reason == "invalid_model_response"
    assert planner.metrics()["attempts"] == 0 and not planner.metrics()["pending"]
    assert calls["grade"] == []


def test_model_exception_never_counts_as_incorrect_or_correct(env):
    async def model(_):
        raise RuntimeError("SECRET ANSWER MUST NOT LEAK")
    host, planner, calls, _ = setup(env, model=model)
    planner.enable(owner_approved=True)
    host.enable(owner_approved=True)
    report = run(host)
    assert report.reason == "host_callback_or_clock_failure"
    assert "SECRET" not in repr(report)
    assert planner.metrics()["attempts"] == 0 and not planner.metrics()["pending"]


def test_inference_timeout_aborts_and_cleans_reservation(env):
    async def model(_):
        await asyncio.sleep(2)
        return "too late"
    host, planner, calls, _ = setup(env, model=model, inference_timeout_s=1)
    planner.enable(owner_approved=True)
    host.enable(owner_approved=True)
    assert run(host).reason == "local_inference_timeout"
    assert host.metrics()["timeouts"] == 1
    assert not planner.metrics()["pending"]
    assert calls["grade"] == []


def test_grader_timeout_aborts_without_self_grade(env):
    async def grader(*args):
        await asyncio.sleep(2)
        return None
    host, planner, _, _ = setup(env, grader=grader, grading_timeout_s=1)
    planner.enable(owner_approved=True)
    host.enable(owner_approved=True)
    assert run(host).reason == "independent_grader_timeout"
    assert not planner.metrics()["pending"]
    assert planner.metrics()["attempts"] == 0


@pytest.mark.parametrize("telemetry", [None, replace(READY, live=True),
    replace(READY, free_vram_mib=100),
    replace(READY, game_active=True, game_fps=20),
    replace(READY, speech_backlog_ms=700)])
def test_resource_gating_refuses_to_run_model(env, telemetry):
    host, planner, calls, state = setup(env)
    state["telemetry"] = telemetry
    planner.enable(owner_approved=True)
    host.enable(owner_approved=True)
    assert run(host).status == "deferred"
    assert calls["model"] == []
    assert planner.metrics()["attempts"] == 0


def test_stream_starts_during_inference_never_sends_answer_to_grader(env):
    state_ref = {}
    async def model(_):
        state_ref["state"]["telemetry"] = replace(READY, live=True)
        return "a fictional character"
    host, planner, calls, state = setup(env, model=model)
    state_ref["state"] = state
    planner.enable(owner_approved=True)
    host.enable(owner_approved=True)
    assert run(host).reason == "offline_window_closed"
    assert calls["grade"] == []
    assert planner.metrics()["attempts"] == 0


def test_stream_starts_during_grading_does_not_accept_late_grade(env):
    state_ref = {}
    async def grader(qid, ticket, pin, answer):
        state_ref["state"]["telemetry"] = replace(READY, live=True)
        feedback = GradedRecall(qid, ticket, pin, "correct", NOW,
                                "separate_grader", "0" * 64)
        return replace(feedback, receipt=hmac.new(
            KEY, feedback.canonical_bytes(), "sha256").hexdigest())
    host, planner, _, state = setup(env, grader=grader)
    state_ref["state"] = state
    planner.enable(owner_approved=True)
    host.enable(owner_approved=True)
    assert run(host).reason == "offline_window_closed"
    assert planner.metrics()["attempts"] == 0


def test_reviewed_source_changed_during_inference_rejects_feedback(env):
    store, planner, _, ident = env
    async def model(_):
        store.db.execute("UPDATE notes SET text=? WHERE id=?",
                         ("changed by an editor", ident))
        store.db.commit()
        return "a fictional character"
    host, _, _, _ = setup(env, model=model)
    planner.enable(owner_approved=True)
    host.enable(owner_approved=True)
    assert run(host).reason == "unsigned_or_stale_grade"
    assert planner.metrics()["attempts"] == 0


def test_concurrent_second_attempt_fails_fast_and_cancelled_reservation_cleans(env):
    async def scenario():
        started = asyncio.Event()
        unblock = asyncio.Event()
        async def model(_):
            started.set()
            await unblock.wait()
            return "a fictional character"
        host, planner, calls, _ = setup(env, model=model)
        planner.enable(owner_approved=True)
        host.enable(owner_approved=True)
        first = asyncio.create_task(host.run_once())
        await started.wait()
        assert (await host.run_once()).reason == "one_practice_attempt_at_a_time"
        assert host.metrics()["busy"] is True
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not planner.metrics()["pending"]
        assert host.metrics()["busy"] is False
        unblock.set()
        assert (await host.run_once()).status == "verified"
    asyncio.run(scenario())


def test_owner_disable_cancels_inflight_inference(env):
    async def scenario():
        started = asyncio.Event()
        async def model(_):
            started.set()
            await asyncio.sleep(120)
        host, planner, _, _ = setup(env, model=model)
        planner.enable(owner_approved=True)
        host.enable(owner_approved=True)
        task = asyncio.create_task(host.run_once())
        await started.wait()
        host.disable()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert planner.metrics()["pending"] is False
        assert not host.metrics()["enabled"]
        assert (await host.run_once()).reason == "host_opt_in_missing"
    asyncio.run(scenario())


@pytest.mark.parametrize("bad", [
    PracticeQuestion("sample", "a" * 64, "valid"),
])
def test_planner_digest_accessor_has_no_note_body(env, bad):
    _, planner, q, _ = env
    assert planner.pinned_source_for(q.question_id) == q.source_sha256
    assert planner.pinned_source_for("not-present") is None
    with pytest.raises(ValueError):
        planner.pinned_source_for("not allowed!")
    assert bad.source_sha256 != planner.pinned_source_for("sample")


@pytest.mark.parametrize("field", ["id", "digest", "prompt", "null", "too_long"])
def test_question_manifest_validation(field):
    kwargs = dict(question_id="q", source_sha256="f" * 64, prompt="a question")
    kwargs[{"id": "question_id", "digest": "source_sha256",
            "prompt": "prompt", "null": "prompt", "too_long": "prompt"}[field]] = {
                "id": "bad id", "digest": "0", "prompt": "",
                "null": "okay\x00", "too_long": "x" * 2049}[field]
    with pytest.raises(ValueError):
        PracticeQuestion(**kwargs)


def test_rejects_unsafe_configuration_and_callback_shapes(env):
    _, planner, q, _ = env
    async def model(prompt):
        return prompt
    async def grader(*args):
        return None
    base = dict(planner=planner, questions=(q,), infer_local=model,
                grade_independently=grader, host_clock=lambda: NOW,
                host_telemetry=lambda: READY)
    for changes in ({"inference_timeout_s": 0}, {"grading_timeout_s": 100},
                    {"inference_timeout_s": True}, {"infer_local": None},
                    {"questions": [q, q]}, {"questions": []}):
        with pytest.raises((ValueError, TypeError)):
            KnowledgePracticeHost(**(base | changes))


def test_resource_headroom_lost_during_inference_aborts_without_grading(env):
    state_ref = {}
    async def model(_):
        state_ref["state"]["telemetry"] = replace(READY, free_vram_mib=100)
        return "a fictional character"
    host, planner, calls, state = setup(env, model=model)
    state_ref["state"] = state
    planner.enable(owner_approved=True)
    host.enable(owner_approved=True)
    assert run(host).reason == "offline_window_closed"
    assert calls["grade"] == []
    assert planner.metrics()["attempts"] == 0


def test_rejects_surrogate_in_owner_curated_prompt():
    with pytest.raises(ValueError, match="UTF-8"):
        PracticeQuestion("bad", "f" * 64, "question\ud800")


def test_untrusted_grader_cannot_forge_another_question_or_ticket(env):
    async def grader(qid, ticket, pin, answer):
        fake = GradedRecall("other", ticket, pin, "correct", NOW, "grader", "0" * 64)
        return replace(fake, receipt=hmac.new(
            KEY, fake.canonical_bytes(), "sha256").hexdigest())
    host, planner, _, _ = setup(env, grader=grader)
    planner.enable(owner_approved=True)
    host.enable(owner_approved=True)
    assert run(host).reason == "unsigned_or_stale_grade"
    assert planner.metrics()["attempts"] == 0
