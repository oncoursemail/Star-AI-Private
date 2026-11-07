"""Temporary-database emotion persistence checks; no model, settings changes or eval fixtures."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star import emotion  # noqa: E402


class PersistenceChecks(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1_800_000_000.0
        self.path = Path(self.temp.name) / "emotion.sqlite3"
        self.engine = emotion.EmotionEngine(self.path, clock=lambda: self.now)
        self.warnings = patch.object(emotion._log, "warning")
        self.warnings.start()
        self.addCleanup(self.warnings.stop)

    def put(self, state):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("INSERT OR REPLACE INTO state(id,json) VALUES(1,?)", (json.dumps(state),))
            db.commit()

    def saved(self):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT json FROM state WHERE id=1").fetchone()
        return row[0] if row else None

    def assert_bounded(self, mood):
        self.assertTrue(all(math.isfinite(value) and 0 <= value <= emotion.CAPS.get(name, 1)
                            for name, value in mood["emotions"].items()))
        self.assertTrue(math.isfinite(mood["bond"]) and 0 <= mood["bond"] <= 1)
        self.assertTrue(math.isfinite(mood["valence"]) and -1 <= mood["valence"] <= 1)
        self.assertTrue(math.isfinite(mood["arousal"]) and 0 <= mood["arousal"] <= 1)
        json.dumps(emotion.prosody_dict(mood["prosody"]), allow_nan=False)

    def assert_recovers(self, state):
        self.put(state)
        stored = self.saved()
        snapshot = self.engine.snapshot("friend-1")
        self.assertEqual(snapshot["emotions"], emotion.BASELINE)
        self.assertEqual(snapshot["bond"], 0)
        self.assert_bounded(snapshot)
        self.assertEqual(self.saved(), stored, "snapshot must not repair the file by writing")
        updated = self.engine.on_event("owner_praise", person="friend-1")
        self.assert_bounded(updated)
        self.assertGreater(updated["emotions"]["joy"], emotion.BASELINE["joy"])
        repaired_text = self.saved()
        assert repaired_text is not None
        repaired = json.loads(repaired_text)
        json.dumps(repaired, allow_nan=False)
        restarted = emotion.EmotionEngine(self.path, clock=lambda: self.now)
        self.assertEqual(restarted.snapshot("friend-1"), updated)

    def test_malformed_nested_shapes_recover_and_next_event_persists(self):
        cases = [None, [], "state"]
        for key, value in (("e", None), ("drift", []), ("seen", []), ("bonds", []),
                           ("bonds", {"friend-1": []}), ("bonds", {"friend-1": [1]}),
                           ("bonds", {"friend-1": [0.2, self.now, 9]}),
                           ("bonds", {"friend-1": "12"}), ("amends", {}),
                           ("amends", [[]]), ("amends", [["friend-1"]]),
                           ("amends", [["friend-1", self.now, 9]]), ("amends", [[True, self.now]])):
            state = self.engine._fresh(self.now)
            state[key] = value
            cases.append(state)
        for index, state in enumerate(cases):
            with self.subTest(index=index):
                self.assert_recovers(state)

    def test_nonfinite_values_in_all_numeric_fields_recover(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            cases = []
            for key in ("t", "last_active", "last_tick", "valence", "arousal", "streak"):
                state = self.engine._fresh(self.now)
                state[key] = value
                cases.append(state)
            for key in ("e", "drift"):
                state = self.engine._fresh(self.now)
                state[key]["anger"] = value
                cases.append(state)
            state = self.engine._fresh(self.now)
            state["seen"]["owner_praise"] = value
            cases.append(state)
            for index in (0, 1):
                state = self.engine._fresh(self.now)
                state["bonds"]["friend-1"] = [0.5, self.now]
                state["bonds"]["friend-1"][index] = value
                cases.append(state)
            state = self.engine._fresh(self.now)
            state["amends"] = [["friend-1", value]]
            cases.append(state)
            for index, state in enumerate(cases):
                with self.subTest(value=value, field=index):
                    self.assert_recovers(state)

    def test_numeric_bounds_and_opaque_ids_are_checked(self):
        cases = []
        for key, value in (("valence", 2), ("valence", -2), ("arousal", -1),
                           ("arousal", 2), ("streak", -1), ("last_tick", 10 ** 400)):
            state = self.engine._fresh(self.now)
            state[key] = value
            cases.append(state)
        for key, name, value in (("e", "anger", 1000), ("e", "joy", -0.1),
                                 ("e", "jealousy", 0.6), ("drift", "joy", 0.11),
                                 ("drift", "joy", -0.11)):
            state = self.engine._fresh(self.now)
            state[key][name] = value
            cases.append(state)
        for person, pair in (("friend-1", [-1, self.now]), ("friend-1", [1.1, self.now]),
                             ("bad id", [0.5, self.now]), ("x" * 65, [0.5, self.now])):
            state = self.engine._fresh(self.now)
            state["bonds"][person] = pair
            cases.append(state)
        state = self.engine._fresh(self.now)
        state["amends"] = [["bad id", self.now]]
        cases.append(state)
        for index, state in enumerate(cases):
            with self.subTest(index=index):
                self.assert_recovers(state)

    def test_relationship_table_capacity_is_validated(self):
        state = self.engine._fresh(self.now)
        state["bonds"] = {f"friend-{i}": [0.5, self.now] for i in range(emotion.MAX_BONDS + 1)}
        self.assert_recovers(state)
        state = self.engine._fresh(self.now)
        state["amends"] = [[f"friend-{i}", self.now] for i in range(emotion.MAX_AMENDS + 1)]
        self.assert_recovers(state)

    def test_booleans_and_numeric_strings_are_not_saved_numeric_state(self):
        for value in (True, False, "0.5"):
            for key in ("t", "last_active", "last_tick", "valence", "arousal", "streak"):
                state = self.engine._fresh(self.now)
                state[key] = value
                with self.subTest(value=value, field=key):
                    self.assert_recovers(state)
            for key in ("e", "drift"):
                state = self.engine._fresh(self.now)
                state[key]["joy"] = value
                with self.subTest(value=value, field=key):
                    self.assert_recovers(state)
            for key, nested in (("seen", {"owner_praise": value}),
                                ("bonds", {"friend-1": [value, self.now]}),
                                ("bonds", {"friend-1": [0.5, value]}),
                                ("amends", [["friend-1", value]])):
                state = self.engine._fresh(self.now)
                state[key] = nested
                with self.subTest(value=value, field=key):
                    self.assert_recovers(state)

    def test_valid_boundary_state_is_preserved(self):
        state = self.engine._fresh(self.now)
        state["e"] = {name: emotion.CAPS.get(name, 1.0) for name in emotion.EMOTIONS}
        state["drift"] = {name: emotion.MAX_DRIFT for name in emotion.EMOTIONS}
        state.update(valence=-1, arousal=1)
        state["bonds"] = {f"friend-{i}": [1, self.now] for i in range(emotion.MAX_BONDS)}
        state["amends"] = [["", self.now], *[[f"friend-{i}", self.now] for i in range(emotion.MAX_AMENDS - 1)]]
        self.put(state)
        with self.engine._db() as db:
            self.assertEqual(self.engine._load(db, self.now), state)
        self.assert_bounded(self.engine.snapshot("friend-1"))

    def test_genuine_seven_emotion_schema_still_loads(self):
        state = self.engine._fresh(self.now)
        state["e"] = {name: state["e"][name] for name in
                      ("joy", "pride", "curiosity", "frustration", "boredom", "affection", "nervousness")}
        state["e"]["joy"] = 0.7
        state.pop("drift")
        state.pop("seen")
        state["bonds"] = {"friend-1": [0.6, self.now]}
        self.put(state)
        snapshot = self.engine.snapshot("friend-1")
        self.assertEqual(snapshot["emotions"]["joy"], 0.7)
        self.assertEqual(snapshot["emotions"]["sadness"], emotion.BASELINE["sadness"])
        self.assertEqual(snapshot["bond"], 0.6)
        self.assert_bounded(snapshot)
        state.pop("bonds")
        state.pop("amends")
        self.put(state)
        snapshot = self.engine.snapshot("friend-1")
        self.assertEqual(snapshot["emotions"]["joy"], 0.7)
        self.assertEqual(snapshot["bond"], 0)

    def test_clock_rollback_does_not_reset_valid_emotions_or_bond(self):
        mood = self.engine.on_event("owner_praise", person="friend-1")
        stored = self.saved()
        self.now -= 3600
        self.assertEqual(self.engine.snapshot("friend-1"), mood)
        self.assertEqual(self.saved(), stored)

    def test_strict_save_rejects_new_nonfinite_state_atomically(self):
        self.engine.on_event("owner_praise")
        stored, log = self.saved(), self.engine.history()
        with self.assertRaises(ValueError):
            self.engine._transaction(lambda state, now: state["drift"].update(anger=float("nan")))
        self.assertEqual(self.saved(), stored)
        self.assertEqual(self.engine.history(), log)

    def test_unused_extra_fields_cannot_poison_later_valid_saves(self):
        state = self.engine._fresh(self.now)
        state["e"]["joy"] = 0.7
        state["bonds"]["friend-1"] = [0.6, self.now]
        state["unused_extra"] = {"nonfinite": float("nan")}
        self.put(state)
        self.assertEqual(self.engine.snapshot()["emotions"]["joy"], 0.7)
        self.assertEqual(self.engine.snapshot("friend-1")["bond"], 0.6)
        self.engine.on_event("owner_praise")
        stored = self.saved()
        assert stored is not None
        recovered = json.loads(stored)
        self.assertNotIn("unused_extra", recovered)
        self.assertEqual(recovered["bonds"]["friend-1"], [0.6, self.now])
        json.dumps(recovered, allow_nan=False)

    def test_two_engine_instances_keep_concurrent_writes_valid(self):
        engines = [self.engine, emotion.EmotionEngine(self.path, clock=lambda: self.now)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: engines[i % 2].on_event("owner_praise", person=f"friend-{i}"), range(32)))
        self.assertEqual(len(self.engine.history(100)), 32)
        stored = self.saved()
        assert stored is not None
        state = json.loads(stored)
        self.assertEqual(len(state["bonds"]), 32)
        self.assert_bounded(self.engine.snapshot("friend-1"))

    def test_default_off_hook_still_creates_no_emotion_database(self):
        home = Path(self.temp.name) / "disabled"
        self.assertFalse(emotion.enabled(home))
        self.assertIsNone(emotion.on_event("owner_praise", home=home, only_if_enabled=True))
        self.assertFalse(home.exists())

    def test_nonfinite_or_boolean_clock_is_rejected_without_saving(self):
        self.engine.on_event("owner_praise")
        stored, log = self.saved(), self.engine.history()
        for value in (float("nan"), float("inf"), float("-inf"), True):
            self.now = value
            for call in (self.engine.snapshot, self.engine.tick,
                         lambda: self.engine.on_event("task_success")):
                with self.subTest(clock=value, call=call), self.assertRaises(ValueError):
                    call()
            self.assertEqual(self.saved(), stored)
            self.assertEqual(self.engine.history(), log)


if __name__ == "__main__":
    unittest.main(verbosity=2)
