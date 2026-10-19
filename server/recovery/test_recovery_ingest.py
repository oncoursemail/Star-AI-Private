import contextlib
import datetime as dt
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

import recovery_ingest as ingest

SOURCES = ['windows-star-config', 'windows-star-data']


def make_archive(*, unsafe=False, bad_hash=False, link=False, sources=None):
    files = [('windows-star-config/settings.json', b'{"enabled": true}'),
             ('windows-star-data/state.json', b'{"checkpoint": 7}')]
    if unsafe:
        files[0] = ('../escaped', files[0][1])
    manifest = {'schema': 1, 'source_names': SOURCES if sources is None else sources,
                'total_bytes': sum(len(data) for _, data in files), 'files': []}
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as stream:
        for index, (name, data) in enumerate(files):
            member = tarfile.TarInfo(name)
            member.size = len(data)
            stream.addfile(member, io.BytesIO(data))
            digest = '0' * 64 if bad_hash and index == 0 else hashlib.sha256(data).hexdigest()
            manifest['files'].append({'path': name, 'size': len(data), 'sha256': digest, 'sqlite': False})
        if link:
            member = tarfile.TarInfo('windows-star-data/link')
            member.type, member.linkname = tarfile.SYMTYPE, '/tmp'
            stream.addfile(member)
        data = json.dumps(manifest).encode()
        member = tarfile.TarInfo('RECOVERY_MANIFEST.json')
        member.size = len(data)
        stream.addfile(member, io.BytesIO(data))
    return output.getvalue()


class ReceiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name) / 'received.tar'

    def test_exact_binary_limit_is_accepted(self):
        data = bytes(range(256)) * 400
        with tempfile.TemporaryFile() as source:
            source.write(data)
            source.seek(0)
            self.assertEqual(ingest.receive(source.fileno(), self.target, len(data), 2), len(data))
        self.assertEqual(self.target.read_bytes(), data)

    def test_overrun_is_rejected_before_excess_reaches_disk(self):
        with tempfile.TemporaryFile() as source:
            source.write(b'x' * 1025)
            source.seek(0)
            with self.assertRaisesRegex(RuntimeError, 'size limit'):
                ingest.receive(source.fileno(), self.target, 1024, 2)
        self.assertLessEqual(self.target.stat().st_size, 1024)

    def test_stalled_input_has_a_wall_clock_deadline(self):
        incoming, writer = os.pipe()
        self.addCleanup(os.close, incoming)
        self.addCleanup(os.close, writer)
        started = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, 'deadline'):
            ingest.receive(incoming, self.target, 1024, 0.05)
        self.assertLess(time.monotonic() - started, 1)

    def test_existing_target_is_never_overwritten(self):
        self.target.write_bytes(b'owner data')
        with tempfile.TemporaryFile() as source, self.assertRaises(FileExistsError):
            ingest.receive(source.fileno(), self.target, 1024, 1)
        self.assertEqual(self.target.read_bytes(), b'owner data')


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cfg = {'state_file': str(self.root / 'status.json'), 'cache_dir': str(self.root / 'cache'),
                    'repository': str(self.root / 'repo'), 'password_file': str(self.root / 'password'),
                    'baseline_repository': str(self.root / 'baseline'),
                    'baseline_password_file': str(self.root / 'baseline-password'),
                    'restic': '/test/restic-not-invoked', 'workload': 'star-main',
                    'max_export_bytes': 256 * 1024, 'max_upload_bytes': 320 * 1024,
                    'min_free_bytes': 0, 'max_repository_bytes': 10 * 1024**2,
                    'expected_sources': SOURCES}
        self.config = self.root / 'config.json'
        self.write_config()
        self.state_file = Path(self.cfg['state_file'])
        self.previous = {'last_snapshot_id': 'old-good', 'last_success_utc': ingest.utc_now(),
                         'latest_complete': True, 'in_progress': False}
        self.state_file.write_text(json.dumps(self.previous))
        self.addCleanup(signal.signal, signal.SIGTERM, signal.getsignal(signal.SIGTERM))

    def write_config(self):
        self.config.write_text(json.dumps(self.cfg))

    def invoke(self, payload=b'', command='backup'):
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryFile() as source:
            source.write(payload)
            source.seek(0)
            with patch.object(sys, 'argv', ['recovery_ingest.py', '--config', str(self.config)]), \
                 patch.object(sys, 'stdin', source), patch.dict(os.environ, SSH_ORIGINAL_COMMAND=command), \
                 contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = ingest.main()
        return code, out.getvalue(), err.getvalue()

    def test_forced_command_rejects_every_unapproved_form_before_config_read(self):
        self.config.unlink()
        for command in ['', 'ls', 'verify', 'backup ', ' backup', 'backup; echo secret', 'health extra']:
            with self.subTest(command=command), patch.object(ingest, 'Backup') as worker:
                code, out, err = self.invoke(command=command)
                self.assertEqual(code, 126)
                self.assertEqual(out, '')
                self.assertNotIn('echo secret', err)
                worker.assert_not_called()

    def test_health_is_read_only_and_needs_no_repository_config(self):
        self.config.unlink()
        with patch.object(ingest, 'Backup') as worker:
            code, out, err = self.invoke(command='health')
        self.assertEqual((code, out.strip(), err), (0, 'star-main-backup-v1', ''))
        worker.assert_not_called()
        self.assertEqual(json.loads(self.state_file.read_text()), self.previous)

    def assert_rejected_without_restic(self, payload):
        with patch.object(ingest.Backup, 'call') as restic:
            code, out, err = self.invoke(payload)
        self.assertEqual(code, 1)
        self.assertEqual(out, '')
        self.assertIn('Recovery upload failed:', err)
        restic.assert_not_called()
        state = json.loads(self.state_file.read_text())
        self.assertFalse(state['latest_complete'])
        self.assertFalse(state['in_progress'])
        self.assertEqual(state['last_snapshot_id'], 'old-good')
        self.assertEqual(state['last_success_utc'], self.previous['last_success_utc'])
        self.assertFalse(list(self.root.glob('restore-check-*')))

    def test_traversal_fails_before_snapshot_or_escape(self):
        self.assert_rejected_without_restic(make_archive(unsafe=True))
        self.assertFalse(list(self.root.rglob('escaped')))

    def test_hash_mismatch_fails_before_snapshot(self):
        self.assert_rejected_without_restic(make_archive(bad_hash=True))

    def test_symlink_fails_before_snapshot(self):
        self.assert_rejected_without_restic(make_archive(link=True))

    def test_missing_required_source_fails_before_snapshot(self):
        self.assert_rejected_without_restic(make_archive(sources=[SOURCES[0]]))

    def test_partial_upload_creates_no_snapshot(self):
        self.assert_rejected_without_restic(make_archive()[:1024])

    def test_upload_limit_is_enforced_before_snapshot(self):
        raw = make_archive()
        self.cfg['max_upload_bytes'] = len(raw) - 1
        self.write_config()
        self.assert_rejected_without_restic(raw)

    def test_concurrent_operation_does_not_read_or_replace_state(self):
        with self.state_file.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(ingest, 'receive') as receive, patch.object(ingest.Backup, 'call') as restic:
                code, out, err = self.invoke(make_archive())
        self.assertEqual(code, 1)
        self.assertEqual(out, '')
        self.assertIn('Another recovery operation', err)
        receive.assert_not_called()
        restic.assert_not_called()
        self.assertEqual(json.loads(self.state_file.read_text()), self.previous)

    def test_rate_limit_does_not_extend_window_or_claim_a_fresh_upload(self):
        recent = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=60)).isoformat()
        self.state_file.write_text(json.dumps(dict(self.previous, last_ingest_attempt_utc=recent)))
        with patch.object(ingest, 'receive') as receive, patch.object(ingest.Backup, 'call') as restic:
            code, out, _ = self.invoke(make_archive())
        self.assertEqual((code, out), (1, ''))
        receive.assert_not_called()
        restic.assert_not_called()
        state = json.loads(self.state_file.read_text())
        self.assertEqual(state['last_ingest_attempt_utc'], recent)
        self.assertEqual(state['last_snapshot_id'], 'old-good')
        self.assertEqual(state['last_success_utc'], self.previous['last_success_utc'])
        self.assertTrue(state['latest_complete'])

    def test_recent_failed_attempt_cannot_be_reported_as_a_success(self):
        self.state_file.write_text(json.dumps(dict(self.previous, latest_complete=False,
                                                  last_ingest_attempt_utc=ingest.utc_now())))
        with patch.object(ingest, 'receive') as receive, patch.object(ingest.Backup, 'call') as restic:
            code, out, _ = self.invoke(make_archive())
        self.assertEqual((code, out), (1, ''))
        receive.assert_not_called()
        restic.assert_not_called()
        self.assertFalse(json.loads(self.state_file.read_text())['latest_complete'])

    def test_crash_staging_is_cleaned_before_disk_space_guard(self):
        stale = self.root / 'restore-check-abcd1234'
        stale.mkdir()
        (stale / 'private.tar').write_bytes(b'private')

        def space_check(worker, multiplier=1):
            self.assertFalse(stale.exists())
            raise RuntimeError('disk reserve unavailable')

        with patch.object(ingest.Backup, 'space_check', autospec=True, side_effect=space_check), \
             patch.object(ingest, 'receive') as receive, patch.object(ingest.Backup, 'call') as restic:
            code, _, _ = self.invoke(make_archive())
        self.assertEqual(code, 1)
        receive.assert_not_called()
        restic.assert_not_called()
        self.assertFalse(stale.exists())

    def test_verified_upload_after_rate_window_reaches_restic_and_gets_receipt(self):
        expired = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=601)).isoformat()
        self.state_file.write_text(json.dumps(dict(self.previous, last_ingest_attempt_utc=expired)))
        raw, commands = make_archive(), []

        def restic(worker, *args, **kwargs):
            commands.append(args[0])
            if args[0] == 'backup':
                self.assertEqual(worker.cfg['export_command'][0], '/usr/bin/cat')
                self.assertEqual(Path(worker.cfg['export_command'][1]).read_bytes(), raw)
                return json.dumps({'message_type': 'summary', 'snapshot_id': 'new-good'})
            return ''

        with patch.object(ingest.Backup, 'call', autospec=True, side_effect=restic):
            code, out, err = self.invoke(raw)
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(json.loads(out)['snapshot'], 'new-good')
        self.assertEqual(commands, ['unlock', 'backup', 'check'])
        state = json.loads(self.state_file.read_text())
        self.assertTrue(state['latest_complete'])
        self.assertEqual(state['last_ingest_validation']['files'], 2)
        self.assertEqual(state['last_ingest_validation']['source_names'], SOURCES)
        self.assertFalse(list(self.root.glob('restore-check-*')))

    def test_restic_failure_never_sends_success_receipt(self):
        with patch.object(ingest.Backup, 'call', side_effect=RuntimeError('private producer detail')):
            code, out, err = self.invoke(make_archive())
        self.assertEqual((code, out), (1, ''))
        self.assertNotIn('private producer detail', err)
        state = json.loads(self.state_file.read_text())
        self.assertFalse(state['latest_complete'])
        self.assertEqual(state['last_snapshot_id'], 'old-good')


if __name__ == '__main__':
    unittest.main()
