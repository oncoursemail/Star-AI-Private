"""Cross-process single-writer lock for STAR's private artifact staging root.

The lock is cooperative and local-host only. Every trusted materializer must
hold it across recovery, compare-and-swap, replacement, and journal finalization.
The persistent lock file must never be unlinked while any process may use it.
"""
from __future__ import annotations

import errno
import math
import os
from pathlib import Path
import stat
import threading
import time


_LOCK_NAME = ".star-materializer.lock"
_BUSY_ERRNOS = {
    errno.EACCES,
    errno.EAGAIN,
    errno.EDEADLK,
    errno.EINTR,
    getattr(errno, "EWOULDBLOCK", errno.EAGAIN),
}
_WINDOWS_LOCK_VIOLATION = 33


class StagingRootLockError(RuntimeError):
    """The trusted host could not safely acquire the staging-root lock."""


class StagingRootLockTimeout(StagingRootLockError):
    """Another trusted process held the staging root beyond the bounded wait."""


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    junction_check = getattr(path, "is_junction", None)
    if not callable(junction_check):
        return False
    return bool(junction_check())


class StagingRootLock:
    """Cooperative, cross-process exclusive lock for one local staging root.

    A process-local lock registry also serializes distinct materializer instances
    in the same process. POSIX uses flock; Windows uses a one-byte msvcrt region
    lock. The persistent file is not deleted: unlinking a held lock file could
    let another process lock a replacement inode at the same pathname.
    """

    _registry_guard = threading.Lock()
    _thread_locks: dict[str, threading.Lock] = {}

    def __init__(
        self,
        lock_path: Path,
        *,
        timeout_seconds: float = 10.0,
        poll_interval_seconds: float = 0.05,
    ) -> None:
        if not isinstance(lock_path, Path) or not lock_path.is_absolute():
            raise ValueError("Lock path must be an absolute pathlib.Path")
        if lock_path.name != _LOCK_NAME or not lock_path.parent.is_dir():
            raise ValueError("Lock path must be inside an existing staging root")
        if _is_link_or_junction(lock_path.parent):
            raise StagingRootLockError("Staging root cannot be a symlink or junction")
        if (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(float(timeout_seconds))
            or timeout_seconds < 0
            or timeout_seconds > 60
        ):
            raise ValueError("Lock timeout must be finite and between 0 and 60 seconds")
        if (
            type(poll_interval_seconds) not in (int, float)
            or not math.isfinite(float(poll_interval_seconds))
            or poll_interval_seconds <= 0
            or poll_interval_seconds > 1
        ):
            raise ValueError("Lock poll interval must be finite and between 0 and 1 second")

        self.lock_path = lock_path
        self.timeout_seconds = float(timeout_seconds)
        self.poll_interval_seconds = float(poll_interval_seconds)
        self._fd: int | None = None
        self._thread_locked = False

        key = os.path.normcase(str(lock_path.resolve(strict=False)))
        with self._registry_guard:
            self._thread_lock = self._thread_locks.setdefault(key, threading.Lock())

    def _open_lock_file(self) -> int:
        try:
            existing = self.lock_path.lstat()
        except FileNotFoundError:
            existing = None
        if existing is not None and (
            not stat.S_ISREG(existing.st_mode) or _is_link_or_junction(self.lock_path)
        ):
            raise StagingRootLockError("Staging lock path must be a regular non-link file")

        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
        if os.name == "posix":
            flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.lock_path, flags, 0o600)
        except OSError as exc:
            raise StagingRootLockError("Could not open the staging-root lock file") from exc

        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise StagingRootLockError("Staging lock handle is not a regular file")
            try:
                named = self.lock_path.lstat()
            except FileNotFoundError as exc:
                raise StagingRootLockError("Staging lock path disappeared during open") from exc
            if not stat.S_ISREG(named.st_mode) or _is_link_or_junction(self.lock_path):
                raise StagingRootLockError("Staging lock path changed during open")
            opened_identity = (opened.st_dev, opened.st_ino)
            named_identity = (named.st_dev, named.st_ino)
            if opened.st_ino and named.st_ino and opened_identity != named_identity:
                raise StagingRootLockError("Staging lock path was replaced during open")
            if os.name == "posix":
                os.fchmod(descriptor, 0o600)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _try_os_lock(descriptor: int) -> bool:
        if os.name == "posix":
            import fcntl

            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in _BUSY_ERRNOS:
                    return False
                raise StagingRootLockError("Could not acquire the POSIX staging lock") from exc
            return True

        if os.name == "nt":
            import msvcrt

            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                if (
                    exc.errno in _BUSY_ERRNOS
                    or getattr(exc, "winerror", None) == _WINDOWS_LOCK_VIOLATION
                ):
                    return False
                raise StagingRootLockError("Could not acquire the Windows staging lock") from exc
            return True

        raise StagingRootLockError("Cross-process staging locks are unsupported on this platform")

    def acquire(self) -> "StagingRootLock":
        if self._fd is not None:
            raise StagingRootLockError("This lock instance is already acquired")
        if not self._thread_lock.acquire(timeout=self.timeout_seconds):
            raise StagingRootLockTimeout("Another thread is using this staging root")
        self._thread_locked = True
        descriptor: int | None = None
        deadline = time.monotonic() + self.timeout_seconds
        try:
            descriptor = self._open_lock_file()
            while True:
                if self._try_os_lock(descriptor):
                    self._fd = descriptor
                    descriptor = None
                    return self
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise StagingRootLockTimeout("Another process is using this staging root")
                time.sleep(min(self.poll_interval_seconds, remaining))
        except BaseException:
            if descriptor is not None:
                os.close(descriptor)
            self._thread_lock.release()
            self._thread_locked = False
            raise

    def release(self) -> None:
        descriptor = self._fd
        if descriptor is None:
            return
        self._fd = None
        try:
            if os.name == "posix":
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
            elif os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        except OSError:
            # Closing the descriptor below also releases the OS lock.
            pass
        finally:
            try:
                os.close(descriptor)
            finally:
                if self._thread_locked:
                    self._thread_locked = False
                    self._thread_lock.release()

    def __enter__(self) -> "StagingRootLock":
        return self.acquire()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.release()
