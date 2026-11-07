#!/usr/bin/env python3
"""Build a consistent, bounded Linux backup export, then stream a deterministic tar.

Config: sources=[{name, path, exclude_patterns?}], staging_dir, max_total_bytes,
min_free_bytes, sqlite_timeout_seconds, exclude_patterns?. Source paths must be
absolute. Global exclusions match archive paths; per-source exclusions match
paths relative to that source (fnmatch syntax). No implicit cache exclusions.
The private staging directory must be outside the sources. No links or special
files are exported. SQLite sidecars are omitted only for included databases.
This captures individual files/databases consistently, not a cross-service
transaction; quiesce related writers if they require one common transaction.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import fcntl
import fnmatch
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import sys
import tarfile
import tempfile
import time
from urllib.parse import quote

MAGIC = b"SQLite format 3\x00"
DB_SUFFIXES = (".db", ".sqlite", ".sqlite3")
SIDECARS = ("-wal", "-shm", "-journal")
MANIFEST = "RECOVERY_MANIFEST.json"
CHUNK = 1024 * 1024
STAGE_PREFIX = "recovery-export-v1-"


class ExportError(Exception):
    pass


def absolute_path(value):
    if not isinstance(value, str) or not value.startswith("/") or "\x00" in value:
        raise ExportError("Paths must be absolute Linux paths")
    if ".." in Path(value).parts:
        raise ExportError("Parent traversal is not allowed")
    return str(Path(value))


def open_directory(path, create=False, readable=True):
    """Walk with dirfds: no user-controlled symlink component is followed."""
    components = Path(path).parts[1:]
    common = os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", common | (os.O_PATH if components or not readable else os.O_RDONLY))
    try:
        for index, part in enumerate(components):
            flags = common | (os.O_RDONLY if readable and index == len(components) - 1 else os.O_PATH)
            try:
                next_fd = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def signature(s):
    return (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


class Exporter:
    def __init__(self, config):
        self.config = config
        self.limit = config.get("max_total_bytes")
        self.floor = config.get("min_free_bytes")
        self.timeout = config.get("sqlite_timeout_seconds")
        if type(self.limit) is not int or self.limit <= 0:
            raise ExportError("max_total_bytes must be a positive integer")
        if type(self.floor) is not int or self.floor < 0:
            raise ExportError("min_free_bytes must be a nonnegative integer")
        if type(self.timeout) not in (int, float) or not math.isfinite(self.timeout) or not 0 < self.timeout <= 3600:
            raise ExportError("sqlite_timeout_seconds must be within (0, 3600]")
        self.stage_parent = absolute_path(config.get("staging_dir"))
        self.sources = config.get("sources")
        if not isinstance(self.sources, list) or not self.sources:
            raise ExportError("At least one required source is needed")
        names = set()
        self.patterns = self.get_patterns(config)
        for source in self.sources:
            if not isinstance(source, dict):
                raise ExportError("Each source must be an object")
            name = source.get("name", "")
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name) or name == MANIFEST or name in names:
                raise ExportError("Source names must be unique safe directory names")
            names.add(name)
            source["path"] = absolute_path(source.get("path"))
            self.get_patterns(source)
            if Path(self.stage_parent).is_relative_to(source["path"]):
                raise ExportError("staging_dir must be outside every source")
        self.used = 0
        self.files = []
        self.directories = {}

    @staticmethod
    def get_patterns(value):
        patterns = value.get("exclude_patterns", [])
        if not isinstance(patterns, list) or any(not isinstance(p, str) or not p or "\x00" in p for p in patterns):
            raise ExportError("exclude_patterns must contain nonempty strings")
        return patterns

    def excluded(self, source, relative):
        archive = f"{source['name']}/{relative}"
        return any(fnmatch.fnmatchcase(archive, p) or fnmatch.fnmatchcase(archive + "/", p) for p in self.patterns) or any(fnmatch.fnmatchcase(relative, p) or fnmatch.fnmatchcase(relative + "/", p) for p in self.get_patterns(source))

    def guard(self, pending, allocation=0):
        if self.used + pending > self.limit:
            raise ExportError("Export exceeds max_total_bytes")
        vfs = os.fstatvfs(self.stage_fd)
        if vfs.f_bavail * vfs.f_frsize - allocation < self.floor:
            raise ExportError("Staging would cross min_free_bytes")

    @staticmethod
    def open_file(parent_fd, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent_fd)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise ExportError("Links and special files are not supported")
        return fd

    def database(self, fd, parent_fd, name, target):
        deadline = time.monotonic() + self.timeout
        initial = os.fstat(fd)
        # SQLite resolves this pinned descriptor to the original path, which is
        # necessary for its WAL/journal handling. Check identity around the open
        # and export; fail if a rename/replacement or symlink is observed.
        uri = "file:" + quote(f"/proc/self/fd/{fd}", safe="/") + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=min(1.0, self.timeout))) as src:
            current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino, stat.S_IFMT(current.st_mode)) != (initial.st_dev, initial.st_ino, stat.S_IFREG):
                raise ExportError("Database path changed during export")
            with closing(sqlite3.connect(target)) as dst:
                page_size = src.execute("PRAGMA page_size").fetchone()[0]

                def progress(status, remaining, total):
                    if time.monotonic() >= deadline:
                        raise ExportError("SQLite backup deadline exceeded")
                    expected = total * page_size
                    self.guard(expected, max(0, expected - target.stat().st_size))

                expected = src.execute("PRAGMA page_count").fetchone()[0] * page_size
                self.guard(expected, expected)
                src.backup(dst, pages=128, progress=progress, sleep=0.025)
                dst.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
                if dst.execute("PRAGMA journal_mode=DELETE").fetchone() != ("delete",):
                    raise ExportError("SQLite export could not become a standalone database")
                if dst.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ExportError("SQLite integrity check failed")
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (current.st_dev, current.st_ino, stat.S_IFMT(current.st_mode)) != (initial.st_dev, initial.st_ino, stat.S_IFREG):
            raise ExportError("Database path changed during export")
        if time.monotonic() >= deadline:
            raise ExportError("SQLite backup deadline exceeded")

    def copy_file(self, parent_fd, name, archive, original, is_db):
        target = self.stage / archive
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        for attempt in range(3):
            fd = self.open_file(parent_fd, name)
            try:
                before = os.fstat(fd)
                self.guard(before.st_size, before.st_size)
                if not is_db and os.pread(fd, 16, 0) == MAGIC:
                    raise ExportError("Source type changed during export")
                if is_db:
                    if os.pread(fd, 16, 0) != MAGIC:
                        raise ExportError("SQLite header is missing or corrupt")
                    self.database(fd, parent_fd, name, target)
                    mode = before.st_mode & 0o777
                    break
                digest = hashlib.sha256()
                size = 0
                with target.open("wb") as out:
                    while chunk := os.read(fd, CHUNK):
                        size += len(chunk)
                        self.guard(size, len(chunk))
                        out.write(chunk)
                        digest.update(chunk)
                after = os.fstat(fd)
                current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if signature(before) == signature(after) == signature(current) and size == before.st_size:
                    mode = before.st_mode & 0o777
                    break
                target.unlink()
            finally:
                os.close(fd)
        else:
            raise ExportError("Source kept changing during bounded copy attempts")
        size = target.stat().st_size
        self.guard(size)
        self.used += size
        if is_db:
            digest = hashlib.sha256()
            with target.open("rb") as stream:
                while chunk := stream.read(CHUNK):
                    digest.update(chunk)
        if len(self.files) >= 100000:
            raise ExportError("Export exceeds 100000 files")
        self.files.append({"path": archive, "original_path": original, "size": size, "sha256": digest.hexdigest(), "mode": mode, "mtime": int(before.st_mtime), "sqlite": is_db})

    def walk(self, source, directory_fd, relative=""):
        archive_dir = source["name"] + ("/" + relative if relative else "")
        directory_info = os.fstat(directory_fd)
        self.directories[archive_dir] = (directory_info.st_mode & 0o777, int(directory_info.st_mtime))
        names = sorted(n for n in os.listdir(directory_fd) if not self.excluded(source, f"{relative}/{n}".lstrip("/")))
        databases = set()
        for name in names:
            info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISREG(info.st_mode):
                fd = self.open_file(directory_fd, name)
                try:
                    if name.lower().endswith(DB_SUFFIXES) or os.pread(fd, 16, 0) == MAGIC:
                        databases.add(name)
                finally:
                    os.close(fd)
            elif not stat.S_ISDIR(info.st_mode):
                raise ExportError("An included source contains a link or special file")
        omitted = {base + suffix for base in databases for suffix in SIDECARS}
        for name in names:
            if name in omitted:
                continue
            child = f"{relative}/{name}".lstrip("/")
            info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd)
                try:
                    self.walk(source, fd, child)
                finally:
                    os.close(fd)
            else:
                self.copy_file(directory_fd, name, source["name"] + "/" + child, source["path"] + "/" + child, name in databases)
        final_names = sorted(n for n in os.listdir(directory_fd) if n not in omitted and not self.excluded(source, f"{relative}/{n}".lstrip("/")))
        if final_names != [n for n in names if n not in omitted]:
            raise ExportError("Source directory changed during export")

    def build(self):
        for source in sorted(self.sources, key=lambda s: s["name"]):
            path = Path(source["path"])
            parent_fd = open_directory(str(path.parent), readable=False)
            try:
                info = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
                    try:
                        self.walk(source, fd)
                    finally:
                        os.close(fd)
                elif stat.S_ISREG(info.st_mode):
                    fd = self.open_file(parent_fd, path.name)
                    try:
                        is_db = path.name.lower().endswith(DB_SUFFIXES) or os.pread(fd, 16, 0) == MAGIC
                    finally:
                        os.close(fd)
                    self.directories[source["name"]] = (0o700, 0)
                    self.copy_file(parent_fd, path.name, source["name"] + "/" + path.name, str(path), is_db)
                else:
                    raise ExportError("A required source is a link or special file")
            finally:
                os.close(parent_fd)
        manifest = {"schema": 1, "source_names": sorted(s["name"] for s in self.sources), "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "total_bytes": self.used, "sources": sorted(self.sources, key=lambda s: s["name"]), "exclude_patterns": self.patterns, "files": sorted(self.files, key=lambda f: f["path"])}
        data = (json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()
        self.guard(len(data), len(data))
        (self.stage / MANIFEST).write_bytes(data)

    def export(self, output):
        if not hasattr(os, "O_PATH") or not hasattr(os, "O_NOFOLLOW") or not Path("/proc/self/fd").is_dir():
            raise ExportError("Exporter requires Linux with descriptor paths")
        self.stage_fd = open_directory(self.stage_parent, create=True)
        lock_fd = None
        try:
            info = os.fstat(self.stage_fd)
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ExportError("staging_dir must be owned by this user with mode 0700")
            lock_fd = os.open(".export.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self.stage_fd)
            if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
                raise ExportError("Export lock must be a regular file")
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ExportError("Another recovery export is already running") from None
            # Only our exact private temporary-directory namespace is cleaned.
            # The held lock means none can belong to an active export.
            for name in os.listdir(self.stage_fd):
                if re.fullmatch(re.escape(STAGE_PREFIX) + r"[a-z0-9_]{8}", name):
                    stale = os.stat(name, dir_fd=self.stage_fd, follow_symlinks=False)
                    if not stat.S_ISDIR(stale.st_mode) or stale.st_uid != os.getuid():
                        raise ExportError("Unexpected object in export staging namespace")
                    shutil.rmtree(f"/proc/self/fd/{self.stage_fd}/{name}")
            self.guard(0)
            with tempfile.TemporaryDirectory(prefix=STAGE_PREFIX, dir=f"/proc/self/fd/{self.stage_fd}") as tmp:
                self.stage = Path(tmp)
                self.build()  # Nothing is written to stdout until all inputs pass.
                with tarfile.open(fileobj=output, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                    for name, (mode, mtime) in sorted(self.directories.items()):
                        entry = tarfile.TarInfo(name + "/")
                        entry.type, entry.mode, entry.mtime = tarfile.DIRTYPE, mode, mtime
                        archive.addfile(entry)
                    records = self.files + [{"path": MANIFEST, "mode": 0o600, "size": (self.stage / MANIFEST).stat().st_size}]
                    for record in sorted(records, key=lambda r: r["path"]):
                        entry = tarfile.TarInfo(record["path"])
                        entry.mode, entry.size = record["mode"], record["size"]
                        entry.mtime = record.get("mtime", 0)
                        with (self.stage / record["path"]).open("rb") as stream:
                            archive.addfile(entry, stream)
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
            os.close(self.stage_fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        with open(args.config, encoding="utf-8") as stream:
            config = json.load(stream)
        if not isinstance(config, dict):
            raise ExportError("Configuration must be an object")
        Exporter(config).export(sys.stdout.buffer)
        sys.stdout.buffer.flush()
        return 0
    except ExportError as error:
        print(f"Recovery export failed: {error}", file=sys.stderr)
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        print("Recovery export failed: a required source, database, staging path, or configuration is unavailable or invalid", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
