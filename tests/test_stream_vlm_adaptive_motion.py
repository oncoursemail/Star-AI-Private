"""Offline A/B contracts for auto-selecting the sparse negative RGB prefilter.

No OS capture, private image, network, model server, GPU or streaming session.
The adapter is not enabled by default and cannot decide gameplay outcomes.
"""
from __future__ import annotations

import json

import pytest

from star.stream_local_vlm import LocalLlamaComparisonWorker
from star.stream_windows_game_capture import CapturedVisionFrame, WorkerReport


def _frame(ms: int, *, value: int = 20, size=(96, 72)) -> CapturedVisionFrame:
    w, h = size
    return CapturedVisionFrame(
        memoryview(bytes([value]) * (w * h * 3)), w, h, ms,
    )


def _patch_frame(ms: int, *, patch: bool) -> CapturedVisionFrame:
    w, h = 96, 72
    rgb = bytearray([45] * (w * h * 3))
    if patch:
        # A small high-contrast rectangle is entirely outside the 64 sampled
        # byte positions; matching sparse samples MUST NOT imply equality.
        samples = {i * (len(rgb) - 1) // 63 for i in range(64)}
        for y in range(19, 26):
            for x in range(38, 46):
                base = (y * w + x) * 3
                for channel, color in enumerate((255, 0, 0)):
                    if base + channel not in samples:
                        rgb[base + channel] = color
    return CapturedVisionFrame(memoryview(bytes(rgb)), w, h, ms)


def _reply() -> tuple[int, bytes]:
    content = json.dumps({"findings": [
        {"kind": "scene_change", "region": "world", "confidence": 0.91},
    ]})
    return 200, json.dumps({"choices": [{
        "finish_reason": "stop", "message": {"content": content},
    }]}).encode()


def _worker(*, adaptive: bool) -> tuple[LocalLlamaComparisonWorker, list[bytes]]:
    requests: list[bytes] = []

    def transport(body: bytes) -> tuple[int, bytes]:
        requests.append(body)
        return _reply()

    adapter = LocalLlamaComparisonWorker(
        model="local-vision", transport=transport, skip_identical=True,
        raw_exact_fast_path=True, raw_sparse_prescreen=True,
        adaptive_sparse_prescreen=adaptive,
    )
    adapter.enable(owner_approved=True, local_model_approved=True)
    return adapter, requests


@pytest.mark.parametrize("bad", [True, 1, "true", None])
def test_requires_explicit_sparse_dependency_and_bool(bad):
    kwargs = dict(model="local-vision", skip_identical=True,
                  raw_exact_fast_path=True, raw_sparse_prescreen=True)
    if bad is True:
        kwargs["raw_sparse_prescreen"] = False
    with pytest.raises(ValueError):
        LocalLlamaComparisonWorker(**kwargs, adaptive_sparse_prescreen=bad)


def test_default_off_and_optin_stationary_period_skips_extra_sampling():
    w = LocalLlamaComparisonWorker(
        model="local", skip_identical=True, raw_exact_fast_path=True,
        raw_sparse_prescreen=True,
    )
    assert not w.metrics()["adaptive_sparse_prescreen_enabled"]
    w, sent = _worker(adaptive=True)
    assert w(_frame(1000, value=10)) == WorkerReport(True, True)
    assert w(_frame(1500, value=40)).perception is not None
    first = w.metrics()
    assert first["adaptive_sparse_active"]
    assert first["sparse_checks"] == 0
    assert first["adaptive_motion_hints"] == 1

    # The moving pair pays for sparse checks; a mismatch can safely bypass
    # full SHA without skipping model requests.
    assert w(_frame(2000, value=70)).succeeded
    assert w(_frame(2300, value=120)).perception is not None
    second = w.metrics()
    assert second["sparse_checks"] >= 2
    assert second["sparse_mismatch_hash_skips"] >= 1

    # Two consecutive still comparisons switch the hint back to exact-only.
    assert w(_frame(2600, value=60)).succeeded
    assert w(_frame(2800, value=60)).succeeded
    assert w(_frame(2900, value=60)).succeeded
    still = w.metrics()
    assert not still["adaptive_sparse_active"]
    assert still["adaptive_still_hints"] >= 2
    before = still["sparse_checks"]
    assert w(_frame(3000, value=60)).succeeded
    after = w.metrics()
    assert after["sparse_checks"] == before
    assert after["raw_exact_fast_skips"] >= 1
    assert len(sent) == 2


def test_motion_restart_and_disable_clears_hints_without_neural_side_effects():
    w, sent = _worker(adaptive=True)
    w(_frame(1000, value=10))
    assert w(_frame(1200, value=70)).perception is not None
    assert w.metrics()["adaptive_sparse_active"]
    w.disable()
    assert not w.metrics()["adaptive_sparse_active"]
    assert w(_frame(1500, value=100)) == WorkerReport(True, False)
    w.enable(owner_approved=True, local_model_approved=True)
    assert not w.metrics()["adaptive_sparse_active"]
    w(_frame(2000, value=60))
    assert w(_frame(2300, value=80)).perception is not None
    assert len(sent) == 2
    assert w.metrics()["adaptive_sparse_active"]


def test_geometry_or_clock_reset_does_not_carry_motion_hint():
    w, sent = _worker(adaptive=True)
    w(_frame(1000, value=10))
    w(_frame(1400, value=90))
    assert w.metrics()["adaptive_sparse_active"]
    w(_frame(2000, size=(100, 80)))
    w(_frame(2500, size=(96, 72)))
    assert not w.metrics()["adaptive_sparse_active"]
    assert not sent[-1:] or len(sent) == 1


def test_unsampled_region_edit_never_fools_exact_equality_gate():
    w, sent = _worker(adaptive=True)
    raw = _patch_frame(1000, patch=False)
    patch = _patch_frame(1500, patch=True)
    assert w._sparse_digest(raw.rgb) == w._sparse_digest(patch.rgb)
    assert w(raw).perception is None
    assert w(patch).perception is not None
    assert len(sent) == 1
    assert w.metrics()["adaptive_motion_hints"] == 1
    assert w.metrics()["raw_exact_fast_skips"] == 0


def test_deterministic_replay_equal_dispatches_to_fixed_sparse_mode():
    adaptive, auto_sent = _worker(adaptive=True)
    fixed, fixed_sent = _worker(adaptive=False)
    states = [10, 10, 10, 30, 40, 40, 40, 90, 90, 10, 10,
              10, 120, 121, 121, 121, 121, 5, 5, 5, 120]
    a, b = [], []
    for index, value in enumerate(states):
        snap = _frame(1000 + 200 * index, value=value)
        x = adaptive(snap)
        y = fixed(snap)
        a.append((x.stopped, x.succeeded, x.perception))
        b.append((y.stopped, y.succeeded, y.perception))
    assert a == b, "adaptive mode may change CPU work but never model semantics"
    assert auto_sent == fixed_sent
    assert adaptive.metrics()["requests"] == fixed.metrics()["requests"]
    assert adaptive.metrics()["identical_pairs_skipped"] == fixed.metrics()["identical_pairs_skipped"]
    assert adaptive.metrics()["sparse_checks"] < fixed.metrics()["sparse_checks"]


def test_missing_owner_consent_still_fails_closed():
    adapter = LocalLlamaComparisonWorker(
        model="local", skip_identical=True,
        raw_exact_fast_path=True, raw_sparse_prescreen=True,
        adaptive_sparse_prescreen=True,
    )
    assert adapter(_frame(1000)) == WorkerReport(True, False)
    with pytest.raises(PermissionError):
        adapter.enable(owner_approved=True)
