import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from recovery_backup import Backup, atomic_json, cleanup_restore_staging, run_command, validate_archive


def archive(path, payload=b'owner data', *, digest=None, member='state/data.json', extra=None):
    manifest = {'schema': 1, 'source_names': ['state'], 'total_bytes': len(payload),
                'files': [{'path': member, 'size': len(payload), 'sqlite': False,
                           'sha256': digest or hashlib.sha256(payload).hexdigest()}]}
    with tarfile.open(path, 'w') as stream:
        info = tarfile.TarInfo(member)
        info.size = len(payload)
        stream.addfile(info, io.BytesIO(payload))
        if extra:
            stream.addfile(extra)
        raw = json.dumps(manifest).encode()
        info = tarfile.TarInfo('RECOVERY_MANIFEST.json')
        info.size = len(raw)
        stream.addfile(info, io.BytesIO(raw))


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tar = self.root / 'backup.tar'

    def test_verified_restore_and_expected_sources(self):
        archive(self.tar)
        result = validate_archive(self.tar, self.root / 'out', 1024 * 1024, ['state'])
        self.assertEqual(result['files'], 1)
        self.assertEqual((self.root / 'out/state/data.json').read_bytes(), b'owner data')

    def test_checksum_tampering_fails(self):
        archive(self.tar, digest='0' * 64)
        with self.assertRaisesRegex(ValueError, 'checksum'):
            validate_archive(self.tar, self.root / 'out', 1024 * 1024)

    def test_source_disappearance_fails(self):
        archive(self.tar)
        with self.assertRaisesRegex(ValueError, 'source list'):
            validate_archive(self.tar, self.root / 'out', 1024 * 1024, ['state', 'world'])

    def test_traversal_fails(self):
        archive(self.tar, member='../escape')
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            validate_archive(self.tar, self.root / 'out', 1024 * 1024)
        self.assertFalse((self.root / 'escape').exists())

    def test_symlink_fails(self):
        link = tarfile.TarInfo('unsafe')
        link.type = tarfile.SYMTYPE
        link.linkname = '/tmp'
        archive(self.tar, extra=link)
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            validate_archive(self.tar, self.root / 'out', 1024 * 1024)

    def test_size_limit_fails(self):
        archive(self.tar)
        with self.assertRaisesRegex(ValueError, 'size limit'):
            validate_archive(self.tar, self.root / 'out', 5)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {'state_file': str(self.root / 'status.json'), 'cache_dir': str(self.root / 'cache'),
                       'repository': str(self.root / 'repo'), 'password_file': str(self.root / 'key'),
                       'baseline_repository': str(self.root / 'baseline'),
                       'baseline_password_file': str(self.root / 'baseline-key'), 'workload': 'starai'}

    def test_existing_repository_missing_key_never_reinitialized(self):
        repo = self.root / 'repo'
        repo.mkdir()
        (repo / 'config').write_text('{}')
        worker = Backup(self.config)
        with patch.object(worker, 'call') as call:
            with self.assertRaisesRegex(RuntimeError, 'password is missing'):
                worker.initialize()
            call.assert_not_called()
        self.assertFalse((self.root / 'key').exists())

    def test_baseline_cannot_alias_rolling_repository(self):
        for path in [self.config['repository'], self.config['repository'] + '/baseline']:
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'distinct and disjoint'):
                Backup({**self.config, 'baseline_repository': path})

    def test_baseline_cannot_share_password_file(self):
        with self.assertRaisesRegex(ValueError, 'password files must be separate'):
            Backup({**self.config, 'baseline_password_file': self.config['password_file']})

    def test_recorded_baseline_missing_never_replaced(self):
        worker = Backup(self.config)
        worker.state['baseline_snapshot_id'] = 'original'
        with patch.object(worker, 'initialize') as initialize:
            with self.assertRaisesRegex(RuntimeError, 'missing'):
                worker.baseline()
            initialize.assert_not_called()

    def test_recorded_baseline_identity_never_replaced(self):
        path = Path(self.config['baseline_repository'])
        path.mkdir()
        (path / 'config').write_text('{}')
        worker = Backup(self.config)
        worker.state['baseline_snapshot_id'] = 'original'
        with patch.object(worker, 'initialize'), patch.object(worker, 'call', return_value='[{"id":"replacement"}]') as call:
            with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                worker.baseline()
            self.assertEqual(call.call_count, 1)

    def test_unverified_baseline_never_prunes(self):
        worker = Backup(self.config)
        with patch.object(worker, 'call') as call:
            with self.assertRaisesRegex(RuntimeError, 'verified baseline'):
                worker.retention()
            call.assert_not_called()

    def test_export_failure_never_advances_success(self):
        atomic_json(self.config['state_file'], {'last_snapshot_id': 'old-good', 'last_success_utc': 'before'})
        worker = Backup({**self.config, 'export_command': ['/bin/false']})
        with patch.object(worker, 'space_check'), patch.object(worker, 'call', side_effect=['', RuntimeError('exit 3')]):
            with self.assertRaises(RuntimeError):
                worker.backup()
        self.assertEqual(worker.state['last_snapshot_id'], 'old-good')
        self.assertEqual(worker.state['last_success_utc'], 'before')
        self.assertFalse(worker.state['latest_complete'])

    def test_stale_plaintext_cleanup_is_scoped(self):
        stale = self.root / 'restore-check-abcd1234'
        stale.mkdir()
        (stale / 'private.tar').write_bytes(b'private')
        unrelated = self.root / 'owner-files'
        unrelated.mkdir()
        cleanup_restore_staging(self.root)
        self.assertFalse(stale.exists())
        self.assertTrue(unrelated.exists())

    def test_stale_cleanup_rejects_symlink(self):
        outside = self.root / 'owner-files'
        outside.mkdir()
        (self.root / 'restore-check-abcd1234').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'Unexpected'):
            cleanup_restore_staging(self.root)
        self.assertTrue(outside.exists())

    def test_command_nonzero_is_error(self):
        with self.assertRaisesRegex(RuntimeError, 'exit code 3'):
            run_command([sys.executable, '-c', 'raise SystemExit(3)'], timeout=5, env=os.environ.copy())

    def test_timeout_stops_child(self):
        with self.assertRaisesRegex(RuntimeError, 'deadline'):
            run_command([sys.executable, '-c', 'import time; time.sleep(30)'], timeout=0.05, env=os.environ.copy())


if __name__ == '__main__':
    unittest.main()
