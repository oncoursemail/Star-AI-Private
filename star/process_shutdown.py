"""Bounded graceful shutdown for STAR-owned process trees.

POSIX process groups receive SIGTERM first and SIGKILL only after a bounded grace
period. Windows Job Objects retain their immediate, reliable termination path:
Python's Windows SIGTERM maps to TerminateProcess rather than a cooperative
group shutdown, and CTRL_BREAK requires a shared console.
"""
from __future__ import annotations

import asyncio
import math
import os
import signal
import time

from star.process_supervisor import ProcessTreeSupervisor


def _validate_bounds(grace_period_s: float, poll_s: float, kill_wait_s: float) -> None:
    bounds = (
        (grace_period_s, "grace_period_s", 0.0, 5.0, False),
        (poll_s, "poll_s", 0.0, 1.0, True),
        (kill_wait_s, "kill_wait_s", 0.0, 10.0, False),
    )
    for value, name, lower, upper, lower_open in bounds:
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or value < lower
            or value > upper
            or (lower_open and value <= lower)
        ):
            raise ValueError(f"invalid {name}")


def _wait_sync_tree_empty(
    tree: ProcessTreeSupervisor,
    timeout_s: float,
    poll_s: float,
) -> bool:
    deadline = time.monotonic() + float(timeout_s)
    poll = getattr(tree.process, "poll", None)
    while True:
        if callable(poll):
            poll()
        if tree.wait_empty(0.0, poll_s):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(float(poll_s), remaining))


def terminate_managed(
    tree: ProcessTreeSupervisor,
    *,
    grace_period_s: float = 0.35,
    poll_s: float = 0.02,
    kill_wait_s: float = 2.0,
) -> bool:
    """Gracefully stop a synchronous worker tree, escalating within fixed bounds.

    Returns whether the supervisor observed an empty process tree. A False result
    is an explicit cleanup warning, not evidence that the tree has stopped.
    """
    _validate_bounds(grace_period_s, poll_s, kill_wait_s)
    if tree.mode != "posix_process_group":
        tree.terminate()
        return _wait_sync_tree_empty(tree, kill_wait_s, poll_s)

    try:
        os.killpg(tree.pid, signal.SIGTERM)
    except ProcessLookupError:
        return _wait_sync_tree_empty(tree, 0.0, poll_s)
    except OSError:
        tree.terminate()
        return _wait_sync_tree_empty(tree, kill_wait_s, poll_s)

    deadline = time.monotonic() + float(grace_period_s)
    poll = getattr(tree.process, "poll", None)
    while True:
        # Reap the root before checking the group so a completed root does not
        # keep an otherwise-empty group visible as a zombie.
        if callable(poll):
            poll()
        if tree.wait_empty(0.0, poll_s):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(float(poll_s), remaining))

    tree.terminate()
    return _wait_sync_tree_empty(tree, kill_wait_s, poll_s)


async def terminate_managed_async(
    tree: ProcessTreeSupervisor,
    *,
    grace_period_s: float = 0.35,
    poll_s: float = 0.02,
    kill_wait_s: float = 2.0,
) -> bool:
    """Async counterpart; group polling runs off the event loop.

    Cancellation forces the existing hard-stop path before propagating, so
    cancellation cannot leave a managed worker deliberately running.
    """
    _validate_bounds(grace_period_s, poll_s, kill_wait_s)
    process = tree.process
    wait_task = asyncio.create_task(process.wait())

    async def wait_for_empty(timeout_s: float) -> bool:
        return await asyncio.to_thread(tree.wait_empty, timeout_s, poll_s)

    async def wait_for_root() -> bool:
        try:
            await asyncio.wait_for(asyncio.shield(wait_task), timeout=kill_wait_s)
        except TimeoutError:
            return False
        return True

    try:
        if tree.mode != "posix_process_group":
            tree.terminate()
            if not await wait_for_root():
                return False
            return await wait_for_empty(kill_wait_s)

        try:
            os.killpg(tree.pid, signal.SIGTERM)
        except ProcessLookupError:
            if not await wait_for_root():
                return False
            return await wait_for_empty(0.0)
        except OSError:
            tree.terminate()
            if not await wait_for_root():
                return False
            return await wait_for_empty(kill_wait_s)

        await asyncio.wait({wait_task}, timeout=grace_period_s)
        empty = await wait_for_empty(grace_period_s)
        if not empty:
            tree.terminate()
        if not await wait_for_root():
            return False
        return await wait_for_empty(kill_wait_s)
    except asyncio.CancelledError:
        tree.terminate()
        try:
            await asyncio.wait_for(asyncio.shield(wait_task), timeout=kill_wait_s)
        except TimeoutError:
            pass
        raise
