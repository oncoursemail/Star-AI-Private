"""Offline, fake-Port tests for trusted-host Roblox Studio playtest dispatch.

No Roblox process, keyboard input, streaming, model, or network is contacted.
"""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor

import pytest

from star.game_action_gate import GameActionHint, GameFrame, GameScope
from star.stream_budget import StreamTelemetry
from star.studio_playtest_host import (
    StudioBinding, StudioPlaytestHost, StudioSnapshot,
)

SCOPE = GameScope("studio_demo", "v3", "session_1")
HASH = "c" * 64


def frame(seq=1, at=1000):
    return GameFrame(SCOPE, seq, at, HASH, True, True, .94)


def hint(f, action="jump", hold=70):
    return GameActionHint(action, f.sequence, f.evidence_sha256,
                          f.captured_ms + 10, hold)


def tele(fps=60, active=True):
    return StreamTelemetry(False, active, 4200, 8192, fps, 0)


class FakePort:
    def __init__(self):
        self.status = StudioSnapshot("studio_7", SCOPE, True, True, True, True)
        self.calls = []
        self.fail_down = False
        self.fail_up = False
        self.lose_focus_on_second_check = False
        self.snapshot_count = 0

    def snapshot(self, studio_id):
        self.snapshot_count += 1
        self.calls.append(("snapshot", studio_id))
        if self.lose_focus_on_second_check and self.snapshot_count == 2:
            return replace(self.status, focused=False)
        return self.status

    def key_down(self, studio_id, key):
        self.calls.append(("down", studio_id, key))
        if self.fail_down:
            raise OSError("fake transport down failure")

    def key_up(self, studio_id, key):
        self.calls.append(("up", studio_id, key))
        if self.fail_up:
            raise OSError("fake transport up failure")


def ready():
    now = [1020.0]
    host = StudioPlaytestHost(clock_ms=lambda: now[0],
                              sleeper=lambda seconds: now.__setitem__(
                                  0, now[0] + 1000 * seconds))
    host.start(studio_id="studio_7", scope=SCOPE,
               bindings=[StudioBinding("jump", "SPACE"),
                         StudioBinding("move_left", "A")],
               owner_approved=True)
    return host, now


def offer(host, *, seq=1, at=1000, action="jump", hold=70, time=1020):
    f = frame(seq, at)
    return host.request(f, hint(f, action, hold),
                        now_ms=time, host_verified=True, telemetry=tele())


def test_disabled_by_default_and_exact_owner_consent():
    host = StudioPlaytestHost()
    with pytest.raises(PermissionError):
        host.start(studio_id="studio_7", scope=SCOPE,
                   bindings=[StudioBinding("jump", "SPACE")])
    with pytest.raises(PermissionError):
        host.start(studio_id="studio_7", scope=SCOPE,
                   bindings=[StudioBinding("jump", "SPACE")],
                   owner_approved=1)
    assert not host.metrics()["enabled"]


@pytest.mark.parametrize("bad", ["ALT", "F4", "CTRL", "ENTER", "ESC", "DELETE", "W+E"])
def test_restrict_key_bindings(bad):
    with pytest.raises(ValueError):
        StudioBinding("jump", bad)


def test_private_studio_pulse_and_no_claim_of_game_success():
    host, now = ready()
    port = FakePort()
    permit = offer(host)
    assert permit.offered
    result = host.dispatch(permit, port=port)
    assert result.sent and result.input_released
    assert not result.gameplay_success_verified
    assert [entry[0] for entry in port.calls] == [
        "snapshot", "snapshot", "down", "up"]
    assert port.calls[2] == ("down", "studio_7", "SPACE")
    assert port.calls[3] == ("up", "studio_7", "SPACE")
    assert now[0] == pytest.approx(1090)
    assert host.metrics()["gate"]["released"] == 1
    assert not host.dispatch(permit, port=port).sent
    assert host.revoke(port=port)


def test_copying_or_forging_permit_cannot_trigger_keys():
    host, now = ready()
    port = FakePort()
    permit = offer(host)
    copied = replace(permit)
    assert not host.dispatch(copied, port=port).sent
    forged_action = replace(permit, action_id="move_left")
    assert not host.dispatch(forged_action, port=port).sent
    forged_hold = replace(permit, hold_ms=1)
    assert not host.dispatch(forged_hold, port=port).sent
    assert not any(x[0] == "down" for x in port.calls)
    assert host.dispatch(permit, port=port).sent
    assert port.calls[-2][2] == "SPACE"


@pytest.mark.parametrize("change", [
    {"playtesting": False}, {"focused": False},
    {"private_local_test": False}, {"owner_authorized": False},
    {"studio_id": "different"}, {"scope": GameScope("other", "v3", "session_1")},
])
def test_no_input_outside_exact_private_studio_playtest(change):
    host, _ = ready()
    port = FakePort()
    port.status = replace(port.status, **change)
    result = host.dispatch(offer(host), port=port)
    assert not result.sent
    assert result.reason == "not_authorized_private_studio_playtest"
    assert not any(entry[0] in {"down", "up"} for entry in port.calls)


def test_focus_loss_between_claim_and_input_releases_without_press():
    host, _ = ready()
    port = FakePort()
    port.lose_focus_on_second_check = True
    result = host.dispatch(offer(host), port=port)
    assert not result.sent and result.input_released
    assert result.reason == "playtest_focus_changed"
    assert not any(entry[0] == "down" for entry in port.calls)
    assert ("up", "studio_7", "SPACE") in port.calls


def test_key_down_exception_still_sends_key_up():
    host, _ = ready()
    port = FakePort()
    port.fail_down = True
    result = host.dispatch(offer(host), port=port)
    assert not result.sent and result.input_released
    assert any(row[0] == "up" for row in port.calls)
    assert not host.metrics()["key_release_pending"]


def test_failed_key_up_quarantines_and_operator_can_recover():
    host, now = ready()
    port = FakePort()
    port.fail_up = True
    result = host.dispatch(offer(host), port=port)
    assert not result.sent and not result.input_released
    assert host.metrics()["key_release_pending"]
    assert not host.revoke(port=port)
    with pytest.raises(RuntimeError):
        host.start(studio_id="studio_7", scope=SCOPE,
                   bindings=[StudioBinding("jump", "SPACE")],
                   owner_approved=True)
    port.fail_up = False
    assert host.recover_key_up(port=port)
    assert not host.metrics()["key_release_pending"]
    assert host.revoke(port=port)


def test_pressure_and_bad_proposal_do_not_send_any_keys():
    host, now = ready()
    port = FakePort()
    f = frame()
    rejected = host.request(f, hint(f, "open_chat"),
                            now_ms=now[0], host_verified=True, telemetry=tele())
    assert not rejected.offered
    assert not host.dispatch(rejected, port=port).sent
    pressure = host.request(f, hint(f), now_ms=now[0],
                            host_verified=True, telemetry=tele(fps=15))
    assert not pressure.offered
    assert not any(row[0] == "down" for row in port.calls)


def test_concurrent_dispatch_cannot_double_press():
    host, _ = ready()
    port = FakePort()
    permit = offer(host)
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(lambda _: host.dispatch(permit, port=port),
                                range(10)))
    assert sum(result.sent for result in results) == 1
    assert sum(row[0] == "down" for row in port.calls) == 1


def test_snapshot_and_bindings_strict_validation():
    with pytest.raises(ValueError):
        StudioSnapshot("studio_7", SCOPE, True, True, True, 1)
    host, _ = ready()
    with pytest.raises(RuntimeError):
        host.start(studio_id="studio_7", scope=SCOPE,
                   bindings=[StudioBinding("jump", "SPACE")],
                   owner_approved=True)
    assert host.revoke()
    with pytest.raises(ValueError):
        host.start(studio_id="studio_7", scope=SCOPE,
                   bindings=[StudioBinding("jump", "SPACE"),
                             StudioBinding("jump", "W")],
                   owner_approved=True)

def test_revoke_unclaimed_offer_clears_slot_without_ever_pressing_key():
    host, _ = ready()
    unused = offer(host)
    assert unused.offered
    assert host.revoke()
    host.start(studio_id="studio_7", scope=SCOPE,
               bindings=[StudioBinding("jump", "SPACE")],
               owner_approved=True)


def test_old_identity_rejected_after_new_studio_session():
    host, _ = ready()
    old = offer(host)
    host.revoke()
    host.start(studio_id="studio_7", scope=SCOPE,
               bindings=[StudioBinding("jump", "SPACE")],
               owner_approved=True)
    assert not host.dispatch(old, port=FakePort()).sent
