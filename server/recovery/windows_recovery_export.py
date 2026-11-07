#!/usr/bin/env python3
"""Create a bounded, verified STAR state archive; binary tar is the only stdout.

Sources are explicit required directories. Default exclusions cover top-level
downloadable engines/models/caches and disposable logs/lock/backup files. SQLite
uses online backup, including committed WAL data. Snapshots are consistent per
file/database, not one cross-application transaction. No restoration is done.
Windows requires Python 3.13+ (private mode-0700 temporary directories).
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager, ExitStack
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import sys
import tarfile
import tempfile
import time

MAGIC = b'SQLite format 3\0'
MANIFEST = 'RECOVERY_MANIFEST.json'
MAX_BYTES = 256 * 1024**2
MIN_FREE = 2 * 1024**3
CHUNK = 1024**2
SIDECARS = ('-wal', '-shm', '-journal')
DB_SUFFIXES = ('.db', '.sqlite', '.sqlite3')
DEFAULT_EXCLUDES = ('cache', 'caches', '.cache', 'models', 'downloads', 'engines',
                    'updates', 'logs', '*.log', '*.lock', '*.bak', '**/__pycache__', '__pycache__')
STAGE_PREFIX = 'windows-recovery-v1-'


class ExportError(Exception):
    pass


def signature(info):
    mode = stat.S_IFMT(info.st_mode) if os.name == 'nt' else info.st_mode
    core = (info.st_dev, info.st_ino, mode, info.st_size, info.st_mtime_ns)
    # Windows lstat infers execute bits from .cmd/.exe names; fstat does not.
    # It can also report different ctime semantics for an unchanged file.
    return core if os.name == 'nt' else core + (info.st_ctime_ns,)


def safe_info(path):
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400
            or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))):
        raise ExportError('An included path is a link, junction, reparse point, or special file')
    return info


def absolute(value):
    if not isinstance(value, str) or '\0' in value:
        raise ExportError('An explicit absolute path is required')
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise ExportError('An explicit absolute path without parent traversal is required')
    if os.name == 'nt' and not re.fullmatch(r'[A-Za-z]:', path.drive):
        raise ExportError('Only local Windows drive paths are supported')
    return path


def win_open(path, directory=False, writable=False, create=False):
    """Open the final object itself; deny rename while its handle is held."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.GetFileInformationByHandleEx.argtypes = (wintypes.HANDLE, ctypes.c_int,
                                                   wintypes.LPVOID, wintypes.DWORD)
    flags = 0x00200000 | (0x02000000 if directory else 0x08000000)
    access = 0x80 if directory else (0xC0000000 if writable else 0x80000000)
    handle = kernel.CreateFileW(str(path), access, 0x1 | 0x2, None, 4 if create else 3, flags, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    attributes = (wintypes.DWORD * 2)()
    if not kernel.GetFileInformationByHandleEx(handle, 9, attributes, ctypes.sizeof(attributes)):
        error = ctypes.get_last_error()
        kernel.CloseHandle(handle)
        raise ctypes.WinError(error)
    if attributes[0] & 0x400 or bool(attributes[0] & 0x10) != directory:
        kernel.CloseHandle(handle)
        raise ExportError('A path handle resolved to a link, junction, or unexpected type')
    return handle, kernel


@contextmanager
def pinned_directory(path):
    handles = []
    try:
        for item in [*reversed(path.parents), path]:
            if not stat.S_ISDIR(safe_info(item).st_mode):
                raise ExportError('A source ancestor is not a directory')
            if os.name == 'nt':
                handles.append(win_open(item, directory=True))
        yield
    finally:
        for handle, kernel in reversed(handles):
            kernel.CloseHandle(handle)


@contextmanager
def read_file(path):
    before = safe_info(path)
    if not stat.S_ISREG(before.st_mode):
        raise ExportError('Expected an ordinary file')
    if os.name == 'nt':
        import msvcrt
        handle, kernel = win_open(path)
        try:
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            kernel.CloseHandle(handle)
            raise
    else:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if (not stat.S_ISREG(opened.st_mode)
                or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)):
            raise ExportError('Source identity changed while opening it')
        yield stream


def ensure_staging_parent(path):
    missing, existing = [], path
    while not existing.exists() and not existing.is_symlink():
        missing.append(existing)
        existing = existing.parent
    with ExitStack() as stack:
        stack.enter_context(pinned_directory(existing))
        for item in reversed(missing):
            item.mkdir(mode=0o700)
            stack.enter_context(pinned_directory(item))


@contextmanager
def export_lock(parent):
    path = parent / '.export.lock'
    if path.exists() or path.is_symlink():
        safe_info(path)
    if os.name == 'nt':
        import msvcrt
        handle, kernel = win_open(path, writable=True, create=True)
        try:
            fd = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
        except BaseException:
            kernel.CloseHandle(handle)
            raise
    else:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+b', buffering=0) as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ExportError('Export lock must be an ordinary file')
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
            raise ExportError('An export is already running or its lock is unavailable') from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def cleanup_orphans(parent):
    """Only this exporter's exact temporary namespace, under its exclusive lock."""
    def check_tree(path):
        if stat.S_ISDIR(safe_info(path).st_mode):
            with pinned_directory(path):
                for child in path.iterdir():
                    check_tree(child)

    for path in parent.iterdir():
        if not re.fullmatch(re.escape(STAGE_PREFIX) + r'[a-z0-9_]{8}', path.name):
            continue
        if not stat.S_ISDIR(safe_info(path).st_mode):
            raise ExportError('Unexpected object in the exporter temporary namespace')
        check_tree(path)
        shutil.rmtree(path)


def validate_tar(path):
    """Validate the complete staged tar before any byte is sent to the receiver."""
    observed, manifest, seen = {}, None, set()
    with tarfile.open(path, 'r:') as archive:
        for member in archive:
            name = member.name
            if (not member.isfile() or member.issparse() or name in seen
                    or PurePosixPath(name).is_absolute() or '\\' in name
                    or any(part in ('', '.', '..') for part in name.split('/'))):
                raise ExportError('Unsafe staged archive member')
            seen.add(name)
            with archive.extractfile(member) as stream:
                if name == MANIFEST:
                    manifest = json.load(stream)
                else:
                    digest, count = hashlib.sha256(), 0
                    while chunk := stream.read(CHUNK):
                        digest.update(chunk)
                        count += len(chunk)
                    observed[name] = (count, digest.hexdigest())
    if not isinstance(manifest, dict) or manifest.get('schema') != 1 or not manifest.get('files'):
        raise ExportError('Missing or empty staged manifest')
    expected = {item['path']: (item['size'], item['sha256']) for item in manifest['files']}
    if (len(expected) != len(manifest['files']) or expected != observed
            or manifest.get('total_bytes') != sum(item[0] for item in observed.values())):
        raise ExportError('Staged archive checksum or manifest mismatch')
    return manifest


class Exporter:
    def __init__(self, config):
        self.limit = config.get('max_total_bytes', MAX_BYTES)
        self.floor = config.get('min_free_bytes', MIN_FREE)
        self.timeout = config.get('sqlite_timeout_seconds', 60)
        if type(self.limit) is not int or not 0 < self.limit <= MAX_BYTES:
            raise ExportError('max_total_bytes must be within 1..256 MiB, including the staged tar')
        if type(self.floor) is not int or self.floor < MIN_FREE:
            raise ExportError('min_free_bytes must reserve at least 2 GiB')
        if type(self.timeout) not in (int, float) or not math.isfinite(self.timeout) or not 0 < self.timeout <= 300:
            raise ExportError('sqlite_timeout_seconds must be within (0, 300]')
        default_stage = str(Path(os.environ['LOCALAPPDATA']) / 'StarRecovery') if 'LOCALAPPDATA' in os.environ else None
        self.parent = absolute(config.get('staging_dir', default_stage))
        if os.name == 'nt':
            if sys.version_info < (3, 13):
                raise ExportError('Windows requires Python 3.13+ for private temporary directories')
            if not self.parent.is_relative_to(absolute(os.environ.get('LOCALAPPDATA'))):
                raise ExportError('Windows staging must be inside this user LOCALAPPDATA')
        self.sources = config.get('sources')
        if not isinstance(self.sources, list) or not self.sources:
            raise ExportError('At least one explicit required source is needed')
        names = set()
        for source in self.sources:
            name = source.get('name', '')
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', name) or name.casefold() in names or name == MANIFEST:
                raise ExportError('Sources need unique safe names')
            names.add(name.casefold())
            path = absolute(source.get('path'))
            if self.parent.is_relative_to(path) or path.is_relative_to(self.parent):
                raise ExportError('Staging and sources must be disjoint')
            patterns = source.get('exclude_patterns', [])
            if not isinstance(patterns, list) or any(not isinstance(p, str) or not p for p in patterns):
                raise ExportError('exclude_patterns must be a list of nonempty strings')
        self.files, self.occupied = [], 0

    def guard(self, additional=0):
        if self.occupied + additional > self.limit:
            raise ExportError('Export exceeds the 256 MiB staged-storage budget')
        if shutil.disk_usage(self.parent).free - additional < self.floor:
            raise ExportError('Export would cross the 2 GiB free-space reserve')

    @staticmethod
    def excluded(source, relative):
        value = relative.casefold()
        return any(fnmatch.fnmatchcase(value, pattern.casefold())
                   for pattern in (*DEFAULT_EXCLUDES, *source.get('exclude_patterns', [])))

    def database(self, path, target, initial):
        deadline = time.monotonic() + self.timeout
        with ExitStack() as stack:
            for suffix in SIDECARS:
                sidecar = path.with_name(path.name + suffix)
                if sidecar.exists() or sidecar.is_symlink():
                    stack.enter_context(read_file(sidecar))
            src = stack.enter_context(closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)))
            page_size = src.execute('PRAGMA page_size').fetchone()[0]
            self.guard(src.execute('PRAGMA page_count').fetchone()[0] * page_size)
            dst = stack.enter_context(closing(sqlite3.connect(target)))

            def progress(status, remaining, total):
                self.guard(max(total * page_size, target.stat().st_size))
                if time.monotonic() >= deadline:
                    raise ExportError('SQLite online backup deadline exceeded')

            src.backup(dst, pages=max(1, min(64, CHUNK // page_size)), progress=progress, sleep=0.02)
            dst.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            if dst.execute('PRAGMA journal_mode=DELETE').fetchone() != ('delete',):
                raise ExportError('SQLite snapshot is not standalone')
            if dst.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ExportError('SQLite snapshot integrity check failed')
        current = safe_info(path)
        if (current.st_dev, current.st_ino) != (initial.st_dev, initial.st_ino):
            raise ExportError('SQLite source was replaced during backup')
        if time.monotonic() >= deadline:
            raise ExportError('SQLite online backup deadline exceeded')

    def capture(self, source, path, relative, is_db):
        archive_name = source['name'] + '/' + relative
        target = self.payload.joinpath(*archive_name.split('/'))
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        for attempt in range(3):
            allocated = 0
            with read_file(path) as incoming:
                before = os.fstat(incoming.fileno())
                self.guard(before.st_size)
                magic = incoming.read(16) == MAGIC
                incoming.seek(0)
                if magic != is_db:
                    raise ExportError('Source format changed or a database is corrupt')
                if is_db:
                    self.database(path, target, before)
                    allocated = target.stat().st_size
                    self.guard(allocated)
                    self.occupied += allocated
                    break
                with target.open('wb') as outgoing:
                    while chunk := incoming.read(CHUNK):
                        self.guard(len(chunk))
                        outgoing.write(chunk)
                        allocated += len(chunk)
                        self.occupied += len(chunk)
                if (signature(before) == signature(os.fstat(incoming.fileno())) == signature(safe_info(path))
                        and allocated == before.st_size):
                    break
            target.unlink(missing_ok=True)
            self.occupied -= allocated
        else:
            raise ExportError('Source kept changing during three bounded copy attempts')
        with target.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        self.files.append({'path': archive_name, 'size': allocated, 'sha256': digest,
                           'sqlite': is_db, 'mtime': int(before.st_mtime)})
        if len(self.files) > 100000:
            raise ExportError('Too many selected files')

    def walk(self, source, directory, prefix=''):
        with pinned_directory(directory):
            names = sorted(name for name in os.listdir(directory)
                           if not self.excluded(source, prefix + name))
            regular = set()
            for name in names:
                if any(char in name for char in ('/', '\\', ':', '\0')) or name in ('.', '..'):
                    raise ExportError('Unsafe source filename')
                path = directory / name
                if stat.S_ISREG(safe_info(path).st_mode):
                    regular.add(name)
            databases = {name for name in regular if name.lower().endswith(DB_SUFFIXES)}
            # A database sorts before its own sidecars, including extensionless
            # databases. SQLite owns byte-range locks in active WAL/SHM files;
            # validate their paths above and pin them in database(), but never
            # inspect their content as ordinary files when their DB is included.
            for name in sorted(regular - databases):
                if any(name.endswith(suffix) and name[:-len(suffix)] in databases for suffix in SIDECARS):
                    continue
                path = directory / name
                with read_file(path) as stream:
                    if stream.read(16) == MAGIC:
                        databases.add(name)
            # Capture databases first. Their sidecars are omitted only once backup succeeds.
            for name in sorted(databases):
                self.capture(source, directory / name, prefix + name, True)
            omitted = {name + suffix for name in databases for suffix in SIDECARS}
            for name in names:
                if name in databases or name in omitted:
                    continue
                path = directory / name
                if stat.S_ISDIR(safe_info(path).st_mode):
                    self.walk(source, path, prefix + name + '/')
                else:
                    self.capture(source, path, prefix + name, False)
            final = sorted(name for name in os.listdir(directory)
                           if name not in omitted and not self.excluded(source, prefix + name))
            if final != [name for name in names if name not in omitted]:
                raise ExportError('A source directory changed during export')

    def export(self, output):
        # Validate every required root before staging or reading any file contents.
        for source in self.sources:
            with pinned_directory(absolute(source['path'])):
                pass
        ensure_staging_parent(self.parent)
        with pinned_directory(self.parent), export_lock(self.parent):
            cleanup_orphans(self.parent)
            self.guard()
            with tempfile.TemporaryDirectory(prefix=STAGE_PREFIX, dir=self.parent) as temporary:
                work = Path(temporary)
                if os.name != 'nt' and work.stat().st_mode & 0o077:
                    raise ExportError('Staging is not private')
                self.payload = work / 'payload'
                self.payload.mkdir(mode=0o700)
                for source in sorted(self.sources, key=lambda item: item['name']):
                    self.walk(source, absolute(source['path']))
                manifest = {'schema': 1, 'source_names': sorted(item['name'] for item in self.sources),
                            'created_at': datetime.now(timezone.utc).isoformat(),
                            'files': sorted(self.files, key=lambda item: item['path']),
                            'total_bytes': sum(item['size'] for item in self.files)}
                data = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode() + b'\n'
                if len(data) > 16 * CHUNK:
                    raise ExportError('Manifest exceeds the receiver size limit')
                self.guard(len(data))
                (self.payload / MANIFEST).write_bytes(data)
                self.occupied += len(data)
                exporter = self

                class BoundedWriter:
                    def __init__(self, stream):
                        self.stream = stream

                    def tell(self):
                        return self.stream.tell()

                    def write(self, chunk):
                        exporter.guard(len(chunk))
                        count = self.stream.write(chunk)
                        exporter.occupied += count
                        return count

                archive_path = work / 'recovery.tar'
                with archive_path.open('wb') as stream:
                    with tarfile.open(fileobj=BoundedWriter(stream), mode='w', format=tarfile.PAX_FORMAT) as archive:
                        for name in sorted([MANIFEST, *(item['path'] for item in self.files)]):
                            path = self.payload.joinpath(*name.split('/'))
                            info = tarfile.TarInfo(name)
                            info.size, info.mode, info.mtime = path.stat().st_size, 0o600, 0
                            with path.open('rb') as incoming:
                                archive.addfile(info, incoming)
                    stream.flush()
                    os.fsync(stream.fileno())
                validate_tar(archive_path)
                with archive_path.open('rb') as incoming:
                    shutil.copyfileobj(incoming, output, CHUNK)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    try:
        config = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
        if os.name == 'nt':
            import msvcrt
            msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
        Exporter(config).export(sys.stdout.buffer)
    except Exception as error:
        # Do not print arbitrary OS/SQLite exception strings, paths, or secret contents.
        detail = str(error) if isinstance(error, ExportError) else type(error).__name__
        print('recovery export failed: ' + detail, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
