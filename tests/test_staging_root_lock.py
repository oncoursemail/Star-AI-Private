"""Cross-process and path-safety tests for STAR staging-root locks."""
import multiprocessing
import os
from pathlib import Path
import stat

import pytest

from star.staging_root_lock import (
    StagingRootLock,
    StagingRootLockError,
    StagingRootLockTimeout,
)


def _hold_lock(lock_path: str, ready, release) -> None:
    with StagingRootLock(
        Path(lock_path),
        timeout_seconds=5,
        poll_interval_seconds=0.01,
    ):
        ready.set()
        if not release.wait(10):
            raise RuntimeError("parent did not release the test worker")


def test_lock_file_is_persistent_and_private(tmp_path):
    lock_path = tmp_path / ".star-materializer.lock"

    with StagingRootLock(lock_path, timeout_seconds=1):
        assert lock_path.is_file()

    assert lock_path.is_file()
    if os.name == "posix":
        assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600


def test_cross_process_lock_times_out_then_recovers(tmp_path):
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    lock_path = tmp_path / ".star-materializer.lock"
    worker = context.Process(
        target=_hold_lock,
        args=(str(lock_path), ready, release),
    )
    worker.start()

    contender = StagingRootLock(
        lock_path,
        timeout_seconds=0.15,
        poll_interval_seconds=0.01,
    )
    try:
        assert ready.wait(10), "child did not acquire the staging lock"
        with pytest.raises(StagingRootLockTimeout):
            contender.acquire()

        release.set()
        worker.join(10)
        assert worker.exitcode == 0

        with contender:
            assert lock_path.is_file()
    finally:
        release.set()
        if worker.is_alive():
            worker.terminate()
        worker.join(5)


def test_symlink_lock_file_is_rejected(tmp_path):
    if os.name == "nt":
        pytest.skip("Symlink creation may require Windows developer mode or privilege")
    target = tmp_path / "target"
    target.write_text("do not follow")
    lock_path = tmp_path / ".star-materializer.lock"
    lock_path.symlink_to(target)

    with pytest.raises(StagingRootLockError):
        with StagingRootLock(lock_path, timeout_seconds=0.1):
            pass


def test_directory_cannot_be_used_as_lock_file(tmp_path):
    lock_path = tmp_path / ".star-materializer.lock"
    lock_path.mkdir()

    with pytest.raises(StagingRootLockError):
        with StagingRootLock(lock_path, timeout_seconds=0.1):
            pass


def test_lock_rejects_invalid_timeout(tmp_path):
    lock_path = tmp_path / ".star-materializer.lock"
    with pytest.raises(ValueError):
        StagingRootLock(lock_path, timeout_seconds=float("inf"))
    with pytest.raises(ValueError):
        StagingRootLock(lock_path, poll_interval_seconds=0)
