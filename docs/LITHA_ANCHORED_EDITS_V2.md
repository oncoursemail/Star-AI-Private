# Litha Anchored Edits v2

Date: 2026-11-01  
Motivation: retain the efficiency of OMP-style hashline edits while eliminating short-tag ambiguity and adding stronger transactional behavior.

## Goals

1. A model changes only content it has actually inspected.
2. Concurrent changes are rejected or safely rebased, never silently overwritten.
3. Multi-file mutations can be recovered after partial filesystem failure.
4. Edits are compact enough for local 4B–9B models.
5. The verifier can prove exactly what changed.
6. The protocol works with Python, TypeScript, Rust, Luau and ordinary text.

## Non-goals

- replace LSP rename;
- replace AST rewrites;
- make all files globally transactional at the filesystem level;
- permit a fuzzy match merely because it "looks close."

## Snapshot identity

Do not use a 4-hex snapshot id as the authoritative identity.

Each read records:

```text
snapshot_id = BLAKE3-128(
    canonical_path
    || normalized_content_bytes
    || content_length
)
```

Display may abbreviate the id for humans, but tool calls carry the full identity.

Per revealed region:

```text
range_id = BLAKE3-128(
    snapshot_id
    || start_line
    || end_line
    || exact_region_bytes
)
```

Optional line anchors can use shorter display ids, but apply verification always resolves them back to the full recorded snapshot/range metadata.

## Seen provenance

Session records:

```text
ReadProvenance {
  path
  snapshot_id
  ranges[]
  timestamp
  source_tool_call_id
}
```

An edit is invalid if its destructive range is outside inspected provenance.

Pure insertion at a known boundary is permitted only if both neighboring anchors are known, except insertion at explicitly read start/end.

## Edit operation

```json
{
  "path": "src/example.ts",
  "snapshot": "<128-bit-id>",
  "operations": [
    {
      "kind": "replace",
      "range": {"start": 41, "end": 45},
      "range_id": "<128-bit-id>",
      "content": "..."
    }
  ]
}
```

Supported operations:
- replace range;
- insert before/after anchor;
- delete range;
- move with explicit source/destination;
- create new file through a separate create/write primitive.

## Prepare phase

For every file:
1. canonicalize and policy-check path;
2. read current bytes;
3. compute current snapshot;
4. check expected snapshot;
5. if stale, do not immediately fuzzy-apply;
6. attempt deterministic recovery only when a unique exact context/range mapping is proven;
7. render proposed diff;
8. run syntax/AST parse when available;
9. run formatting preview when configured;
10. create staged file in same filesystem where possible.

Any ambiguity stops the whole transaction before canonical files are touched.

## Transaction journal

Create:

```text
<Litha data>/transactions/<txid>/
  manifest.json
  before/
  staged/
  status.json
```

Manifest contains:
- canonical paths;
- before hashes;
- after hashes;
- operation provenance;
- model/tool-call id;
- policy decision id.

## Apply phase

For each path:
1. verify current hash still equals prepared before hash;
2. flush staged content;
3. replace target atomically when the platform/filesystem permits;
4. record applied step in journal.

After all writes:
1. invalidate workspace caches;
2. emit file-watch events to LSP/indexers;
3. run immediate parse/diagnostic verification;
4. mark committed.

## Partial failure

If write N fails after 1..N-1:
- journal remains non-committed;
- restore already-replaced files from `before/`;
- verify restored hashes;
- report rollback result;
- if rollback itself fails, surface a high-severity recovery state with exact affected paths.

Do not claim full ACID semantics across arbitrary filesystems. The guarantee is **journaled best-effort all-or-rollback with verified recovery**.

## Stale recovery policy

Allowed automatically:
- line offset moved but exact anchored region + context occurs uniquely;
- formatter-only surrounding drift with exact semantic anchor and a deterministic single mapping;
- destination path renamed and LSP/VCS mapping proves identity.

Not automatic:
- multiple candidate matches;
- changed code inside destructive range;
- generated/minified file without explicit opt-in;
- binary or undecodable file;
- path outside workspace;
- untrusted symlink/reparse-point escape.

## Model-specific edit modes

Litha should benchmark per model:
- Anchors v2;
- AST edit;
- apply patch;
- full replace for tiny files.

A model can have a preferred protocol profile. No edit mode is declared universally best.

## Verification ladder

```text
prepare
  -> syntax parse
  -> semantic/LSP diagnostics
  -> formatter
  -> targeted tests
  -> project tests as budget permits
  -> diff-risk classifier
  -> commit/promote
```

Failed verification produces a compact repair packet containing only:
- failed check;
- relevant diagnostics;
- changed ranges;
- nearest semantic context.

## Benchmark acceptance

Anchors v2 must beat current full-file replacement on:
- first-pass correct edit rate;
- stale-edit rejection;
- unchanged-line preservation;
- output tokens;
- repair iterations;
- wall time.

Required adversarial cases:
- concurrent editor modifies same range;
- concurrent editor modifies different range;
- hash-prefix collision;
- same snippet appears multiple times;
- CRLF/LF differences;
- Unicode normalization;
- file renamed between read/apply;
- formatter changes line layout;
- OS failure on second file of multi-file transaction;
- symlink/reparse-point path change.
