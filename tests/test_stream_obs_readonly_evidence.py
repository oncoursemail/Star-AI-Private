"""Offline contract tests for OBS v5 read-only measurement; no sockets, media or streams."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import unittest

from star.stream_obs_readonly_evidence import (
    ObsReadOnlyEvidenceGate,
    ObsReadOnlyWitness,
)
from star.stream_rehearsal_recorder import StreamRehearsalRecorder


_TYPES = ("GetStats", "GetStreamStatus", "GetRecordStatus")


def triplet(
    *, sequence=1, at=1000.0, render=(2, 100), output=(0, 0),
    stream_active=False, recording_active=False,
):
    ids = {kind: f"req_{sequence}_{i}" for i, kind in enumerate(_TYPES)}
    bodies = {
        "GetStats": {
            "renderSkippedFrames": render[0], "renderTotalFrames": render[1],
            "outputSkippedFrames": output[0], "outputTotalFrames": output[1],
            "cpuUsage": 8.2, "activeFps": 59.8,
        },
        "GetStreamStatus": {"outputActive": stream_active},
        "GetRecordStatus": {"outputActive": recording_active},
    }
    samples = {}
    for i, kind in enumerate(_TYPES):
        samples[kind] = ObsReadOnlyWitness(at + i * 10, {
            "op": 7,
            "d": {
                "requestType": kind, "requestId": ids[kind],
                "requestStatus": {"result": True, "code": 100},
                "responseData": bodies[kind],
            },
        })
    return samples, ids


def override_message(samples, kind, **changes):
    original = samples[kind]
    msg = dict(original.message)
    msg.update(changes)
    samples[kind] = ObsReadOnlyWitness(original.at_monotonic_ms, msg)


def override_data(samples, kind, **changes):
    original = samples[kind]
    msg = dict(original.message)
    data = dict(msg["d"])
    data.update(changes)
    msg["d"] = data
    samples[kind] = ObsReadOnlyWitness(original.at_monotonic_ms, msg)


def override_body(samples, kind, **changes):
    original = samples[kind]
    msg = dict(original.message)
    data = dict(msg["d"])
    body = dict(data["responseData"])
    body.update(changes)
    data["responseData"] = body
    msg["d"] = data
    samples[kind] = ObsReadOnlyWitness(original.at_monotonic_ms, msg)


class TestObsReadOnlyEvidence(unittest.TestCase):
    def gate(self, **kwargs):
        return ObsReadOnlyEvidenceGate(owner_approved=True, **kwargs)

    def accept(self, gate, *, samples=None, ids=None, **kwargs):
        if samples is None:
            samples, ids = triplet()
        assert ids is not None
        return gate.accept(
            witnesses=samples, expected_request_ids=ids, host_verified=True, **kwargs,
        )

    def test_off_by_default_and_host_verified_not_magic(self):
        with self.assertRaises(PermissionError):
            ObsReadOnlyEvidenceGate()
        gate = self.gate()
        samples, ids = triplet()
        with self.assertRaises(PermissionError):
            gate.accept(witnesses=samples, expected_request_ids=ids)
        self.assertEqual(gate.report()["sample_count"], 0)

    def test_accept_only_three_offline_v5_responses(self):
        gate = self.gate()
        s1, ids1 = triplet()
        first = self.accept(gate, samples=s1, ids=ids1)
        self.assertEqual(first.render_total_frames, 100)
        s2, ids2 = triplet(sequence=2, at=2000, render=(5, 160), output=(2, 50))
        second = self.accept(gate, samples=s2, ids=ids2)
        self.assertEqual(second.output_total_frames, 50)
        report = gate.report()
        self.assertEqual(report["sample_count"], 2)
        self.assertEqual(report["render_skipped_fraction"], 0.05)
        self.assertEqual(report["output_skipped_fraction"], 0.04)
        self.assertTrue(report["nonbroadcast_verified_only_at_sample_times"])
        public = json.dumps(report)
        for sensitive in (*ids1.values(), *ids2.values(), "cpuUsage", "activeFps"):
            self.assertNotIn(sensitive, public)

    def test_render_stats_go_to_rehearsal_not_output_encoder_stats(self):
        gate = self.gate()
        recorder = StreamRehearsalRecorder(episode_id="obs_test", owner_approved=True)
        recorder.record("scene_observed", at_ms=900, host_verified=True, scene_sequence=1)
        s1, i1 = triplet()
        self.accept(gate, samples=s1, ids=i1, recorder=recorder)
        s2, i2 = triplet(sequence=2, at=1050, render=(4, 200), output=(80, 100))
        self.accept(gate, samples=s2, ids=i2, recorder=recorder)
        recorder.end(at_ms=1200, host_verified=True)
        self.assertEqual(recorder.report()["obs_skipped_fraction"], 0.02)
        self.assertEqual(gate.report()["render_skipped_fraction"], 0.02)
        self.assertEqual(gate.report()["output_skipped_fraction"], 0.8)
        self.assertEqual(recorder.report()["obs_samples"], 2)

    def test_rejected_downstream_record_does_not_advance_gate(self):
        gate = self.gate()
        recorder = StreamRehearsalRecorder(episode_id="obs_test", owner_approved=True)
        recorder.record("scene_observed", at_ms=9000, host_verified=True, scene_sequence=1)
        samples, ids = triplet()
        with self.assertRaises(ValueError):
            self.accept(gate, samples=samples, ids=ids, recorder=recorder)
        self.assertEqual(gate.report()["sample_count"], 0)
        self.assertEqual(recorder.report()["obs_samples"], 0)
        self.accept(gate, samples=samples, ids=ids)
        self.assertEqual(gate.report()["sample_count"], 1)

    def test_streaming_active_record_active_paused_record_still_rejected(self):
        for override in (
            {"stream_active": True},
            {"recording_active": True},
            {"stream_active": None},
            {"recording_active": 0},
        ):
            with self.subTest(override=override):
                gate = self.gate()
                samples, ids = triplet(**override)
                with self.assertRaises(PermissionError):
                    self.accept(gate, samples=samples, ids=ids)
                self.assertEqual(gate.report()["sample_count"], 0)

        samples, ids = triplet(recording_active=True)
        override_body(samples, "GetRecordStatus", outputPaused=True)
        with self.assertRaises(PermissionError):
            self.accept(self.gate(), samples=samples, ids=ids)

    def test_nonread_only_request_or_mismatched_ids_not_accepted(self):
        for kind in _TYPES:
            with self.subTest(kind=kind):
                samples, ids = triplet()
                override_data(samples, kind, requestType="StartStream")
                with self.assertRaises(ValueError):
                    self.accept(self.gate(), samples=samples, ids=ids)
        samples, ids = triplet()
        ids["GetStreamStatus"] = ids["GetStats"]
        with self.assertRaises(ValueError):
            self.accept(self.gate(), samples=samples, ids=ids)
        samples, ids = triplet()
        override_data(samples, "GetStats", requestId="old_req")
        with self.assertRaises(ValueError):
            self.accept(self.gate(), samples=samples, ids=ids)

    def test_replay_ids_and_reversed_time_fail_without_mutation(self):
        gate = self.gate()
        samples, ids = triplet()
        self.accept(gate, samples=samples, ids=ids)
        with self.assertRaises(ValueError):
            self.accept(gate, samples=samples, ids=ids)
        older, older_ids = triplet(sequence=2, at=900, render=(4, 200))
        with self.assertRaises(ValueError):
            self.accept(gate, samples=older, ids=older_ids)
        later, later_ids = triplet(sequence=2, at=1600, render=(4, 200))
        self.accept(gate, samples=later, ids=later_ids)
        self.assertEqual(gate.report()["sample_count"], 2)

    def test_concurrent_duplicate_triplet_only_once_accepted(self):
        gate = self.gate()
        samples, ids = triplet()

        def try_accept(_):
            try:
                self.accept(gate, samples=samples, ids=ids)
                return True
            except ValueError:
                return False

        with ThreadPoolExecutor(max_workers=6) as pool:
            accepted = list(pool.map(try_accept, range(6)))
        self.assertEqual(accepted.count(True), 1)
        self.assertEqual(gate.report()["sample_count"], 1)

    def test_cross_triplet_stale_partial_response_and_long_gap_rejected(self):
        gate = self.gate()
        self.accept(gate)
        # Last first-triplet receipt is t=1020. A second GetStats response at
        # 1010 is stale even when later stream/record responses are fresh.
        mixed, ids = triplet(sequence=2, at=1010, render=(4, 200))
        with self.assertRaises(ValueError):
            self.accept(gate, samples=mixed, ids=ids)
        gap, gap_ids = triplet(sequence=2, at=12000, render=(4, 200))
        with self.assertRaises(ValueError):
            self.accept(gate, samples=gap, ids=gap_ids)
        fresh, fresh_ids = triplet(sequence=2, at=2000, render=(4, 200))
        self.accept(gate, samples=fresh, ids=fresh_ids)
        self.assertEqual(gate.report()["sample_count"], 2)

    def test_reset_wrap_and_impossible_skips_rejected(self):
        gate = self.gate()
        self.accept(gate)
        for rendering, output in (
            ((2, 99), (0, 0)),
            ((200, 201), (0, 0)),
            ((4, 101), (0, 0)),
            ((4, 200), (1, 0)),
        ):
            with self.subTest(rendering=rendering, output=output):
                samples, ids = triplet(sequence=2, at=2000, render=rendering, output=output)
                with self.assertRaises(ValueError):
                    self.accept(gate, samples=samples, ids=ids)
                self.assertEqual(gate.report()["sample_count"], 1)
        valid, ids = triplet(sequence=2, at=2000, render=(4, 200))
        self.accept(gate, samples=valid, ids=ids)
        self.assertEqual(gate.report()["sample_count"], 2)

    def test_encoder_counters_cannot_reset_or_skip_without_frames(self):
        gate = self.gate()
        s1, i1 = triplet(output=(1, 50))
        self.accept(gate, samples=s1, ids=i1)
        for output in ((0, 50), (2, 50), (1, 49)):
            with self.subTest(output=output):
                s2, i2 = triplet(sequence=2, at=2000, render=(3, 200), output=output)
                with self.assertRaises(ValueError):
                    self.accept(gate, samples=s2, ids=i2)
        s2, i2 = triplet(sequence=2, at=2000, render=(3, 200), output=(1, 50))
        self.accept(gate, samples=s2, ids=i2)
        self.assertIsNone(gate.report()["output_skipped_fraction"])

    def test_missing_status_body_or_false_request_status(self):
        for change in (
            {"result": False, "code": 608},
            {"result": True, "code": 500},
            {"result": 1, "code": 100},
            {"result": True, "code": True},
        ):
            samples, ids = triplet()
            override_data(samples, "GetStats", requestStatus=change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.accept(self.gate(), samples=samples, ids=ids)
        samples, ids = triplet()
        override_data(samples, "GetStats", responseData=None)
        with self.assertRaises(ValueError):
            self.accept(self.gate(), samples=samples, ids=ids)

    def test_wrong_opcode_missing_and_untrusted_body(self):
        samples, ids = triplet()
        override_message(samples, "GetStreamStatus", op=6)
        with self.assertRaises(ValueError):
            self.accept(self.gate(), samples=samples, ids=ids)
        samples, ids = triplet()
        del samples["GetRecordStatus"]
        with self.assertRaises(ValueError):
            self.accept(self.gate(), samples=samples, ids=ids)
        samples, ids = triplet()
        samples["StartStream"] = samples.pop("GetRecordStatus")
        with self.assertRaises(ValueError):
            self.accept(self.gate(), samples=samples, ids=ids)

    def test_numeric_and_missing_counter_fail_closed(self):
        for value in (True, False, -1, 3.1, float("nan"), float("inf"), 10**20, "4"):
            samples, ids = triplet()
            override_body(samples, "GetStats", renderSkippedFrames=value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.accept(self.gate(), samples=samples, ids=ids)
        samples, ids = triplet()
        override_body(samples, "GetStats", renderTotalFrames=100.0)
        self.accept(self.gate(), samples=samples, ids=ids)
        samples, ids = triplet()
        body = dict(samples["GetStats"].message["d"]["responseData"])
        del body["renderTotalFrames"]
        override_body(samples, "GetStats", **body)
        msg = dict(samples["GetStats"].message)
        data = dict(msg["d"])
        del data["responseData"]["renderTotalFrames"]
        with self.assertRaises(ValueError):
            self.accept(self.gate(), samples=samples, ids=ids)

    def test_response_skew_and_invalid_clock(self):
        samples, ids = triplet()
        s = samples["GetRecordStatus"]
        samples["GetRecordStatus"] = ObsReadOnlyWitness(999999, s.message)
        with self.assertRaises(ValueError):
            self.accept(self.gate(), samples=samples, ids=ids)
        for at in (float("nan"), float("inf"), -1, True, "1"):
            samples, ids = triplet()
            s = samples["GetStats"]
            samples["GetStats"] = ObsReadOnlyWitness(at, s.message)
            with self.subTest(at=at), self.assertRaises(ValueError):
                self.accept(self.gate(), samples=samples, ids=ids)

    def test_bounded_samples_and_config(self):
        for config in ({"max_samples": 1}, {"max_samples": True},
                       {"max_response_span_ms": -1}, {"max_response_span_ms": 6000}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                self.gate(**config)
        gate = self.gate(max_samples=2)
        for sequence in (1, 2):
            samples, ids = triplet(sequence=sequence, at=1000 * sequence,
                                   render=(sequence, sequence * 100))
            self.accept(gate, samples=samples, ids=ids)
        samples, ids = triplet(sequence=3, at=3000, render=(3, 300))
        with self.assertRaises(RuntimeError):
            self.accept(gate, samples=samples, ids=ids)
        self.assertEqual(gate.report()["sample_count"], 2)

    def test_explicit_correlators_cannot_be_content_or_reused(self):
        gate = self.gate()
        for value in ("Viewer: name", "a" * 100, "", "🔑", False):
            samples, ids = triplet()
            ids["GetStats"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.accept(gate, samples=samples, ids=ids)
        self.assertEqual(gate.report()["sample_count"], 0)


class PrivateRecordingWitnessTests(unittest.TestCase):
    def gate(self, **kwargs):
        return ObsReadOnlyEvidenceGate(owner_approved=True, **kwargs)

    def accept(self, gate, *, samples, ids):
        return gate.accept(witnesses=samples, expected_request_ids=ids,
                           host_verified=True)

    def _triplet(self, index: int, *, recording: bool, paused: object = False,
                 streaming: bool = False):
        start = float(index * 1000)
        ids = {kind: f"private{index}{j}" for j, kind in
               enumerate(("GetStats", "GetStreamStatus", "GetRecordStatus"))}
        bodies = {
            "GetStats": {
                "renderSkippedFrames": 0, "renderTotalFrames": index * 60,
                "outputSkippedFrames": 0, "outputTotalFrames": index * 60,
            },
            "GetStreamStatus": {"outputActive": streaming},
            "GetRecordStatus": {"outputActive": recording, "outputPaused": paused},
        }
        return (
            {kind: ObsReadOnlyWitness(start + j, {
                "op": 7, "d": {
                    "requestType": kind, "requestId": ids[kind],
                    "requestStatus": {"result": True, "code": 100},
                    "responseData": bodies[kind],
                }
            }) for j, kind in enumerate(ids)}, ids
        )

    def test_recording_opt_in_requires_two_fresh_active_unpaused_samples(self):
        gate = ObsReadOnlyEvidenceGate(
            owner_approved=True, require_private_recording=True,
        )
        for i in (1, 2):
            witnesses, ids = self._triplet(i, recording=True)
            gate.accept(witnesses=witnesses, expected_request_ids=ids, host_verified=True)
        report = gate.report()
        self.assertEqual(report["sample_count"], 2)
        self.assertTrue(report["private_recording_verified_only_at_sample_times"])
        self.assertTrue(report["nonbroadcast_verified_only_at_sample_times"])

    def test_private_recording_off_by_default_and_strict_mode(self):
        with self.assertRaises(ValueError):
            ObsReadOnlyEvidenceGate(owner_approved=True, require_private_recording=1)
        inactive = ObsReadOnlyEvidenceGate(owner_approved=True)
        witnesses, ids = self._triplet(1, recording=True)
        with self.assertRaises(PermissionError):
            inactive.accept(witnesses=witnesses, expected_request_ids=ids,
                            host_verified=True)
        self.assertEqual(inactive.report()["sample_count"], 0)

    def test_private_recording_not_paused_absent_or_broadcast(self):
        for paused, streaming in ((True, False), (None, False), (False, True)):
            gate = ObsReadOnlyEvidenceGate(owner_approved=True,
                                           require_private_recording=True)
            witnesses, ids = self._triplet(1, recording=True, paused=paused,
                                          streaming=streaming)
            with self.subTest(paused=paused, streaming=streaming):
                with self.assertRaises(PermissionError):
                    gate.accept(witnesses=witnesses, expected_request_ids=ids,
                                host_verified=True)
                self.assertEqual(gate.report()["sample_count"], 0)


    def test_private_progress_requires_explicit_private_mode(self):
        with self.assertRaises(ValueError):
            self.gate(require_recording_progress=True)
        with self.assertRaises(ValueError):
            self.gate(require_private_recording=True, require_recording_progress=1)

    def test_private_progress_rejects_missing_malformed_and_stale_counters(self):
        gate = self.gate(require_private_recording=True, require_recording_progress=True)
        s1, i1 = triplet(recording_active=True)
        override_body(s1, "GetRecordStatus", outputPaused=False,
                      outputDuration=1000, outputBytes=4096)
        self.accept(gate, samples=s1, ids=i1)
        for corrupt in (
            {"outputDuration": 1000, "outputBytes": 5000},
            {"outputDuration": 800, "outputBytes": 5000},
            {"outputDuration": 1300, "outputBytes": 4000},
            {"outputDuration": 1300, "outputBytes": True},
            {"outputDuration": "1300", "outputBytes": 5000},
            {"outputDuration": 1300.5, "outputBytes": 5000},
            {"outputDuration": 9000, "outputBytes": 5000},
        ):
            sample, ids = triplet(sequence=2, at=2000, render=(4, 200), recording_active=True)
            override_body(sample, "GetRecordStatus", outputPaused=False, **corrupt)
            with self.subTest(corrupt=corrupt), self.assertRaises(ValueError):
                self.accept(gate, samples=sample, ids=ids)
            self.assertEqual(gate.report()["sample_count"], 1)
        fresh, ids = triplet(sequence=2, at=2000, render=(4, 200), recording_active=True)
        override_body(fresh, "GetRecordStatus", outputPaused=False,
                      outputDuration=1300, outputBytes=5000)
        self.accept(gate, samples=fresh, ids=ids)
        self.assertTrue(gate.report()["recording_progress_verified_only_at_sample_times"])

    def test_private_progress_no_media_bytes_requires_deferred_report(self):
        gate = self.gate(require_private_recording=True, require_recording_progress=True)
        for seq, at, duration, total in ((1, 1000, 100, 100), (2, 2000, 400, 200)):
            samples, ids = triplet(sequence=seq, at=at, render=(0, total),
                                   recording_active=True)
            override_body(samples, "GetRecordStatus", outputPaused=False,
                          outputDuration=duration, outputBytes=0)
            self.accept(gate, samples=samples, ids=ids)
        self.assertFalse(gate.report()["recording_progress_verified_only_at_sample_times"])
        samples, ids = triplet(sequence=3, at=3000, render=(0, 300), recording_active=True)
        override_body(samples, "GetRecordStatus", outputPaused=False,
                      outputDuration=700, outputBytes=4096)
        self.accept(gate, samples=samples, ids=ids)
        self.assertTrue(gate.report()["recording_progress_verified_only_at_sample_times"])
        self.assertNotIn("4096", json.dumps(gate.report()))

if __name__ == "__main__":
    unittest.main()
