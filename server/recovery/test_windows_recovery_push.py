import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

if os.name == 'nt' and sys.version_info < (3, 13):
    raise unittest.SkipTest('The Windows exporter requires Python 3.13+ (private temporary directories)')

import windows_recovery_push as push


class WindowsRecoveryPushTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stage = self.root / 'push'
        self.state = self.stage / 'status.json'
        self.cfg = {'staging_dir': str(self.stage), 'state_file': str(self.state),
                    'exporter': 'fixture-exporter.py', 'export_config': 'fixture.json',
                    'ssh_command': ['fixture-ssh', 'backup'], 'max_archive_bytes': 10000}
        self.old = {'latest_complete': True, 'last_success_utc': '2026-10-19T01:00:00Z',
                    'receipt': {'status': 'backed_up', 'snapshot': 'a' * 64,
                                'last_success_utc': '2026-10-19T01:00:00Z'}}
        self.new = {'status': 'backed_up', 'snapshot': 'b' * 64,
                    'last_success_utc': '2026-10-19T02:00:00+00:00'}
        patcher = mock.patch.dict(os.environ, {'LOCALAPPDATA': str(self.root)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def seed(self):
        self.stage.mkdir(mode=0o700, exist_ok=True)
        push.atomic_status(self.state, self.old)

    def load(self):
        return json.loads(self.state.read_text())

    def runner(self, command, **kwargs):
        if command == self.cfg['ssh_command']:
            self.assertEqual(kwargs['stdin'].read(), b'complete fixture archive')
            return SimpleNamespace(returncode=0, stdout=json.dumps(self.new).encode())
        kwargs['stdout'].write(b'complete fixture archive')
        return SimpleNamespace(returncode=0)

    def test_pending_is_fsynced_before_export_and_success_uses_server_timestamp(self):
        self.seed()
        actual_sync = push.os.fsync
        with mock.patch.object(push.os, 'fsync', wraps=actual_sync) as synced:
            def checked(command, **kwargs):
                current = self.load()
                self.assertFalse(current['latest_complete'])
                self.assertTrue(current['in_progress'])
                self.assertEqual(current['receipt'], self.old['receipt'])
                self.assertEqual(current['last_success_utc'], self.old['last_success_utc'])
                self.assertGreater(synced.call_count, 0)
                return self.runner(command, **kwargs)

            code, status = push.run_push(self.cfg, checked)
        self.assertEqual(code, 0)
        self.assertTrue(status['latest_complete'])
        self.assertFalse(status['in_progress'])
        self.assertEqual(status['last_success_utc'], self.new['last_success_utc'])
        self.assertEqual(status['receipt'], self.new)
        self.assertEqual(status, self.load())

    def test_export_failure_does_not_transfer_and_preserves_last_success(self):
        self.seed()
        calls = []

        def failing(command, **kwargs):
            calls.append(command)
            return SimpleNamespace(returncode=1)

        code, status = push.run_push(self.cfg, failing)
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 1)
        self.assertFalse(status['latest_complete'])
        self.assertFalse(status['in_progress'])
        self.assertEqual(status['receipt'], self.old['receipt'])
        self.assertEqual(status['last_success_utc'], self.old['last_success_utc'])

    def test_network_failure_and_invalid_receipts_never_replace_last_success(self):
        cases = [None, {'status': 'recent_backup_exists'},
                 {'status': 'backed_up', 'last_success_utc': self.new['last_success_utc']},
                 dict(self.new, snapshot=''), dict(self.new, snapshot='not-hex-id'),
                 dict(self.new, last_success_utc='2026-10-19T02:00:00'),
                 dict(self.new, last_success_utc='2026-10-19T02:00:00-05:00')]
        for reply in cases:
            with self.subTest(reply=reply):
                self.seed()

                def broken(command, **kwargs):
                    if command == self.cfg['ssh_command']:
                        return SimpleNamespace(returncode=1 if reply is None else 0,
                                               stdout=json.dumps(reply).encode())
                    return self.runner(command, **kwargs)

                code, status = push.run_push(self.cfg, broken)
                self.assertEqual(code, 1)
                self.assertFalse(status['latest_complete'])
                self.assertEqual(status['receipt'], self.old['receipt'])
                self.assertEqual(status['last_success_utc'], self.old['last_success_utc'])

    def test_crash_after_pending_leaves_durable_incomplete_attempt(self):
        self.seed()
        with self.assertRaises(KeyboardInterrupt):
            push.run_push(self.cfg, lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))
        state = self.load()
        self.assertFalse(state['latest_complete'])
        self.assertTrue(state['in_progress'])
        self.assertEqual(state['receipt'], self.old['receipt'])
        self.assertEqual(state['last_success_utc'], self.old['last_success_utc'])

    def test_single_flight_failure_never_clobbers_active_status(self):
        self.seed()
        config = self.root / 'push.json'
        config.write_text(json.dumps(self.cfg))
        original = self.state.read_bytes()
        with push.push_lock(self.stage):
            result = subprocess.run([sys.executable, push.__file__, '--config', str(config)], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'already running', result.stdout)
        self.assertEqual(self.state.read_bytes(), original)

    def test_lock_remains_held_through_transfer_and_final_receipt(self):
        self.seed()

        def checked(command, **kwargs):
            with self.assertRaisesRegex(push.PushError, 'already running'):
                push.run_push(self.cfg, self.runner)
            self.assertFalse(self.load()['latest_complete'])
            return self.runner(command, **kwargs)

        code, _ = push.run_push(self.cfg, checked)
        self.assertEqual(code, 0)

    def test_exact_orphan_cleanup_leaves_other_namespace_and_status(self):
        self.seed()
        orphan = self.stage / 'main-push-abcdefgh'
        orphan.mkdir()
        (orphan / 'partial.tar').write_text('partial')
        keep = self.stage / 'windows-recovery-v1-abcdefgh'
        keep.mkdir()
        (keep / 'keep').write_text('keep')
        similar = self.stage / 'main-push-not-an-exact-name'
        similar.mkdir()

        def checked(command, **kwargs):
            self.assertFalse(orphan.exists())
            self.assertTrue(keep.is_dir())
            self.assertTrue(similar.is_dir())
            self.assertFalse(self.load()['latest_complete'])
            return self.runner(command, **kwargs)

        self.assertEqual(push.run_push(self.cfg, checked)[0], 0)
        self.assertEqual((keep / 'keep').read_text(), 'keep')

    @unittest.skipIf(os.name == 'nt', 'Real POSIX symlink fixture; exporter covers portable reparse checks')
    def test_orphan_symlink_rejected_without_following_it(self):
        self.seed()
        valuable = self.root / 'valuable'
        valuable.mkdir()
        (valuable / 'keep').write_text('keep')
        link = self.stage / 'main-push-abcdefgh'
        link.symlink_to(valuable, target_is_directory=True)
        runner = mock.Mock()
        code, status = push.run_push(self.cfg, runner)
        self.assertEqual(code, 1)
        runner.assert_not_called()
        self.assertFalse(status['latest_complete'])
        self.assertTrue(link.is_symlink())
        self.assertEqual((valuable / 'keep').read_text(), 'keep')

    def test_atomic_write_failure_preserves_previous_file_and_skips_export(self):
        self.seed()
        old = self.state.read_bytes()
        runner = mock.Mock()
        with mock.patch.object(push.os, 'fsync', side_effect=OSError('fixture failure')):
            with self.assertRaises(OSError):
                push.run_push(self.cfg, runner)
        self.assertEqual(self.state.read_bytes(), old)
        runner.assert_not_called()
        self.assertEqual(list(self.stage.glob('.push-status-*')), [])

    def test_receipt_helper_accepts_eight_or_sixty_four_hex_snapshot_ids(self):
        for identifier in ['0123abcd', '1' * 64]:
            reply = dict(self.new, snapshot=identifier)
            self.assertEqual(push.validate_receipt(json.dumps(reply)), reply)


if __name__ == '__main__':
    unittest.main()
