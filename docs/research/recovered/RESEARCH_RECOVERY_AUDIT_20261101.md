# Research recovery and implementation audit — 2026-11-01

This is a **tracking and verification ledger**, not a claim that all research was integrated or that any model became smarter. Target: `star/next`. Preserve all historical PRs and source material. Never automatically merge or publish private artifacts.

## Status definitions
- **MERGED**: source is present on the target branch at an identified commit.
- **PR_ONLY**: proposed changes exist in a specific unmerged PR.
- **LOCAL_ONLY**: original deliverable exists outside GitHub; no matching GitHub publication proven.
- **PARTIAL**: some topic coverage exists, but original artifact or acceptance evidence is missing.
- **UNKNOWN**: not enough evidence. Do not silently upgrade this to MERGED.

## Priority recovery register

| Original research / chat | Current audit status | Required verification / action |
|---|---|---|
| Lemonade SDK + AnythingLLM, 2026-10-29 (`Litha_Lemonade_AnythingLLM_Research.md`, `litha-lemonade-anythingllm-integration.zip`) | LOCAL_ONLY / PARTIAL | Recover source archive, review licenses and secrets, import research as provenance-preserving text and separately review bridge code |
| Rust ranking pilot, 2026-10-30 (`STAR_Performance_Audit_2026-10-30.md`, `STAR_Performance_Audit_and_Rust_Pilot_2026-10-30.zip`) | PARTIAL | Rust work was merged separately; original pilot and its process-start overhead, parity and benchmarks require preservation and independent replication |
| Broad Litha AI/UI discovery, 2026-10-29 (`Litha_AI_Research_Kit_2026-10-29.zip`, `Litha_UI_Research_Pack_2026-10-29.zip`) | PARTIAL | Compare 9,004 discovered candidates, 104 reviewed sources and UI-specific evidence against current source registries; do not call all discovered links reviewed |
| Awesome catalog, 2026-10-31 (`Litha_Awesome_Research_Package_2026-10-31.zip`) | LOCAL_ONLY / PARTIAL | Preserve original 78 assessments, evidence/backlog/search utility after checking duplicates and licenses |
| Dessa research, 2026-10-29 (`Dessa_for_Star_AI_Research_2026-10-29.pdf`) | PARTIAL | Compare the 20 acceptance scenarios and voice findings against PR #845 and live test results |
| Computer-control research, 2026-10-31 | PR_ONLY | Review PR #858; require native Windows interaction, latency and failure-recovery evidence before promotion |
| Repomix/Claude/Crawl4AI/caveman/design sources, 2026-10-31 | PR_ONLY | Review relevant open PR; check source pinning and executable acceptance tests |
| Earlier frontier / agent-skills / self-learning reports, 2026-10-09 through 2026-10-25 | UNKNOWN / PARTIAL | Compare original reports and their source registers against docs, code and open/closed PR history |
| Oct 19 evolution, performance, debugger and storage archives | PARTIAL | Some code/roadmaps were committed; recover blocked uploads, verify original contents and link to later implementations |
| Blender, UI, VFX, animation, creator mastery | PARTIAL | Check visual evidence, Blender/Studio native acceptance, and geometry integrity rather than treating offline tests as proof |
| Companion and autonomous digital-life work | PARTIAL | Check deployed functionality separately from merged fakes/synthetic tests; preserve user-approved constraints |

## Recovery gate
1. Recover original files from the user's Library or previously generated archives; record original filename, size and SHA-256.
2. Inventory every file inside archives; reject secrets, personal data, executable binaries, copyrighted third-party assets without permission, and duplicate generated files.
3. Record a row per source item: chat/date, original file, original SHA-256, destination path, source URL/license, exact PR/commit, status and tests.
4. Compare normalized content and pinned source IDs, not just filenames or topic keywords.
5. Add missing research under `docs/research/recovered/` with a provenance header. Keep experimental code isolated and OFF by default.
6. For each proposed code change, require correctness and speed baselines (p50/p95, memory, CPU, GPU, Windows packaging, Roblox Studio when relevant), failure cases and rollback.
7. Keep draft PRs unmerged until independent checks pass. Do not mark deployment/live capability complete from synthetic tests.

## Current limitations
This ledger captures known gaps and follow-up tasks. It is not a completed full-chat export or an exact-content comparison of every archive. No production behavior is changed by this document.
