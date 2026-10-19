# Recompilation analysis

STAR provides three original, bounded tools for reviewing PS3 recompilation inputs and evidence. They help identify structural problems and incomplete verification; they do not translate or execute a game.
The implementation is in [re_recompilation.py](../star/re_recompilation.py), [re_ps3_elf.py](../star/re_ps3_elf.py),
[re_semantic_evidence.py](../star/re_semantic_evidence.py) and [recompilation_guidance.py](../star/recompilation_guidance.py).

## Availability and workflow

The existing `reverse_engineering_enabled` setting remains **OFF by default**.
A selected workspace is required, including for guidance. This addition does not change agent settings,
permission gates, evaluation fixtures or lesson approval rules. The existing gateway validates tool arguments,
selected tool names and intent before dispatch. Recompilation-specific requests can select the three new tools;
unrelated prompts do not expose them. Existing binary-analysis requests retain the established gateway behavior.

1. Select a workspace containing the files you intend to inspect and enable the existing RE option when needed.
2. Request guidance for the relevant topic and establish the intended guest/runtime profile.
3. Run structural preflight on an unencrypted ELF; review blockers and unresolved ABI details.
4. Establish an expected test contract independently of the observed results.
5. Obtain reference and candidate records from your separately controlled test process, then compare them.
6. Investigate the first counterexample or coverage issues. Any reusable lesson still needs STAR's existing review.

Tool calls below illustrate argument shapes and paths; they are not records of executed guest tests. Paths use forward slashes and are relative to the selected workspace.

| Tool | Required arguments | Optional arguments |
| --- | --- | --- |
| `re_ps3_elf_preflight` | `path` | `expected_source_sha256` |
| `re_verify_recompilation_evidence` | `contract_path`, `reference_path`, `candidate_path` | `expected_contract_sha256`, `expected_reference_sha256` |
| `re_recompilation_guidance` | None | `topic`, default `overview` |

Unknown arguments are rejected. An expected SHA-256 must contain exactly 64 hexadecimal characters.

## Inspect a PS3 ELF candidate

~~~json
{"name":"re_ps3_elf_preflight","arguments":{"path":"analysis/guest.elf"}}
~~~

Add `expected_source_sha256` when you have an independently recorded hash for the exact input bytes. A wrong pin raises an input error; it does not produce a successful structural report.

The parser checks declared ELF headers, bounded program/section tables, file ranges, load memory ranges,
alignment and zero-fill regions. It reports the raw entry value and its declared mappings, plus recognized
section metadata. File widths and candidate profiles are deliberately separate:

| Candidate profile | Required container | Additional scoped check |
| --- | --- | --- |
| `ppu_32bit_effective_address` | Big-endian ELF64, `EM_PPC64` / machine 21 | Load regions fit the inspected project's 32-bit effective-address profile |
| `spu_local_store` | Big-endian ELF32, `EM_SPU` / machine 23 | Load regions fit a 256 KiB local store |

The PPU check follows the reviewed project's runtime profile; it is not a universal PowerPC address limit.
See the pinned [runtime documentation](https://github.com/sp00nznet/ps3recomp/blob/749182eebb936f086a007f63e1c7d853f3cf708a/docs/RUNTIME.md)
and the [ELF header](https://gabi.xinuos.com/elf/02-eheader.html) and
[program loading](https://gabi.xinuos.com/elf/07-pheader.html) format references.

`entry.callable` remains `null`: a mapped entry value does not establish a callable function.
An `.opd` section is metadata only; descriptor layout, target function and TOC are not inferred.
If section names are unavailable, `opd.present` can be `null` rather than a claim that descriptors are absent.
Overlapping load regions produce a warning because legitimate page sharing requires loader-specific review.

| Status | Meaning |
| --- | --- |
| `ready_for_review` | No structural errors, unsupported constructs or profile blockers were identified within the supported checks |
| `blocked` | A candidate has a profile/load-map blocker requiring review |
| `malformed` | A checked structure violates the declared format |
| `not_ps3_candidate` | The parsed class/machine/byte-order combination does not match either candidate profile |
| `unsupported` | The format, object type or extension is outside the bounded parser's scope |
| `unsupported_container` | An SCE/SELF signature was recognized; its wrapped payload was not interpreted |

`ready_for_review` is a structural result, not proof of loadability, instruction correctness, ABI correctness,
rendering or playability. SCE containers are not decrypted, unpacked or classified into SELF/FSELF subtypes.
Extended ELF numbering is unsupported. Instruction lifting, relocation processing and import resolution are outside this tool.

## Compare semantic evidence

~~~json
{
  "name":"re_verify_recompilation_evidence",
  "arguments":{
    "contract_path":"analysis/contract.json",
    "reference_path":"analysis/reference.json",
    "candidate_path":"analysis/candidate.json"
  }
}
~~~

The three inputs must be distinct UTF-8 JSON object files. The tool reads and compares them; it does not create reference runs or candidate runs. Duplicate JSON keys, NaN, infinity, unknown schema fields and malformed values
are rejected. Finite numeric floats are also invalid wherever the schema requires integers or raw bit strings.

Add `expected_contract_sha256` and/or `expected_reference_sha256` to pin those exact files.
The reader hashes each file's actual bytes and returns an input receipt. No candidate-file pin argument is exposed;
its actual hash is still reported. A pin authenticates neither its origin nor the process that produced a file.

### Shared value rules

Every field listed in the schema tables is required. Objects allow exactly their listed fields, with the
observable fields selected by `kind`. Identifiers are case-sensitive ASCII strings of 1–120 characters matching
`[A-Za-z0-9][A-Za-z0-9._:@/+~-]{0,119}` in full. SHA-256 strings contain exactly 64 hex characters and are normalized
to lowercase. All integer constraints reject booleans as well as floats.

`suite_sha256` is a caller-declared identity for the logical suite, such as a reproducibly defined suite source.
It is **not the hash of the contract JSON file**. `expected_contract_sha256` separately pins that file's actual bytes.
The case input and artifact digests are likewise declared identities; this comparison does not open those artifacts.

### Contract: `star-semantic-contract-v1`

| Field | Type and constraint |
| --- | --- |
| `schema_version` | Exactly `"star-semantic-contract-v1"` |
| `suite_id` | Identifier |
| `suite_sha256` | SHA-256 for the declared suite identity |
| `reference_artifact_sha256` | SHA-256 expected in the reference report |
| `candidate_artifact_sha256` | SHA-256 expected in the candidate report |
| `cases` | Array of 1–256 contract cases; unique `case_id` values |

| Contract case field | Type and constraint |
| --- | --- |
| `case_id` | Identifier |
| `input_sha256` | SHA-256 expected for this case in both reports |
| `observables` | Array of 1–16 observable specifications; unique `name` values within the case |

An empty expected inventory is rejected. Establish the inventory independently of the logs being assessed; deriving it from whichever cases happened to report would defeat the coverage guarantee.

### Evidence: `star-semantic-evidence-v1`

Reference and candidate reports use the same exact schema.

| Field | Type and constraint |
| --- | --- |
| `schema_version` | Exactly `"star-semantic-evidence-v1"` |
| `suite_id`, `suite_sha256` | Identifier and SHA-256 matching the contract |
| `artifact_sha256` | SHA-256 matching the role-specific contract artifact |
| `producer_id` | Identifier; must differ between the two reports |
| `run_id` | Identifier; must differ between the two reports |
| `complete` | Boolean; only `true` permits comparison |
| `exit_code` | Integer from -2,147,483,648 through 4,294,967,295, or `null`; only `0` permits comparison |
| `unsupported_operations` | Integer 0–1,000,000; only `0` permits comparison |
| `unverified_stubs` | Integer 0–1,000,000; only `0` permits comparison |
| `cases` | Array of 0–256 evidence cases; complete exact coverage is required for comparison |

| Evidence case field | Type and constraint |
| --- | --- |
| `case_id` | Identifier matching an expected case |
| `input_sha256` | SHA-256 matching that contract case |
| `status` | Exactly `complete`, `skipped`, `unsupported`, `error` or `unknown` |
| `observations` | Array of 0–16 observations; complete exact observable coverage is required |

Unreported exit status is represented explicitly as `null` and makes evidence incomplete. A failure, signal-like negative code or unsigned platform error code cannot be hidden by `complete: true`.
Both reports must claim completion and zero unsupported operations/unverified stubs. A measured interpreter
fallback is not automatically an unsupported operation. Different producer and run labels are required,
but their independence remains unauthenticated. The two artifact digests may match when separate runs observe the same test image.

### Observable specifications and recorded values

Every specification and observation has an identifier `name` and one of the following exact `kind` values.

| Kind | Remaining contract specification fields | Remaining evidence observation fields |
| --- | --- | --- |
| `bits` | `width_bits`: integer 1–128 | `width_bits`: integer 1–128; `hex`: fixed-width raw hexadecimal |
| `memory_sha256` | `size_bytes`: integer 0–134,217,728 | `size_bytes`: same range; `sha256`: SHA-256 |
| `events` | `max_events`: integer 1–128 | `events`: ordered array of 0–128 event objects |

For `bits`, `hex` has exactly `ceil(width_bits / 4)` characters, including leading zeroes and no `0x` prefix.
Unused high bits must be zero. For example, a 32-bit format can represent `00000000` and `80000000` as distinct
patterns; STAR does not convert them to host floats or apply a tolerance. Width and kind must match the contract.
Memory length must match the contract, and the supplied digest is compared without reading or reconstructing guest memory.

An event object has exactly `tag` (an identifier) and `data_hex` (0–128 bytes encoded as 0–256 hex characters
with an even length). Its order is significant. An empty event sequence can represent a completed observation
of no events; it does not excuse absent cases, missing observations or incomplete runs.
Each sequence must fit its contract `max_events`; a report has a total budget of 4,096 events across all cases.
Case and observable order may differ between reports because identities select them; event order may not.

### Interpret the verdict

| Verdict | Meaning and next step |
| --- | --- |
| `INCOMPARABLE` | Suite/input/artifact identities disagree, producer/run labels are reused, coverage is duplicate/extra, or observable layouts differ; repair the comparison setup |
| `INCOMPLETE` | Coverage or completion is missing, exit status is absent/nonzero, or unsupported/stub counts are nonzero; obtain complete evidence |
| `MISMATCH` | Coherent complete records disagree on at least one declared raw observation; inspect `first_counterexample` |
| `MATCH` | Every declared observation in the supplied coherent complete records agrees |

Malformed schemas and failed input pins raise errors rather than these verdicts. `INCOMPARABLE` takes precedence over `INCOMPLETE`. No values are compared until all identity and coverage checks pass.
A counterexample follows contract case/observable order and, for events, identifies the first differing index.
`counts` includes expected/reported/compared cases, compared and mismatched observables, and issue/omission totals.

Every comparison declares `scope: "supplied_records_only"`, `runtime_verified: false`,
`reference_authenticity: "unverified"` and `independence_verified: false`.
Even `MATCH` does not prove an execution occurred, validate unreported behavior or establish game compatibility,
timing or speed. The records' hashes, counts, completion and exit status remain caller-supplied claims.

## Retrieve research guidance

~~~json
{"name":"re_recompilation_guidance","arguments":{"topic":"verification"}}
~~~

Topics are `overview`, `elf`, `ppu`, `spu`, `verification`, `runtime` and `porting`.
`overview` returns nine original principles with preconditions and acceptance checks, backed by 13 source entries:
container validation; guest ABI preservation; instruction semantics; explicit SPU state; complete test inventories;
bounded oracle claims; runtime service coverage; reproducible initial state; and separate visual/CPU evidence.

The source snapshot is [sp00nznet/ps3recomp at 749182eebb936f086a007f63e1c7d853f3cf708a](https://github.com/sp00nznet/ps3recomp/tree/749182eebb936f086a007f63e1c7d853f3cf708a),
recorded as v0.16.0 in the guidance and researched on 2026-10-19. Each returned principle cites source IDs,
and the `sources` array supplies direct URLs, including ELF specifications, Alive2 and Csmith.
Guidance has `status: "candidate"` and `evidence_scope: "reference_guidance"`. It provides on-demand context;
it does not browse, train a model, execute fixtures, accept a lesson or change permissions.
Recheck mutable external documentation against the compiler/runtime actually selected.

## Input boundaries and resource limits

The [input reader](../star/re_analysis_input.py) applies the existing workspace and sensitive-file boundary.
It rejects ambiguous portable paths, traversal, rooted/drive paths, Windows device names, alternate data stream
syntax, symbolic links, reparse points, nonregular files and aliases among the selected inputs.
Checks cover file identity, size and timestamps before/during/after reads and after analysis.

| Limit | Bound |
| --- | --- |
| ELF input | 64 MiB; up to 1,024 program headers and 4,096 section headers |
| Evidence inputs | 2 MiB per JSON file; three files total, at most 6 MiB |
| Stream read chunk | 64 KiB |
| Read deadline | 15 seconds shared across input reads, checked cooperatively |
| Parser details/output | At most 24 per detail collection; report further trimmed to 16,000 serialized characters |
| Comparator issues | At most 24 details, retained total/omission counts, one first counterexample |
| Tool output | At most 24,000 serialized characters; an oversized result raises an error |

The deadline is not an OS interruption guarantee for a stalled filesystem read.
`input_stability: "no_change_observed"` reports the outcome of checks, not an atomic snapshot or an OS sandbox
against hostile concurrent ancestor-directory replacement. Successful file analyses include receipts with
`path`, `size_bytes`, `sha256`, `pin_checked` and unauthenticated provenance.
All three tools declare `read_only: true`, `executed: false` and `runtime_verified: false`.
No tool launches a compiler, emulator, shell or target binary, writes output files, or promotes learned content.

## Developer validation and integration scope

This work was prepared against private-repository `main` at `80bf8540b75633c065437036baf75614afe68f74`,
independently of Grand-V PR #499. A temporary three-way merge of both gateway changes was textually clean
and compiled as Python. In that isolated combined snapshot, all 406 selected relevant tests passed, and
hash checks confirmed that the 25 selected source/test files remained unchanged during validation.
This checks the supplied analysis tools together; it does not execute guest programs or merge either PR.
Grand-V-only and PS3-only prompts select their respective tools; a mixed prompt selects the earlier PS3
handler. An ordinary binary-analysis prompt exposes both additions through the existing RE gateway.
Only the existing optional RE gateway is extended; no agent/settings/evaluation gate modification is required.

The focused local review used a partial source snapshot and `pytest --noconftest` because unrelated normal
fixtures import components outside that snapshot. All 276 selected tests passed: 35 existing tests and
241 new cases (29 ELF, 94 semantic evidence, 70 input-reader and 48 gateway cases). Ruff passed for all
10 changed Python files; source compilation, whitespace checks and the explicit changed-path protected
closure check also passed. The 406-test combined check is a separate overlapping run, not 406 additional
unique tests. These tests check analysis and evidence handling; they do not execute guest instructions.

The [validation receipt](research/STAR_PS3RECOMP_VALIDATION_20261019.json) records the pinned base,
commands, environment, result scope and SHA-256 hashes of the reviewed Python files.

In a complete checkout, use the repository's normal checks and fixtures before acceptance:

~~~sh
python -m compileall -q star main.py
python -m pytest -q
~~~

Full-repository GitHub CI with normal fixtures remains pending at this guide's preparation time.
Source inspection, synthetic tests, authenticated target execution and downstream gameplay evidence remain distinct.
