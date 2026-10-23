#!/usr/bin/env python3
"""Relay one producer's stdout with receiver-enforced byte and wall-clock limits.

Usage: bounded_export.py --max-bytes N --timeout-seconds N -- COMMAND ARG...
Partial stdout is not a valid backup: callers must require a zero exit status
(for example, restic backup --stdin-from-command). Producer stderr is discarded
so credentials or source content cannot leak into receiver logs.
"""
from __future__ import annotations

import argparse
import os
import select
import signal
import subprocess
import sys
import time

CHUNK = 64 * 1024


class RelayError(Exception):
    pass


def stop_group(process):
    """The producer owns a separate session; never signal our caller's group."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    # A grandchild may ignore TERM even when the group leader has exited.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def relay(command, max_bytes, timeout_seconds, output_fd):
    deadline = time.monotonic() + timeout_seconds
    interrupted = False
    previous_handlers = {}
    process = None
    output_blocking = os.get_blocking(output_fd)
    success = False

    def request_stop(signum, frame):
        nonlocal interrupted
        interrupted = True

    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.signal(signum, request_stop)
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   start_new_session=True, bufsize=0)
        incoming_fd = process.stdout.fileno()
        os.set_blocking(incoming_fd, False)
        os.set_blocking(output_fd, False)
        pending = b""
        total = 0
        eof = False
        while True:
            if interrupted:
                raise RelayError("interrupted")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RelayError("producer deadline exceeded")
            if eof and not pending:
                code = process.poll()
                if code is not None:
                    if code != 0:
                        raise RelayError("producer exited unsuccessfully")
                    success = True
                    return total
            readable, writable, _ = select.select(
                [] if eof or pending else [incoming_fd],
                [output_fd] if pending else [], [], min(remaining, 0.2))
            if incoming_fd in readable:
                try:
                    # Read one extra byte to distinguish exact-size EOF from an
                    # overrun. Never forward the chunk that exceeds the bound.
                    chunk = os.read(incoming_fd, min(CHUNK, max_bytes - total + 1))
                except BlockingIOError:
                    continue
                if not chunk:
                    eof = True
                else:
                    total += len(chunk)
                    if total > max_bytes:
                        raise RelayError("producer exceeded byte limit")
                    pending = chunk
            if output_fd in writable:
                try:
                    written = os.write(output_fd, pending)
                except BlockingIOError:
                    continue
                if written <= 0:
                    raise RelayError("output is unavailable")
                pending = pending[written:]
    finally:
        if process is not None:
            if not success:
                stop_group(process)
            if process.stdout is not None:
                process.stdout.close()
        os.set_blocking(output_fd, output_blocking)
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-bytes", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=int, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if args.max_bytes <= 0 or not 0 < args.timeout_seconds <= 86400 or not command:
        print("Recovery relay failed: positive limits and a producer command are required", file=sys.stderr)
        return 1
    try:
        relay(command, args.max_bytes, args.timeout_seconds, sys.stdout.buffer.fileno())
        return 0
    except RelayError as error:
        print("Recovery relay failed: " + str(error), file=sys.stderr)
    except (OSError, ValueError, KeyboardInterrupt):
        print("Recovery relay failed: producer or output unavailable", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
