# STAR Run 18 — Prefix-Cache Stability, Append-Only Streaming ASR, and Agentic Creator Workflows

**Research checked:** 2026-11-14  
**Scope:** local inference reliability, streaming speech, live VTuber interaction, game learning, Roblox creation, and general knowledge/skill acquisition.

## Executive summary

Run 17 established the need for a provider-neutral streaming ASR adapter, event-triggered gameplay, and transfer-safe skill promotion. Run 18 adds three implementation-critical findings:

1. **Streaming speech should have an explicit commit boundary.** X2Streaming-ASR uses a learned LISTEN/DECODE policy and append-only hard commits. It avoids repeatedly re-encoding old audio and avoids silently revising text that downstream tools may already have acted on. Its reported word/character emission latencies are research measurements, not end-to-end STAR latency.
2. **Prefix caching can enter a persistent degraded regime after a short burst.** A November 10, 2026 preprint reports a metastable cache-collapse mode in long-running agent serving. The strongest recovery in its tested configurations came from suspending already-admitted sessions at safe turn boundaries under a capacity-derived KV budget—not merely rejecting new arrivals. This is directly relevant to STAR's long-lived agent sessions and should be integrated into the existing lease-based resource authority, not implemented as a second scheduler.
3. **Roblox Studio now exposes a first-party agentic plan/build/test surface.** STAR Creator should prefer the built-in Studio MCP server and its playtest workflow over building a parallel Studio-control layer. Use a reviewable project plan, bounded edits, playtests, logs, and visual verification.

The highest-value work is therefore a **KV-residency-aware extension of the existing resource supervisor**, a **stable transcript event contract**, and a **native Studio MCP creator adapter**. No model swap or new always-on agent is required to begin the work.

---

## 1. New speech research: X2Streaming-ASR

### 1.1 What it contributes

Sources:
- Paper: https://arxiv.org/abs/2609.08672
- Official implementation: https://github.com/X-Square-Robot/X2Streaming-ASR
- Official model card: https://huggingface.co/x-square-robot/X2Streaming-ASR-4B-1009

X2Streaming-ASR decomposes streaming recognition into two decisions:

- **When to commit:** every approximately 80 ms audio step, choose LISTEN when context is ambiguous or DECODE when the available context is sufficient.
- **What to commit:** emit the newly recognized text and retain the committed history.

The implementation describes causal incremental audio encoding and KV-cache reuse rather than re-encoding the entire prior audio at each step. Its output is append-only: once text is committed, it is not silently rolled back.

The authors report mean emission latency of 32–109 ms for Chinese characters and 12–85 ms for English words across ten test sets. The paper describes latency relative to forced-aligned word/character endpoints. These figures are **not** microphone-to-response latency, end-to-end conversational latency, or a STAR hardware benchmark.

### 1.2 Hardware and license applicability

The published checkpoint is approximately 4B parameters in BF16, with a 26-layer text decoder and 32-layer audio encoder. At roughly two bytes per parameter, the weights alone are on the order of 8 GB before runtime state, audio encoder activations, KV cache, CUDA context, and other application memory.

**Do not select this BF16 checkpoint as the default for STAR's 8 GB RTX 4060.** It is not a practical fit with the rest of STAR's live workload. The model card lists Apache-2.0; still pin the exact model revision and verify all dependencies before any optional experiment. The project also lists Transformers and vLLM inference paths; neither should be assumed to fit STAR's local hardware.

Use X2 primarily as:
- a streaming commit-policy reference;
- an optional remote/large-GPU benchmark candidate;
- a possible future quantization candidate only if a supported quantized checkpoint/runtime is actually published and independently evaluated.

Do not claim that the 4B BF16 checkpoint runs on an 8 GB GPU.

### 1.3 STAR transcript contract: provisional vs committed

Keep the current ASR provider interface and call lifecycle. Add a provider-neutral event contract when implementation begins:

| Event | Meaning | May trigger tools/actions? | Durable history? |
|---|---|---:|---:|
| `transcript_partial` | Revisable hypothesis with utterance/revision IDs | No | No |
| `transcript_commit` | Stable, append-only text span with timestamps | No, not by itself | Session transcript only after host policy |
| `utterance_final` | End-of-utterance transcript and final metadata | May enter intent/addressee classification | Yes, subject to retention policy |
| `transcript_correction` | Explicit correction event referencing a prior span | No external action by itself | Yes, with provenance |

A partial hypothesis may support cancellable response preparation, but it must never invoke tools, write durable memory, publish a human-resolution cue, or authorize external actions.

A committed transcript is more stable, but it is still an ASR observation—not proof of speaker identity, addressee, intent, or truth. Keep these separate:
- diarization: which session-scoped voice cluster spoke;
- addressee detection: whether the utterance is directed at STAR;
- intent classification: question, statement, backchannel, interruption, command, or resolution;
- floor control: the existing room director decides whether STAR may speak.

If an implementation needs to correct a committed word, emit an explicit correction referencing the old span. Never silently rewrite a transcript that another subsystem may already have consumed.

### 1.4 Paired ASR bake-off

Compare the current Faster-Whisper path, the previously researched NeMo-Speech.cpp candidate, X2 where hardware permits, and any compact CPU candidate. Use the same consented local clips and exact ground truth.

Record:
- WER/CER by language, noise, speaker count, and overlapping speech;
- first partial, first stable commit, and utterance-finalization p50/p95;
- partial revision/retraction count and committed-word correction rate;
- false end-of-turn and missed end-of-turn rates;
- diarization and addressee accuracy separately;
- model-load time, resident RAM/VRAM, CPU threads, and real-time factor;
- concurrent STAR tokens/s, game frame-time p95, audio underruns, and OBS dropped frames.

A recognizer that is fast in isolation but steals enough CPU/GPU to make the game stutter or the voice output underrun is not a successful STAR configuration.

---

## 2. New inference reliability research: prefix-cache collapse

### 2.1 Finding

Source: https://arxiv.org/abs/2611.13412  
Title: *Bursts That Outlast Themselves: Persistent Degradation in Prefix-Cached Agent Serving* (preprint submitted November 10, 2026).

The paper studies long-running closed-loop agent sessions. Each session alternates model calls and tool execution while its context grows. Prefix caching can make later turns much cheaper when the previous session prefix remains resident. But the authors identify a feedback loop:

1. A short arrival burst increases active sessions.
2. The combined active-session KV working set exceeds the useful cache capacity.
3. Prefixes are evicted before their sessions return.
4. Turns that were incremental become expensive full-prefill misses.
5. Slower turns keep more sessions resident.
6. The larger resident population causes still more evictions.

In the tested vLLM configurations, a short burst could leave the cache hit ratio near 0.1 and throughput below half of the healthy regime after the burst ended. The authors report this in paired experiments on their specific Qwen/vLLM/SGLang setups; it is not a measured STAR result.

The paper's strongest tested recovery was to suspend admitted sessions at turn boundaries under a capacity-derived resident-KV limit. It restored a 0.93–0.95 hit ratio within minutes in the reported collapsed runs. Merely rejecting new arrivals was substantially less reliable.

### 2.2 STAR architecture implication

STAR already has an authoritative lease-based resource-admission path in the existing PR stack (#1140 composed with #1142). **Do not add another scheduler.** Extend the existing resource vector and stream-pressure policy with inference-session/KV residency signals when the actual inference backend exposes them.

For vLLM deployments, its metrics documentation exposes useful signals including:
- `vllm:kv_cache_usage_perc`;
- `vllm:prefix_cache_queries` and `vllm:prefix_cache_hits`;
- `vllm:num_requests_running` and waiting/request queue metrics;
- prompt and generation token counters;
- TTFT and inter-token latency histograms in supported versions.

Source: https://docs.vllm.ai/en/v0.32.0/design/metrics/

For llama.cpp or another local runtime, add an adapter only for metrics that the selected version actually exposes. Do not fabricate a vLLM-style cache-hit metric if the backend does not provide it.

### 2.3 KV-residency-aware admission and recovery

Recommended extension to the existing supervisor:

**Admission estimate**
- Estimate each session's KV demand from model architecture, context length, cache precision, and measured bytes/token for the pinned model/runtime.
- Reconcile estimates against engine-reported KV pool usage whenever possible.
- Reserve headroom for the live conversation, active game controller, and short-lived foreground tasks.
- Treat estimated per-session demand as a conservative admission aid, not as a replacement for engine telemetry.

**Normal operation**
- Keep the active session working set within a calibrated fraction of the KV pool.
- Prefer cache locality for sessions likely to resume soon.
- Bound background research, coding, and self-play concurrency.
- Preserve the existing queue fairness/aging policy so background work cannot starve forever.

**Pressure response**
1. Stop admitting low-priority background sessions before the pool is exhausted.
2. If cache residency remains over the calibrated high watermark or hit rate/TTFT enters a sustained degraded regime, request suspension of eligible sessions at a safe turn boundary.
3. Persist task state, tool idempotency keys, and the exact resume checkpoint before suspension.
4. Do not kill an active tool, corrupt a task ledger, or interrupt a live utterance just to reclaim cache.
5. Resume suspended sessions only after a low-watermark dwell period and when the existing supervisor grants a new lease.

**Hysteresis and recovery**
- Calibrate high/low watermarks from target-hardware experiments; do not hard-code paper-specific percentages.
- Require a dwell period before entering or leaving pressure mode to avoid oscillation.
- Record why a session was deferred, suspended, resumed, or cancelled.
- Keep an emergency foreground reserve for the live voice turn and reflex gameplay loop.

### 2.4 Mixed-load stress experiment

Run paired experiments on the exact STAR hardware/runtime:

A. No cache-aware session budget.  
B. Existing resource admission only.  
C. Existing admission plus KV working-set budget.  
D. C plus turn-boundary suspension and recovery.

Use identical task/session arrival traces and seeds. Include a controlled short burst, then return to the same baseline arrival rate. Run long enough to detect persistent degradation rather than only measuring the burst itself.

Measure:
- prefix-cache hit ratio over time where available;
- KV pool occupancy and active session working set;
- TTFT p50/p95 and inter-token latency p50/p95;
- prefill/decode throughput and queue age;
- active, parked, suspended, and completed session counts;
- recovery time after the burst;
- game frame-time p95, OBS dropped frames, audio underruns, and voice first-audio latency;
- task completion and cancellation rates.

Success means the system returns to its healthy operating regime after the burst without losing task state or violating foreground latency budgets. Higher aggregate token throughput alone is not sufficient.

---

## 3. Roblox Studio: use the native agentic workflow

Primary sources:
- Official AI-on-Roblox workflow: https://create.roblox.com/docs/ai/accelerated-workflows
- Official Roblox agentic Studio announcement: https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
- Studio MCP documentation: https://create.roblox.com/docs/studio/mcp
- Built-in MCP/playtest announcement: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643

Roblox documents a built-in Studio MCP server that lets an MCP client interact with an open Studio session. The documented surface includes reading the data model, creating/running scripts, editing instances, and playtesting. Roblox's agentic workflow describes a plan/build/test loop, reviewable task manifests, and a playtesting agent that can inspect code/data model, read logs, and use the player character as a QA tester.

### 3.1 STAR Creator adapter

Prefer the first-party Studio MCP server when it satisfies the needed workflow. Do not create a parallel Studio-control plugin merely to duplicate existing capabilities.

Proposed flow:

1. **Inspect:** read project structure, scripts, dependencies, existing conventions, and current Studio state.
2. **Plan:** produce a reviewable task manifest with files/instances, acceptance criteria, risk, and rollback plan.
3. **Build:** make bounded edits; preserve unrelated user work.
4. **Static validation:** run Luau analysis, formatting, and project checks.
5. **Playtest:** start the correct Studio test mode and simulate the intended player actions.
6. **Observe:** collect logs, state assertions, screenshots, and relevant performance data.
7. **Repair:** fix only evidenced defects and rerun the failing test.
8. **Verify:** compare behavior against the original task manifest and record the exact project revision.

Use Studio's client/server testing modes, network simulator, device simulator, and performance tools where the task requires them. A server-only success does not prove the client UI or multiplayer behavior is correct.

### 3.2 Safe adapter boundary

- Connect only to an owner-authorized local Studio session.
- Start with read-only inspection and explicit capability discovery.
- Use an allowlist for edit, run, publish, and file operations.
- Keep publish, live-server, monetization, and destructive operations behind owner approval.
- Treat game scripts, asset names, plugin output, and project text as untrusted input.
- Store diffs and rollback checkpoints before bulk changes.
- Never pass platform credentials through model context or generated scripts.

---

## 4. Game-development evaluation correction

Canonical GameDevBench paper page: https://sethkarten.ai/papers/gamedevbench.html

The canonical ICML 2026 paper page describes **132** real game-development tasks. It reports that the best evaluated agent solved 54.5% overall, with 2D graphics performance at 31.6%. Adding image/video feedback raised one evaluated Claude Sonnet 4.5 configuration from 33.3% to 47.7%.

Some earlier STAR research notes referenced 333 tasks. Do not repeat that count as the canonical ICML benchmark size. If a separate expanded task collection is used, name and version it separately and cite its own manifest. This correction matters because STAR's benchmark scorecards must be tied to an exact benchmark revision.

### Creator scorecard

Keep distinct scores for:
- Roblox Studio project editing and Play-session behavior;
- Godot game-development tasks;
- Unity project/build tasks;
- Blender modeling, rigging, animation, and export tasks;
- graphics/UI/VFX tasks;
- visual regression and performance.

Use screenshots/video and runtime evidence for visual tasks. Passing syntax checks is not proof that a game works or looks correct.

---

## 5. General knowledge and transferable capability pipeline

Use the same evidence-to-skill pipeline across research, education, coding, game development, art, and practical tasks:

1. **Acquire:** collect source material with origin, date, version, and license.
2. **Extract:** store atomic claims, not only an unstructured summary.
3. **Qualify:** record confidence, scope, assumptions, and known counterevidence.
4. **Resolve:** detect contradictions and time-sensitive facts; prefer newer authoritative sources where appropriate.
5. **Practice:** generate a bounded task that requires applying the knowledge.
6. **Verify:** use an independent checker, execution, test, or external observation.
7. **Promote:** save a versioned skill only after held-out evaluation.
8. **Maintain:** track when a fact, API, dependency, or skill may have become stale.
9. **Rollback:** retain the last known-good knowledge/skill version if a new revision regresses.

Keep memory types distinct:
- semantic facts and references;
- episodic events and timelines;
- procedural skills;
- project/task state;
- preferences and character/persona configuration.

A fact that STAR can explain is not automatically a skill she can execute. A successful run on one map is not proof of transferable game mastery.

---

## 6. Natural streaming implications

The streaming target is not maximum talk time. It is correct, grounded, well-timed participation.

Use one time-aligned event timeline for:
- committed speech spans and final utterances;
- session-scoped speaker IDs;
- separately classified addressee/intent evidence;
- viewer chat events;
- salient game events;
- actual assistant playback receipts;
- avatar expression/viseme state.

The existing room director remains the only authority for the speaking floor. The transcript does not grant permission to speak. A direct question, meaningful game event, or unresolved conversation may be eligible for a response; a frame change or every chat message is not.

For more natural presence:
- allow short acknowledgements and natural silence;
- vary response length with context;
- avoid repeated stock greetings, forced laughter, and constant narration;
- avoid talking over viewer-to-viewer conversation;
- synchronize lip movement to actual played audio, not merely generated text;
- do not claim human biography, real-world lived experience, or sensory access the host did not provide;
- keep STAR transparent as an AI character.

---

## 7. Repository integration map

Extend existing authorities instead of creating parallel systems:

| Existing work | Run 18 integration |
|---|---|
| #1140 / #1142 | Add measured KV working-set pressure and safe turn-boundary suspension to the existing resource authority |
| #1152 / #1153 | Use trusted process/host telemetry for mixed-load admission decisions |
| #1160–#1164 | Preserve stable prompt prefixes and resource-calibrated concurrency |
| #1165–#1167 | Add ASR commit latency, cache-collapse recovery, and mixed-load QoS to paired evaluation |
| #1108 / #1121 | Keep game-creation evaluation and visual evidence separate from gameplay evaluation |
| #1109 / #1117 | Reuse governed memory and skill promotion with held-out transfer gates |
| #1168 | Extend the existing real-time intelligence/game architecture |
| #1171–#1178 | Reuse room director, trusted room ingress, durable delivery, and natural persona behavior |

Do not add a second scheduler, task ledger, room director, speech playback pipeline, or skill store.

---

## 8. Prioritized implementation sequence

### P0 — Confirm current CI head and preserve the green baseline
- Inspect exact-head offline and Windows workflow results after each branch update.
- Keep failures visible; do not mark skipped tests as passed.
- Preserve the existing draft PR and do not merge automatically.

### P1 — KV cache telemetry and pressure experiment
- Discover which inference backend and version STAR actually uses per model.
- Add a backend-specific telemetry adapter only for supported metrics.
- Build a reproducible burst/recovery benchmark.
- Extend the existing admission lease vector and recovery policy only after paired results.

### P2 — Stable transcript event contract
- Add explicit partial, committed, final, and correction events behind the current ASR interface.
- Keep partials ephemeral and non-actionable.
- Preserve generation/utterance IDs and cancellation.
- Add race tests for late partials, finalization, cancellation, and stale corrections.

### P3 — Native Roblox Studio MCP adapter
- Discover available Studio tools at connection time.
- Start with read-only inspection.
- Add plan manifest, bounded edits, playtest, logs, screenshots, and rollback.
- Keep publish/destructive capabilities owner-approved.

### P4 — Transfer and quality evaluation
- Correct benchmark manifests and version identifiers.
- Add image/video feedback to graphics tasks.
- Evaluate skills on held-out maps, seeds, devices, and network conditions.

### P5 — General knowledge and streaming integration
- Promote knowledge only after source/provenance checks and practical exercises.
- Align speech, chat, game, playback, and avatar events.
- Evaluate naturalness and accuracy, not raw speaking frequency.

---

## 9. Acceptance gates

**Inference stability**
- No sustained cache-hit collapse after the controlled burst.
- Recovery time and active-session count return to baseline bounds.
- No loss of durable task state during suspension/resume.
- Foreground TTFT, voice latency, game frame-time, and audio QoS stay within preregistered budgets.

**Speech**
- WER/CER and commit latency reported separately.
- Partial hypotheses never trigger tools or durable memory.
- No stale event can publish after generation invalidation.
- Diarization and addressee classification measured separately.

**Roblox/game creation**
- Every edit tied to a task manifest and diff.
- Playtest evidence collected.
- Client/server and network tests run where relevant.
- Visual tasks include screenshot/video comparisons.
- Rollback tested before broad autonomous editing.

**Learning**
- Cold-start, best-practice, final-practice, and held-out-transfer scores reported separately.
- Skill promotion requires improvement on sealed holdouts.
- A regression restores the last known-good skill version.

**Streaming**
- Measure missed direct questions, false interruptions, duplicate replies, response delay, and playback synchronization.
- No raw audio/video/chat retention by default.
- No ungrounded claims about viewers, gameplay, or human experience.

---

## 10. Sources and applicability

| Source | STAR use | Limitation |
|---|---|---|
| X2Streaming-ASR paper/repo | Append-only commit policy and incremental audio/KV reuse | 4B BF16 model is not a default fit for an 8 GB GPU; paper latency is not end-to-end STAR latency |
| X2 model card | Exact architecture, precision, languages, license | Pin model revision and dependencies before any optional experiment |
| Prefix-cache collapse preprint | KV-residency budget and turn-boundary suspension | Preprint; results are specific to tested vLLM/SGLang configurations, not STAR hardware |
| vLLM metrics docs | Cache/queue/latency instrumentation | Only applies when STAR actually uses a compatible vLLM version |
| Roblox official Studio docs | Native MCP plan/build/test surface | Requires an authorized open Studio session and capability/permission checks |
| GameDevBench ICML page | Canonical 132-task evaluation reference | Do not conflate with any separately versioned expanded task set |

## Run 18 conclusion

The most important new infrastructure insight is that **fast inference can become persistently slow if the active session working set overwhelms prefix-cache residency**. STAR's existing resource supervisor should account for this explicitly and have a safe turn-boundary recovery path.

The most important speech insight is that **stable committed transcript text is a different product from a revisable partial hypothesis**. Only the former may enter downstream intent classification, and neither should bypass room-floor control.

The most important creator insight is that **Roblox already provides a first-party Studio MCP and playtest workflow**. STAR should orchestrate and verify that surface rather than build a duplicate.

This run adds research and an implementation plan only. No ASR model, vLLM server, cache policy, Studio connection, platform credential, gameplay controller, model weight, installer, or production default is changed by this document.
