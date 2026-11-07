# STAR — Public-Approved Knowledge Retrieval and Multi-Timescale Gaming/VTuber Intelligence

**Research and engineering date:** 2026-11-02 UTC (2026-11-01 America/Chicago)
**Scope:** local-first, offline-safe, draft stacked on the preceding scene-memory PR; no live broadcasts or autonomous external actions.
**Evidence distinction:** sections labeled **Implemented** describe tested code in this branch; **Proposals** are not deployed.

## Executive finding

STAR's factual recall during streams can fail **even if a correct, reviewed, explicitly owner-approved fact exists**. Prior to this change, `public_knowledge_packet()` asked `KnowledgeStore.find()` for the 25 highest-ranked *reviewed* notes, and filtered that list by the owner's narrower *public-broadcast* allowlist afterwards. A collection of reviewed-but-not-public notes can consume every one of those 25 slots. The result is no answer, despite a relevant public-approved fact being available. This is an avoidable recall failure, not an AI model-quality limitation.

This matters to STAR's intended naturalness. Humanlike conversation requires timely recall of **relevant and permitted** history—not hallucinated confidence or ever-growing context. It is better to fix evidence-selection quality before making the model larger.

## Implemented: restrict retrieval before ranking and LIMIT

- `KnowledgeStore.find(..., allowed_note_ids=frozenset(...))` adds a *backward-compatible*, optional, bounded permission-aware retrieval path. The FTS5/BM25 path and parameterized LIKE fallback restrict IDs at the SQL query stage, before relevance ranking and `LIMIT`.
- Accepted ID allowlists must be an immutable `frozenset` containing 0–128 positive **non-boolean** integer IDs. SQL placeholders are parameter-bound; the identifiers are never concatenated as untrusted SQL text. Empty sets return no results.
- Original callers without the allowlist preserve the existing 50-result maximum. The allowlisted path permits up to 128 results so that all explicitly approved candidates can be examined before secondary kind, age, and packet-budget screening.
- The stream adapter now requests only the explicitly public-approved IDs from SQL, while still requiring `reviewed=True`, matching project, accepted kind, source, bounded text, nonfuture creation date, a maximum age, and a total packet ≤1,400 characters.
- This **does not** treat any note as independently verified truth. Public approval and review remain distinct from source accuracy; external tool authority remains separate.

### Reproduced baseline and regression

Created one reviewed, owner-approved checkpoint fact, then 70 additional reviewed but *not public-approved* notes matching the same query. The old global top-25 retrieval omitted the approved fact. The old `public_knowledge_packet()` returned `None` under both FTS5 and LIKE. After the fix, the authorized checkpoint fact is recovered in both engines and non-approved content never appears in the packet.

Additional tests cover first-result allowlist filtering, malformed/mutable/oversized allowlists, and empty allowlists. Existing tests for unreviewed notes, project isolation, age, secret source metadata, and injection into stream conversations remain important regression gates.

**Quality guardrail:** do not substitute a generated guess when no permitted evidence is available; say the fact could not be verified and defer, or fetch a vetted source with explicit research permission.

## Research: why this is an intelligence upgrade without retraining

**Memory is valuable only when it improves future decisions.** The October 21, 2026 *Memory-Centric Continual Learning* preprint proposes assessing memory under interference, adaptation and transfer rather than treating recall counts as intelligence. The June 1, 2026 *AGENTCL* preprint likewise reports that naive retrieval can cause memory-induced degradation on held-out tasks. Both support evaluating downstream outcomes, not merely growing a database.

This fix removes a deterministic source of **retrieval interference**. It cannot increase neural parameters, model reasoning capacity, game win rate, or speech quality by itself. Next, STAR should keep three separate knowledge lanes: (a) source-reviewed facts with timestamps and citations; (b) genuine game observations with game/version/situation binding; (c) creative persona fiction clearly marked as fiction. A retrieval service should return a bounded, confidence-labeled set of facts with provenance, never raw private notes or hidden tool instructions.

For internet facts that change quickly (game patch notes, service availability, world news), local knowledge should expire by *fact type*, not just blanket 180-day age. Build periodic source revalidation and correction records; never silently overwrite evidence. Promotion must be gated by owner approval or independently reproducible tests. Keep holdout questions to detect misinformation after every retrieval/ranking change.

### Proposal: STAR intelligence conductor

1. **Reflex lane**: deterministic host game-control loops, frame/timestamp alignment, controller heartbeat and collision safety. An LLM should not be on every 16–33 ms action path.
2. **Fast tactical lane**: compact model consumes sparse verified game observations and chooses a bounded goal/action with a deadline. If the deadline is missed, the game host follows a safe fallback.
3. **Teacher lane**: stronger reasoning after an episode, comparing recorded states to success criteria, proposing a *few* causal strategy changes and writing a replayable skill candidate.
4. **Experiment lane**: tests candidate on different random seeds, levels, and unseen objectives. Only accept a skill whose objective score, resource usage and safety are better than the frozen baseline; retain rollback.
5. **Truth/knowledge lane**: owner-approved public notes for streaming, scoped episodic memory for game-specific commentary, independent retrieval for up-to-date general knowledge, citation/provenance and correction handling.
6. **Presentation lane**: decides when speaking is valuable; aligns actual audio playback, captions, gaze, expression, silence and attention with verified game/voice events.

The October 14, 2026 *RealtimeBench* preprint investigated this slow-teacher/fast-student division on 180 live-clock game tasks. Its model and score gains are **external findings**, not STAR results. STAR needs its own deadline-aware, unseen-game holdouts.

## Proposals: faster performance without sacrificing the gaming GPU

**Measure whole-system quality, not just generated tokens/s.** On 8-GB GPUs, LLM weights, KV cache, game textures, OBS, compositor and avatar rendering compete for capacity. Rehearse under actual game load; do not extrapolate from an idle GPU snapshot. A full benchmark row should include:

- exact model / quantization / context / GPU offload / binary version, prompt-cache hit rate, first-token latency p50/p95, completion latency p50/p95, throughput and answer accuracy;
- game FPS p50/p1, missed action deadlines, OBS render and output dropped frames, GPU minimum free VRAM, host RAM peak, CPU utilization and audio underruns;
- measured voice first-audio latency, interruption completion time, lip-sync drift and turn-taking false cutoffs.

Try stable prompt prefixes, admission-controlled concurrent slots, smaller action models, quantized KV only if accuracy holds, and speculative decoding only when the actual draft acceptance and end-to-end latency are better than baseline. Upstream llama.cpp SPEED-Bench includes category-level latency/throughput and speculative acceptance measurements. Consider CPU or a second host for TTS/teacher tasks; avoid swapping large weight matrices through a narrow PCIe link during live gameplay.

**Acceptance gate:** three reproducible A/B runs, with frozen prompts and seeded tasks, should preserve task quality while lowering p95 latency and not worsening game p1 FPS, OBS loss, or audio glitches. Record failures, not only passing examples. Changes are disabled by default until evidence exists.

## Proposals: learned gaming and professional game creation

A strong game-player should maintain a **belief state** rather than narrating each screenshot. Extract game events, UI goals, player health/resources, positions and action acknowledgments with confidence scores; update observations at adaptive rates. React to state changes, not every frame. Use short-horizon controllers for jumps/aiming, strategic planning at slower intervals, and stored skills only after verification. During practice, support action replay, counterfactual comparisons, difficulty schedules, and unseen maps. Never falsely claim to have won a game based solely on an unverified agent message.

For Roblox creation: enforce geometry/collision checks, valid native Luau API, automated client/server regression, dynamic camera and UI tests, network latency simulation, device aspect ratios, and visual references. Roblox's official Studio testing documentation describes `StudioTestService` programmatic multi-client sessions (up to eight clients), `VirtualInput`, and device simulation. A finished game should pass real playthroughs, not merely compile.

Use "best-of-N plus verify" on small isolated prototypes: generate 4–8 candidate scripts/scenes, reject parse errors, run analyzer/test/Studio simulation, measure scene quality, compare, and deliver a passing candidate. Heavy testing belongs off-stream. Keep an internal local experiment ledger with semantic diffs and rollback; GitHub remains optional for collaborative publication.

## Proposals: a more natural, honest STAR VTuber

Naturalness is *contingent timing and continuity*, not merely more expressive text.

- **Voice**: test the CPU-oriented Pocket TTS family (including its October 2026 small-English releases) against STAR's existing voice for first-audio latency, timbre consistency, pronunciation, audible interruptions and sustained CPU cost. Do not switch engines based on an isolated demo.
- **Listening**: compare VAD-only endpointing with LiveKit's locally running `v1-mini` audio turn detector. It uses acoustic/semantic cues to avoid cutting off mid-thought pauses; measure both false interruptions and delayed responses.
- **Facial performance**: use authenticated VTube Studio custom parameter injection to map evidenced events to expressive gaze, blinks, mouth movement, head nods and lightweight idle motion. Tie animation to actual playback state, not merely text generation intent.
- **Personality**: consistent interests, favorites, jokes, growth and relationships among STAR/Astro/Amber can develop through verified experiences; distinguish persona fiction from real past events. A stream audience should know STAR is an AI VTuber.
- **Conversation**: allow natural silence, brief listening acknowledgments, viewer-question fairness, stream-safe humor, game-specific frustration/excitement triggered by verified events, and respectful topic changes. State transitions must invalidate stale game events *and* stale long-term memories. Audio must actually stop before canceling the corresponding spoken action.
- **Safety and rights**: independent hobbies, offline game practice and PC maintenance can be automated inside a preapproved policy. Broadcasting, purchases, identity/account claims, confidential data exposure and irreversible external actions must remain separately authorized.

The official VTube Studio wiki documents plugin authentication and custom parameters; the OBS websocket project recommends protecting access with a password. Use read-only OBS metrics during rehearsal before enabling broadcasting. Never use a hidden unapproved capture or expose private messages as on-stream "memories."

## Recommended implementation order, with falsifiable exits

**P0 — already delivered here:** permission-aware knowledge retrieval. Show the exact baseline failure and a passing FTS/LIKE regression. No broadcast or model calls.

**P1 — runtime connection:** attach the approved note IDs from a trusted, owner-visible broadcast-approval UI; never let the LLM supply the allowlist. Add a stream episode integration test proving approved recall survives 100 irrelevant reviewed notes, including multi-game transitions, while private facts stay absent. Exit when no cross-project or cross-scene leakage occurs.

**P2 — nonbroadcast end-to-end Windows rehearsal:** actual game input/telemetry, verified speech output, avatar motion, OBS stats, signed game scenes and timed scene changes. Record a deterministic local trace and p95 metrics. Reject stale game event playback or mismatch between stage state and physical audio. Do not broadcast.

**P3 — teacher/student curriculum:** implement per-game held-out level packs with positive/negative outcome labels, speed budgets, resource usage and strategy rollback. Promote only when median and worst-case held-out gains are demonstrated across repeated seeded episodes.

**P4 — natural presence and scale:** compare two local TTS and end-of-turn setups on identical scripted situations; evaluate blinded voice perception and objective delay; implement social continuity and independent creative hobbies with approved operating policies.

## Source register, verified in research pass

- SQLite FTS5 ranking, BM25, and `rank` semantics: https://www.sqlite.org/fts5.html
- RealtimeBench / TORSI (Pan et al., submitted **October 14, 2026**): https://arxiv.org/abs/2610.20665
- AgentCL (Shu et al., submitted **June 1, 2026**): https://arxiv.org/abs/2606.02461
- Memory-Centric Continual Learning (Li et al., submitted **October 21, 2026**): https://arxiv.org/abs/2610.29357
- llama.cpp SPEED-Bench official README: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- LiveKit audio turn detector and v1-mini: https://docs.livekit.io/agents/logic/turns/turn-detector/
- Kyutai Pocket TTS, October 2026 small models: https://github.com/kyutai-labs/pocket-tts
- VTube Studio authentication/custom plugin parameters: https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins
- OBS WebSocket authentication: https://github.com/obsproject/obs-websocket
- Roblox Creator Hub Studio testing: https://create.roblox.com/docs/studio/testing-modes

## What this branch does NOT demonstrate

No model retraining, GPU speed gain, new game victories, real voice-naturalness gains, live OBS broadcast, new VTube Studio connection, or human consciousness. The tested improvement is **correct, permission-aware retrieval of public facts under interference**. All other directions are engineering proposals with explicit measurement gates.
