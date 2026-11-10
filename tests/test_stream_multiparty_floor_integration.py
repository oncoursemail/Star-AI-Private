from __future__ import annotations

from star.stream_brain_governor import StreamBrainGovernor
from star.stream_director import StreamSignal
from star.stream_hardware_telemetry import RealtimeTelemetryHost
from star.stream_multiparty_floor import FloorObservation, StreamMultipartyFloorGate
from star.stream_qos import AdaptiveQoS
from star.stream_stage import StarStage


class Rig:
    def __init__(self):
        self.now = 100_000.0
        self.cpu = (300, 1000)
        self.memory = (32768, 16000)
        self.hardware = RealtimeTelemetryHost(
            gpu_probe=lambda: {"vram_total_mib": 8192, "vram_used_mib": 2500},
            cpu_probe=lambda: self.cpu,
            memory_probe=lambda: self.memory,
            clock_ms=lambda: self.now,
        )
        self.stage = StarStage(clock=lambda: self.now / 1000)
        self.floor = StreamMultipartyFloorGate()
        self.governor = StreamBrainGovernor(
            telemetry=self.hardware,
            qos=AdaptiveQoS(),
            stage=self.stage,
            clock_ms=lambda: self.now,
            multiparty_floor=self.floor,
        )
        self.governor.enable(owner_approved=True, live=True, game_active=True)
        self.warm()

    def warm(self):
        assert self.hardware.refresh_hardware()
        self.cpu = (310, 1100)
        self.now += 100
        assert self.hardware.refresh_hardware()
        for _ in range(24):
            self.now += 16
            assert self.hardware.presented_frame(self.now)
        assert self.hardware.report_audio_backlog(backlog_ms=20, at_ms=self.now)
        self.cpu = (320, 1200)
        assert self.hardware.refresh_hardware()

    def signal(self, kind="viewer_question", ident="turn-0001"):
        return StreamSignal(
            ident, kind, self.now / 1000,
            "Where is the next checkpoint?",
            "session-speaker-slot-1" if kind.startswith("viewer") else "",
            "reported" if kind.startswith("viewer") else "observed",
        )

    def observation(self, signal, *, addressed_to="star", captured_ms=None, sequence=1):
        return FloorObservation(
            turn_id=signal.signal_id,
            session_epoch=self.floor.session_epoch,
            sequence=sequence,
            captured_ms=self.now if captured_ms is None else captured_ms,
            speaker_slot=1,
            addressed_to=addressed_to,
            speech_act="question",
            speaker_confidence=0.95,
            addressee_confidence=0.95,
            act_confidence=0.95,
        )


def test_spoken_question_addressed_to_star_enters_governed_stage():
    rig = Rig()
    signal = rig.signal()
    receipt = rig.observation(signal)
    assert rig.governor.offer(
        signal, moderated=True, spoken_turn=True, floor_observation=receipt
    )
    plan = rig.governor.prepare()
    assert plan is not None
    assert plan.signal_id == signal.signal_id
    assert rig.governor.status()["floor_admitted"] == 1


def test_spoken_question_addressed_to_another_person_never_enters_queue():
    rig = Rig()
    signal = rig.signal()
    receipt = rig.observation(signal, addressed_to="other")
    assert not rig.governor.offer(
        signal, moderated=True, spoken_turn=True, floor_observation=receipt
    )
    assert rig.governor.prepare() is None
    assert rig.governor.status()["floor_suppressed"] == 1


def test_group_address_and_overlap_are_suppressed():
    rig = Rig()
    group_signal = rig.signal(ident="turn-0001")
    group = rig.observation(group_signal, addressed_to="group")
    assert not rig.governor.offer(
        group_signal, moderated=True, spoken_turn=True, floor_observation=group
    )
    overlap_signal = rig.signal(ident="turn-0002")
    overlap = FloorObservation(
        turn_id=overlap_signal.signal_id,
        session_epoch=rig.floor.session_epoch,
        sequence=2,
        captured_ms=rig.now,
        speaker_slot=1,
        addressed_to="star",
        speech_act="question",
        speaker_confidence=0.95,
        addressee_confidence=0.95,
        act_confidence=0.95,
        active_speakers=2,
    )
    assert not rig.governor.offer(
        overlap_signal, moderated=True, spoken_turn=True, floor_observation=overlap
    )
    assert rig.governor.status()["floor_suppressed"] == 2


def test_spoken_turn_requires_receipt_moderation_and_exact_signal_binding():
    rig = Rig()
    signal = rig.signal()
    assert not rig.governor.offer(signal, moderated=True, spoken_turn=True)
    wrong = rig.observation(signal)
    wrong_id = FloorObservation(
        turn_id="turn-0002", session_epoch=wrong.session_epoch, sequence=1,
        captured_ms=wrong.captured_ms, speaker_slot=wrong.speaker_slot,
        addressed_to="star", speech_act="question", speaker_confidence=0.95,
        addressee_confidence=0.95, act_confidence=0.95,
    )
    assert not rig.governor.offer(
        signal, moderated=True, spoken_turn=True, floor_observation=wrong_id
    )
    assert not rig.governor.offer(
        signal, moderated=False, spoken_turn=True, floor_observation=wrong
    )
    assert rig.governor.status()["floor_missing"] == 1
    assert rig.governor.status()["floor_rejected"] == 2


def test_receipt_and_signal_must_share_the_same_monotonic_time():
    rig = Rig()
    signal = rig.signal()
    receipt = rig.observation(signal, captured_ms=rig.now + 500)
    assert not rig.governor.offer(
        signal, moderated=True, spoken_turn=True, floor_observation=receipt
    )
    assert rig.governor.status()["floor_rejected"] == 1


def test_ordinary_chat_and_owner_interrupt_paths_remain_compatible():
    rig = Rig()
    chat = rig.signal()
    assert rig.governor.offer(chat, moderated=True)
    rig.stage.finish(rig.governor.prepare(), now=rig.now / 1000, played_to_end=False)
    owner = StreamSignal(
        "owner-interrupt-1", "owner_interrupt", rig.now / 1000,
        "Please stop and listen.", "owner", "observed",
    )
    assert rig.governor.offer(owner, moderated=False)


def test_governor_disable_invalidates_the_floor_session():
    rig = Rig()
    old_epoch = rig.floor.session_epoch
    rig.governor.disable(audio_stopped_and_flushed=True)
    assert rig.floor.status()["enabled"] is False
    assert rig.floor.session_epoch != old_epoch
    signal = rig.signal()
    receipt = rig.observation(signal)
    assert rig.governor.offer(
        signal, moderated=True, spoken_turn=True, floor_observation=receipt
    ) is False


def test_spoken_turn_is_rejected_when_floor_gate_is_not_configured():
    now = 10_000.0
    hardware = RealtimeTelemetryHost(
        gpu_probe=lambda: {"vram_total_mib": 8192, "vram_used_mib": 2500},
        cpu_probe=lambda: (300, 1000),
        memory_probe=lambda: (32768, 16000),
        clock_ms=lambda: now,
    )
    stage = StarStage(clock=lambda: now / 1000)
    governor = StreamBrainGovernor(
        telemetry=hardware, qos=AdaptiveQoS(), stage=stage,
        clock_ms=lambda: now,
    )
    governor.enable(owner_approved=True, live=True, game_active=True)
    signal = StreamSignal(
        "turn-0001", "viewer_question", now / 1000, "Hello?",
        "session-speaker-slot-1", "reported",
    )
    assert not governor.offer(signal, moderated=True, spoken_turn=True)
    assert governor.status()["floor_missing"] == 1
