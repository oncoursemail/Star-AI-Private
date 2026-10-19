# Bulk tasks across workspaces and brains

This opt-in desktop feature adds two explicit workflows to **Inside STAR** while
preserving the existing Studio, Settings, and Brain overview design:

1. Send the same **read-only task** to selected, owner-captured local/LAN brains.
2. Preview and apply the same **text replacement** to explicit files in selected
   workspaces, with per-target receipts and a separate guarded undo preview.

The feature is off on first use. Opening the page starts no model request. The
page never selects every target implicitly. Brain responses are analyses or
proposals; they do not execute tools, edit files, or publish anything.

## Use it

1. Configure the desired project, workspace, provider, and model in the existing
   Settings. For a LAN brain, configure its current server key there as usual.
2. Open **Inside STAR → Bulk tasks**, turn on bulk tasks, give the configuration
   a name, and choose **Save current target**. To permit edits for this target,
   both Settings' workspace editing switch and the capture checkbox must be on.
3. Repeat capture after selecting another workspace or brain in Settings. Each
   saved target keeps its own immutable workspace and connection snapshot.
4. Select the intended targets. Choose a read-only brain prompt or workspace
   text edit. File paths are explicit relative paths; there is no recursive
   wildcard or “all workspaces” fallback. Brain prompts may include only the
   explicitly selected context files.
5. Choose concurrency, the number of initial canary targets, and the failure
   cutoff. Review the named targets and, for edits, the file diffs. **Send reviewed
   batch** approves the recorded intent hash. Changing the draft invalidates its
   current preview.
6. Inspect each target's result. **Request cancellation** stops new dispatch and
   signals active work. Already completed edits remain recorded. Leaving the
   page does not stop the desktop's active batch; its history is available when
   the page is reopened.
7. For completed workspace targets, create a separate undo preview. Undo checks
   that every file still contains the original batch's output before replacing
   it. Later owner edits are preserved by refusing a stale undo.

A target cannot provide an arbitrary endpoint or workspace through the bridge.
Capture reads the current trusted Settings. Remove and recapture a target to
change its configuration or update its saved LAN credential. Cloud providers
are outside this first workflow.

## What is durable

The local `bulk-tasks/operations.sqlite3` journal records immutable batch intent,
stable per-target operation IDs, selected targets, configuration fingerprints,
before/after content hashes, cancellation requests, bounded results, and status.
SQLite uses full synchronous commits. An OS-owned lifetime lock prevents two
desktop processes from independently recovering or dispatching the same ledger.

An identical idempotency key and identical intent return the existing batch. A
changed intent with the same key is rejected. Double Send and lost UI replies
do not automatically repeat work. Creating a new, explicitly reviewed batch is
different from replaying an old one.

The desktop does **not** automatically resume prepared or unfinished batches on
startup. Operations accepted/running when the process ended become
`outcome_unknown`, and undispatched targets stop. A lost completion record cannot
prove whether an external effect occurred. The owner must reconcile the reported
paths/results before creating further work. This does not claim exactly-once
execution on external servers or filesystems.

Prepared previews currently have no automatic time expiry. Target fingerprints,
current edit permission, root identity, file hashes, and selected context are
checked again when they are used. The underlying engine supports an explicit
expiry for future application-owned workflows.

### Status meanings

| Status | Meaning |
| --- | --- |
| Prepared | Intent is stored and awaits the owner's Send action. |
| Running | The desktop has started dispatch, or an adapter is active. `dispatch_pending` distinguishes the brief handoff before the ledger marks running. |
| Succeeded | The adapter returned its completed result. Read-only model output remains unverified analysis. |
| Partial | Some confirmed work completed and other work stopped or failed. |
| Failed / conflict | A confirmed failure or stale precondition prevented completion. |
| Cancelled | The engine did not dispatch the operation, or the adapter confirmed cancellation. |
| Stopped / skipped | No new work started for the remaining targets after a canary, failure, or recovery stop. |
| Outcome unknown | The host cannot establish the effect; it does not retry the operation. |

Cancellation never changes a returned completed result into a cancelled result.
Closing an HTTP request establishes local cancellation, not termination of model
computation inside a remote server. Closing STAR requests cancellation before
the normal desktop shutdown path; an interrupted process is reconciled by the
journal on its next start.

## Execution and quality controls

Only one bulk batch is active per desktop. Its shared executor allows up to four
target callbacks. All initial canary targets must succeed before dispatch widens.
The failure cutoff prevents new dispatch; already running operations can finish.
An unknown effect always stops further dispatch, independent of the cutoff.

Brain requests are serialized by endpoint across saved profiles, including the
`localhost` / `127.0.0.1` spelling pair. Different private addresses may alias one
physical machine; this first implementation cannot prove that relationship. This
client-side limit is not a server-wide resource lease: ordinary chat, media work,
other applications, and other STAR desktops can still use the server.

Each brain request uses the existing read-only conductor fleet, one selected
model, one call, no tools, no proxy routing, no redirects, and no automatic HTTP
retries. Receipts report requested/observed model identity where available, token
counts when supplied, output/input hashes, and elapsed time. They never label
the answer independently verified. Responses are bounded, and truncation is
explicit. Provider error bodies are not copied to the batch journal or interface.

Workspace edits reuse `Workspace` path protection and write handling. Preview and
apply refuse protected/sensitive paths, symlink and reparse aliases, hardlink
aliases, nonregular files, unsupported encodings, and stale roots/files. All files
in a target are checked before its first write, then checked again before each
write. After each atomic file replacement the exact expected content hash is
read back. Receipts retain confirmed writes even if a later file fails.

These checks verify **written bytes**, not program correctness. Syntax checks,
tests, visual review, and installed-app acceptance remain separate evidence. A
batch across files/workspaces is not an atomic filesystem transaction. The
in-process edit lock covers overlapping roots, but external editors do not take
that lock; the implementation does not promise OS-level atomic compare-and-swap.

### Bounds

| Resource | Limit |
| --- | --- |
| Saved/selected targets | 32 |
| Active bulk batches | 1 per desktop |
| Parallel target callbacks | 1–4, chosen for each batch |
| Concurrent bulk brain requests | 1 per normalized endpoint |
| Selected files | 16 per target |
| Before + after edit content | 1 MiB per target, with a 2 MiB total batch payload limit |
| Prompt | 5,000 characters |
| Selected context | 6,000 characters total per target; no silent truncation |
| Prompt + context task | 12,000 characters |
| Per-target stored result | 64 KiB, preserving the supported workspace receipts; oversized custom results are explicitly truncated |
| Model response | 850 requested tokens; bounded displayed answer |
| Model request deadline | Existing provider timeout, bounded to 30–600 seconds |

Large diffs are explicitly marked as truncated. A broad batch can reach the total
payload limit before reaching the target/file count limit; split it into smaller
reviewable batches.

## Local data and credential boundaries

The journal contains selected prompt/context and before/after source text needed
for review and undo. It belongs in STAR's local application data, not source
control, public releases, or a shared network database. New bulk data directories
use private owner permissions where supported. The feature does not install
services or synchronize workspace files to another machine.

LAN keys live in separate OS-keyring entries, bound to both saved target ID and
canonical endpoint. The JSON profile and SQLite payload contain a credential
reference only. Changing the current global server key does not silently change
an older captured target. Capture refuses LAN persistence when a supported secure
OS-keyring backend is unavailable; there is no plaintext fallback.

## Implementation map

| File | Responsibility |
| --- | --- |
| `star/bulk_operations.py` | Durable immutable intent, operation receipts, bounded scheduling, canaries, cancellation, recovery. |
| `star/bulk_workspace.py` | Protected file context, preview, byte/hash checks, writes, reverse plans. |
| `star/bulk_profiles.py` | Current-Settings capture, local metadata, endpoint-bound OS credentials. |
| `star/bulk_tasks.py` | Desktop action contract, adapters, background batch lifecycle, review/status projection. |
| `star/react_shell.py` | Explicit action allowlist, lazy service, off-UI-thread requests, shutdown cancellation. |
| `frontend/src/BulkTasksPanel.tsx` | Opt-in controls, explicit targets, review, per-target results, history and status reconciliation. |

The integration does not modify `Desktop.tsx`, Settings layouts, core policy,
provider routing, release workflows, or model/server configuration. The small
Brain overview insertion is intended to remain compatible with ongoing Studio
design work; overlapping future shell integrations still need deliberate review.

## Useful next additions

These are proposals, not implemented capabilities or measured speedups.

1. **Prepare once, specialize per workspace.** Build one structured change recipe
   and render a workspace-specific plan. Cache preparation by recipe revision and
   selected source hashes, never across unrelated private projects. This can
   reduce duplicate model calls while keeping edits independently reviewable.
2. **Generate → verify → compare.** Run proposal workers across brains, then
   developer-owned syntax/test checks and an independent review worker. Keep the
   fastest result that passes the required checks, with observed evidence for
   why it was selected. Model self-ratings must not stand in for test results.
3. **Dispatch from real capacity.** Add server-issued expiring leases for CPU,
   memory, VRAM, model slots and long media jobs, using stable physical server
   identity. Telemetry should inform the scheduler; only a valid reservation
   should authorize scarce capacity. This would coordinate bulk work with chat
   and media instead of relying only on per-client endpoint limits.
4. **Checkpoint large jobs by stage.** Persist preparation, proposal, verification,
   and review artifacts separately. Resume only completed read-only stages whose
   inputs and worker revisions still match. Side effects continue to require
   reconciliation and an explicit new reviewed intent after uncertainty.
5. **Reusable target groups and task recipes.** Save named groups such as “docs
   workspaces” or “review brains,” show their resolved membership every time, and
   require an explicit reviewed snapshot. Group membership changes must invalidate
   the preview. Never treat an empty group as all targets.
6. **Diff-focused quality review.** Show which files and checks are affected by a
   change, detect conflicting proposals, and separate successful byte edits from
   passing tests and native/visual acceptance. Add partial-target undo only for
   confirmed applied files, with the same fresh hash checks.
7. **Measure useful work, not activity.** Record end-to-end completion latency,
   verified task success, queue delay, model-call count, retries avoided, and
   observed resource contention. Compare the same representative tasks before
   claiming that more workers make STAR faster or higher quality.

## Validation scope

Focused automated checks cover real local file effects, crash recovery in a child
process, deduplicated intent, cancellation, concurrency, stale previews, guarded
undo, profile/credential isolation, and bridge behavior. Model transports are
fakes in these tests. They do not demonstrate live brain performance or native
Windows packaging. The PR records the exact executed commands and results.
