"""Synthetic offline authentication tests for independent game-vision truth.

The test HMAC signer simulates a separate trusted Studio observer. No actual
Roblox Studio, webcam, Windows desktop, OBS, network, or neural model is used.
"""
from dataclasses import replace
import hashlib
import hmac
import json

import pytest

from star.stream_vision_trace_host import (
    HostFrameRef, PairedVisionTraceHost, VisionTraceTicket,
)
from star.stream_vision_truth_receipt import (
    VisionTruthReceipt, verify_vision_truth_receipt,
)
from star.stream_visual_perception import VisualFinding, VisualPacket
from star.stream_vision_eval import read_jsonl

KEY = b"separate-independent-engine-observer-key-2026"
OTHER_KEY = b"different-engine-observer-secret-key-2026"


def host_and_ticket(*, seal=True):
    host = PairedVisionTraceHost(game_id="private_obby", game_version="v2")
    host.enable(owner_approved=True, offline_capture_approved=True)
    frame = HostFrameRef(5, "a" * 64, 2000.0)
    ticket = host.reserve(frame, capture_approved=True)
    for variant in ("baseline", "candidate"):
        host.record_worker(
            ticket, variant=variant,
            packet=VisualPacket(
                frame.captured_ms, 640, 360,
                (VisualFinding("hud_change", "hud", .97),),
            ), status="accepted", started_ms=2020.0,
            finished_ms=2060.0, worker_stopped=True,
        )
    if seal:
        host.seal_predictions()
    return host, ticket


def receipt_for(ticket):
    return VisionTruthReceipt(
        game_id="private_obby", game_version="v2",
        trace_epoch=ticket.epoch, trace_serial=ticket.serial,
        frame_sequence=5, frame_sha256="a" * 64,
        captured_ms=2000.0, truth_source="studio_engine",
        labels=(("hud_change", "hud"),), observer_run_id="engine-run-0001",
        evidence_sha256="b" * 64,
    )


def sign(receipt, key=KEY):
    return hmac.new(key, receipt.canonical_bytes(), hashlib.sha256).hexdigest()


def submit(host, ticket, receipt, signature=None, **extras):
    args = dict(
        receipt=receipt, signature=sign(receipt) if signature is None else signature,
        verification_key=KEY, owner_approved=True,
        independent_scorer_approved=True,
    )
    args.update(extras)
    return host.record_signed_truth(ticket, **args)


def test_signed_observer_truth_updates_existing_paired_quality_evaluator(tmp_path):
    host, ticket = host_and_ticket()
    evidence = receipt_for(ticket)
    assert evidence.canonical_bytes().startswith(
        b"star.stream.vision.truth.v1\0"
    )
    assert evidence.canonical_bytes() == receipt_for(ticket).canonical_bytes()
    verify_vision_truth_receipt(evidence, sign(evidence), verification_key=KEY)
    submit(host, ticket, evidence)
    report = host.owner_report(owner_approved=True)
    assert report["candidate"]["f1"] == 1
    assert report["baseline"]["f1"] == 1
    assert report["cases"] == 1
    assert host.metrics()["truth_labels"] == 1
    assert host.metrics()["signed_truth_labels"] == 1

    private = tmp_path / "vision-truth.jsonl"
    host.export_jsonl(private, owner_approved=True)
    cases = read_jsonl(private)
    assert cases[0].truth == (("hud_change", "hud"),)
    # Observer run IDs, evidence digests, MAC and the key never enter a trace.
    raw = private.read_text(encoding="ascii")
    for secret in ("engine-run-0001", "b" * 64, KEY.decode(), sign(evidence)):
        assert secret not in raw
    assert "frame_sha256" not in raw
    assert "observer_run_id" not in json.dumps(report)


def test_truth_cannot_be_written_before_freeze_or_without_host_consents():
    host, ticket = host_and_ticket(seal=False)
    r = receipt_for(ticket)
    with pytest.raises(PermissionError, match="freeze"):
        submit(host, ticket, r)
    host.seal_predictions()
    for fields in (
        dict(owner_approved=False),
        dict(independent_scorer_approved=False),
    ):
        with pytest.raises(PermissionError, match="approval"):
            submit(host, ticket, r, **fields)
    assert host.metrics()["unlabelled"] == 1
    submit(host, ticket, r)
    with pytest.raises(ValueError, match="replace"):
        submit(host, ticket, r)


@pytest.mark.parametrize("changes", [
    {"game_id": "other_game"},
    {"game_version": "v3"},
    {"trace_epoch": 9},
    {"trace_serial": 9},
    {"frame_sequence": 6},
    {"frame_sha256": "d" * 64},
    {"captured_ms": 2000.01},
])
def test_validly_signed_but_wrong_frame_scope_is_rejected(changes):
    host, ticket = host_and_ticket()
    wrong = replace(receipt_for(ticket), **changes)
    with pytest.raises(PermissionError, match="exact host frame"):
        submit(host, ticket, wrong)
    assert host.metrics()["unlabelled"] == 1


def test_tamper_wrong_signer_invalid_mac_and_replayed_ticket_are_denied():
    host, ticket = host_and_ticket()
    original = receipt_for(ticket)
    original_mac = sign(original)
    tampered = replace(original, evidence_sha256="c" * 64)
    with pytest.raises(PermissionError, match="did not verify"):
        submit(host, ticket, tampered, original_mac)
    with pytest.raises(PermissionError, match="did not verify"):
        submit(host, ticket, original, sign(original, OTHER_KEY))
    with pytest.raises(PermissionError, match="invalid independent truth signature"):
        submit(host, ticket, original, "INVALID")
    with pytest.raises(PermissionError):
        submit(host, VisionTraceTicket(ticket.epoch, ticket.serial), original)
    with pytest.raises(ValueError, match="32"):
        submit(host, ticket, original, verification_key=b"short")
    assert host.metrics()["unlabelled"] == 1
    submit(host, ticket, original)


def test_old_session_signed_truth_is_not_reusable_after_owner_stop():
    host, ticket = host_and_ticket()
    previous = receipt_for(ticket)
    old_mac = sign(previous)
    host.disable()
    host.enable(owner_approved=True, offline_capture_approved=True)
    successor = host.reserve(
        HostFrameRef(5, "a" * 64, 2000.0), capture_approved=True,
    )
    for variant in ("baseline", "candidate"):
        host.record_worker(
            successor, variant=variant,
            packet=None, status="timeout", started_ms=2010,
            finished_ms=2070, worker_stopped=True,
        )
    host.seal_predictions()
    with pytest.raises(PermissionError):
        submit(host, ticket, previous, old_mac)
    with pytest.raises(PermissionError, match="exact host frame"):
        submit(host, successor, previous, old_mac)
    submit(host, successor, receipt_for(successor))
    assert host.metrics()["truth_labels"] == 1


@pytest.mark.parametrize("changes", [
    {"trace_epoch": True},
    {"frame_sequence": 0},
    {"captured_ms": float("nan")},
    {"captured_ms": float("inf")},
    {"captured_ms": True},
    {"frame_sha256": "ABC"},
    {"evidence_sha256": "x" * 64},
    {"game_id": "../../leak"},
    {"observer_run_id": ""},
    {"truth_source": "model_self_report"},
    {"labels": (("unknown", "hud"),)},
    {"labels": (("hud_change", "hud"), ("hud_change", "hud"))},
    {"labels": (("menu_change", "hud"), ("hud_change", "hud"))},
    {"labels": ((True, "hud"),)},
    {"labels": tuple()},
])
def test_strict_categorical_receipt_validation(changes):
    good = receipt_for(VisionTraceTicket(1, 1))
    if changes == {"labels": tuple()}:
        # Empty labels are valid negatives, not missing evidence.
        empty = replace(good, **changes)
        assert empty.labels == ()
    else:
        with pytest.raises(ValueError):
            replace(good, **changes)


def test_signed_truth_must_be_exact_receipt_type():
    host, ticket = host_and_ticket()
    with pytest.raises(TypeError):
        submit(host, ticket, {"fake": "true"}, signature="a" * 64)
    with pytest.raises(TypeError):
        verify_vision_truth_receipt({"fake": "true"}, "a" * 64, verification_key=KEY)
