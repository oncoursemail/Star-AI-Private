# Home activity recovery, 2026-10-26

The existing Home cycle now applies its current GPU resource check to explicitly
requested activities and paused continuations. Previously only automatic picks
honored that check. A blocked request stays queued; the previous continuation is
preserved until the request can start. A blocked continuation keeps its original
timestamp, so repeated waiting does not extend the configured resume deadline.
A newer request arriving while resource inspection runs keeps its priority.
The cycle also checks owner STOP again after resource inspection and selection,
before starting the activity, and restores deferred work when stopped there.

`needs_brain` continues to filter automatic picks. An explicit invitation or
continuation can use an adapter's separately configured brain or local fallback,
as the existing Minecraft integration does. This change does not replace those
adapter checks with a requirement that `Context.chat` exist.

Activity results now pass through `normalize_outcome` before pausing, recording,
goal updates, or curiosity processing. Invalid result types, string booleans,
malformed evidence/failure lists, text that cannot encode as UTF-8, invalid resume states, negative or nonfinite
durations, and invalid step counters produce a recorded failed attempt. Step
counters must be nonnegative signed 64-bit integers. Success requires literal
`ok=True` and `verified=True`; a string cannot finish a goal. `Life.record` also
validates direct callers. A well-formed paused result still records no completed
session and resumes with its prior state.

Verification is offline and uses temporary directories, fake activities, a fake
GPU probe, and the real Attention/Life/cycle implementations. The retained runner
is `python scripts/verify_autonomy_recovery.py`. It injects failures and checks
later recovery, request priority, GPU unavailability, continuation expiry, STOP,
result validation, goal accounting, and preserved pause behavior. Existing Home
tests are run without edits. No PC inputs, model calls, accounts, network calls,
or evaluation fixtures are involved.

Recorded local results for the initial resource/outcome change: the standalone
runner passed 13 checks, including 23 malformed-result subcases followed by a
successful retry. The existing
`tests/test_star_home.py` and `tests/test_home_wiring.py` passed all 93 tests.
Ruff, Pyright, targeted compileall, and whitespace checking passed for the changed
Python files. These establish fake-backend behavior; live PC testing remains
separate.

## Owner STOP and game cleanup

`run_steps` now checks owner STOP before and after each step, even when attention
interrupts are disabled, and during waits in slices of at most 250 ms. A STOP
result is neither verified nor paused. Roblox and Minecraft adapters check STOP
around controller/transport and session startup, then use `finally` to stop each
session and unregister its exact cleanup callback. Controllers close on normal
completion, exceptions, STOP, or failed session cleanup. A normal attention pause
keeps the controller and remaining time but stops the old fast session; resuming
creates a fresh session.

Persistent controller and active session cleanup callbacks use the Runtime
`track_activity(name, stopper)` API. These give the runtime watcher a cleanup
path while the main game step is stalled. Session cleanup is idempotent only
after completion; a concurrent cleanup attempt reports an unfinished operation
as a failure. Minecraft retains its transport until close succeeds, allowing a
failed close to be retried. Cleanup errors cannot produce a verified completion.

The expanded standalone runner covers 31 checks, including STOP during startup,
step execution and stalled execution, factory/start/step exceptions, failed and
concurrent cleanup, cleanup-log failure, normal completion, and pause/resume. These use fake child
transports and sessions. The final existing Home run passed all 93 tests in
47.40 seconds. No harness fixtures were modified.

Game preview checks cover both a context executor and a runtime executor fallback.
Either preview path returns an unverified preview before invoking controller
start, session creation, or child transport creation. An absent runtime executor
does not fail while evaluating the fallback. The verifier also checks that the
runtime's pending-cleanup admission guard blocks the Home cycle even when the
owner STOP file is absent.

This does not forcibly terminate an arbitrary plugin stuck inside a blocking native call, restore
in-memory continuations after a process restart, verify an adapter's evidence
independently, or replay uncertain desktop actions. Those require their own
execution/receipt contracts. Tracked built-in game cleanup signals the fast/slow
session loops and closes the owned Minecraft child; it does not terminate
unrelated processes. Live game and hardware behavior still requires the planned
PC test.
