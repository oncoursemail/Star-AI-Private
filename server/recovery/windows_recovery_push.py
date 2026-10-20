#!/usr/bin/env python3
"""Stage a complete Windows STAR export and submit it over one restricted SSH key."""
import argparse
from contextlib import contextmanager
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

import windows_recovery_export as exporter


class PushError(Exception):
    pass


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z')


@contextmanager
def push_lock(root):
    path = root / '.push.lock'
    if path.exists() or path.is_symlink():
        exporter.safe_info(path)
    if os.name == 'nt':
        import msvcrt
        handle, kernel = exporter.win_open(path, writable=True, create=True)
        try:
            fd = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
        except BaseException:
            kernel.CloseHandle(handle)
            raise
    else:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+b', buffering=0) as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise PushError('Push lock must be an ordinary file')
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write(b'0')
        stream.seek(0)
        try:
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise PushError('Another backup push is already running or its lock is unavailable') from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def cleanup_push_orphans(root):
    def check_tree(path):
        if stat.S_ISDIR(exporter.safe_info(path).st_mode):
            with exporter.pinned_directory(path):
                for child in path.iterdir():
                    check_tree(child)

    for path in root.iterdir():
        if not re.fullmatch(r'main-push-[a-z0-9_]{8}', path.name):
            continue
        if not stat.S_ISDIR(exporter.safe_info(path).st_mode):
            raise PushError('Unexpected object in push temporary namespace')
        check_tree(path)
        shutil.rmtree(path)


def atomic_status(path, status):
    if path.exists() or path.is_symlink():
        if not stat.S_ISREG(exporter.safe_info(path).st_mode):
            raise PushError('Status destination must be an ordinary file')
    fd, name = tempfile.mkstemp(prefix='.push-status-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(status, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            move = ctypes.WinDLL('kernel32', use_last_error=True).MoveFileExW
            move.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
            move.restype = wintypes.BOOL
            if not move(name, str(path), 0x1 | 0x8):  # REPLACE_EXISTING | WRITE_THROUGH
                raise ctypes.WinError(ctypes.get_last_error())
        else:
            os.replace(name, path)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def validate_receipt(data):
    if not isinstance(data, (bytes, str)) or len(data) > 65536:
        raise PushError('Unexpected backup receipt')
    reply = json.loads(data)
    if not isinstance(reply, dict) or reply.get('status') != 'backed_up':
        raise PushError('Remote backup was not confirmed with a new snapshot')
    snapshot, timestamp = reply.get('snapshot'), reply.get('last_success_utc')
    if not isinstance(snapshot, str) or not re.fullmatch(r'[0-9a-fA-F]{8,64}', snapshot):
        raise PushError('Backup receipt lacks a valid snapshot identifier')
    try:
        instant = dt.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    except (AttributeError, TypeError, ValueError):
        raise PushError('Backup receipt lacks a valid UTC success timestamp') from None
    if instant.utcoffset() != dt.timedelta(0):
        raise PushError('Backup receipt success timestamp must be UTC')
    return {'status': 'backed_up', 'snapshot': snapshot, 'last_success_utc': timestamp}


def run_push(cfg, runner=None):
    runner = subprocess.run if runner is None else runner
    root, state = exporter.absolute(cfg['staging_dir']), exporter.absolute(cfg['state_file'])
    if os.name == 'nt':
        local = exporter.absolute(os.environ.get('LOCALAPPDATA'))
        if sys.version_info < (3, 13) or not root.is_relative_to(local) or not state.is_relative_to(local):
            raise PushError('Private push staging/status require Python 3.13+ and this user LOCALAPPDATA')
    exporter.ensure_staging_parent(root)
    exporter.ensure_staging_parent(state.parent)
    with exporter.pinned_directory(root), exporter.pinned_directory(state.parent), push_lock(root):
        if state.exists() or state.is_symlink():
            with exporter.read_file(state) as stream:
                status = json.load(stream)
            if not isinstance(status, dict):
                raise PushError('Previous status is invalid; refusing to replace its history')
        else:
            status = {}
        status.update(last_attempt_utc=utc_now(), latest_complete=False, in_progress=True, error=None)
        # Durable pending state precedes cleanup, export, and network activity.
        # A crash leaves the last successful receipt intact but never labels this attempt complete.
        atomic_status(state, status)
        try:
            cleanup_push_orphans(root)
            with tempfile.TemporaryDirectory(prefix='main-push-', dir=root) as name:
                archive = Path(name) / 'recovery.tar'
                with archive.open('xb') as payload, tempfile.TemporaryFile() as errors:
                    result = runner([sys.executable, cfg['exporter'], '--config', cfg['export_config']],
                                    stdout=payload, stderr=errors, timeout=600)
                    if result.returncode:
                        raise PushError('STAR data export failed; no transfer attempted')
                if not 0 < archive.stat().st_size <= cfg.get('max_archive_bytes', 320 * 1024**2):
                    raise PushError('Complete export is empty or exceeds the transfer size limit')
                with archive.open('rb') as payload, tempfile.TemporaryFile() as errors:
                    result = runner(cfg['ssh_command'], stdin=payload, stdout=subprocess.PIPE,
                                    stderr=errors, timeout=1200)
                    if result.returncode:
                        raise PushError('Remote backup was not confirmed; previous recovery points retained')
                reply = validate_receipt(result.stdout)
            status.update(latest_complete=True, receipt=reply, last_success_utc=reply['last_success_utc'])
            code = 0
        except Exception as error:
            status['error'] = str(error) if isinstance(error, (PushError, exporter.ExportError)) else type(error).__name__
            code = 1
        status['in_progress'] = False
        atomic_status(state, status)
        return code, status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    try:
        cfg = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
        code, status = run_push(cfg)
    except Exception as error:
        status = {'latest_complete': False, 'error': str(error) if isinstance(error, (PushError, exporter.ExportError)) else type(error).__name__}
        code = 1
    print(json.dumps(status))
    return code


if __name__ == '__main__':
    sys.exit(main())
