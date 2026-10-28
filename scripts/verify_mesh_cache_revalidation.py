"""Real temporary SQLite + gated fake verifier transport; no sockets, keys, models or evaluation fixtures."""
from __future__ import annotations

import asyncio
import collections
import copy
from contextlib import closing
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.mesh import instant, router


class Reply:
    def __init__(self, verdict):
        self.status = 503 if verdict is None else 200
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.closed = False
        self.verdict = verdict

    async def body(self):
        self.entered.set()
        await self.release.wait()
        return json.dumps({"ok": self.verdict, "needs_fix": self.verdict is False}).encode()

    def close(self):
        self.closed = True


class Keys(router.KeyFile):
    def __init__(self):
        pass  # No path or credential file; only this synthetic first() implementation is used.

    def first(self):
        return "synthetic-not-a-credential"


class CacheChecks(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="mesh-cache-revalidation-")
        self.cache = instant.AnswerCache(str(Path(self.directory.name) / "answers.db"))
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.cache.db.close)
        self.clock = patch("time.time", return_value=1000.0)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        no_network = patch("socket.create_connection", side_effect=AssertionError("Network forbidden"))
        no_network.start()
        self.addCleanup(no_network.stop)
        # Use actual Router methods; no constructor/key-file reads or server creation.
        self.host = router.Router.__new__(router.Router)
        self.host.cache = self.cache
        self.host.keys = Keys()
        self.host.cfg = {"verify_url": "http://127.0.0.1:9", "cache_reverify_s": 0.0}
        self.host.counters = collections.Counter()
        self.host.decisions = collections.deque()

    def put(self, answer="old answer", question="How do Roblox doors work?", *, ttl=100.0, source="synthetic"):
        return self.cache.put(question, answer, "roblox", source, 1.0, [1.0, 0.0], ttl)

    def snapshot(self, rid):
        row = self.cache.get(rid)
        assert row is not None
        return row

    async def begin(self, snapshot, verdict):
        reply, requests = Reply(verdict), []

        async def transport(url, method, body, headers, **_kwargs):
            requests.append((url, method, json.loads(body), headers))
            return reply

        transport_patch = patch.object(router, "open_upstream", side_effect=transport)
        transport_patch.start()
        self.addCleanup(transport_patch.stop)
        task = asyncio.create_task(self.host._reverify(snapshot))
        self.addAsyncCleanup(self.finish, task, reply)
        await asyncio.wait_for(reply.entered.wait(), 2)
        self.assertEqual(requests[0][2], {"answer": snapshot["answer"]})
        self.assertEqual(len(requests), 1)
        return task, reply

    async def finish(self, task, reply):
        reply.release.set()
        if task.cancelled():
            reply.close()
            return
        await asyncio.wait_for(task, 2)
        self.assertTrue(reply.closed)

    async def test_current_success_refreshes_and_hits_do_not_invalidate_snapshot(self):
        rid = self.put()
        task, reply = await self.begin(self.snapshot(rid), True)
        self.cache.hit(rid)
        with patch("time.time", return_value=1100.0):
            await self.finish(task, reply)
        row = self.snapshot(rid)
        self.assertEqual((row["verified_at"], row["hits"]), (1100.0, 1))
        self.assertIn(rid, self.cache.vectors)

    async def test_current_failure_deletes_and_reassigns_canonical_vector(self):
        rid = self.put()
        other = self.put(question="How do Roblox gates work?")
        group = self.cache.vectors[rid][4]
        task, reply = await self.begin(self.snapshot(rid), False)
        self.cache.hit(rid)
        await self.finish(task, reply)
        self.assertIsNone(self.cache.get(rid))
        self.assertNotIn(rid, self.cache.vectors)
        self.assertEqual(self.cache.canon[group], other)
        self.assertEqual(self.host.counters["cache_dropped_on_reverify"], 1)

    async def test_replaced_answer_same_id_and_timestamp_survives_old_failure_or_success(self):
        for verdict in (False, True):
            with self.subTest(verdict=verdict):
                rid = self.put()
                old = self.snapshot(rid)
                task, reply = await self.begin(old, verdict)
                self.assertEqual(self.put("fresh answer"), rid)
                fresh = self.snapshot(rid)
                self.assertEqual(old["verified_at"], fresh["verified_at"])
                vectors, canon = copy.deepcopy(self.cache.vectors), dict(self.cache.canon)
                with patch("time.time", return_value=1100.0):
                    await self.finish(task, reply)
                self.assertEqual(self.snapshot(rid), fresh)
                self.assertEqual(self.cache.vectors, vectors)
                self.assertEqual(self.cache.canon, canon)
                self.assertEqual(self.host.counters["cache_dropped_on_reverify"], 0)

    async def test_same_answer_changed_expiry_or_provenance_survives_old_verdict(self):
        for verdict in (False, True):
            with self.subTest(verdict=verdict):
                rid = self.put()
                task, reply = await self.begin(self.snapshot(rid), verdict)
                self.put(ttl=200.0, source="new provenance")
                fresh = self.snapshot(rid)
                with patch("time.time", return_value=1200.0):
                    await self.finish(task, reply)
                self.assertEqual(self.snapshot(rid), fresh)

    async def test_reused_id_equal_timestamp_and_answer_different_question_is_untouched(self):
        rid = self.put()
        task, reply = await self.begin(self.snapshot(rid), False)
        self.assertTrue(self.cache.delete(rid))
        self.assertEqual(self.put(question="How do Roblox lights work?"), rid)
        fresh = self.snapshot(rid)
        await self.finish(task, reply)
        self.assertEqual(self.snapshot(rid), fresh)
        self.assertIn(rid, self.cache.vectors)
        self.assertEqual(self.host.counters["cache_dropped_on_reverify"], 0)

    async def test_deleted_row_and_unavailable_verifier_do_not_change_state_or_drop_counter(self):
        for verdict in (False, True, None):
            with self.subTest(verdict=verdict):
                rid = self.put()
                task, reply = await self.begin(self.snapshot(rid), verdict)
                if verdict is not None:
                    self.cache.delete(rid)
                before = self.cache.get(rid)
                await self.finish(task, reply)
                self.assertEqual(self.cache.get(rid), before)
                self.assertEqual(self.host.counters["cache_dropped_on_reverify"], 0)

    async def test_older_failure_cannot_remove_newer_reverification_of_same_answer(self):
        rid = self.put()
        snapshot = self.snapshot(rid)
        old_task, old_reply = await self.begin(snapshot, False)
        fresh_task, fresh_reply = await self.begin(dict(snapshot), True)
        with patch("time.time", return_value=1100.0):
            await self.finish(fresh_task, fresh_reply)
        await self.finish(old_task, old_reply)
        self.assertEqual(self.snapshot(rid)["verified_at"], 1100.0)
        self.assertEqual(self.host.counters["cache_dropped_on_reverify"], 0)

    async def test_fixed_clock_accepted_success_invalidates_an_older_failure(self):
        rid = self.put()
        snapshot = self.snapshot(rid)
        old_task, old_reply = await self.begin(snapshot, False)
        fresh_task, fresh_reply = await self.begin(dict(snapshot), True)
        await self.finish(fresh_task, fresh_reply)
        fresh = self.snapshot(rid)
        self.assertEqual(fresh["verified_at"], snapshot["verified_at"])
        self.assertNotEqual(fresh["revision"], snapshot["revision"])
        await self.finish(old_task, old_reply)
        self.assertEqual(self.snapshot(rid), fresh)
        self.assertEqual(self.host.counters["cache_dropped_on_reverify"], 0)

    async def test_fixed_clock_aba_and_identical_row_reinsert_reject_old_verdict(self):
        for verdict in (False, True):
            for reinsert in (False, True):
                with self.subTest(verdict=verdict, reinsert=reinsert):
                    rid = self.put("answer A")
                    snapshot = self.snapshot(rid)
                    task, reply = await self.begin(snapshot, verdict)
                    if reinsert:
                        self.cache.delete(rid)
                    else:
                        self.put("answer B")
                    self.assertEqual(self.put("answer A"), rid)
                    fresh = self.snapshot(rid)
                    self.assertEqual({k: v for k, v in snapshot.items() if k != "revision"},
                                     {k: v for k, v in fresh.items() if k != "revision"})
                    self.assertNotEqual(snapshot["revision"], fresh["revision"])
                    await self.finish(task, reply)
                    self.assertEqual(self.snapshot(rid), fresh)
                    self.assertIn(rid, self.cache.vectors)
                    self.assertEqual(self.host.counters["cache_dropped_on_reverify"], 0)

    async def test_legacy_reverified_and_backwards_clock_replacement_advance_revision(self):
        rid = self.put()
        snapshot = self.snapshot(rid)
        self.cache.reverified(rid)
        self.assertEqual(self.snapshot(rid)["verified_at"], snapshot["verified_at"])
        self.assertNotEqual(self.snapshot(rid)["revision"], snapshot["revision"])
        self.assertFalse(self.cache.delete_if_current(snapshot))
        snapshot = self.snapshot(rid)
        with patch("time.time", return_value=900.0):
            self.put()
        self.assertEqual(self.snapshot(rid)["verified_at"], 900.0)
        self.assertFalse(self.cache.reverified_if_current(snapshot))
        self.assertFalse(self.cache.delete_if_current(snapshot))

    async def test_legacy_schema_migration_preserves_rows_and_revision_survives_reopen(self):
        path = str(Path(self.directory.name) / "legacy.db")
        with closing(sqlite3.connect(path)) as db:
            db.execute(instant.AnswerCache.SCHEMA.replace("        revision TEXT NOT NULL DEFAULT '',\n", ""))
            db.execute("INSERT INTO answers (norm,context,question,answer,source,score,created,verified_at,expires,hits) "
                       "VALUES ('question','','question','legacy answer','legacy',NULL,1,2,3000,7)")
            db.commit()
        migrated = instant.AnswerCache(path)
        try:
            row = migrated.get(1)
            assert row is not None
            self.assertEqual((row["answer"], row["verified_at"], row["hits"], row["revision"]),
                             ("legacy answer", 2.0, 7, ""))
            self.assertTrue(migrated.reverified_if_current(row))
            fresh = migrated.get(1)
            assert fresh is not None
            self.assertTrue(fresh["revision"])
            self.assertFalse(migrated.delete_if_current(row))
        finally:
            migrated.db.close()
        reopened = instant.AnswerCache(path)
        try:
            self.assertEqual(reopened.get(1), fresh)
            self.assertTrue(reopened.delete_if_current(fresh))
        finally:
            reopened.db.close()

    async def test_second_connection_replacement_and_sql_cas_winner_are_durable(self):
        rid = self.put()
        old = self.snapshot(rid)
        path = str(Path(self.directory.name) / "answers.db")
        second = instant.AnswerCache(path)
        try:
            self.assertEqual(second.get(rid), old)
            self.assertEqual(second.put(old["question"], "new answer", "roblox", "synthetic", 1.0, [1.0, 0.0], 100), rid)
            fresh = second.get(rid)
            assert fresh is not None
            self.assertFalse(self.cache.reverified_if_current(old))
            self.assertFalse(self.cache.delete_if_current(old))
            self.assertEqual(self.cache.get(rid), fresh)
            self.assertTrue(second.reverified_if_current(fresh))
            self.assertFalse(self.cache.delete_if_current(fresh))
            self.assertEqual(self.cache.get(rid), second.get(rid))
        finally:
            second.db.close()

    async def test_migration_failure_closes_connection_and_preserves_old_schema(self):
        path = str(Path(self.directory.name) / "migration-failure.db")
        with closing(sqlite3.connect(path)) as db:
            db.execute(instant.AnswerCache.SCHEMA.replace("        revision TEXT NOT NULL DEFAULT '',\n", ""))
        connections = []
        real_connect = sqlite3.connect

        class RefuseMigration(sqlite3.Connection):
            def execute(self, sql, parameters=(), /):
                if sql.startswith("ALTER TABLE"):
                    raise sqlite3.OperationalError("synthetic migration failure")
                return super().execute(sql, parameters)

        def connect(*args, **kwargs):
            connection = real_connect(*args, **kwargs, factory=RefuseMigration)
            connections.append(connection)
            return connection

        with patch.object(instant.sqlite3, "connect", side_effect=connect):
            with self.assertRaisesRegex(sqlite3.OperationalError, "synthetic migration failure"):
                instant.AnswerCache(path)
        with self.assertRaises(sqlite3.ProgrammingError):
            connections[0].execute("SELECT 1")
        with closing(real_connect(path)) as db:
            self.assertNotIn("revision", {row[1] for row in db.execute("PRAGMA table_info(answers)")})

    async def test_cancellation_before_verifier_returns_cannot_apply_verdict(self):
        rid = self.put()
        old = self.snapshot(rid)
        task, reply = await self.begin(old, False)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        # Existing verify_ok does not promise transport closure on cancellation. Finish its inert resource here.
        reply.close()
        self.assertEqual(self.snapshot(rid), old)

    async def test_actual_serve_cached_captures_snapshot_before_background_check(self):
        rid = self.put()
        row = self.snapshot(rid)
        done = asyncio.Event()
        actual_reverify = self.host._reverify

        async def reverify(snapshot):
            try:
                await actual_reverify(snapshot)
            finally:
                done.set()

        reply, requests = Reply(False), []
        reply.release.set()

        async def transport(_url, _method, body, *_args, **_kwargs):
            requests.append(json.loads(body))
            return reply

        with (patch.object(router, "open_upstream", side_effect=transport),
              patch.object(self.host, "_reverify", side_effect=reverify)):
            with patch("time.time", return_value=1100.0):
                with patch.object(router, "send_json") as send:
                    await self.host.serve_cached(row, "exact", None, 0.0, False, object(), 0.0)
            send.assert_called_once()
            # The background task has not run yet. Mutate the caller's dict and replace SQLite content.
            row["answer"] = "mutated caller object"
            self.put("fresh answer")
            fresh = self.snapshot(rid)
            await asyncio.wait_for(done.wait(), 2)
        self.assertEqual(requests, [{"answer": "old answer"}])
        self.assertEqual(self.snapshot(rid), fresh)
        self.assertEqual(self.host.counters["cache_dropped_on_reverify"], 0)
        self.assertTrue(reply.closed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
