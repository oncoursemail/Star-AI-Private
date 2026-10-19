import hashlib
import fcntl
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

import recovery_export as exporter


class RecoveryExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.stage = self.root / "stage"
        self.stage.mkdir(mode=0o700)
        self.config = {
            "sources": [{"name": "star", "path": str(self.source)}],
            "staging_dir": str(self.stage),
            "max_total_bytes": 10 * 1024 * 1024,
            "min_free_bytes": 0,
            "sqlite_timeout_seconds": 5,
        }

    def tearDown(self):
        self.temp.cleanup()

    def capture(self):
        output = io.BytesIO()
        exporter.Exporter(self.config).export(output)
        with tarfile.open(fileobj=io.BytesIO(output.getvalue()), mode="r:") as archive:
            members = archive.getmembers()
            data = {m.name: archive.extractfile(m).read() for m in members if m.isfile()}
        self.assert_stage_clean()
        return members, data

    def assert_stage_clean(self):
        self.assertEqual([p for p in self.stage.iterdir() if p.name != ".export.lock"], [])

    def run_cli(self):
        path = self.root / "config.json"
        path.write_text(json.dumps(self.config))
        return subprocess.run([sys.executable, str(Path(exporter.__file__)), "--config", str(path)], capture_output=True)

    def test_manifest_hash_modes_empty_directory_and_binary_payload(self):
        (self.source / "nested").mkdir()
        (self.source / "empty").mkdir()
        payload = b"\x00secret binary\xff" * 100
        (self.source / "nested" / "state.json").write_bytes(payload)
        (self.source / "nested" / "state.json").chmod(0o4750)
        members, files = self.capture()
        manifest = json.loads(files[exporter.MANIFEST])
        self.assertEqual(manifest["schema"], 1)
        self.assertEqual(manifest["source_names"], ["star"])
        self.assertTrue(manifest["created_at"].endswith("Z"))
        self.assertEqual(manifest["total_bytes"], len(payload))
        self.assertEqual(manifest["files"][0]["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(manifest["files"][0]["size"], len(payload))
        self.assertFalse(manifest["files"][0]["sqlite"])
        self.assertEqual(files["star/nested/state.json"], payload)
        self.assertTrue(any(m.name == "star/empty" and m.isdir() for m in members))
        self.assertTrue(all(m.isfile() or m.isdir() for m in members))
        self.assertTrue(all(m.mode & 0o7000 == 0 for m in members))

    def test_wal_database_is_consistent_and_sidecars_are_not_archived(self):
        path = self.source / "kb.sqlite3"
        writer = sqlite3.connect(path)
        try:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("CREATE TABLE notes(id INTEGER PRIMARY KEY, text TEXT)")
            writer.execute("INSERT INTO notes(text) VALUES ('committed in WAL')")
            writer.commit()
            self.assertGreater(Path(str(path) + "-wal").stat().st_size, 0)
            writer.execute("INSERT INTO notes(text) VALUES ('uncommitted')")
            _, files = self.capture()
            self.assertNotIn("star/kb.sqlite3-wal", files)
            self.assertNotIn("star/kb.sqlite3-shm", files)
            restored = self.root / "restored.sqlite3"
            restored.write_bytes(files["star/kb.sqlite3"])
            with sqlite3.connect(restored) as conn:
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
                self.assertEqual(conn.execute("SELECT text FROM notes").fetchall(), [("committed in WAL",)])
            manifest = json.loads(files[exporter.MANIFEST])
            self.assertTrue(manifest["files"][0]["sqlite"])
        finally:
            writer.close()

    def test_sqlite_detected_without_extension(self):
        path = self.source / "state"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE things(id)")
        conn.commit()
        conn.close()
        _, files = self.capture()
        self.assertTrue(json.loads(files[exporter.MANIFEST])["files"][0]["sqlite"])

    def test_missing_required_source_fails_cli_without_stdout(self):
        self.config["sources"].append({"name": "required", "path": str(self.root / "missing")})
        (self.source / "secret.txt").write_text("DO NOT LEAK THIS CONTENT")
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")
        self.assertNotIn(b"DO NOT LEAK", result.stderr)
        self.assert_stage_clean()

    def test_permission_error_propagates_and_no_stdout(self):
        (self.source / "private.txt").write_text("secret")
        output = io.BytesIO()
        with mock.patch.object(exporter.Exporter, "open_file", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                exporter.Exporter(self.config).export(output)
        self.assertEqual(output.getvalue(), b"")
        self.assert_stage_clean()

    def test_symlink_file_and_ancestor_are_rejected(self):
        (self.root / "private.txt").write_text("secret")
        (self.source / "escape").symlink_to(self.root / "private.txt")
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")
        (self.source / "escape").unlink()
        (self.root / "alias").symlink_to(self.source, target_is_directory=True)
        (self.source / "nested").mkdir()
        self.config["sources"][0]["path"] = str(self.root / "alias" / "nested")
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")

    def test_explicit_exclusions_skip_cache_and_excluded_symlinks(self):
        (self.source / "cache").mkdir()
        (self.source / "cache" / "huge").write_bytes(b"x" * 100000)
        (self.source / "external").symlink_to(self.root)
        (self.source / "keep").write_text("keep")
        self.config["exclude_patterns"] = ["star/cache/**", "star/external"]
        _, files = self.capture()
        self.assertEqual(set(files), {exporter.MANIFEST, "star/keep"})

    def test_size_and_free_space_bounds(self):
        (self.source / "state").write_bytes(b"x" * 5000)
        self.config["max_total_bytes"] = 4000
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")
        self.config["max_total_bytes"] = 100000
        self.config["min_free_bytes"] = 10**30
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")

    def test_manifest_size_counts_towards_staging_limit(self):
        (self.source / "zero").write_bytes(b"")
        self.config["max_total_bytes"] = 1
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")

    def test_corrupt_database_fails_without_stdout(self):
        (self.source / "broken.db").write_bytes(exporter.MAGIC + b"corrupted" * 1000)
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")
        self.assert_stage_clean()

    def test_unstable_regular_file_retries_only_twice_then_fails(self):
        (self.source / "state.json").write_text("{}")
        calls = []
        actual = exporter.signature

        def changing_signature(info):
            calls.append(1)
            return actual(info) + (len(calls),)

        output = io.BytesIO()
        with mock.patch.object(exporter, "signature", side_effect=changing_signature):
            with self.assertRaisesRegex(exporter.ExportError, "bounded copy"):
                exporter.Exporter(self.config).export(output)
        self.assertEqual(len(calls), 6)
        self.assertEqual(output.getvalue(), b"")
        self.assert_stage_clean()

    def test_sqlite_deadline_is_bounded(self):
        path = self.source / "state.db"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE example(id)")
        conn.commit()
        conn.close()
        output = io.BytesIO()
        with mock.patch.object(exporter.time, "monotonic", side_effect=[0, 10]):
            with self.assertRaisesRegex(exporter.ExportError, "deadline"):
                exporter.Exporter(self.config).export(output)
        self.assertEqual(output.getvalue(), b"")
        self.assert_stage_clean()

    def test_lock_blocks_concurrent_export_without_stdout(self):
        with (self.stage / ".export.lock").open("wb") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"already running", result.stderr)

    def test_orphan_cleanup_is_limited_to_exporter_namespace(self):
        orphan = self.stage / (exporter.STAGE_PREFIX + "abcdefgh")
        orphan.mkdir(mode=0o700)
        (orphan / "partial.db").write_bytes(b"partial")
        unrelated = self.stage / "keep-this"
        unrelated.mkdir()
        (self.source / "state").write_text("ready")
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(orphan.exists())
        self.assertTrue(unrelated.is_dir())

    def test_orphan_symlink_is_never_followed(self):
        valuable = self.root / "valuable"
        valuable.mkdir()
        (valuable / "keep").write_text("keep")
        (self.stage / (exporter.STAGE_PREFIX + "abcdefgh")).symlink_to(valuable, target_is_directory=True)
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")
        self.assertEqual((valuable / "keep").read_text(), "keep")

    def test_single_file_source(self):
        path = self.source / "state.json"
        path.write_text('{"ready":true}')
        self.config["sources"] = [{"name": "state", "path": str(path)}]
        _, files = self.capture()
        self.assertEqual(files["state/state.json"], b'{"ready":true}')

    def test_execute_only_ancestor_uses_path_descriptor(self):
        ancestor = self.root / "traverse-only"
        child = ancestor / "readable-child"
        child.mkdir(parents=True)
        (child / "allowed.json").write_text('{"allowed":true}')
        ancestor.chmod(0o100)
        self.config["sources"] = [{"name": "allowed", "path": str(child)}]
        actual_open, opened = os.open, []

        def recording_open(path, flags, *args, **kwargs):
            opened.append((str(path), flags))
            return actual_open(path, flags, *args, **kwargs)

        try:
            with mock.patch.object(exporter.os, "open", side_effect=recording_open):
                _, files = self.capture()
            self.assertEqual(files["allowed/allowed.json"], b'{"allowed":true}')
            ancestor_flags = [flags for name, flags in opened if name == "traverse-only"]
            self.assertTrue(ancestor_flags)
            self.assertTrue(all(flags & os.O_PATH for flags in ancestor_flags))
            self.assertTrue(all(flags & os.O_NOFOLLOW for flags in ancestor_flags))
        finally:
            ancestor.chmod(0o700)

    def test_wal_export_archive_passes_actual_restore_validator(self):
        from recovery_backup import validate_archive

        path = self.source / "kb.sqlite3"
        writer = sqlite3.connect(path)
        try:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("CREATE TABLE memories(id INTEGER PRIMARY KEY, text TEXT)")
            writer.execute("INSERT INTO memories(text) VALUES ('committed WAL memory')")
            writer.commit()
            writer.execute("INSERT INTO memories(text) VALUES ('incomplete transaction')")
            (self.source / "settings.json").write_text('{"enabled":true}')
            (self.source / "empty").mkdir()
            output = self.root / "export.tar"
            with output.open("wb") as stream:
                exporter.Exporter(self.config).export(stream)
            restored = self.root / "validated"
            result = validate_archive(output, restored, self.config["max_total_bytes"], ["star"])
            self.assertEqual(result["files"], 2)
            self.assertEqual(result["sqlite_databases"], 1)
            with sqlite3.connect(restored / "star/kb.sqlite3") as conn:
                self.assertEqual(conn.execute("SELECT text FROM memories").fetchall(), [("committed WAL memory",)])
            self.assertEqual((restored / "star/settings.json").read_text(), '{"enabled":true}')
            self.assertTrue((restored / "star/empty").is_dir())
            self.assert_stage_clean()
        finally:
            writer.close()

    def test_special_file_rejected_without_hanging(self):
        os.mkfifo(self.source / "pipe")
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")

    def test_nested_or_public_staging_rejected(self):
        self.config["staging_dir"] = str(self.source / "staging")
        with self.assertRaises(exporter.ExportError):
            exporter.Exporter(self.config)
        self.config["staging_dir"] = str(self.stage)
        self.stage.chmod(0o755)
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")


if __name__ == "__main__":
    unittest.main()
