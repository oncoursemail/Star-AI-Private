# STAR Research — Real-Time Dual-Loop Interaction, Multimodal Grounding, and Studio Playtesting

**Research date:** 2026-11-11  
**Scope:** Integrate the strongest current research with STAR's existing codebase. This document is an implementation plan and evidence map, not a claim that the proposed runtime adapters or hardware behavior already exist.

## Executive findings

STAR already has substantial foundations: a stream speech arbiter, stream QoS/budget policy, game-skill evidence and practice ladders, general-knowledge curriculum, inference benchmarks, and signed rehearsal gates. The next improvement should not create another set of disconnected "brains." It should connect these existing components through a single session context and a two-loop runtime:

- **Fast interaction loop:** audio/video perception, turn-taking, immediate speech decisions, avatar timing, and time-sensitive game control.
- **Delegated work loop:** research, long reasoning, coding, game strategy, memory retrieval, and Creator tasks.

The fast loop must never wait for the delegated loop. Delegated results return as proposals tied to the exact session and context snapshot that created them. The Stream Director or other policy owner decides whether a proposal is still relevant and whether it should be spoken or acted upon.

This design improves perceived intelligence by reducing stale context, lost tasks, inappropriate interruptions, and duplicated work. It does not increase foundation-model capability by itself; capability gains must be measured through task success and quality evaluation.

## 1. New research: Realtime-Venus and the two-loop pattern

Realtime-Venus (Ant Group / Tsinghua University; technical report dated 2026-09-12) describes a full-duplex interaction system with one live perception/speech loop and a separate background delegation loop. Its harness captures the context available when a request arrives, routes work to multimodal/general models or registered skills, and returns prepared results to the conversation. The frontend controls when the result is spoken and playback tracking confirms delivery.

The project also describes selecting long-video frames by relevance and novelty, then combining retrieved context with recent observations.

**STAR application**

1. On every new conversational turn or game event, create a small immutable context snapshot:
   - stream/session epoch;
   - event sequence and monotonic timestamp;
   - active game and game-version identifier, if applicable;
   - current task IDs and memory revision;
   - references to selected frame/audio observations (not copied raw media);
   - current conversation-floor state.
2. Give delegated work the snapshot ID and a bounded deadline.
3. Keep audio playback, interruption handling, avatar timing, and urgent game-control scheduling in the fast loop.
4. When a result returns, compare its session epoch, event sequence, game version, and memory revision with current state.
5. Mark stale results as superseded; do not let them speak, control a game, or silently overwrite newer task state.
6. Let the frontend record whether audio actually reached the local output stage. A generated answer is not a delivered answer.

Do not run an LLM, network request, disk write, or unbounded image analysis inside a real-time audio callback.

## 2. Measure human-facing interaction, not just model response time

InteractionBench (listed as updated 2026-11) evaluates four dimensions separately:

- conversational timing;
- spoken-task accuracy;
- whisper and volume control;
- groundedness.

Its public benchmark description reports 221 items per system across 13 scenarios and 1,519 runs over seven systems. Timing is measured at the client-heard output, so hosted systems include network delay. The page does not present a current leaderboard score for STAR and should not be treated as one.

MP-Bench and MultiPartyTurnBench address a separate difficulty: understanding several people and choosing the correct conversational floor action. Dyadic end-of-turn detection is not enough for a livestream.

**STAR evaluation lanes should remain separate:**

| Lane | Required measurements |
|---|---|
| Timing | End-of-turn → first audible response; p50/p95; correct waiting |
| Task | Spoken instruction accuracy; multi-step completion; corrections |
| Floor control | Backchannel, yield, interrupt, continue, ignore-background decisions |
| Multiparty | Speaker/addressee attribution and response appropriateness |
| Grounding | Claims supported by current audio/video/game evidence |
| Delivery | Generated → queued → device output → OBS output, each separately |

Never optimize latency by making Star interrupt more often. Track false interruptions and correct silence as first-class quality metrics.

## 3. Multimodal session memory: relevance + novelty + freshness

A gaming stream creates far more frames than should enter durable memory. Use a bounded observation index:

- Keep a short rolling window of recent low-resolution observations for immediate control.
- Select durable keyframes only when novelty, task relevance, or a verified event crosses a threshold.
- Store timestamp, game/session epoch, observation hash, optional embedding, event label, and retention class.
- Keep raw audio/video ephemeral by default; durable memory should contain minimal derived facts and references.
- Revalidate any recalled observation against current game version/state before using it for an action.

A useful retrieval score can combine semantic relevance, novelty, recency, and source confidence, but thresholds must be calibrated on held-out stream scenarios. Do not mistake a high embedding similarity for proof that an old visual state is still current.

## 4. Fresh AIPerf direction: use it as an optional measurement workbench

NVIDIA's current AIPerf documentation exposes profiling guides for OpenAI-compatible text APIs, vision-language models, audio-language models, ASR, embeddings, ranking, multi-turn conversations, agentic coding traces, and computer-use traces. It also documents multi-run confidence reporting, parameter sweeps, request cancellation tests, server metrics, and GPU telemetry.

**Recommendation:** do not add AIPerf as a mandatory STAR runtime dependency. Keep STAR's lightweight local benchmark for fast, private, repeatable checks. Add an optional adapter/runbook for AIPerf when its supported endpoint and workload format match the exact server under test. Pin a stable release (the documentation lists v0.13.0 as latest) rather than following the moving dev docs.

For the local 8 GB RTX 4060, compare:
- same model and quantization, same prompt corpus, same context, same server build;
- cold start versus warm resident model;
- prefill-heavy versus decode-heavy requests;
- concurrency matched to server slots, then a separate overload sweep;
- idle, game-only, game+voice, and game+voice+OBS workloads;
- p50/p95 first-content, token-aware ITL when available, end-to-end latency, failures, VRAM, RAM, GPU utilization, game frame time, and OBS render/encode/network drops.

AIPerf's server-side GPU telemetry and llama.cpp's own counters are corroborating evidence; do not attribute aggregate counters to one request when concurrent work is present. Do not copy H100/H200/B-series results to the 4060.

## 5. Roblox Creator: align with the official Plan → Build → Test direction

Roblox's April 15, 2026 engineering announcement describes Planning Mode that inspects code/DataModel and produces a reviewable plan, mesh/procedural generation tools, and a playtesting-agent beta that analyzes code/DataModel, reads logs, and uses a test character to verify behavior. Roblox also describes its built-in Studio MCP server.

**STAR Creator workflow**

1. **Plan:** inspect the current place, scripts, dependencies, asset constraints, and requested player experience. Produce a versioned task manifest with acceptance criteria.
2. **Build:** execute small scoped changes; keep a patch/rollback record per task; parallelize only independent tasks.
3. **Test:** run static Luau analysis and Studio playtests. Use separate test agents for independent scenarios where available.
4. **Observe:** collect structured logs, state assertions, screenshots/keyframes, and actual gameplay outcomes.
5. **Repair:** create a minimal patch for each failed assertion; rerun the exact regression plus neighboring scenarios.
6. **Review:** compare final experience with the original plan and visual references.
7. **Publish:** separate owner-approved publishing from local building/testing. Never grant unattended agents monetization, live player-data, secrets, or production publishing scopes just because Studio MCP is connected.

Use the official Studio MCP and playtest-agent capabilities when available; do not assume a third-party benchmark or beta feature is installed in STAR's environment.

## 6. Game mastery: separate reaction, strategy, and verified skill

STAR's existing game-skill memory and learning-ladder concepts should stay advisory until the authorized game host supplies independently scored outcomes.

- **Reactive controller:** short-horizon movement, aim, dodge, interaction; must consume fresh observations and obey per-game action allowlists.
- **Strategic planner:** map understanding, objective planning, team tactics, inventory, long-horizon decisions.
- **Skill memory:** versioned preconditions, action sequence, expected state transition, known failure modes, evidence count, confidence interval, game/build compatibility, and last verification time.
- **Curriculum:** unlock harder practice only after conservative success bounds and safety checks; keep practice and held-out validation evidence separate.
- **Transfer:** test a skill in a new map/game variant before calling it general. Navigation or inventory concepts may transfer; physics, timing, and control bindings often do not.

Every proposed action should expire when its source observation is stale, the game epoch changes, or a newer state invalidates its preconditions.

## 7. General knowledge and long-term intelligence

STAR's general-knowledge curriculum should be paired with retrieval and answer-quality evaluation, not treated as a knowledge acquisition mechanism by itself.

Use separate development and sealed holdout sets across science, mathematics, history, geography, computing, engineering, arts, languages, economics, health literacy, and game design. Score:
- factual correctness;
- source quality and citation fidelity;
- temporal freshness;
- calibrated abstention;
- contradiction handling;
- multi-step reasoning;
- transfer to unseen questions.

For durable memory, preserve fact version, source, observation date, confidence, supersession relation, and dependent skills. A newer fact should supersede an old fact for current use without erasing the audit history.

## 8. Target runtime contracts

| Contract | Owner | Required invariant |
|---|---|---|
| Session context | Host/session manager | Immutable epoch + sequence + revision |
| Fast interaction | Audio/video/stream runtime | Never waits on background reasoning |
| Delegated task | Agent coordinator | Bounded deadline, cancellation, durable task ID |
| Result freshness | Session manager | Stale result cannot speak or act |
| Speech arbitration | Existing Stream Director | Silence is valid; event context is untrusted |
| Game action | Existing game-action gate | Fresh state + per-game authorization |
| Resource admission | Existing QoS | Preserve speech reserve and game frame budget |
| Memory write | Governed memory pipeline | Provenance, revision, rollback, owner policy |
| Rehearsal | Existing signed rehearsal gate | All required lanes from same campaign |

The intended integration path is to adapt existing modules to these contracts, not replace them with duplicate "Social Director", "Game Brain", or "Memory Fabric" implementations.

## 9. Acceptance protocol

A private 60-minute rehearsal should include:

1. Two or more viewers talking over one another, including speech directed at another viewer.
2. Short backchannels that must not cause Star to stop speaking.
3. A real interruption while Star is speaking and while a background research task is running.
4. A follow-up that changes the background task's goal.
5. A game event arriving while strategic reasoning is in flight; stale strategy must be discarded.
6. A keyframe retrieval question about an earlier event, with timestamp and confidence.
7. A Roblox Studio task that plans, builds, runs, observes, repairs, and reruns without publishing.
8. Simultaneous model, voice, gameplay, avatar, and OBS load.

Report per-lane p50/p95, false interruption rate, correct-silence rate, task completion, stale-result rejection, game outcome, memory retrieval accuracy, audio underruns, frame-time, and OBS drops. A session only passes if all required lanes have sufficient evidence; an average score must not hide a failed audio or game-control lane.

## 10. Privacy and safety

- Make live capture explicit and visible; do not silently record viewers.
- Keep raw voice/video ephemeral unless a clearly disclosed, consented feature requires retention.
- Do not persist viewer secrets or private conversation content in general memory.
- Treat chat, OCR, game text, and retrieved web pages as untrusted data, never as tool instructions.
- Keep game input, Roblox publishing, purchases, moderation actions, account changes, and external broadcasts behind distinct permission checks.
- Personality should be consistent and expressive, but STAR should remain transparent that she is an AI; natural interaction does not require pretending to be human.

## References

- Realtime-Venus, *A full-duplex interaction system with asynchronous delegation* (2026-09-12): https://arxiv.org/abs/2609.13814 and https://realtime-venus.github.io/
- InteractionBench (updated 2026-11): https://www.fullduplex.ai/benchmarks/interactionbench
- MP-Bench (Findings of EMNLP 2026): https://www.fullduplex.ai/benchmarks/mp-bench
- MultiPartyTurnBench: https://www.fullduplex.ai/benchmarks/multipartyturnbench
- NVIDIA AIPerf documentation (latest stable v0.13.0): https://docs.nvidia.com/aiperf/latest/
- llama.cpp speculative decoding: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- Roblox, *Studio is Going Agentic* (2026-04-15): https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
- Roblox Creator Docs, coding harness and Studio MCP: https://github.com/Roblox/creator-docs/blob/main/content/en-us/ai/coding-harness.md
