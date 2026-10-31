"""Source-pinned, independently graded recall practice: offline and fail-closed."""
from __future__ import annotations

from dataclasses import replace
import hmac
import json
from threading import Thread

import pytest

from star.knowledge import KnowledgeStore
from star.knowledge_recall import (
    GradedRecall, KnowledgeRecallPlanner, RecallCard, note_fingerprint,
)
from star.stream_budget import StreamTelemetry

NOW = 1_800_000_000
KEY = b"trusted-offline-knowledge-grader-key-123456789012"
GOOD = StreamTelemetry(
    live=False, game_active=False, total_vram_mib=8192,
    free_vram_mib=6000, game_fps=60, speech_backlog_ms=0,
)


@pytest.fixture
def scene(tmp_path):
    store = KnowledgeStore(tmp_path)
    try:
        cards = []
        for domain, text in (
            ("math", "The sum of 2 + 3 equals 5."),
            ("history", "The Magna Carta was sealed in 1215."),
            ("science", "Water consists of hydrogen and oxygen."),
        ):
            ident = store.add_note(
                project="STAR", kind="fact", text=text,
                source="owner-reviewed-source", revision="2026-10-26",
            )
            store.review_note(project="STAR", note_id=ident,
                              evidence="externally checked offline")
            card = RecallCard(
                question_id=domain, domain=domain, note_id=ident,
                source_sha256=note_fingerprint(
                    text=text, source="owner-reviewed-source", revision="2026-10-26"),
            )
            cards.append(card)
        yield store, tuple(cards)
    finally:
        store.close()


def planner(scene, cards=None):
    store, original = scene
    return KnowledgeRecallPlanner(
        store, project="STAR", cards=original if cards is None else cards,
        verification_key=KEY,
    )


def grade(advice, source_sha256, *, outcome="correct", now=NOW, grader="grader_v1"):
    unsigned = GradedRecall(
        question_id=advice.question_id, ticket=advice.ticket,
        source_sha256=source_sha256, outcome=outcome,
        observed_unix_s=now, grader_revision=grader, receipt="0" * 64,
    )
    receipt = hmac.new(KEY, unsigned.canonical_bytes(), "sha256").hexdigest()
    return replace(unsigned, receipt=receipt)


def test_default_off_and_owner_opt_in(scene):
    p = planner(scene)
    assert p.reserve(now_unix_s=NOW, telemetry=GOOD).reason == "offline_recall_opt_in_missing"
    with pytest.raises(PermissionError):
        p.enable()
    with pytest.raises(PermissionError):
        p.enable(owner_approved=1)
    p.enable(owner_approved=True)
    with pytest.raises(RuntimeError):
        p.enable(owner_approved=True)
    assert p.reserve(now_unix_s=NOW, telemetry=GOOD).status == "practice_candidate"


@pytest.mark.parametrize("telemetry,reason", [
    (None, "trusted_telemetry_missing"),
    (replace(GOOD, live=True), "never_run_rehearsal_while_live"),
    (replace(GOOD, game_active=True, game_fps=20), "gameplay_fps_protection"),
    (replace(GOOD, speech_backlog_ms=500), "speech_backlog_protection"),
    (replace(GOOD, free_vram_mib=200), "insufficient_offline_compute_headroom"),
])
def test_no_background_load_during_live_or_pressure(scene, telemetry, reason):
    p = planner(scene)
    p.enable(owner_approved=True)
    assert p.reserve(now_unix_s=NOW, telemetry=telemetry).reason == reason
    assert p.metrics()["attempts"] == 0


def test_signed_grade_and_due_time_are_not_self_reported(scene):
    p = planner(scene)
    p.enable(owner_approved=True)
    advice = p.reserve(now_unix_s=NOW, telemetry=GOOD)
    assert not advice.authorized_to_run_model
    assert advice.ticket and len(advice.ticket) == 32
    assert p.reserve(now_unix_s=NOW, telemetry=GOOD).reason == "graded_recall_pending"
    card = next(c for c in scene[1] if c.question_id == advice.question_id)
    unsigned = grade(advice, card.source_sha256, now=NOW + 1)
    assert not p.finish(replace(unsigned, receipt="a" * 64), now_unix_s=NOW + 1)
    assert p.metrics()["pending"]
    assert p.finish(unsigned, now_unix_s=NOW + 1)
    assert not p.finish(unsigned, now_unix_s=NOW + 1)  # replay
    assert p.metrics()["verified"] == 1
    assert p.metrics()["correct"] == 1


def test_repeated_correct_recall_spaced_and_failure_resets_streak(scene):
    p = planner(scene, cards=scene[1][:1])
    p.enable(owner_approved=True)
    def attempt(at, outcome):
        a = p.reserve(now_unix_s=at, telemetry=GOOD)
        assert a.status == "practice_candidate"
        assert p.finish(grade(a, scene[1][0].source_sha256, outcome=outcome, now=at + 1),
                        now_unix_s=at + 1)
    attempt(NOW, "correct")
    assert p.reserve(now_unix_s=NOW + 3500, telemetry=GOOD).reason == "no_practice_due"
    attempt(NOW + 3601, "correct")
    assert p.reserve(now_unix_s=NOW + 7000, telemetry=GOOD).reason == "no_practice_due"
    attempt(NOW + 25202, "incorrect")
    assert p.reserve(now_unix_s=NOW + 25500, telemetry=GOOD).reason == "no_practice_due"
    attempt(NOW + 26103, "abstained")
    assert p.metrics()["correct"] == 2
    assert p.metrics()["attempts"] == 4


def test_balanced_domains_before_repeating_one(scene):
    p = planner(scene)
    p.enable(owner_approved=True)
    seen = set()
    for at in range(NOW, NOW + 3):
        a = p.reserve(now_unix_s=at, telemetry=GOOD)
        assert a.question_id not in seen
        seen.add(a.question_id)
        card = next(c for c in scene[1] if c.question_id == a.question_id)
        assert p.finish(grade(a, card.source_sha256, now=at), now_unix_s=at)
    assert seen == {"math", "history", "science"}
    assert p.reserve(now_unix_s=NOW + 5, telemetry=GOOD).reason == "no_practice_due"


def test_unreviewed_wrong_project_or_changed_source_skipped(scene):
    store, cards = scene
    bad = store.add_note(project="STAR", kind="fact",
                         text="Model generated guess", source="ai", revision="guess")
    other = RecallCard("unreviewed", "science", bad,
                       note_fingerprint(text="Model generated guess", source="ai", revision="guess"))
    p = planner(scene, cards=(other,))
    p.enable(owner_approved=True)
    assert p.reserve(now_unix_s=NOW, telemetry=GOOD).reason == "no_current_reviewed_pinned_sources"
    store.review_note(project="STAR", note_id=bad, evidence="owner-check")
    assert p.reserve(now_unix_s=NOW + 1, telemetry=GOOD).status == "practice_candidate"
    p.disable()
    store.db.execute("UPDATE notes SET reviewed=0 WHERE id=?", (bad,))
    store.db.commit()
    assert p.reserve(now_unix_s=NOW + 2, telemetry=GOOD).status == "deferred"
    p.enable(owner_approved=True)
    assert p.reserve(now_unix_s=NOW + 2, telemetry=GOOD).reason == "no_current_reviewed_pinned_sources"
    with pytest.raises(ValueError):
        planner(scene, cards=(replace(cards[0], source_sha256="not-a-digest"),))


def test_changed_pinned_content_blocks_submission(scene):
    store, cards = scene
    p = planner(scene, cards=(cards[0],))
    p.enable(owner_approved=True)
    a = p.reserve(now_unix_s=NOW, telemetry=GOOD)
    store.db.execute("UPDATE notes SET revision='changed' WHERE id=?", (cards[0].note_id,))
    store.db.commit()
    assert not p.finish(grade(a, cards[0].source_sha256), now_unix_s=NOW)
    assert p.metrics()["correct"] == 0
    assert p.cancel(ticket=a.ticket, now_unix_s=NOW)
    assert p.reserve(now_unix_s=NOW, telemetry=GOOD).reason == "no_current_reviewed_pinned_sources"


def test_source_change_does_not_cross_another_project(scene):
    store, cards = scene
    p = KnowledgeRecallPlanner(store, project="OTHER", cards=(cards[0],), verification_key=KEY)
    p.enable(owner_approved=True)
    assert p.reserve(now_unix_s=NOW, telemetry=GOOD).reason == "no_current_reviewed_pinned_sources"


def test_future_backdated_and_expired_attempts_denied(scene):
    p = planner(scene, cards=scene[1][:1])
    p.enable(owner_approved=True)
    a = p.reserve(now_unix_s=NOW, telemetry=GOOD)
    digest = scene[1][0].source_sha256
    assert not p.finish(grade(a, digest, now=NOW + 10), now_unix_s=NOW)
    assert not p.finish(grade(a, digest, now=NOW - 1), now_unix_s=NOW)
    assert p.reserve(now_unix_s=NOW + 301, telemetry=GOOD).status == "practice_candidate"
    assert not p.finish(grade(a, digest, now=NOW + 1), now_unix_s=NOW + 301)
    assert p.metrics()["expired"] == 1
    with pytest.raises(ValueError):
        p.reserve(now_unix_s=NOW - 10, telemetry=GOOD)


def test_cross_card_replay_invalid_ticket_and_invalid_grader(scene):
    p = planner(scene)
    p.enable(owner_approved=True)
    a = p.reserve(now_unix_s=NOW, telemetry=GOOD)
    card = next(c for c in scene[1] if c.question_id == a.question_id)
    good = grade(a, card.source_sha256)
    assert not p.finish(replace(good, question_id="different"), now_unix_s=NOW)
    assert not p.finish(replace(good, ticket="f" * 32), now_unix_s=NOW)
    assert not p.finish(replace(good, grader_revision="revised"), now_unix_s=NOW)
    assert p.finish(good, now_unix_s=NOW)


def test_rejects_forged_receipt_bad_outcome_and_wrong_source(scene):
    p = planner(scene, cards=scene[1][:1])
    p.enable(owner_approved=True)
    a = p.reserve(now_unix_s=NOW, telemetry=GOOD)
    item = scene[1][0]
    good = grade(a, item.source_sha256)
    assert not p.finish(replace(good, source_sha256="e" * 64), now_unix_s=NOW)
    assert not p.finish(replace(good, receipt="f" * 64), now_unix_s=NOW)
    with pytest.raises(ValueError):
        p.finish(replace(good, outcome="human_approved"), now_unix_s=NOW)
    assert p.metrics()["correct"] == 0


def test_checkpoint_restores_only_same_reviewed_roster_without_text(scene):
    p = planner(scene, cards=scene[1][:1])
    p.enable(owner_approved=True)
    a = p.reserve(now_unix_s=NOW, telemetry=GOOD)
    assert p.finish(grade(a, scene[1][0].source_sha256), now_unix_s=NOW)
    with pytest.raises(RuntimeError):
        p.checkpoint()
    p.disable()
    saved = p.checkpoint()
    assert b"hydrogen" not in saved and b"Magna" not in saved
    other = planner(scene, cards=scene[1][:1])
    other.restore(saved)
    assert other.metrics()["attempts"] == 1
    other.enable(owner_approved=True)
    assert other.reserve(now_unix_s=NOW + 1, telemetry=GOOD).reason == "no_practice_due"


def test_checkpoint_mutation_and_wrong_roster_rejected(scene):
    p = planner(scene, cards=scene[1][:1])
    sealed = p.checkpoint()
    altered = json.loads(sealed)
    altered["payload"]["rows"][0][1] = 5
    bad = json.dumps(altered).encode()
    with pytest.raises(PermissionError):
        planner(scene, cards=scene[1][:1]).restore(bad)
    with pytest.raises(ValueError):
        planner(scene, cards=scene[1][:2]).restore(sealed)
    with pytest.raises(ValueError):
        planner(scene, cards=scene[1][:1]).restore(b"{" + b"x" * 20000)


def test_no_restore_into_active_state_and_no_cross_thread_sqlite(scene):
    p = planner(scene)
    p.enable(owner_approved=True)
    with pytest.raises(RuntimeError):
        p.restore(b"{}")
    errors = []
    def worker():
        try:
            p.reserve(now_unix_s=NOW, telemetry=GOOD)
        except Exception as exc:
            errors.append(exc)
    thread = Thread(target=worker)
    thread.start()
    thread.join(timeout=5)
    assert len(errors) == 1 and isinstance(errors[0], RuntimeError)


def test_cards_validate_duplicates_key_and_bad_provenance(scene):
    store, cards = scene
    with pytest.raises(ValueError):
        KnowledgeRecallPlanner(store, project="STAR", cards=(cards[0], cards[0]), verification_key=KEY)
    with pytest.raises(ValueError):
        KnowledgeRecallPlanner(store, project="STAR", cards=cards, verification_key=b"short")
    with pytest.raises(ValueError):
        RecallCard(question_id="bad/slash", domain="math", note_id=1, source_sha256="f"*64)
    with pytest.raises(ValueError):
        note_fingerprint(text="", source="url", revision="v1")


def test_recall_checks_entire_roster_in_one_sqlite_query(scene):
    store, cards = scene
    statements = []
    store.db.set_trace_callback(statements.append)
    try:
        p = planner(scene)
        p.enable(owner_approved=True)
        assert p.reserve(now_unix_s=NOW, telemetry=GOOD).status == "practice_candidate"
    finally:
        store.db.set_trace_callback(None)
    reads = [statement for statement in statements
             if "select" in statement.lower() and "from notes" in statement.lower()]
    assert len(reads) == 1


def test_tampered_grader_receipt_cannot_reset_a_verified_wrong_answer(scene):
    p = planner(scene, cards=scene[1][:1])
    p.enable(owner_approved=True)
    a = p.reserve(now_unix_s=NOW, telemetry=GOOD)
    bad = grade(a, scene[1][0].source_sha256, outcome="incorrect")
    # The actual trusted grader marked this answer wrong. The model cannot
    # turn a signed failure into a success by editing the outcome field.
    assert not p.finish(replace(bad, outcome="correct"), now_unix_s=NOW)
    assert p.finish(bad, now_unix_s=NOW)
    assert p.metrics()["attempts"] == 1
    assert p.metrics()["correct"] == 0
