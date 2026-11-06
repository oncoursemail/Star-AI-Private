# STAR AI — strict host input evidence, ACK deadlines, and research-driven intelligence roadmap
**Date:** 2026-11-06. **Implementation:** local-only, opt-in host diagnostics. **Not** a validated live-game controller, GPU speedup, model fine-tune or broadcast feature.

## 1. Measured code gap and exact repair

Inspected `star/host_monotonic_game_probe.py` after PR #1016. The new `require_submit_confirmation=True` check only occurred in `guarded_dispatch`. A host caller could still invoke `pre_submit_check` -> `action_submitted` -> `action_ack` in strict mode without any callback confirming submission. That path could finalize a deceptively "strict" latency replay. The *configured requirement* was bypassed despite normal timestamp ordering.

This change:
- Blocks direct `action_submitted` in strict confirmation mode, permanently revoking the whole sample window. Only `guarded_dispatch` may perform submission and check the callback's **exact boolean True**.
- Adds optional `max_ack_wait_ns` (1 ms–10 s) to reject a host ACK arriving too long after local submission; revokes prior successes in the same window so no cherry-picked low-latency report remains.
- Adds counts-only `ack_deadline_violations` and **false** `ack_delivery_attested`; no media, chat, IDs, raw timestamps or secrets are exposed.
- Preserves legacy manual submission when strict confirmation is disabled.
- Includes deterministic regression tests: exact boundary, late acknowledgment, bypass before/after precheck, prior completed-frame revocation, invalid parameters, no evidence leak.

**Critical trust limit:** A host callback returning `True` can attest only local *acceptance of a submission request*. A host ACK does not prove input delivery, in-game effect, collision avoidance, score increase, learning, or genuine hardware attestation. Testing uses an injectable fake clock and fake callback; no actual Windows/game/OBS event was sampled. The real native input edge and independent game/engine telemetry remain mandatory for claims about gameplay outcomes. This change does not automatically stop a blocking native callback.

## 2. Why real-time matters more than raw token speed

Aggarwal & Welleck, *Gym-Anything-RT* (2026-10-27), evaluate 100 real-time visual minigames, with a model-specific example falling from **75% success when paused to 9% live**. This is **not a STAR benchmark result**. Source: https://arxiv.org/abs/2610.37567

Star should have three independently measured loops:
1. **Fast controller** (bounded latency): predict one near-term hazard, take only currently authorized inputs, drop stale frame epochs and release keys on independent stop. Never block on a long-form LLM answer.
2. **Tactical controller** (seconds): map obstacles/objectives, learn controls in a private sandbox, choose the next bounded action sequence with a short expiry and confidence.
3. **Practice/learning** (off-stream): generate new challenge variants, request 4–8 candidate policies only when compute is available, score each by independent state transitions and unseen holdouts, retain failed episodes to diagnose generalization rather than hiding them.

A useful scorecard must report objective completion, unsafe collisions, retries, frame coverage, captured→submitted→ACK p50/p95/p99, FPS 1% low, audio underruns and OBS rendering/encoding drops *separately*. Faster tokens do not imply better gameplay.

## 3. Hardware-aware, high-intelligence inference for an 8-GiB-class GPU

The observed Windows host previously had ~8 GiB graphics memory and high utilization; this report did **not remeasure** that machine. Plan:
- Game/OBS/VTuber rig have priority over expensive AI work. Sample actual host GPU free VRAM, game frame times, OBS dropped frames, CPU pressure and real audio queue; reserve conservative headroom. Never infer process GPU usage from aggregate load alone.
- Route short intent detection and commentary to a small, low-latency model or deterministic policies; use larger VLM only for meaningful changed scenes; batch long coding/research tasks while not streaming.
- Benchmark `llama.cpp` speculative modes (draft model, EAGLE-3, n-gram) and KV reuse *per actual workload*, tracking acceptance, time-to-first-token, final answer quality and memory headroom. Speculation can lose speed if a draft steals VRAM from game rendering. Official: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- Cache immutable documentation, project graph, local Luau API references and verified skills with provenance. Isolate all viewer/session context; never restore private KV states across users or trust chat for system instructions.
- Track *time-to-correct-action*, not just tokens/second. Pair A/B runs on the same hardware/holdout tasks; change one variable at a time and retain the baseline.
- Keep CPU/RAM optimization as a first-class path: adaptive batching, memory-mapped caches, async I/O, precomputed scene features, smaller TTS and resource-aware admission. No claim of a measured speedup until paired device tests.

## 4. VTuber: believable social timing, authentic continuity, transparent identity

Proact-VL (2026-03-03) investigates choosing **when** a real-time gaming companion should interject and the appropriate response size. Source: https://arxiv.org/abs/2603.03447

DyaPlex (NVIDIA, June 2026) explores causal full-duplex speech and coordinated motion. This is research, not a drop-in implementation for Star. Source: https://research.nvidia.com/labs/amri/projects/DyaPlex/

Kyutai Pocket TTS v4.0.0 (2026-10-20) added 18m, 7m and experimental 2m English model variants; v4.0.1 (2026-10-21) corrected small-model pronunciations. Benchmark voice naturalness, first audible chunk, CPU load and interruptions before choosing a runtime; do not download large weights on a nearly full Linux system. Source: https://github.com/kyutai-labs/pocket-tts/releases

**Host-engineering milestones:**
- Full-duplex mic/chat listening with deterministic priority for owner commands, emergency mute, viewer-directed answers, critical gameplay, celebration and ambient remarks. No unprompted rambling during high-pressure actions.
- Speech must be *audibly grounded*: TTS chunk ID, speaker playback ACK, audible timestamps, matching lip shapes, breathing and eye motion. Cancelled/stale utterances must never be journaled as spoken.
- Add interrupt detection, cancellation and backchanneling; keep listening while speaking. Check whether echo cancellation truly separates Star's own synthesized voice.
- Character expression should follow observed events: win/loss, surprise, concentration, curiosity, confusion, laughter. Natural silence, subtle fidgets and calibrated timing matter more than exaggerated motion.
- Verified episodic memory: store completed games and moments only with independent engine/host receipts; attribute viewer statements to viewers, never label them as Star's own events. Add recall confidence and expiry.
- Transparent AI identity and moderation: no pretending to be a human user, fabricated private memories, unconsented spending, unauthorized broadcasts, sharing private desktop/chat or bypassing game anti-cheat.

**Acceptance:** 30-minute private rehearsal with game, avatar, TTS, mic loop and OBS recording; measure interruption→first audible response, utterance cancellation rate, AV lip offset, dropped frames, 1% low FPS, GPU VRAM and per-10-minute grounded-memory errors. Include the *bad* runs, not just highlights.

## 5. Autonomous Roblox and general-purpose game production

Roblox *OpenGameEval* (2026-10-01 paper) scores edits and simulated play on **84** human-curated core tasks in a stateful Studio environment; scene inspection strongly correlates with success. Source: https://arxiv.org/abs/2610.02563 and https://github.com/Roblox/open-game-eval

Roblox expanded **built-in Studio MCP Open Cloud** on **2026-11-04**, with per-game permissions. Some scopes can change live places, spend Robux or change player data. Start with read-only access, isolated test places and exact `studio_id`; use scope prompts/owner approval before any external write. Source: https://create.roblox.com/docs/studio/mcp-open-cloud

**Build pipeline:** inspect game objects and scripts → plan expected state → generate several candidate changes → StyLua/Selene/luau-analyze/type-check → isolated Studio playtest → multiplayer client/server simulation → geometry/visual checks → independent executable task oracle → targeted repairs → holdout regression → owner-approved publish. Avoid "compiled" = "playable" mistakes. Test UI responsiveness, animation/VFX, colliders, physics, audio, network replication, data loss and frame-rate budgets.

**General knowledge growth:** use a capability graph (coding, robotics-like vision, 3D geometry, physics, game strategy, conversational moderation, general science/arts), with per-skill prerequisites, references, canonical examples, verified exercises, confidence, transfer test and freshness timestamps. Schedule spaced re-tests of previously failed tasks. Keep retrieved source evidence separate from model-generated hypotheses; permit self-criticism but never grant skill credit from the model's own favorable narrative.

Google DeepMind *SIMA 2* (announced 2025-11-13) explores cross-game transfer and self-improvement through practice in 3D worlds; it is a research analogy and not a directly available Star runtime. Source: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/

## 6. Ordered next engineering actions

| Priority | Concrete deliverable | Acceptance evidence |
|---|---|---|
| P0 | Merge only after GitHub offline checks + owner review of chained PRs | Strict submission path tested; no test regression; source review |
| P0 | Restore storage headroom with an owner-reviewed cleanup inventory, not destructive automatic removal | Disk utilization and recoverable bytes recorded |
| P1 | Trusted Windows host uses strict `guarded_dispatch`, ACK budget and every-frame coverage in a non-broadcast private game | Real local timestamps from host; failed windows retained |
| P1 | Bind each accepted action to separately signed authoritative game-state outcomes | Independent signed telemetry, no fabricated skill credit |
| P1 | GPU/CPU/OBS/TTS paired benchmark on actual owned hardware | Quality and latency distribution with/without candidate optimization |
| P2 | Multi-game skill curriculum + unseen holdouts | Improvements in task success without holdout contamination |
| P2 | Private full-duplex VTuber/rig/OBS integration | 30-min private A/V recording, interruption and social evaluation |
| P2 | Studio MCP isolated inspect–build–test–repair benchmark | Executable playtest pass@1 and safety/rollback validation |

The main path to "humanlike" streaming is reliable timing, grounded situational reactions, social continuity and expressive audiovisual presence—not asserting that Star is biologically human. All new device-facing integrations must remain owner-authorized, locally scoped and off by default.
