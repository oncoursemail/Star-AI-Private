# Reference engineering: learn useful patterns and verify assets

This add-on lets STAR retrieve a scoped engineering study, plan a target from
reported capabilities, and verify local asset content. The research started from
[Grand-V's launcher release](https://gitlab.com/SebasKitten/Grand-V/-/releases/launcher-2026.10.18).
Its inspected package validator checks file sizes, which cannot detect changed
bytes of the same length. STAR's new verifier requires SHA-256 for every listed
asset. [Pinned validator source](https://gitlab.com/SebasKitten/Grand-V/-/blob/6cef9e1fcca97dde758be845930a7bb9738339b9/LauncherApp/rust/src/config.rs).

## Availability and integration

The existing `reverse_engineering_enabled` desktop setting remains false by
default. The tool family also requires an owner-selected workspace. There is no
new settings file, installer, background service or training job.

`star/reverse_engineering.py` registers and dispatches the tools through the
existing selected-name entitlement and JSON Schema checks. The main agent loop,
workspace policy, lesson store, evaluation gate and existing byte-comparison
tool are unchanged. A prompt about an asset manifest, Grand-V, game portability,
WebAssembly or WebGPU offers only the three new read-only tools unless it also
matches the existing binary-analysis trigger. Unrelated prompts offer none.

The change is a development candidate. The repository's normal independent
review and evaluation requirements apply before activation or distribution.
The examples below describe the candidate code, not a deployed STAR update.

## 1. Verify listed asset bytes

Tool: `re_verify_asset_manifest`

```json
{
  "manifest_path": "asset-manifest.json"
}
```

An optional `expected_manifest_sha256` field pins the raw manifest's SHA-256 to
a separately recorded value. A wrong pin returns `FAIL` before any asset read.
The pin is supplied by the caller; this tool does not authenticate its origin.

The manifest format has exactly four root fields. This example describes an
empty, original fixture file; its SHA-256 is the standard digest of zero bytes.

```json
{
  "schema_version": "star-asset-manifest-v1",
  "package_id": "example-game-assets",
  "version": "1",
  "assets": [
    {
      "path": "assets/empty.bin",
      "size_bytes": 0,
      "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "source": "https://example.org/original-fixture",
      "license": "owner-created example"
    }
  ]
}
```

`source` and `license` are optional provenance labels. Their content is not
fetched or verified. Record manifests from the accepted build; generating new
hashes from already damaged assets would only record the damage as a baseline.

Every member path is relative to the **selected workspace**, including when the
manifest itself is in a subfolder. Unlisted files are outside the audit. This is
a STAR format; Grand-V's existing size-only manifest needs independently
established content hashes before it can supply the same evidence.

| Bound | Value |
|---|---:|
| Manifest file | 128 KiB maximum |
| Assets listed | 1–128 |
| Each asset | 128 MiB maximum |
| Total declared and observed asset size | 512 MiB maximum |
| Streaming read chunk | 64 KiB maximum |
| Cooperative elapsed-time budget | 15 seconds |
| Detailed result entries | 24, failures first |

The time budget is checked between local operations. It cannot interrupt an OS
read or filesystem metadata call already in progress. Oversized packages should
use separate manifests for bounded asset groups; increasing the caps is not part
of this change. A SHA-256 scan consumes I/O proportional to the bytes checked;
it is not a free or metadata-only operation.

`PASS` requires matching sizes and hashes for every listed file, a matching
optional manifest pin, and unchanged observed file identities. `FAIL` records
missing, unreadable, changed or mismatching files. `INCOMPLETE` means the time
budget prevented completion. Output contains total counts, `status_counts`,
`omitted_results`, and bounded per-file details. `bytes_hashed` counts completed
stable reads, so interrupted reads can incur additional I/O.

The entire schema and member paths are validated before hashing the first
asset. The verifier rejects duplicate JSON fields, unsupported fields, malformed
hashes, invalid sizes, case-insensitive duplicate paths, duplicate file aliases,
workspace escapes, credentials, symlinks and Windows reparse points. It checks
portable names using [Windows filename rules](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file).

Identity checks cover the file read and a final pass across earlier assets. A
result is observational, not an atomic filesystem snapshot or a sandbox against
a hostile process concurrently replacing ancestor directories. Keep the selected
asset tree stable during verification. Successful byte consistency does not
establish gameplay, performance, publisher identity, safety or asset rights.

## 2. Plan game portability from reported facts

Tool: `re_game_portability_plan`

```json
{
  "target": "browser",
  "required_linear_memory_mib": 6144,
  "webgpu": true,
  "requires_threads": true,
  "threads": true,
  "cross_origin_isolated": true
}
```

Here the tool reports that the unchanged workload requires wasm64, while
`memory64` remains unknown. It does not select wasm32 or claim that the game ran.
The memory input is a positive integer MiB value for live linear memory,
including static data, stack and heap. It is separate from JavaScript objects,
decoded assets and GPU allocations. The 1,048,576 MiB numeric input ceiling is a
parser bound, not a browser allocation promise.

Targets are `browser`, `roblox` and `native`. Omitted optional booleans remain
unreported. False means reported unavailable, and true still requires actual
runtime validation. Required browser threading retains the separate nonthreaded
build requirement and main-thread responsiveness checks. An unavailable WebGPU
adapter requires a tested alternative; fallback support is not invented.

Browser reports do not validate native or Roblox targets. Roblox plans instead
ask for engine-native profiling, streaming and actual Studio MCP capability
discovery. Native plans call for the selected OS/ABI, renderer, dependencies and
measured workload. All outputs say `status: candidate` and
`runtime_verified: false`.

## 3. Retrieve source-backed engineering guidance

Tool: `re_reference_guidance`

```json
{"topic": "streaming"}
```

Topics: `overview`, `browser`, `streaming`, `multiplayer`, `asset_integrity`, and
`roblox`. Each returns original principles, their preconditions, acceptance
checks and source URLs. The nine principles cover memory capacity, workers,
WebGPU contracts, streaming, performance evidence, asset integrity, hosting
budgets, multiplayer scope, and Roblox profiling.

The overview retains twelve primary documentation sources. Grand-V source
observations are pinned to `6cef9e1fcca97dde758be845930a7bb9738339b9`. Mutable
official documentation is dated 2026-10-19 and must be rechecked for the target
toolchain. Results are bounded to approximately 6,000 serialized characters.

This gives STAR useful reference context on demand. It does not import or accept
persistent lessons, change model weights, or turn a maintainer claim into a
tested fact. Future lesson promotion should attach project-specific execution
evidence and use STAR's existing candidate-review process.

## Verification

The focused suite uses original synthetic fixtures and the real RE gateway:

```text
python -m pytest -q tests/test_reverse_engineering.py tests/test_re_artifact_verifier.py tests/test_re_asset_manifest.py tests/test_reference_engineering_gateway.py tests/test_game_portability.py tests/test_re_manifest_review.py
python -m compileall -q star/reverse_engineering.py star/re_asset_manifest.py star/game_portability.py
```

It covers corruption, missing assets, strict schema and path handling, streamed
reads, input mutation, hard budgets, default-off behavior, selected-tool checks,
and absence of network/process/workspace-write side effects. Planner tests cover
memory boundaries, unknown capabilities, all thread/isolation combinations,
source completeness and bounded output.

These focused Linux checks do not replace the full repository CI, independent
evaluation, native Windows validation, browser/Studio tests or real gameplay
benchmarks. No speedup, new game engine or complete Grand-V reproduction is
claimed. The deeper findings are in
[Grand-V research](research/STAR_GRAND_V_RESEARCH_20261019.md).
