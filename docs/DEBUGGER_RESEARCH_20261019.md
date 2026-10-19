# STAR debugging research and implementation decisions

Research date: 2026-10-19. This note describes the debugger upgrade under development, the evidence behind its design, and the measurements required before claiming that STAR fixes problems faster. It is not a deployment record or a benchmark result for STAR.

## What the upgrade is intended to improve

The useful improvement is a shorter path from a reported problem to a reproducible observation, a source location, and a small justified repair. A larger collection of tools alone does not establish better reasoning or lower latency. The first implementation therefore gives STAR structured evidence, preserves the identity of the tests that produced it, and helps select a focused next investigation.

The workflow is: preserve the failing input; read the failure and nearby source; formulate a small number of hypotheses; collect the observation that distinguishes them; patch the relevant application code; replay the original unchanged test and affected regression tests. A failed collection step, unavailable dependency, skipped test, or incomplete capture remains visible throughout this process.

The new report readers and collectors require no new paid model API. STAR continues to use its existing configured model. The optional developer environment in `requirements-debug.txt` includes the development requirements and pins `debugpy==1.8.22`. Reading an existing report does not require debugpy to be installed.

## Implemented boundary: developer capture and model analysis

The setting `debug_evidence_enabled` defaults to `False`. When explicitly enabled with a selected workspace and a debugging-related request, the existing STAR agent loop can offer four tools from [`star/debug_evidence.py`](../star/debug_evidence.py):

| Model tool | Purpose |
| --- | --- |
| `star_debug_report` | Read a bounded local JSON report, group failures, and identify relevant source locations. |
| `star_debug_compare` | Compare baseline and candidate test reports while checking identities, outcomes, retries, and recorded source hashes. |
| `star_debug_source` | Read a small source window inside the selected workspace. |
| `star_debug_plan` | Propose an investigation for Python, browser, Roblox, Java, .NET, or Rust symptoms; tool installation status remains unprobed. |

These are read-only model tools. They do not launch tests, attach to a process, evaluate debugger expressions, install packages, or promote a proposed fix. Evidence content passes through structural validation, redaction, and output budgets before reaching the model. Workspace access uses the application's existing path enforcement.

In a reviewed build, select the project workspace and enable **Analyze debugger reports** in Settings. A concrete request is: “Debug `artifacts/debug/before.json`, inspect the relevant source, and identify the smallest next check.” Once a candidate and a fresh report exist, ask: “Compare `artifacts/debug/before.json` with `artifacts/debug/after.json` and explain anything that remains inconclusive.” The model can then use its existing authorized coding capabilities with this evidence. The new setting itself does not grant execution or workspace-write permissions.

The developer commands execute separately. The pytest plugin observes an explicitly requested test run. The DAP capture command launches one trusted Python program under debugpy with ordinary developer permissions. Importing the modules does not start a debugger. Variable rendering in a real debugger can invoke a program's `__repr__`, so a debugger capture is an execution capability even when its protocol requests only inspect values.

## Tool selection matrix

These recommendations describe what answers each question; they do not imply that every tool is installed or integrated into STAR.

| Runtime or symptom | First useful evidence | Recommended next tool | Current STAR position |
| --- | --- | --- | --- |
| Python assertion or exception | Exact test identity, phase, exception, stack, and source | pytest evidence, then debugpy at the failing line | Implemented developer collectors and report analysis |
| Python hang | Thread stacks showing where execution waits | `faulthandler`, then `py-spy dump` | Diagnostic planning; external profiler integration is a roadmap item |
| Python CPU or memory growth | Repeated workload and measured hot functions or retained allocations | py-spy/cProfile; tracemalloc/Scalene; Memray on supported hosts | Diagnostic planning; profilers are not automatically installed |
| Browser interaction failure | Assertion, page error, HTTP status, transport error, and trace action | Playwright trace and bounded browser recorder | Developer reporter/runner and read-only report analysis; browser acceptance remains separate |
| Browser latency or heap growth | Performance trace or comparable heap snapshots | Chrome DevTools and its official MCP tooling | Research and planned integration |
| Roblox logic or replication | Correct Studio instance, client/server context, breakpoint state | Studio debugger and controlled multiplayer reproduction | Uses existing Studio boundaries; no new unrestricted execution |
| Roblox frame or script cost | Frame timeline and client/server CPU samples | MicroProfiler and Script Profiler | Diagnostic planning and existing Studio workflow |
| Windows file/process issue | Filtered file, Registry, and process/thread events | Process Monitor | Developer investigation; no process attachment tool added to the model |
| JVM or .NET runtime issue | Allocation, GC, blocking, and CPU events | JFR/jcmd or EventPipe tools | Diagnostic planning |
| Rust memory, concurrency, or CPU issue | A small failing example or measured hotspot | Miri, Loom, or samply | Diagnostic planning; no nightly toolchain or profiler installed by STAR |

The recommendations are grounded in the official [pytest API](https://docs.pytest.org/en/stable/reference/reference.html), [debugpy](https://github.com/microsoft/debugpy), [Python faulthandler](https://docs.python.org/3/library/faulthandler.html), [Playwright Trace Viewer](https://playwright.dev/docs/trace-viewer), [Roblox debugging](https://create.roblox.com/docs/studio/debugging), [Process Monitor](https://learn.microsoft.com/en-us/sysinternals/downloads/procmon), [jcmd](https://docs.oracle.com/en/java/javase/25/docs/specs/man/jcmd.html), and [EventPipe](https://learn.microsoft.com/en-us/dotnet/core/diagnostics/eventpipe) documentation.

## Python evidence: preserve what actually ran

The opt-in plugin is invoked in a developer's selected test environment:

```sh
python -m pytest -p star.debug_pytest --star-debug-report=before.json tests/test_example.py
```

After an application-code repair, invoke the same selected suite with a separate output path such as `after.json`. The output directory must already exist. These examples are instructions for a developer; STAR's model tools do not execute them.

[`star/debug_pytest.py`](../star/debug_pytest.py) writes the `star-debug-evidence-v1` schema with a fresh run ID, process exit code, duration, summary counts, tests, failures, test hashes, harness hashes, and redacted invocation arguments. Environment metadata contains interpreter/platform descriptors, not the process environment. The plugin collects no frame locals or raw stdout/stderr, including when pytest itself is invoked with `--showlocals`.

Every executed setup, call, and teardown phase has its own record. A passing call followed by a teardown error cannot be presented as a successful test. Collection errors, internal errors, interrupted runs, skip, expected failure, and unexpected pass are distinguishable. An empty suite or a suite containing only skips/expected failures does not verify a repair. Passing test identities are retained so removing an earlier passing test is also detectable.

Each test record includes `identity_sha256`, computed from the original node ID before display redaction. Parameter cases such as `password=first` and `password=second` can have identical redacted display names while retaining different identities. All phases for the same test retain the same identity. These hashes establish comparison keys; they are not authentication or encryption.

The collector currently limits phase records to 5,000, failure records to 50, frames per failure to 64, and individual failure messages to 2,000 characters. A shared record-byte budget and the final 2 MB artifact limit bound output. The phase limit is not a promise to record 5,000 complete three-phase tests. Reaching a limit sets truncation and makes verification unavailable.

A pending report with `status: incomplete` replaces a previous artifact at session start. If the process exits abruptly after that point, the earlier passing report cannot remain as the apparent result of the new invocation. Writes are atomic. The initial marker cannot cover failures occurring before pytest starts the session, including initial plugin and conftest imports.

### Test and fixture integrity

Direct test-file hashes are recorded after collection and checked again at session finish. Applicable local `conftest.py`, `pytest.ini`, `pyproject.toml`, `setup.cfg`, and `tox.ini` files are captured at session start and checked again after execution. Harness discovery starts from selected local test paths and their local ancestors, honors recursion exclusions, and has file/entry limits. It does not recursively search a home directory, traverse external paths, or follow symbolic links.

An edit, addition, or deletion in that captured harness makes the report incomplete. Comparing two runs also requires the entire recorded harness map to match, so adding a new conftest that changes behavior cannot silently explain away an earlier failure. Test ID removal, new skip/xfail, changed test source, changed source mapping, incomplete runs, and successful retries remain unresolved evidence.

The comparison result is `evidence_consistent` or `inconclusive`; `verified_fix` remains false. Source snapshots do not authenticate who ran a test, preserve every external dependency, detect all temporary mutations later reverted, or establish test intent. Initial imports, dynamically loaded fixtures, external data, and arbitrary third-party plugin behavior remain limits. STAR's independent evaluation gate and harness ownership remain necessary; a model-produced report cannot certify its own patch or change evaluation fixtures.

## Bounded DAP capture

[Debug Adapter Protocol](https://microsoft.github.io/debug-adapter-protocol/overview.html) supplies a standard request/event boundary for debugger clients. debugpy implements it for Python across Windows, Linux, and macOS. This makes it a better fit for STAR's Windows desktop and Linux development environments than making an interactive terminal debugger the sole integration.

The developer command is:

```sh
python -m star.debug_dap --program examples/repro.py --breakpoint 12 --timeout 15 --output capture.json
```

The current implementation in [`star/debug_dap.py`](../star/debug_dap.py) records the first relevant stop, bounded stack frames and local values, exception information, and cleanup status. It validates framing and response identities, preserves early events, rejects reverse requests, and bounds messages, bytes, output, variables, and elapsed session time. It does not expose expression evaluation, variable assignment, external PID attachment, or terminal launch.

The client communicates with the adapter over stdio; debugpy's helper processes use internal loopback connections. This avoids adding a model-facing debug port. The upstream [debugpy documentation](https://github.com/microsoft/debugpy#debugging-a-script-file) explicitly explains that a client able to connect to a debug port can execute code in the debugged process. Keeping attachment outside the model tool surface is therefore a substantive capability boundary. Timeout/cancellation cleanup is checked, and an incomplete cleanup is reported honestly. This is lifecycle management for trusted programs, not containment of hostile code.

## Browser and Roblox evidence

Playwright traces connect an action to source, DOM snapshots, console messages, and network activity. The bounded reporter should provide a short diagnostic index while the original trace remains a developer artifact. The official [request lifecycle](https://playwright.dev/docs/api/class-request) distinguishes transport failures from HTTP error responses: a 404 or 503 response does not generate `requestfailed`. Capturing both response status and transport error avoids a common blind spot.

The implemented browser recorder strips credential-shaped values and URL query/fragment data, selects explicit fields, and keeps retry attempts. A passing retry does not erase a failed first attempt. Normal Playwright terminal output and separately configured raw traces retain their usual behavior; the small JSON evidence artifact is the sanitized input for STAR.

Use the developer runner from the repository root, with an already installed repository-local Playwright package:

```sh
node scripts/debug_playwright_run.cjs --output artifacts/debug/before.json --timeout-ms 120000 -- --config=playwright.config.ts e2e/star.spec.ts --workers=1
```

After a candidate application-code change, repeat the same test/configuration into `artifacts/debug/after.json`. The runner observes the child process's real exit code and validates the fresh run ID before finalizing the report. A reporter callback by itself normally has no process exit code. Missing, stale, malformed, interrupted, or timed-out capture remains incomplete. The runner does not invoke a shell, use a global CLI fallback, or install a package. Configuration, tests, and their imports still execute trusted repository code with developer permissions.

For browser console, network, and page events, attach the helper through a Playwright fixture such as `e2e/star-fixture.ts`:

```typescript
import { test as base, expect } from '@playwright/test';
const { attachPageDiagnostics, ATTACHMENT_NAME } =
  require('../scripts/debug_playwright_reporter.cjs');

export const test = base.extend<{ starDiagnostics: void }>({
  starDiagnostics: [async ({ page }, use, testInfo) => {
    const recorder = attachPageDiagnostics(page);
    try {
      await use();
    } finally {
      await testInfo.attach(ATTACHMENT_NAME, {
        contentType: 'application/json',
        body: Buffer.from(JSON.stringify(recorder.stop())),
      });
    }
  }, { auto: true }],
});
export { expect };
```

Tests requiring these events import `test` from that fixture. Popups and additional pages need their own recorder. Browser diagnostics are observations: an assertion may intentionally exercise an HTTP error, so a 503 diagnostic does not automatically fail a test. Source/configuration hashes cover the recorded files; imported fixtures, external data, package behavior, and test intent require independent review.

The real Playwright 1.62.1 CLI was exercised with a tiny browser-free test, real worker/reporter callbacks, and a real Buffer attachment. The failing run exited 1; the subsequent passing run exited 0, with unchanged test source/identity and distinct run IDs. STAR's reader/comparator accepted the pair as `evidence_consistent` while keeping `verified_fix: false`. This establishes the collector-to-reader connection. It does not establish browser behavior or acceptance of the live STAR interface.

The official [Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp) adds performance analysis and source-mapped console/network inspection. It also documents browser-data exposure, usage statistics enabled by default, and optional CrUX requests. A local-first integration should explicitly configure its documented `--no-usage-statistics` and `--no-performance-crux` options and test a pinned version in a dedicated development browser. This upgrade does not silently add that server.

For Roblox, [Studio MCP](https://create.roblox.com/docs/studio/mcp) requires an explicit `studio_id`; [Studio breakpoints](https://create.roblox.com/docs/studio/debugging) distinguish client, server, and edit contexts. A replication investigation should compare authoritative server state with each client's observed state in the intended test instance. [MicroProfiler](https://create.roblox.com/docs/performance-optimization/microprofiler) supports frame investigation, while [Script Profiler](https://create.roblox.com/docs/studio/optimization/scriptprofiler) samples script CPU cost and excludes sleeping/waiting work. A low script CPU sample does not establish that a stalled operation is healthy.

## Profiler roadmap and platform constraints

Start with a short reproducible workload. For Python CPU/hang investigations, [py-spy](https://github.com/benfred/py-spy) samples another process and can report thread stacks. Its Linux documentation distinguishes launching a child, which commonly works without elevation, from attaching to an existing PID, which commonly requires additional permission. Container restrictions still apply. Native extension profiling supports Windows x86-64 and selected Linux architectures; idle-thread classification has documented limitations. STAR should report those limitations instead of interpreting every waiting frame as CPU work.

[Scalene 2.0.0](https://github.com/plasma-umass/scalene/releases/tag/v2.0.0) added Windows memory profiling. Older advice that Scalene never provides memory profiling on Windows is outdated. A future integration should pin and test the actual wheel/runtime combination and keep sampling overhead visible. For initial allocation questions, standard-library tracemalloc can provide a smaller first step.

[Memray's supported environments](https://bloomberg.github.io/memray/supported_environments.html) are CPython on Linux and macOS, with WSL tested; native Windows is unsupported. It can track forks but not allocations after an `exec`, which matters for spawned processes. It is consequently a Linux Brain/WSL option, not a universal Windows-desktop dependency.

The next implementation should import bounded profiler summaries tied to a workload, revision, duration, and tool version. It should retain the original capture for developer inspection and report missing symbols or incomplete samples. Adding all profilers to the default desktop installation would increase maintenance and startup dependencies without proving a benefit.

For React-specific failures, the documented [`createRoot` error callbacks](https://react.dev/reference/react-dom/client/createRoot) can provide caught, uncaught, and recoverable error information with component stacks. A future opt-in adapter can add those stacks to the same evidence format. The [React Profiler](https://react.dev/reference/react/Profiler) provides commit/render measurements but adds instrumentation overhead; use a suitable development or profiling build and measure the same interaction. These hooks are research recommendations here, not extra global handlers installed by this change.

Rust investigations should keep separate questions separate: [Miri](https://github.com/rust-lang/miri) checks small supported executions for undefined behavior, [Loom](https://github.com/tokio-rs/loom) explores modeled concurrency schedules, and [samply](https://github.com/mstange/samply) profiles measured CPU work across its supported platforms. Model coverage, unsupported system calls, and missing symbols remain visible limits.

## What AI-debugger research establishes

[Debug2Fix](https://arxiv.org/html/2602.18571v1), a February 2026 paper, reports GPT-5 success increasing from 31.2% to 36.2% on a 400-example Python subset of SWE-Bench Live: **5 percentage points**, approximately 16% relative. Its table also reports higher token consumption: 550k baseline versus 630k main-agent plus 350k debug-subagent tokens. Results vary with model and language. Its Java ablations show that directly exposing debugger tools can underperform a specialized workflow. These are results for the paper's agent and selected benchmarks, not STAR latency or success measurements.

The design inference for STAR is to route difficult runtime questions to focused evidence collection and concise analysis. It does not justify mandatory debugger launches for syntax errors, larger unbounded tool menus, or claims of an immediate speed multiplier.

Microsoft's [debug-gym](https://github.com/microsoft/debug-gym) is useful for controlled agent experiments and supports Hugging Face/vLLM models through an OpenAI-compatible endpoint. Its interactive PDB tooling currently works only on Linux because of terminal/PTY limitations. It belongs in a separate research environment rather than the Windows desktop's default dependency set. [ChatDBG](https://github.com/plasma-umass/ChatDBG) demonstrates debugger-driven natural-language diagnosis, but its current installation instructions require a funded OpenAI account. It is not the no-new-paid-API default chosen here.

[Hypothesis replay](https://hypothesis.readthedocs.io/en/latest/tutorial/replaying-failures.html) provides a complementary direction: retain minimized failing examples, replay them, and promote stable cases to explicit regression inputs. Candidate generated tests should be reviewed independently of the repair being judged. The existing evaluation fixtures remain harness-owned.

## How to measure whether STAR improves

Use paired runs of the same frozen issues, starting revisions, unchanged tests, model, inference settings, hardware, tool budgets, and dependency environment. Compare three conditions: existing STAR; structured reports/source windows; and reports plus developer-produced runtime or profiler evidence. Include Python logic, fixture failures, async hangs, browser failures, and Roblox client/server problems as separate groups. Randomize condition order and retain failures/timeouts in the denominator.

| Metric | What to record |
| --- | --- |
| Repair quality | Independently accepted repairs divided by all assigned cases; changed or skipped oracle tests cannot earn success. |
| Time to diagnosis | Wall time until the first correct, evidence-supported cause is identified. |
| Time to accepted repair | Median and p95 end-to-end time, including capture, model inference, retries, and regression checks. |
| Investigation cost | Tool calls, failed hypotheses, repair attempts, input/output tokens, and local inference duration. |
| Regression behavior | Newly failing tests, new skips/xfails, retries, incomplete evidence, and incorrect success claims. |
| Operational cost | Collector overhead, peak memory, artifact bytes, cleanup failures, and installation failures by OS. |

Publish paired per-case differences with uncertainty, not only averages from successful cases. Distinguish cold setup from warm repeated use. For Python microbenchmarks, [pyperf](https://pyperf.readthedocs.io/en/latest/run_benchmark.html) supplies calibrated loops, warmups, and worker processes; use it after identifying a concrete hotspot. A faster microbenchmark cannot substitute for measuring the full debugging loop.

### Validation recorded during implementation

| Check | Observed result |
| --- | --- |
| Linux: all six new debugger test modules plus agent catalogue/runtime, redaction, and untrusted-content regressions | **293 passed** in 28.40 seconds |
| Windows: evidence, integration, pytest collector, DAP, and the same application regressions | **241 passed, 1 skipped** in 38.20 seconds |
| Windows: final browser reporter/runner modules | **46 passed, 5 skipped** in 10.13 seconds |
| Windows broad Python regression run | **9,618 passed, 328 skipped, 4 failed**, with 27 passing subtests, in 465.52 seconds; baseline findings below |
| TypeScript checking | Passed |
| Frontend production build | Passed; the normal large-chunk advisory remains; website-only refresh/prerender were skipped |
| Frontend unit tests | **562 passed across 63 files** in 78.34 seconds, with the process-local Node flag described below |
| Static checks | Ruff passed on all ten new Python source/test files; both Node scripts passed syntax checking |

The Windows environments used Python 3.12.14, pytest 9.1.1, and debugpy 1.8.22 in an isolated temporary environment. The 33-case DAP suite ran on Windows, including real exception and breakpoint capture, normal completion, timeout/descendant cleanup, and cancellation. The pytest collector's 27 tests use real tiny subprocess suites. Reporter/runner tests cover fresh versus stale reports, retries, configuration changes, redaction, bounded artifacts, and process cleanup. The Windows browser skips comprise three unavailable-symlink cases and two POSIX-only cases; the Windows timeout/descendant cleanup case ran successfully. These scopes overlap and their counts must not be added together.

All four broad-suite failures reproduced in a separate, unchanged, detached worktree at main `bd575de0aba344b145fe7119d23670ec9c954967`, using the same temporary Python environment:

- Three existing `tests/test_blender_brain2_remote.py` launcher cases select the WindowsApps `bash.EXE` launcher, which exits 1 before the expected shell-script behavior is available.
- `tests/test_desktop_genesis.py::test_desktop_doctor_runs_without_gui` fails importing `keyring.backends.Windows`; `keyring` belongs to the separate desktop requirements and was absent from this development/debugger test environment.

The focused baseline run reproduced all four failures in 5.92 seconds. These findings do not make the broad suite green, and optional dependency/platform skips are not acceptance evidence. The broad run was followed by the separately reported final browser-module checks. No unrelated launcher, test, desktop dependency, or environment configuration was changed to conceal these results.

The Windows frontend host used Node 26.11.1. Its initial unit-test invocation reported 55 failures involving browser storage. Repeating the existing suite with process-local `NODE_OPTIONS=--no-experimental-webstorage` passed all 562 tests. The retry changed no frontend source, test, configuration, package manifest, or system-wide Node setting. TypeScript and the production build also passed. This records a compatible test invocation; it does not establish live desktop acceptance.

The local managed execution environment also reproduced an asyncio worker/shutdown hang without STAR or pytest, using `asyncio.run(asyncio.to_thread(lambda: None))`. The final Linux async/DAP checks used a scoped execution context where that minimal runtime probe and loopback communication worked. This is a test-environment observation, not evidence of a production STAR or universal Python defect.

The real Playwright CLI smoke result described above establishes a collector-to-reader connection using a browser-free test. No real browser, live STAR interface acceptance run, or paired STAR repair-quality/latency benchmark is claimed. The implemented tests establish tool behavior; the measurement protocol above remains the gate for claims that STAR solves problems faster or more accurately.
