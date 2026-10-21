import hashlib
from contextlib import closing, contextmanager
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

if os.name == 'nt' and sys.version_info < (3, 13):
    raise unittest.SkipTest('The Windows exporter requires Python 3.13+ (private temporary directories)')

import windows_recovery_export as exporter


class WindowsRecoveryExportTests(unittest.TestCase):
    def test_windows_signature_uses_consistent_identity_size_and_mtime(self):
        first = SimpleNamespace(st_dev=1, st_ino=2, st_mode=33206, st_size=10, st_mtime_ns=300, st_ctime_ns=100)
        second = SimpleNamespace(**vars(first))
        second.st_ctime_ns = 200
        second.st_mode = 33279  # Windows path-based executable suffix inference.
        with mock.patch.object(exporter.os, 'name', 'nt'):
            self.assertEqual(exporter.signature(first), exporter.signature(second))
            second.st_mtime_ns += 1
            self.assertNotEqual(exporter.signature(first), exporter.signature(second))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.stage = self.root / 'stage'
        self.config = {'sources': [{'name': 'star', 'path': str(self.source)}],
                       'staging_dir': str(self.stage), 'max_total_bytes': 8 * 1024**2,
                       'min_free_bytes': exporter.MIN_FREE, 'sqlite_timeout_seconds': 5}
        # Keep Windows tests inside the configured user profile staging boundary.
        patcher = mock.patch.dict(os.environ, {'LOCALAPPDATA': str(self.root)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def capture(self):
        output = io.BytesIO()
        exporter.Exporter(self.config).export(output)
        blob = output.getvalue()
        with tarfile.open(fileobj=io.BytesIO(blob), mode='r:') as archive:
            files = {item.name: archive.extractfile(item).read() for item in archive}
        self.assertEqual([p for p in self.stage.iterdir() if p.name != '.export.lock'], [])
        return blob, files

    def cli(self):
        path = self.root / 'config.json'
        path.write_text(json.dumps(self.config), encoding='utf-8')
        return subprocess.run([sys.executable, exporter.__file__, '--config', str(path)], capture_output=True)

    def test_binary_manifest_and_linux_receiver_compatibility(self):
        payload = b'private\0binary\xff\r\n' * 200
        (self.source / 'settings.bin').write_bytes(payload)
        (self.source / 'skills').mkdir()
        (self.source / 'skills' / 'user.txt').write_text('custom skill')
        blob, files = self.capture()
        manifest = json.loads(files[exporter.MANIFEST])
        self.assertEqual(manifest['schema'], 1)
        self.assertEqual(manifest['source_names'], ['star'])
        self.assertEqual(manifest['total_bytes'], len(payload) + len(b'custom skill'))
        entry = next(item for item in manifest['files'] if item['path'] == 'star/settings.bin')
        self.assertEqual(entry['sha256'], hashlib.sha256(payload).hexdigest())
        self.assertFalse(entry['sqlite'])
        self.assertEqual(files['star/settings.bin'], payload)
        if os.name != 'nt':
            import recovery_backup
            archive = self.root / 'export.tar'
            archive.write_bytes(blob)
            result = recovery_backup.validate_archive(archive, self.root / 'restored', exporter.MAX_BYTES, ['star'])
            self.assertEqual(result['files'], 2)
            self.assertEqual(result['source_bytes'], manifest['total_bytes'])

    def test_wal_snapshot_keeps_committed_rows_and_omits_sidecars(self):
        original_read = exporter.read_file
        opened_sidecars = set()

        class LockedSidecar:
            def read(self, *args):
                raise PermissionError('Fixture: active SQLite sidecar byte-range lock')

        @contextmanager
        def guarded_read(path):
            with original_read(path) as stream:
                if path.name.endswith(exporter.SIDECARS):
                    opened_sidecars.add(path.name)
                    yield LockedSidecar()
                else:
                    yield stream

        for name in ('state.db', 'extensionless'):
            with self.subTest(database=name), closing(sqlite3.connect(self.source / name)) as writer:
                path = self.source / name
                writer.execute('PRAGMA journal_mode=WAL')
                writer.execute('PRAGMA wal_autocheckpoint=0')
                writer.execute('CREATE TABLE messages(text)')
                writer.execute("INSERT INTO messages VALUES ('committed in WAL')")
                writer.commit()
                self.assertGreater(Path(str(path) + '-wal').stat().st_size, 0)
                writer.execute("INSERT INTO messages VALUES ('not committed')")
                with mock.patch.object(exporter, 'read_file', side_effect=guarded_read):
                    _, files = self.capture()
                self.assertNotIn('star/' + name + '-wal', files)
                self.assertNotIn('star/' + name + '-shm', files)
                self.assertTrue({name + '-wal', name + '-shm'}.issubset(opened_sidecars))
                entry = next(item for item in json.loads(files[exporter.MANIFEST])['files']
                             if item['path'] == 'star/' + name)
                self.assertTrue(entry['sqlite'])
                restored = self.root / ('restored-' + name)
                restored.write_bytes(files['star/' + name])
                with closing(sqlite3.connect(restored)) as connection:
                    self.assertEqual(connection.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
                    self.assertEqual(connection.execute('SELECT text FROM messages').fetchall(), [('committed in WAL',)])

    def test_orphan_sidecar_is_included_when_database_is_excluded(self):
        (self.source / 'excluded.db').write_bytes(b'excluded database')
        (self.source / 'excluded.db-wal').write_bytes(b'orphan evidence')
        self.config['sources'][0]['exclude_patterns'] = ['excluded.db']
        _, files = self.capture()
        self.assertEqual(files['star/excluded.db-wal'], b'orphan evidence')

    def test_sqlite_without_extension_and_seven_databases(self):
        for name in ['knowledge', 'one.db', 'two.sqlite', 'three.sqlite3', 'four.db', 'five.db', 'six.db']:
            with closing(sqlite3.connect(self.source / name)) as connection:
                connection.execute('CREATE TABLE values_table(id)')
                connection.commit()
        _, files = self.capture()
        manifest = json.loads(files[exporter.MANIFEST])
        self.assertEqual(sum(item['sqlite'] for item in manifest['files']), 7)

    def test_missing_required_root_emits_no_stdout_or_secret(self):
        (self.source / 'secret').write_text('PRIVATE FIXTURE SECRET')
        self.config['sources'].append({'name': 'missing', 'path': str(self.root / 'missing')})
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'')
        self.assertNotIn(b'PRIVATE FIXTURE', result.stderr)
        self.assertFalse(self.stage.exists())

    def test_disposable_roots_excluded_but_generated_models_and_secrets_kept(self):
        for name in ['cache', 'caches', 'models', 'downloads', 'engines', 'updates', 'logs']:
            (self.source / name).mkdir()
            (self.source / name / 'huge').write_bytes(b'x' * 30000)
        for name in ['agent.log', 'running.lock', 'old.bak']:
            (self.source / name).write_text('skip')
        (self.source / 'generated' / 'models').mkdir(parents=True)
        (self.source / 'generated' / 'models' / 'custom.obj').write_text('user asset')
        (self.source / 'secrets.json').write_text('private fixture')
        _, files = self.capture()
        self.assertEqual(set(files), {exporter.MANIFEST, 'star/generated/models/custom.obj', 'star/secrets.json'})

    def test_source_and_tar_both_count_toward_staging_budget(self):
        (self.source / 'large').write_bytes(b'x' * 40000)
        self.config['max_total_bytes'] = 65000  # Source fits, source plus tar does not.
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'')
        self.assertEqual([p for p in self.stage.iterdir() if p.name != '.export.lock'], [])
        self.config['max_total_bytes'] = 100
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'')

    def test_low_disk_and_below_minimum_reserve_are_rejected(self):
        (self.source / 'state').write_text('state')
        output = io.BytesIO()
        with mock.patch.object(exporter.shutil, 'disk_usage', return_value=SimpleNamespace(free=exporter.MIN_FREE - 1)):
            with self.assertRaisesRegex(exporter.ExportError, 'reserve'):
                exporter.Exporter(self.config).export(output)
        self.assertEqual(output.getvalue(), b'')
        self.config['min_free_bytes'] = 0
        with self.assertRaisesRegex(exporter.ExportError, 'at least 2 GiB'):
            exporter.Exporter(self.config)

    def test_link_or_junction_file_and_ancestor_rejected(self):
        (self.source / 'keep').write_text('safe')
        if os.name == 'nt':
            original = exporter.safe_info

            def reparse(path):
                if path == self.source:
                    raise exporter.ExportError('An included path is a junction')
                return original(path)

            with mock.patch.object(exporter, 'safe_info', side_effect=reparse):
                with self.assertRaisesRegex(exporter.ExportError, 'junction'):
                    exporter.Exporter(self.config).export(io.BytesIO())
            return
        (self.source / 'escape').symlink_to(self.root)
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'')
        (self.source / 'escape').unlink()
        alias = self.root / 'alias'
        alias.symlink_to(self.source, target_is_directory=True)
        self.config['sources'][0]['path'] = str(alias)
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'')

    def test_reparse_attribute_rejected_on_every_platform(self):
        with mock.patch.object(Path, 'lstat', return_value=SimpleNamespace(st_mode=0o100600, st_file_attributes=0x400)):
            with self.assertRaisesRegex(exporter.ExportError, 'reparse'):
                exporter.safe_info(self.source / 'fixture')

    def test_changing_ordinary_file_retries_and_aborts_without_stdout(self):
        (self.source / 'state').write_text('state')
        actual, calls = exporter.signature, []

        def changed(info):
            calls.append(1)
            return actual(info) + (len(calls),)

        output = io.BytesIO()
        with mock.patch.object(exporter, 'signature', side_effect=changed):
            with self.assertRaisesRegex(exporter.ExportError, 'three bounded'):
                exporter.Exporter(self.config).export(output)
        self.assertEqual(len(calls), 6)
        self.assertEqual(output.getvalue(), b'')
        self.assertEqual([p for p in self.stage.iterdir() if p.name != '.export.lock'], [])

    def test_corrupt_database_and_checksum_fail_before_stdout(self):
        (self.source / 'broken.db').write_bytes(exporter.MAGIC + b'invalid database')
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'')
        (self.source / 'broken.db').unlink()
        (self.source / 'state').write_text('ready')
        output = io.BytesIO()
        with mock.patch.object(exporter, 'validate_tar', side_effect=exporter.ExportError('checksum mismatch')):
            with self.assertRaisesRegex(exporter.ExportError, 'checksum mismatch'):
                exporter.Exporter(self.config).export(output)
        self.assertEqual(output.getvalue(), b'')

    def test_modified_archive_checksum_is_detected(self):
        (self.source / 'state').write_text('original payload')
        blob, _ = self.capture()
        with tarfile.open(fileobj=io.BytesIO(blob), mode='r:') as archive:
            offset = archive.getmember('star/state').offset_data
        damaged = bytearray(blob)
        damaged[offset] ^= 1
        archive_path = self.root / 'damaged.tar'
        archive_path.write_bytes(damaged)
        with self.assertRaisesRegex(exporter.ExportError, 'checksum'):
            exporter.validate_tar(archive_path)

    def test_existing_export_lock_rejects_cli_without_output(self):
        self.stage.mkdir(mode=0o700)
        (self.source / 'state').write_text('ready')
        with exporter.export_lock(self.stage):
            result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'')
        self.assertIn(b'already running', result.stderr)

    def test_lock_is_held_until_binary_streaming_finishes(self):
        (self.source / 'state').write_text('ready')
        testcase = self

        class CheckingOutput(io.BytesIO):
            checked = False

            def write(self, data):
                if not self.checked:
                    self.checked = True
                    result = testcase.cli()
                    testcase.assertNotEqual(result.returncode, 0)
                    testcase.assertEqual(result.stdout, b'')
                    testcase.assertIn(b'already running', result.stderr)
                return super().write(data)

        output = CheckingOutput()
        exporter.Exporter(self.config).export(output)
        self.assertTrue(output.checked)
        self.assertGreater(len(output.getvalue()), 0)

    def test_exact_orphan_cleanup_precedes_space_check_and_preserves_other_files(self):
        orphan = self.stage / (exporter.STAGE_PREFIX + 'abcdefgh')
        orphan.mkdir(parents=True, mode=0o700)
        (orphan / 'partial').write_text('partial')
        keep = self.stage / 'windows-recovery-v1-not-an-exact-temp-name'
        keep.mkdir()
        (self.source / 'state').write_text('ready')

        def space(path):
            return SimpleNamespace(free=exporter.MIN_FREE - 1 if orphan.exists() else exporter.MIN_FREE + 10**8)

        with mock.patch.object(exporter.shutil, 'disk_usage', side_effect=space):
            exporter.Exporter(self.config).export(io.BytesIO())
        self.assertFalse(orphan.exists())
        self.assertTrue(keep.is_dir())

    @unittest.skipIf(os.name == 'nt', 'Portable Windows reparse-attribute rejection is covered separately')
    def test_orphan_symlink_is_not_followed_or_removed(self):
        valuable = self.root / 'valuable'
        valuable.mkdir()
        (valuable / 'keep').write_text('keep')
        self.stage.mkdir(mode=0o700)
        link = self.stage / (exporter.STAGE_PREFIX + 'abcdefgh')
        link.symlink_to(valuable, target_is_directory=True)
        (self.source / 'state').write_text('ready')
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'')
        self.assertTrue(link.is_symlink())
        self.assertEqual((valuable / 'keep').read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
