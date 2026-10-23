# Public-page reader: bounded waits and responsive text extraction

Date: 2026-10-19 UTC. Baseline inspected: `star/web_fetch.py` on private `main`, blob
`c6d9e687397f4ab28a6a2b96586b70c54df845e1`.

## Problem and observed code path

Every existing caller of `fetch_page` uses the same public-page reader. The previous implementation
started one 15-second monotonic deadline and applied the remaining budget to HTTP sending and body
reading. However, `asyncio.to_thread(check_url, ...)` was awaited without that deadline. An operating
system DNS lookup could therefore keep the caller waiting beyond the advertised total limit. After
download, decoding and `HTMLParser` extraction ran on the event-loop thread; a costly page could delay
other async work and cancellation while extraction was running.

This change applies to the existing function and preserves its arguments, `Page` representation,
public-address checks, redirect limit, pinned destination/Host/TLS SNI, content-type checks, download
size limit, and untrusted context framing. It does not add a cache, new data permissions, model
parallelism, private endpoints, or another research planner.

## Implementation

DNS/address validation uses four dedicated worker slots. Decoding and text extraction use two separate
slots. Admission is nonblocking: if all slots in a stage are occupied, the reader returns a clear busy
error. Submissions require a slot before entering the executor, so cancelled calls cannot build an
unbounded queue behind a stuck resolver. These small fixed values are resource bounds, not measured
optimum throughput settings.

One monotonic deadline is created at `fetch_page` entry. Remaining time is rechecked for DNS, each
redirect, each HTTP request/body read, and text extraction. The same deadline reaches every hop; a
redirect does not receive another 15 seconds. Expiration during DNS or extraction produces a bounded
failure rather than returning data after the budget.

The underlying concurrent future owns its worker slot. Cancelling or timing out an async waiter does
not release that slot while its thread is still running. Completion, failure, or cancellation before
execution returns it exactly once. Failed executor submission also returns its reservation. Workers
are shared across event loops and separate from asyncio's default executor, which remains available
for unrelated application work.

An operating-system DNS request or running Python parser cannot be forcibly killed by cancelling an
asyncio task. After the caller stops waiting, a bounded worker may remain occupied until the blocking
operation finishes. If all DNS workers remain stuck, new reads fail busy until capacity actually
returns. This change does not claim to repair the operating system resolver or provide a hard real-time
guarantee. Async HTTP cleanup is preserved; Python cancellation/cleanup and thread scheduling can add
overhead around the application budget. A worker thread also does not make Python parsing use several
CPU cores simultaneously on ordinary GIL-enabled CPython.

## Primary sources behind the design

- Python documents `asyncio.wait_for` cancellation and warns that total waiting can exceed the nominal
  timeout while cancellation completes. It also explains `to_thread`, propagation of cancellation,
  and the GIL limitation for CPU-bound Python work:
  https://docs.python.org/3/library/asyncio-task.html
- Python's futures documentation specifies that a running future cannot be cancelled and distinguishes
  pending work from already executing work. This is why the underlying future releases admission:
  https://docs.python.org/3/library/concurrent.futures.html
- HTTPX separates connect, read, write, and pool timeouts. A read timeout measures waiting for a chunk;
  it is not a cumulative deadline for DNS, redirects, downloads, and parsing:
  https://www.python-httpx.org/advanced/timeouts/

Connection pooling is another possible optimization, but this patch keeps each page's current client
lifetime. HTTPX explains why a reusable client can avoid repeated connection setup; an eventual
research-scoped client needs its own carefully reviewed DNS pinning, TLS, cookie, cancellation, and
closure behavior: https://www.python-httpx.org/advanced/clients/

## Verification

New `tests/test_web_fetch_responsiveness.py` uses mocked HTTP, fixed public DNS answers, and Events
controlling when blocking work may finish. No real website or model server is contacted. The checks
establish:

- A stalled DNS caller returns on its configured budget without making an HTTP request.
- Timed-out/cancelled DNS still owns its slot; repeated new calls fail busy instead of queuing work.
- Actual worker completion and worker failure restore usable capacity.
- Blocking text extraction runs off the event loop while an explicit heartbeat continues.
- Timed-out parsing keeps its slot until extraction really ends.
- DNS and redirects share the original deadline, with no HTTP request after it expires.
- Cancelled body reading closes the response.
- Private/mixed DNS answers still fail before any HTTP request, and oversized bodies do not reach
  extraction.

Executed with Python 3.12.14, HTTPX 0.28.1, pytest 9.1.1:

```text
python3 -m pytest -q tests/test_web_fetch_responsiveness.py tests/test_web_fetch_hardening.py tests/test_web_fetch.py \
  -k 'not agent_offers_fetch_with_search_and_runs_it and not fetch_is_refused_without_the_web_switch'

61 passed, 2 deselected in 0.46s
```

The two existing agent integration tests were deselected because the local inspection checkout lacked
the full `star.agent` dependency tree. Existing web-reader tests and fixtures were copied unchanged
from their GitHub blobs; no stored evaluation cases or baselines were altered. This focused run does
not claim that the full application test suite, a live search workflow, or a release gate passed.

The execution sandbox blocked `socket.send` for asyncio's local self-pipe, which caused a standalone
stdlib threaded-future reproducer to time out as well. The offline suite was rerun with the normal
approval reviewer allowing that local socket operation; all HTTP/DNS traffic remained mocked. No
production polling workaround was added for the test sandbox.

These are correctness and responsiveness results. No end-to-end Star AI speed percentage, real-site
latency improvement, token-generation rate, or foundation-model intelligence increase was measured.
