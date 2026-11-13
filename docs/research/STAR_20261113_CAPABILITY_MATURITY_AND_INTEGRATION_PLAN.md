# STAR capability maturity, research transfer, and integration plan
**Research date:** 2026-11-13  
**Target:** `oncoursemail/Star-AI-Project`  
**Branch:** `feat/resource-admission-20261113-run21`  
**Purpose:** keep research, draft work, and shipped capability claims separate while turning the existing PR stack into a verifiable release path.

## Executive finding

STAR's development repository is substantially ahead of its public v1.0 release in several areas: real-time workload admission, causal turn-taking evaluation, privacy-safe telemetry, durable task/delivery ledgers, Live2D frame transport, skill retrieval, temporal-memory evaluation, and multiparty room handling all appear in open draft work.

That is not the same as saying those capabilities are shipped. The default-branch README explicitly says that PRs, CI artifacts, and passing tests do not establish that a feature is in the installer or that the website has been deployed. It describes v1.0 as a local-first Windows chat app with opt-in Roblox/Blender/web/model features and a server-side 300-task practice loop. It also says the measured answer quality was about the same as v0.9.0; v1.0 adds abilities and learning machinery, not a smarter model.

**Engineering conclusion:** STAR's next quality jump should come from integrating and measuring the existing work, not from opening another disconnected subsystem or changing model defaults without paired evidence.

## 1. Capability maturity: what exists versus what is proposed

Use these maturity labels in issues, docs, UI, release notes, and stream announcements:

- **Shipped:** present in the latest published release and covered by its release notes.
- **Opt-in shipped:** present in the release but requires explicit setup or activation.
- **Draft implementation:** code exists on an open PR/branch; not in the installer.
- **Research/evaluation only:** paper, benchmark, plan, or offline evaluator; no runtime capability implied.
- **Host acceptance pending:** requires a real Windows/RTX/audio/OBS/VTube Studio/Roblox/game test.

### Default-branch v1.0 snapshot

The default-branch README currently describes:

| Area | v1.0 state described by README | Do not claim |
|---|---|---|
| Desktop chat | Saved chats, search, rename/delete with undo, streaming replies | Autonomous VTuber |
| Screen/image | User-approved screenshot; image creation through configured ComfyUI | Continuous passive screen monitoring |
| Web | Opt-in search through configured SearXNG or user key | Always-on web access |
| Roblox knowledge | Cited official Roblox/Luau documentation | Autonomous Studio Lab |
| Roblox tools | Opt-in validators and official Studio MCP, read-only first with editing separately enabled | Unsupervised live-game publishing |
| Design | Style database and design checker | Automatic AAA-quality UI |
| Blender | Opt-in remote tools / architecture prototype | Fully autonomous Blender artist |
| Model | Local 4B Vulkan model or user-owned Linux server; hosted providers require user keys | Proven intelligence superiority |
| Discord | Separate owner-only bot, off by default | Public autonomous social account |
| Learning | Server-side 300-task night school, paired gate, owner-reviewed/undoable lessons | Automatic model-weight self-improvement |
| Voice | Basic optional calls/read-aloud exist historically; full voice experience remains listed as coming soon | Human-level multiparty streaming |

Source of truth: root `README.md` and `docs/release/v1.0/RELEASE_NOTES.md` on `main`. Re-check them before every release.

### Open draft work: capability clusters

The repository's current open-PR listing contains a large series of draft changes. The following clusters are useful for planning, but every item remains a draft until merged and released:

| Cluster | Representative PRs | Intended capability | Acceptance still needed |
|---|---|---|---|
| Agent worker lifecycle | #1118–#1120 | Windows process containment, graceful worker-tree shutdown | Windows crash/kill/restart tests |
| Skill retrieval | #1121 | Cached BM25 retrieval, ranked skill discovery, offline quality/latency evaluation | Held-out retrieval + skill-application gain |
| Real-time QoS | #1123, #1140, #1142 | Game-control lane, resource vectors, protected reserves, lease-based admission, pressure governor | Real host telemetry and mixed-load soak |
| Inference/voice performance | #1127–#1131, #1167 | Audio timing, callback isolation, local streaming benchmark, llama.cpp telemetry | Pinned local model and real hardware benchmark |
| Tracing and observability | #1132–#1134, #1158 | Privacy-safe causal traces, span timing, delivery correlation | End-to-end trace from request through audible output |
| Learning and memory | #1117, #1136, #1139 | Governed memory consolidation, temporal transfer/forgetting, cross-session practice | Held-out memory-on/off action transfer |
| Streaming/turn-taking evaluation | #1135, #1143–#1148, #1165–#1166 | Private rehearsal, paired quality/speed tests, causal turn timing, clustered holdouts | Real multi-speaker rehearsal and coverage gates |
| OBS/host telemetry | #1149–#1153 | Epoch-safe output stats, trusted telemetry, coherent sampling windows | Windows OBS/audio/game collector acceptance |
| Task and delivery durability | #1154–#1158, #1177 | Versioned tasks, deadlines, segmented playback, durable delivery recovery, playback receipts | Power-loss and real device-output tests |
| Live2D/VTube | #1159 | Latest-wins frame pump tied to playback epochs | Actual VTube Studio authentication and avatar sync |
| Incremental reasoning | #1160–#1164 | Semantic-prefix gating and resource-calibrated speculative thinking | Paired quality/latency/VRAM tests on target machine |
| Multiparty room streaming | #1171–#1176 | Room director, bounded queue/payloads, moderation, opt-in desktop host bridge | Provider adapters, ASR finalization, consent and live-stream tests |
| Research consolidation | #1168, #1178 | Architecture and capability research | Convert findings into integrated, measured runtime work |

This table is a planning index, not a claim that each PR has passed exact-head CI or is production-ready.

## 2. PR-stack integration rules

The work is deliberately stacked. Examples verified from PR metadata:

- #1142 is based on #1140.
- #1177 is based on #1176.
- #1178 is based on #1177.
- #1166 is based on #1165.

Therefore:

1. Never merge a child PR before its parent contract is in the target branch.
2. Do not retarget a child to `main` merely to make it appear mergeable.
3. Merge in dependency order, or squash a reviewed stack into a single integration branch after preserving commit provenance and test results.
4. Re-run full CI on the exact final commit after every rebase or squash.
5. Keep the public release repository and private development source/release process distinct.
6. A green documentation-only workflow is not a green code test; a skipped job must be reported as skipped.
7. Do not auto-merge a large stack. Keep owner review for release, permissions, model-default, and external-action changes.

### Suggested integration train

**Train A — reliability foundation**
- Worker process containment and bounded shutdown.
- One authoritative resource-admission controller.
- Trusted, epoch-coherent host telemetry.
- Causal traces and bounded diagnostics.

**Train B — durable work and delivery**
- One authoritative task ledger.
- Durable delivery ledger and task-to-delivery bridge.
- Segment-level playback acknowledgement.
- Recovery only after the host confirms old workers/playback have stopped.

**Train C — streaming interaction**
- Room director and bounded event queue.
- Explicit room consent and source allowlists.
- Moderation/rate limits/deduplication.
- Streaming ASR and addressee classification as separate, later adapters.
- Playback-locked Live2D and authenticated OBS/VTube Studio adapters.

**Train D — intelligence and capability**
- Skill retrieval.
- Memory transfer and governed consolidation.
- Gamer skill practice and held-out transfer.
- Creator inspection/edit/playtest loop.
- Paired speed-versus-quality evaluation.

Do not start Train D by adding more agent personas. Start by making the underlying skills, tools, evidence, and evaluation reliable.

## 3. New research transfer: compress memory without destroying evidence

### MemForest (arXiv:2609.08273, 2026-09-08)

MemForest proposes event-centric memory partitioning, semantic/temporal grouping, progressive merging, and anchor-guided retrieval. Its paper reports, in its own evaluated settings, 50% memory compression while retaining 97.1% of baseline performance on Mem0 and 99.7% on M3-Agent; reported retrieval speedups are 1.89x and 2.24x respectively.

Sources:
- Paper: https://arxiv.org/abs/2609.08273
- Implementation: https://github.com/Celina-love-sweet/MemForest

**STAR application (experiment, not default adoption):**

- Partition old episodic records by event, entity, time, and evidence linkage.
- Merge only semantically and temporally redundant summaries.
- Keep source references and immutable evidence hashes outside the compressed summary.
- Preserve conflicting versions and explicit correction events.
- Make compaction reversible by retaining the pre-compaction snapshot.
- Run memory-on/off and compressed/uncompressed paired tasks.
- Measure retrieval latency, memory-token cost, stale-fact reuse, temporal update accuracy, and downstream action success.

Do not compress away raw evidence that is needed for audit or owner-requested deletion. Do not equate a shorter memory with a better memory.

## 4. New research transfer: measure natural turn-taking as a decision problem

### LiveKit End-of-Turn Benchmark

The public `livekit/eot-bench` repository provides a reproducible dataset of real human-to-agent turns across 14 languages. It annotates every silence pause of at least 100 ms, distinguishing mid-turn hesitation from a true end-of-turn. It evaluates causal decisions and reports the tradeoff between false cutoffs and response delay rather than one accuracy score.

Sources:
- Benchmark code/data: https://github.com/livekit/eot-bench
- Leaderboard: https://livekit.com/benchmarks/eot-bench

**STAR application:**

- Keep the existing causal turn-taking evaluator; add an adapter for EoT benchmark predictions rather than a second evaluator.
- Preserve the silence-only baseline.
- Report a Pareto frontier: false-cutoff rate versus delay after true end-of-turn.
- Stratify by language, noise, speaker count, and speaking style.
- Separately score addressee recognition, backchannel filtering, missed interruptions, and recovery after false interruption.
- Never optimize response speed by accepting an unacceptable increase in cutting viewers off.

A benchmark result is not a guarantee of natural streaming in a real room. Use private, consented rehearsal sessions for final acceptance.

## 5. New research transfer: evaluate general game ability across environments

### GameWorld

GameWorld evaluates multimodal game agents across 34 browser games and 170 tasks in five genres, with outcome-based, state-verifiable scoring.

Source: https://gameworld-bench.github.io/

**STAR application:**

- Use GameWorld-style tasks for broad Gamer Brain generalization.
- Use Roblox OpenGameEval for Roblox Studio-specific editing and Play-session validation.
- Keep game-control actions separate from language-model tool calls.
- Run high-frequency movement/camera/timing through a bounded reactive controller; use the model for slower planning and recovery.
- Evaluate held-out levels, seeds, mechanics, and game genres.
- Report success, completion time, invalid actions, retries, and transfer to unseen tasks.
- Do not claim mastery from one successful run or one memorized map.

The browser-game benchmark and Roblox Studio benchmark measure different capabilities; neither replaces the other.

## 6. Skill retrieval is not skill use

Skill Retrieval Augmentation research (arXiv:2604.24594) introduces a decomposed evaluation of retrieval, incorporation, and end-task execution over 5,400 tasks and 26,262 candidate skills. The paper identifies a bottleneck: agents may load skills without correctly determining whether a retrieved skill is relevant or necessary.

Source: https://arxiv.org/abs/2604.24594

STAR already has a draft BM25 retrieval implementation in #1121. The next step should be to evaluate three separate questions:

1. **Retrieval:** did STAR find the right skill?
2. **Incorporation:** did she correctly understand preconditions, constraints, and steps?
3. **Application:** did the skill improve the final result on a held-out task?

Add a no-skill control, a distractor-skill control, and a wrong-skill control. Track token cost and latency. Do not load every skill into every prompt.

## 7. Faster inference: preserve end-to-end measurements

The llama.cpp SPEED-Bench client explicitly recommends matching benchmark concurrency to server slot count and reports latency, throughput, and speculative draft acceptance. It is designed to compare speculative decoding configurations against an already-running server.

Source: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench

OpenTelemetry's GenAI semantic conventions define separate server request duration, time-to-first-token, and time-per-output-token metrics; the conventions are marked Development, so STAR should pin the schema version it adopts.

Source: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md

**STAR's required benchmark vector:**

- first server token;
- first client content chunk;
- first audible sample;
- time per output token;
- total response duration;
- tool-call duration;
- model and KV-cache memory;
- CPU/RAM/VRAM;
- game frame-time p50/p95/p99;
- audio underruns;
- OBS render skips and output drops;
- task correctness and groundedness.

Run baseline and candidate under the same model hash, quantization, prompt, context, tool policy, server slots, and workload. Test idle and mixed-load modes. A higher tokens/sec result is rejected if first-audible latency, task accuracy, game p99, or audio stability regresses.

## 8. Human-natural VTuber behavior: measurable, not deceptive

Define naturalness as:
- context-aware responses;
- correct addressee recognition;
- appropriate silence;
- interruption and recovery;
- varied but consistent expressive delivery;
- speech synchronized to actual playback;
- avatar state synchronized to audible state;
- continuity across a long session;
- transparent disclosure that STAR is an AI character.

Do not use fabricated viewer profiles, synthetic social proof, or claims that STAR is a human. Viewer chat, ASR, OCR, game chat, web content, and retrieved memories remain untrusted input and cannot grant tools or permissions.

### Separate scorecards

| Dimension | Example measurement |
|---|---|
| Conversation | addressee precision/recall, appropriate response rate |
| Turn-taking | false cutoffs, missed turns, endpoint delay |
| Speech | first-audible latency, interruption recovery, intelligibility |
| Avatar | audio/viseme skew, stale-frame age, dropped/coalesced frames |
| Grounding | unsupported-claim rate, source correctness |
| Task continuity | completed, spoken, pending, cancelled obligations |
| Stream stability | audio underruns, OBS drops, game frame-time p99 |

Do not collapse these into one opaque “human-likeness” score.

## 9. Release and acceptance gates

Before describing any draft capability as available:

1. All parent PRs are merged or represented in the same reviewed integration branch.
2. Exact-head offline tests, lint, type checks, and desktop build pass.
3. Windows host test uses the actual packaged application.
4. Hardware telemetry is measured on the target machine; do not reuse thresholds from another GPU.
5. Mixed-load soak runs at least 30 minutes with game, OBS, voice, avatar, and background worker load.
6. Crash/power-loss tests verify task, lease, and playback recovery.
7. Private held-out evaluation demonstrates the intended quality improvement.
8. Permission and revocation tests pass.
9. Release notes clearly distinguish available, opt-in, and coming-soon features.
10. Owner reviews changes to permissions, publishing, external accounts, purchases, destructive operations, model defaults, and release behavior.

## 10. Prioritized next actions

| Priority | Action | Why |
|---|---|---|
| P0 | Reconcile the stacked PR dependency graph and pick one integration train | Prevent a growing collection of unshipped branches |
| P0 | Preserve one authoritative scheduler and host supervisor | Avoid conflicting resource grants |
| P0 | Complete task/delivery/playback recovery path | Long work must survive interruption without duplicate speech |
| P1 | Run exact-head CI across the stack after integration | Establish a trustworthy baseline |
| P1 | Run the 30-minute Windows mixed-load test | Prove streaming and gameplay coexist |
| P1 | Add EoT-Bench and GameWorld adapters to existing evaluators | Measure natural conversation and cross-game transfer |
| P1 | Test reversible MemForest-style compaction offline | Reduce retrieval cost without losing evidence |
| P2 | Evaluate skill retrieval, incorporation, and application separately | Turn the skill library into demonstrated capability |
| P2 | Integrate Twitch/YouTube, OBS, and VTube Studio only after consent/revocation tests | Avoid premature live-account access |
| P2 | Promote skills only after independent held-out validation | Make self-improvement real rather than self-scored |

## Sources and implementation references

- STAR v1.0 release boundary: https://github.com/oncoursemail/Star-AI-Project/blob/main/README.md
- Resource admission PR #1140: https://github.com/oncoursemail/Star-AI-Project/pull/1140
- Resource runtime PR #1142: https://github.com/oncoursemail/Star-AI-Project/pull/1142
- Skill retrieval PR #1121: https://github.com/oncoursemail/Star-AI-Project/pull/1121
- Temporal memory evaluation PR #1136: https://github.com/oncoursemail/Star-AI-Project/pull/1136
- Task/delivery PR #1177: https://github.com/oncoursemail/Star-AI-Project/pull/1177
- Multiparty stream host PR #1176: https://github.com/oncoursemail/Star-AI-Project/pull/1176
- Research consolidation PR #1178: https://github.com/oncoursemail/Star-AI-Project/pull/1178

## Scope and non-claims

This document is a research and integration audit. It does not install MemForest, add new game controls, connect a microphone, enable Twitch/YouTube, control OBS/VTube Studio, modify model weights, change permissions, or alter the v1.0 installer. Paper results are not STAR measurements. Draft PRs are not shipped features. Physical Windows, RTX 4060, Roblox Studio, OBS, VTube Studio, and live-stream acceptance remains outstanding.
