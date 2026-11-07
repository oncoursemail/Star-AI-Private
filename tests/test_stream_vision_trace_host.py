"""Synthetic offline contract tests for blind paired vision trace collection.

These tests DO NOT use real Roblox, Windows, OBS, game input or a vision model.
"""
import json
import os

import pytest

from star.stream_vision_trace_host import (
    HostFrameRef, PairedVisionTraceHost, VisionTraceTicket,
)
from star.stream_visual_perception import VisualFinding, VisualPacket
from star.stream_vision_eval import compare_vision, read_jsonl


def packet(ms, *kinds):
    findings = tuple(
        VisualFinding(kind, "hud" if kind != "unknown" else "world", .96)
        for kind in kinds
    )
    return VisualPacket(ms, 640, 360, findings)


def fresh_host(max_cases=512):
    host = PairedVisionTraceHost(game_id="private_obby", game_version="v1",
                                 max_cases=max_cases)
    host.enable(owner_approved=True, offline_capture_approved=True)
    return host


def reserve(host, i):
    ms = 1000 + i * 1000
    ticket = host.reserve(
        HostFrameRef(i + 1, f"{i + 1:064x}", ms),
        capture_approved=True,
    )
    return ticket, ms


def worker(host, ticket, ms, variant, *kinds, status="accepted",
           stopped=True, started_delta=20, finished_delta=70):
    host.record_worker(
        ticket, variant=variant,
        packet=packet(ms, *kinds) if status == "accepted" else None,
        status=status, started_ms=ms + started_delta,
        finished_ms=ms + finished_delta, worker_stopped=stopped,
    )


def test_blind_80_case_holdout_exports_and_scores_without_pictures(tmp_path):
    host = fresh_host()
    tickets = []
    for i in range(80):
        ticket, ms = reserve(host, i)
        tickets.append(ticket)
        positive = i % 2 == 0
        worker(host, ticket, ms, "baseline", "hud_change" if positive else "menu_change",
               finished_delta=140)
        worker(host, ticket, ms, "candidate", *(
            ["hud_change"] if positive else ["unknown"]
        ), finished_delta=90)

    with pytest.raises(PermissionError, match="freeze"):
        host.record_truth(tickets[0], labels=(("hud_change", "hud"),),
                          truth_source="studio_engine", independent_scorer=True)
    with pytest.raises(RuntimeError, match="no sealed cohort"):
        host.owner_report(owner_approved=True)

    host.seal_predictions()
    with pytest.raises(RuntimeError, match="frozen"):
        worker(host, tickets[0], 1000, "candidate", "hud_change")
    for i, ticket in enumerate(tickets):
        host.record_truth(
            ticket,
            labels=(("hud_change", "hud"),) if i % 2 == 0 else (),
            truth_source="studio_engine", independent_scorer=True,
        )
    report = host.owner_report(owner_approved=True)
    assert report["cases"] == 80
    assert report["positive_cases"] == 40
    assert report["candidate"]["f1"] == 1.0
    assert report["baseline"]["false_alert_rate"] == 1.0
    assert report["verdict"] == "eligible_for_manual_pilot"
    assert "case_00001" not in json.dumps(report)
    assert "truth" not in host.metrics()

    dest = tmp_path / "sealed.jsonl"
    assert host.export_jsonl(dest, owner_approved=True) == 80
    assert (os.stat(dest).st_mode & 0o777) == 0o600
    rows = read_jsonl(dest)
    assert len(rows) == 80
    assert compare_vision(rows).to_dict() == report
    assert all(row.game_id == "private_obby" for row in rows)
    with pytest.raises(FileExistsError):
        host.export_jsonl(dest, owner_approved=True)
    assert host.metrics()["exports"] == 1


def test_denies_unsanctioned_collection_leaked_truth_and_rewrite(tmp_path):
    host = PairedVisionTraceHost(game_id="obby", game_version="v1")
    with pytest.raises(PermissionError):
        host.enable(owner_approved=True, offline_capture_approved=False)
    host.enable(owner_approved=True, offline_capture_approved=True)
    with pytest.raises(PermissionError):
        host.reserve(HostFrameRef(1, "a" * 64, 100), capture_approved=False)
    ticket, ms = reserve(host, 0)
    worker(host, ticket, ms, "baseline", "unknown")
    with pytest.raises(ValueError, match="duplicate"):
        worker(host, ticket, ms, "baseline", "hud_change")
    with pytest.raises(PermissionError, match="worker stop"):
        worker(host, ticket, ms, "candidate", "hud_change", stopped=False)
    with pytest.raises(RuntimeError, match="both workers"):
        host.seal_predictions()
    worker(host, ticket, ms, "candidate", "unknown")
    host.seal_predictions()
    with pytest.raises(PermissionError):
        host.record_truth(ticket, labels=(), truth_source="studio_engine")
    with pytest.raises(ValueError, match="provenance"):
        host.record_truth(ticket, labels=(), truth_source="model_self_report",
                          independent_scorer=True)
    with pytest.raises(ValueError, match="categorical"):
        host.record_truth(ticket, labels=(("victory", "world"),),
                          truth_source="studio_engine", independent_scorer=True)
    host.record_truth(ticket, labels=(), truth_source="studio_engine",
                      independent_scorer=True)
    with pytest.raises(ValueError, match="replace"):
        host.record_truth(ticket, labels=(("hud_change", "hud"),),
                          truth_source="studio_engine", independent_scorer=True)
    with pytest.raises(PermissionError, match="owner"):
        host.owner_report()
    with pytest.raises(PermissionError, match="owner"):
        host.export_jsonl(tmp_path / "secret.jsonl")
    with pytest.raises(ValueError):
        host.export_jsonl(tmp_path / "secret.txt", owner_approved=True)
    original = tmp_path / "already.jsonl"
    original.write_text("preserve!", encoding="utf-8")
    symlink = tmp_path / "linked.jsonl"
    symlink.symlink_to(original)
    with pytest.raises(ValueError, match="symlinks"):
        host.export_jsonl(symlink, owner_approved=True)
    repository = tmp_path / "public_repo"
    repository.mkdir()
    (repository / ".git").write_text("gitdir: tracked", encoding="utf-8")
    with pytest.raises(ValueError, match="Git workspaces"):
        host.export_jsonl(repository / "private.jsonl", owner_approved=True)
    assert original.read_text() == "preserve!"


def test_frame_binding_no_replays_or_model_supplied_time():
    host = fresh_host()
    ticket, ms = reserve(host, 0)
    with pytest.raises(ValueError, match="replayed"):
        host.reserve(HostFrameRef(1, "f" * 64, ms), capture_approved=True)
    with pytest.raises(ValueError, match="duplicate frame"):
        host.reserve(HostFrameRef(2, f"{1:064x}", ms + 1), capture_approved=True)
    with pytest.raises(ValueError, match="out-of-order"):
        host.reserve(HostFrameRef(2, "2" * 64, ms - 1), capture_approved=True)
    with pytest.raises(ValueError, match="match"):
        host.record_worker(ticket, variant="baseline", packet=packet(ms + 1, "hud_change"),
                           status="accepted", started_ms=ms + 10,
                           finished_ms=ms + 20, worker_stopped=True)
    with pytest.raises(ValueError, match="timestamps"):
        worker(host, ticket, ms, "baseline", "unknown",
               started_delta=-2, finished_delta=30)
    with pytest.raises(ValueError, match="timestamps"):
        worker(host, ticket, ms, "baseline", "unknown",
               started_delta=20, finished_delta=120100)
    with pytest.raises(ValueError, match="concrete"):
        host.record_worker(ticket, variant="baseline", packet=None,
                           status="accepted", started_ms=ms + 2,
                           finished_ms=ms + 3, worker_stopped=True)
    with pytest.raises(ValueError):
        worker(host, ticket, ms, "WRONG", "unknown")
    worker(host, ticket, ms, "baseline", "unknown")
    worker(host, ticket, ms, "candidate", status="timeout")
    host.seal_predictions()
    host.record_truth(ticket, labels=(), truth_source="human_annotation",
                      independent_scorer=True)
    report = host.owner_report(owner_approved=True)
    assert report["candidate"]["failed_rate"] == 1
    assert host.metrics()["failed_workers"] == 1


def test_ticket_identity_and_revocation_clear_sensitive_holdout(tmp_path):
    host = fresh_host(max_cases=1)
    ticket, ms = reserve(host, 0)
    with pytest.raises(RuntimeError, match="full"):
        reserve(host, 1)
    # A copied ticket is NOT the original trusted-host handle.
    copy = VisionTraceTicket(ticket.epoch, ticket.serial)
    with pytest.raises(PermissionError):
        worker(host, copy, ms, "baseline", "unknown")
    worker(host, ticket, ms, "baseline", "unknown")
    worker(host, ticket, ms, "candidate", "unknown")
    host.disable()
    assert host.metrics()["cases"] == 0
    with pytest.raises(RuntimeError):
        host.owner_report(owner_approved=True)
    with pytest.raises(PermissionError):
        worker(host, ticket, ms, "baseline", "unknown")
    host.enable(owner_approved=True, offline_capture_approved=True)
    new, new_ms = reserve(host, 0)
    assert new.epoch != ticket.epoch
    worker(host, new, new_ms, "baseline", "unknown")
    worker(host, new, new_ms, "candidate", "unknown")


def test_invalid_frame_id_types_and_empty_cohort():
    host = fresh_host()
    with pytest.raises(RuntimeError, match="no active unsealed"):
        host.seal_predictions()
    for bad in (True, 0, -3, 1.5):
        with pytest.raises(ValueError):
            HostFrameRef(bad, "e" * 64, 200)
    for digest in ("A" * 64, "invalid", "", 4):
        with pytest.raises(ValueError):
            HostFrameRef(1, digest, 200)
    for t in (float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            HostFrameRef(1, "d" * 64, t)
