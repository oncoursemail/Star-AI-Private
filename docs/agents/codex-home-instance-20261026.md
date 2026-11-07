# Home single-instance ownership, 2026-10-26

`python -m star.home run` and `once` previously started independently, allowing
scheduled and manual loops to control the same Home folder concurrently. Both
commands now acquire the existing `InstanceLock` from
`star/discord_bot/instance_lock.py` using the name `home-runtime.lock`. The path
is resolved before setup, and that exact folder is used for setup. Preview and
live execution share the lease. A busy or unavailable lease returns exit code 2
before constructing the executor/runtime or asking a model.

The reused utility holds an operating-system file lock rather than deciding
ownership from PID text. Its Windows implementation uses nonblocking
`msvcrt.locking`; Python documents that overlapping byte ranges cannot be locked
and that the locked byte can be beyond EOF. See the [Python 3.12 reference](https://docs.python.org/3.12/library/msvcrt.html#msvcrt.locking).
The existing Unix implementation uses `flock`. No Qt, new dependency, stale-PID
kill, lock-file deletion, or process discovery was added.

For `once`, the lease covers setup, activity execution, and trusted resource
cleanup. Cleanup closes runtime admission permanently, requests shutdown, waits
for pending callbacks and errors to clear, and retries failed cleanup with
0.1–2 second backoff. Status messages contain no callback names, exception
messages, or private payloads. Repeated Ctrl+C cannot release ownership while
cleanup is unfinished. An unexpected cleanup exception also leaves a strong
process-owned lease reference. Permanent cleanup failure keeps the process
waiting with the folder reserved.

The long-running command has background threads whose complete joining remains
separate work. Its runtime now has a permanent shutdown latch: old watcher ticks
cannot reopen admission after owner resume. Once background execution has been
entered, its lease stays strongly held until the process exits, even if an
embedded caller receives a return value. Restarting an embedded `run` requires
a new process. Startup failure or interruption during runtime construction also
retains ownership until process exit, because partially built resources may not
be available to the caller for cleanup. Failure before runtime construction can
release the lease safely.

Windows releases file locks when their owning process terminates; availability
can be delayed under system resource pressure. This is documented by [Microsoft LockFile](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfile).
Lease recovery after a crash does not establish that every separately spawned
native child exited. Native child recovery remains a separate execution concern.
The guarantee applies to cooperating Home `run`/`once` commands on the same
local data folder. Different Home folders, direct library/executor calls, and
cross-host/network-filesystem coordination have separate scopes.

Owner STOP, resume, status, diagnostics, configuration, and acceptance dispatch
keep their existing availability. The lease guards the two autonomous CLI
commands; it does not change owner permissions or start/stop a public stream.

`python scripts/verify_home_instance.py` passes 19 offline checks, including real
owned subprocesses for simultaneous admission, same-folder refusal, aliases,
different folders, process crash recovery, embedded run retention and once
release, setup/partial-build failure and interruption, pending cleanup, repeated
interrupts, cleanup errors, unexpected cleanup exit, static diagnostics, owner
commands, and permanent shutdown after resume. The test kills only its own fake
subprocesses through their `Popen` objects. It never reads a PID from a lock file
or starts real activities, models, audio, games, network accounts, or PC input.
All 168 existing Home/wiring/acceptance tests passed without fixture edits.
Ruff, Pyright, compilation, and whitespace checks passed for the changed files.

Production changes are limited to `star/home/__main__.py` and the small Runtime
shutdown latch in `star/home/runtime.py`. No default flags, prompts, policy,
authentication, evaluation gates, or workflows changed.
