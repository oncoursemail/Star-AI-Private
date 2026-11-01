"""Offline Home-history provenance checks using temporary memory stores; no model calls."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star.inner import recall, reflect  # noqa: E402
from star.inner.store import InnerStore  # noqa: E402
from star.social.friends import FriendMemory  # noqa: E402


class ProvenanceChecks(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = datetime(2026, 10, 27, 1, tzinfo=timezone.utc).timestamp()
        root = Path(self.temp.name)
        self.store = InnerStore(root / "inner.sqlite3", clock=lambda: self.now)
        self.addCleanup(self.store.close)
        self.memory = FriendMemory(root / "friends.sqlite3", clock=lambda: self.now)
        self.addCleanup(self.memory.close)

    def run_history(self, rows):
        return reflect.run(self.store, self.memory, None, now=self.now, history=rows,
                           curiosity_path=Path(self.temp.name) / "curiosity.jsonl")

    def row(self, index=0, **changes):
        row = {"ts": f"2026-10-26T01:00:{index:02d}Z", "interest": "drawing", "verified": True,
               "summary": f"completed portrait export fixture {index}"}
        row.update(changes)
        return row

    def test_exact_boolean_true_is_required_for_reported_success_kind(self):
        values = [True, False, "false", "true", 1, 0, None, [], {}]
        rows = [self.row(i, verified=value) for i, value in enumerate(values)]
        self.run_history(rows)
        episodes = self.store.episodes(pkey="")
        self.assertEqual(len(episodes), len(values))
        for episode, value in zip(episodes, values):
            self.assertEqual(episode.kind, "home_verified" if value is True else "home_unverified")
            self.assertEqual(episode.importance, 0.5 if value is True else 0.35)
            line = recall.line_for(episode, self.now)
            self.assertIn("activity reported success" if value is True else "unverified activity report", line)
            self.assertNotIn(" you:", line)

    def test_missing_verification_stays_unverified(self):
        row = self.row()
        del row["verified"]
        self.run_history([row])
        episode = self.store.episodes()[0]
        self.assertEqual(episode.kind, "home_unverified")
        self.assertIn("unverified activity report", recall.line_for(episode, self.now))

    def test_unverified_completion_summary_is_rendered_as_report(self):
        self.run_history([self.row(verified=False, summary="successfully completed a finished landscape")])
        recalled = recall.recall(self.store, "", "remember the landscape?", now=self.now)
        self.assertEqual(len(recalled.lines), 1)
        self.assertIn("unverified activity report", recalled.lines[0])
        self.assertNotIn("you:", recalled.lines[0])
        self.assertNotIn("activity reported success", recalled.lines[0])

    def test_actual_history_time_is_preserved_in_store_and_recall(self):
        row = self.row()
        expected = datetime(2026, 10, 26, 1, tzinfo=timezone.utc).timestamp()
        self.run_history([row])
        episode = self.store.episodes()[0]
        self.assertEqual(episode.ts, expected)
        self.assertTrue(recall.line_for(episode, self.now).startswith("yesterday "))
        self.assertEqual(self.store.db.execute("SELECT src FROM episodes").fetchone()[0], f"h:{row['ts']}")

    def test_aware_offset_and_fractional_timestamps_keep_their_instant_and_source_id(self):
        stamp = "2026-10-25T20:00:00.125-05:00"
        self.run_history([self.row(ts=stamp)])
        episode = self.store.episodes()[0]
        self.assertEqual(episode.ts, datetime.fromisoformat(stamp).timestamp())
        self.assertEqual(self.store.db.execute("SELECT src FROM episodes").fetchone()[0], f"h:{stamp}")

    def test_bad_or_unknown_time_never_gets_reflection_time_as_event_time(self):
        stamps = [None, True, 1_800_000_000, "", "t1", "not a timestamp", "2026-10-26", "2026-10-26T01:00:00"]
        rows = [self.row(i, ts=stamp) for i, stamp in enumerate(stamps)]
        missing = self.row(20)
        del missing["ts"]
        self.run_history([*rows, missing])
        self.assertEqual(self.store.episodes(pkey=""), [])

    def test_history_is_validated_once_before_diary_opinions_and_episode_consumers(self):
        valid = self.row(verified="false", interest="drawing" * 10, summary="portrait" * 100)
        bad = [None, [], "report", self.row(1, ts="t1"), self.row(2, interest=None),
               self.row(3, summary=["finished"]), self.row(4, summary="\ud800"), self.row(5, interest="\udfff")]
        source = [valid, *bad]
        with (patch.object(reflect.opinions, "earn_from_history", return_value=0) as opinions_call,
              patch.object(reflect, "write_diary", return_value={"diary": "fixture", "notes": "", "opinions_moved": 0}) as diary_call):
            self.run_history(iter(source))
        filtered = opinions_call.call_args.args[1]
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["verified"], "false", "unknown status must not become boolean False")
        self.assertEqual(len(filtered[0]["interest"]), 40)
        self.assertEqual(len(filtered[0]["summary"]), 600)
        self.assertEqual(diary_call.call_args.kwargs["history"], filtered)
        self.assertEqual(len(self.store.episodes()), 1)
        self.assertEqual(self.store.episodes()[0].kind, "home_unverified")
        self.assertEqual(source[0]["interest"], "drawing" * 10, "normalization must preserve input rows")

    def test_replayed_history_is_idempotent_across_reflection_and_consolidation(self):
        rows = [self.row(0), self.row(1, verified=False), self.row(2, verified="false")]
        self.run_history(rows)
        initial = [(e.id, e.ts, e.kind, e.text) for e in self.store.episodes()]
        self.now += 3600
        self.run_history(rows)
        reflect.consolidate(self.store, self.now)
        self.assertEqual([(e.id, e.ts, e.kind, e.text) for e in self.store.episodes()], initial)
        self.assertEqual(self.store.db.execute("SELECT count(DISTINCT src) FROM episodes").fetchone()[0], 3)

    def test_distinct_home_events_keep_status_and_sources_even_with_identical_summary(self):
        rows = [self.row(0, summary="portrait exported"), self.row(1, summary="portrait exported", verified=False),
                self.row(2, summary="portrait exported")]
        self.run_history(rows)
        episodes = self.store.episodes()
        self.assertEqual(len(episodes), 3)
        self.assertEqual([e.kind for e in episodes], ["home_verified", "home_unverified", "home_verified"])
        self.assertEqual(reflect.consolidate(self.store, self.now)["merged"], 0)
        self.run_history(rows)
        self.assertEqual(len(self.store.episodes()), 3)

    def test_legacy_home_is_unverified_and_replay_does_not_promote_or_duplicate_it(self):
        row = self.row(summary="portrait exported")
        event_ts = datetime.fromisoformat(row["ts"]).timestamp()
        legacy_id = self.store.add_episode("", "drawing: portrait exported", kind="home", ts=event_ts,
                                           importance=0.5, src=f"h:{row['ts']}")
        self.run_history([row])
        episodes = self.store.episodes()
        self.assertEqual(len(episodes), 1)
        self.assertEqual((episodes[0].id, episodes[0].kind, episodes[0].ts), (legacy_id, "home", event_ts))
        self.assertIn("legacy unverified report", recall.line_for(episodes[0], self.now))
        self.assertNotIn("you:", recall.line_for(episodes[0], self.now))

    def test_existing_fact_and_moment_rendering_and_text_consolidation_stay_compatible(self):
        for kind in ("fact", "moment"):
            episode_id = self.store.add_episode("", f"my favorite topic is {kind}", kind=kind, ts=self.now)
            assert episode_id is not None
            episode = self.store.episode(episode_id)
            assert episode is not None
            self.assertEqual(recall.line_for(episode, self.now), f"today they said: my favorite topic is {kind}")
        self.store.add_episode("", "identical nonhome note", kind="moment", ts=self.now, src="fixture:1")
        self.store.add_episode("", "identical nonhome note", kind="moment", ts=self.now, src="fixture:2")
        self.assertEqual(reflect.consolidate(self.store, self.now)["merged"], 1)

    def test_all_provenance_labels_fit_line_budget_with_long_reports(self):
        for kind in ("home", "home_verified", "home_unverified", "fact", "moment"):
            episode_id = self.store.add_episode("", "landscape " * 100, kind=kind, ts=self.now)
            assert episode_id is not None
            episode = self.store.episode(episode_id)
            assert episode is not None
            for age in (0, 86400, 5 * 86400, 10 * 86400, 30 * 86400, 100 * 86400):
                line = recall.line_for(episode, self.now + age)
                self.assertLessEqual(len(line), recall.MAX_LINE)
                self.assertTrue(line.endswith("…"))
                if kind.startswith("home"):
                    self.assertNotIn("you:", line)


if __name__ == "__main__":
    unittest.main(verbosity=2)
