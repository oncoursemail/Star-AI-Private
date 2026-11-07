#!/usr/bin/env python3
"""Restricted SSH receiver: one bounded, verified STAR archive; no shell or deletion."""
import argparse
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import sys
import tempfile
import time

from recovery_backup import Backup, cleanup_restore_staging, utc_now, validate_archive


def receive(fd, target, maximum, timeout):
    deadline, total = time.monotonic() + timeout, 0
    with target.open('xb') as output:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError('Upload deadline exceeded')
            readable, _, _ = select.select([fd], [], [], min(remaining, 1))
            if not readable:
                continue
            chunk = os.read(fd, min(1024**2, maximum - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise RuntimeError('Upload exceeds size limit')
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    command = os.environ.get('SSH_ORIGINAL_COMMAND', '')
    if command == 'health':
        print('star-main-backup-v1')
        return 0
    if command != 'backup':
        print('Only the configured backup operation is permitted', file=sys.stderr)
        return 126
    os.umask(0o077)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    cfg = json.loads(Path(args.config).read_text())
    state_path = Path(cfg['state_file'])
    state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with state_path.with_suffix('.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another recovery operation is running', file=sys.stderr)
            return 1
        worker = Backup(cfg)
        try:
            recent = worker.state.get('last_ingest_attempt_utc')
            if recent and (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(recent)).total_seconds() < 600:
                raise RuntimeError('Upload rate limit: retry after ten minutes')
            worker.state.update(last_ingest_attempt_utc=utc_now(), latest_complete=False)
            worker.save()
            cleanup_restore_staging(state_path.parent)
            worker.space_check(2)
            with tempfile.TemporaryDirectory(prefix='restore-check-', dir=state_path.parent) as name:
                root = Path(name)
                archive = root / 'recovery.tar'
                receive(sys.stdin.fileno(), archive, cfg.get('max_upload_bytes', 320 * 1024**2), 600)
                proof = validate_archive(archive, root / 'restored', cfg['max_export_bytes'], cfg['expected_sources'])
                worker.cfg = dict(cfg, export_command=['/usr/bin/cat', str(archive)])
                snapshot = worker.backup()
                worker.state['last_ingest_validation'] = dict(proof, verified_utc=utc_now())
                worker.save()
            print(json.dumps({'status': 'backed_up', 'snapshot': snapshot,
                              'last_success_utc': worker.state['last_success_utc']}))
            return 0
        except Exception as error:
            worker.state['last_error'] = {'at': utc_now(), 'action': 'ingest', 'type': type(error).__name__,
                                          'message': str(error)[:300]}
            worker.state['in_progress'] = False
            worker.save()
            print('Recovery upload failed: ' + type(error).__name__, file=sys.stderr)
            return 1


if __name__ == '__main__':
    sys.exit(main())
