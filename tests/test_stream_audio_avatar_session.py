"""End-to-end offline tests with real stage, PCM clock and VTS protocol bridge.

No speaker, OBS, game controller, VTube Studio or network connection is used.
"""
from __future__ import annotations

import json
import unittest

from star.stream_audio_avatar_session import AudibleAvatarSession
from star.stream_audio_sample_host import DeviceAudibleSampleHost, DevicePlayoutEpoch
from star.stream_director import StreamSignal
from star.stream_motion import AudioLevel
from star.stream_playout_clock import StarPlayoutClock
from star.stream_stage import StarStage
from star.vtube_live2d_bridge import VTubeLive2DBridge
from star.vtube_local_host import VTubeLocalHost


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeVTSSocket:
    def __init__(self):
        self.sent = []
        self.closed = False
        self.timeout = 0
        self.fail_injections = False

    def send(self, raw):
        packet = json.loads(raw)
        if self.fail_injections and packet["messageType"] == "InjectParameterDataRequest":
            raise OSError("simulated VTS output loss")
        self.sent.append(packet)

    def recv(self):
        request = self.sent[-1]
        kind = request["messageType"]
        data = {}
        if kind == "APIStateRequest":
            data = {"active": True}
        elif kind == "AuthenticationRequest":
            data = {"authenticated": True}
        elif kind == "ParameterCreationRequest":
            data = {"parameterName": request["data"]["parameterName"]}
        return json.dumps({
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": request["requestID"],
            "messageType": kind.replace("Request", "Response"),
            "data": data,
        })

    def settimeout(self, seconds):
        self.timeout = seconds

    def close(self):
        self.closed = True

    def injections(self):
        return [p for p in self.sent
                if p["messageType"] == "InjectParameterDataRequest"]


def fixture(*, session_enabled=True, vts_connected=True, vts_registered=True):
    clock = Clock()
    stage = StarStage(clock=clock)
    stage.enable(owner_approved=True, mode="cat")
    assert stage.offer(StreamSignal(
        "game-1", "game_success", clock.now,
        "Host saw checkpoint", evidence="observed",
    ), now=clock.now)
    plan = stage.prepare(now=clock.now)
    assert plan
    assert stage.queue_audio(plan, now=clock.now)
    assert stage.acknowledge_audible(plan, now=clock.now)
    playout = StarPlayoutClock(stage, clock=clock)
    playout.enable(owner_approved=True)
    assert playout.arm(plan, duration_s=1, audio_levels=(
        AudioLevel(0, .72), AudioLevel(.1, .60), AudioLevel(.2, .4),
        AudioLevel(.4, 0.0),
    ))
    device = DeviceAudibleSampleHost(playout)
    device.enable(owner_approved=True)
    epoch = device.bind(plan, sample_rate_hz=48000, total_samples=48000)
    assert epoch
    bridge = VTubeLive2DBridge(stage, owner_approved=True)
    socket = FakeVTSSocket()
    renderer = VTubeLocalHost(
        bridge, owner_approved=True,
        socket_factory=lambda _url, _timeout: socket,
        monotonic=clock,
    )
    if vts_connected:
        assert renderer.connect(authentication_token="test-token") == "test-token"
        if vts_registered:
            renderer.register_parameters()
    session = AudibleAvatarSession(stage, device, renderer, clock=clock)
    if session_enabled:
        session.enable(owner_approved=True)
    return clock, stage, plan, device, epoch, socket, renderer, bridge, session


class EndToEndAvatarTests(unittest.TestCase):
    def test_disabled_by_default_and_owner_only(self):
        _, _, plan, _, epoch, _, _, _, session = fixture(session_enabled=False)
        self.assertFalse(session.bind(plan, epoch, playback_epoch="speech1"))
        with self.assertRaises(PermissionError):
            session.enable()
        with self.assertRaises(PermissionError):
            session.enable(owner_approved=1)
        session.enable(owner_approved=True)
        self.assertTrue(session.bind(plan, epoch, playback_epoch="speech1"))

    def test_all_three_hosts_share_exact_stage(self):
        clock, _, _, device, _, _, renderer, _, _ = fixture()
        other = StarStage(clock=clock)
        with self.assertRaises(ValueError):
            AudibleAvatarSession(other, device, renderer, clock=clock)

    def test_requires_connected_authenticated_vts(self):
        _, _, plan, _, epoch, _, _, _, session = fixture(vts_connected=False)
        self.assertFalse(session.bind(plan, epoch, playback_epoch="speech1"))

    def test_transport_without_registered_custom_parameters_is_not_ready(self):
        _, _, plan, _, epoch, _, renderer, _, session = fixture(
            vts_registered=False,
        )
        self.assertTrue(renderer.connected)
        self.assertFalse(renderer.ready)
        self.assertFalse(session.bind(plan, epoch, playback_epoch="speech1"))

    def test_device_revocation_mid_turn_closes_vts(self):
        clock, _, plan, device, epoch, socket, _, _, session = fixture()
        self.assertTrue(session.bind(plan, epoch, playback_epoch="speech1"))
        device.stop(epoch, output_stopped_and_flushed=True)
        self.assertFalse(session.render(epoch))
        self.assertTrue(socket.closed)
        self.assertEqual(session.metrics()["faults"], 1)

    def test_fresh_pcm_reaches_vts_mouth_with_authorized_epoch(self):
        clock, _, plan, _, epoch, socket, _, _, session = fixture()
        self.assertTrue(session.bind(plan, epoch, playback_epoch="speech1"))
        self.assertTrue(session.report_played(
            epoch, played_samples=2400, sampled_at=clock.now,
        ))
        self.assertTrue(session.render(epoch))
        inject = socket.injections()
        self.assertEqual(len(inject), 1)
        values = {p["id"]: p["value"] for p in inject[0]["data"]["parameterValues"]}
        self.assertGreater(values["StarMouthOpen"], 0)
        self.assertGreaterEqual(values["StarEyeOpenLeft"], 0)
        self.assertTrue(session.metrics()["active"])
        self.assertEqual(session.metrics()["rendered"], 1)
        # Same audible sample cannot be replayed to inflate expressions.
        self.assertFalse(session.render(epoch))
        self.assertEqual(len(socket.injections()), 1)

    def test_zero_samples_never_open_mouth_and_pause_holds_neutral(self):
        clock, _, plan, _, epoch, socket, _, _, session = fixture()
        self.assertTrue(session.bind(plan, epoch, playback_epoch="speech1"))
        self.assertTrue(session.report_played(epoch, played_samples=0,
                                              sampled_at=clock.now))
        self.assertFalse(session.render(epoch))
        self.assertEqual(len(socket.injections()), 1)
        first = socket.injections()[0]["data"]["parameterValues"]
        self.assertEqual({p["id"]: p["value"] for p in first}["StarMouthOpen"], 0)
        # Repeat silence does not overload the VTS socket.
        self.assertFalse(session.render(epoch))
        self.assertEqual(len(socket.injections()), 1)
        clock.advance(.05)
        self.assertTrue(session.report_played(epoch, played_samples=2400,
                                              sampled_at=clock.now))
        self.assertTrue(session.render(epoch))
        self.assertGreater(len(socket.injections()), 1)
        clock.advance(.05)
        self.assertTrue(session.report_played(
            epoch, played_samples=2400, sampled_at=clock.now, playing=False,
        ))
        newest = socket.injections()[-1]["data"]["parameterValues"]
        self.assertEqual({p["id"]: p["value"] for p in newest}["StarMouthOpen"], 0)
        self.assertFalse(session.render(epoch))

    def test_resume_same_epoch_after_pause_without_new_auth(self):
        clock, _, plan, _, epoch, socket, _, _, session = fixture()
        self.assertTrue(session.bind(plan, epoch, playback_epoch="speech1"))
        self.assertTrue(session.report_played(epoch, played_samples=2400,
                                              sampled_at=clock.now))
        self.assertTrue(session.render(epoch))
        clock.advance(.05)
        self.assertTrue(session.report_played(
            epoch, played_samples=2400, sampled_at=clock.now, playing=False,
        ))
        count = len(socket.injections())
        clock.advance(.05)
        self.assertTrue(session.report_played(
            epoch, played_samples=4800, sampled_at=clock.now, playing=True,
        ))
        self.assertTrue(session.render(epoch))
        self.assertEqual(len(socket.injections()), count + 1)
        self.assertFalse(socket.closed)

    def test_stalled_output_neutralizes_without_guessing_cursor(self):
        clock, _, plan, _, epoch, socket, _, _, session = fixture()
        session.bind(plan, epoch, playback_epoch="speech1")
        session.report_played(epoch, played_samples=2400, sampled_at=clock.now)
        self.assertTrue(session.render(epoch))
        clock.advance(.25)
        self.assertFalse(session.render(epoch))
        self.assertEqual(
            {p["id"]: p["value"] for p in socket.injections()[-1]["data"]["parameterValues"]}["StarMouthOpen"],
            0,
        )

    def test_other_epoch_cannot_cancel_or_drive_current_one(self):
        clock, _, plan, _, epoch, socket, _, _, session = fixture()
        session.bind(plan, epoch, playback_epoch="speech1")
        impostor = DevicePlayoutEpoch(epoch.sequence, epoch.generation,
                                     epoch.sample_rate_hz, epoch.total_samples)
        self.assertFalse(session.report_played(
            impostor, played_samples=2400, sampled_at=clock.now,
        ))
        self.assertFalse(session.render(impostor))
        self.assertFalse(session.end(impostor, output_stopped_and_flushed=True))
        self.assertFalse(socket.closed)
        self.assertTrue(session.report_played(
            epoch, played_samples=2400, sampled_at=clock.now,
        ))
        self.assertTrue(session.render(epoch))

    def test_invalid_device_feedback_fail_closes_vts_without_stopping_sound(self):
        clock, _, plan, _, epoch, socket, _, _, session = fixture()
        session.bind(plan, epoch, playback_epoch="speech1")
        self.assertFalse(session.report_played(
            epoch, played_samples=epoch.total_samples + 1,
            sampled_at=clock.now,
        ))
        self.assertTrue(socket.closed)
        self.assertFalse(session.render(epoch))
        self.assertTrue(session.metrics()["faulted"])
        # A physical stop/flush acknowledgement remains mandatory.
        with self.assertRaises(RuntimeError):
            session.end(epoch)
        self.assertTrue(session.end(epoch, output_stopped_and_flushed=True))
        self.assertFalse(session.metrics()["active"])

    def test_interrupt_closes_socket_and_suppresses_old_frames(self):
        clock, stage, plan, _, epoch, socket, _, _, session = fixture()
        session.bind(plan, epoch, playback_epoch="speech1")
        session.report_played(epoch, played_samples=2400, sampled_at=clock.now)
        self.assertTrue(session.render(epoch))
        stage.interrupt(now=clock.now)
        self.assertFalse(session.render(epoch))
        self.assertTrue(socket.closed)
        self.assertFalse(session.report_played(
            epoch, played_samples=4800, sampled_at=clock.now,
        ))
        session.end(epoch, output_stopped_and_flushed=True)

    def test_network_failure_closes_and_keeps_audio_stop_gate(self):
        clock, _, plan, _, epoch, socket, _, _, session = fixture()
        session.bind(plan, epoch, playback_epoch="speech1")
        session.report_played(epoch, played_samples=2400, sampled_at=clock.now)
        socket.fail_injections = True
        self.assertFalse(session.render(epoch))
        self.assertTrue(socket.closed)
        self.assertTrue(session.metrics()["faulted"])
        with self.assertRaises(RuntimeError):
            session.disable()
        session.disable(output_stopped_and_flushed=True)
        self.assertFalse(session.metrics()["enabled"])

    def test_stop_requires_real_audio_flush_and_sends_final_neutral(self):
        clock, _, plan, _, epoch, socket, _, _, session = fixture()
        session.bind(plan, epoch, playback_epoch="speech1")
        session.report_played(epoch, played_samples=2400, sampled_at=clock.now)
        self.assertTrue(session.render(epoch))
        with self.assertRaises(RuntimeError):
            session.disable()
        self.assertTrue(session.end(epoch, output_stopped_and_flushed=True))
        final = socket.injections()[-1]
        self.assertEqual(
            {p["id"]: p["value"] for p in final["data"]["parameterValues"]}["StarMouthOpen"], 0,
        )
        self.assertFalse(session.metrics()["active"])
        self.assertFalse(session.end(epoch, output_stopped_and_flushed=True))
        self.assertEqual(session.metrics()["stops"], 1)

    def test_hold_silence_is_host_attested_and_avoids_repeated_packets(self):
        clock, _, plan, _, epoch, socket, renderer, bridge, session = fixture()
        session.bind(plan, epoch, playback_epoch="speech1")
        with self.assertRaises(PermissionError):
            bridge.hold_silence(plan, playback_epoch="speech1", sampled_ms=100000)
        self.assertFalse(renderer.send_silence(
            plan, playback_epoch="incorrect", sampled_ms=100000,
            host_reports_no_fresh_playback=True,
        ))
        self.assertTrue(renderer.send_silence(
            plan, playback_epoch="speech1", sampled_ms=100000,
            host_reports_no_fresh_playback=True,
        ))
        self.assertFalse(renderer.send_silence(
            plan, playback_epoch="speech1", sampled_ms=100000,
            host_reports_no_fresh_playback=True,
        ))
        self.assertEqual(len(socket.injections()), 1)

    def test_no_raw_audio_or_credentials_in_metrics(self):
        clock, _, plan, _, epoch, socket, _, _, session = fixture()
        session.bind(plan, epoch, playback_epoch="speech1")
        session.report_played(epoch, played_samples=2400, sampled_at=clock.now)
        session.render(epoch)
        serialized = json.dumps(session.metrics())
        for secret in ("test-token", "speech1", "Host saw checkpoint"):
            self.assertNotIn(secret, serialized)


if __name__ == "__main__":
    unittest.main()
