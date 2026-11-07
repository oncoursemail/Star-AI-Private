# STAR Intelligence: honest game mastery + grounded VTuber attention
**Research date:** November 1, 2026
**Status:** Two small offline-verified implementation changes; other items are proposals, NOT deployed capabilities.
**Owner intent:** Maximize real-time game competence, verified learning, natural avatar behavior, general knowledge and speed on limited local hardware. Preserve opt-in boundaries and avoid unverifiable performance claims.

## What this iteration actually changes

1. **Cross-arm, cross-mode holdout contamination guard** in `star/game_skill_gate.py`. Previously the baseline and candidate arms validated practice/holdout separation independently. A mixed-mode study could put a seed in one arm's *practice* records and the other arm's *paused holdout* records while the compared real-time holdouts were perfectly matched; the eligibility check did not reject that overall study. The new gate checks all practice seeds against all holdout seeds across both arms and both modes before returning any favorable verdict.
2. **Repeated, cross-scenario evidence needed for a game-skill improvement claim.** Previously one lucky win among 24 paired holdouts (and a single +0.6 progress point) qualified a candidate as improved. Now the advisory verdict requires at least five distinct materially improved paired cases and improvements represented in at least two scenarios. These are deliberately conservative, **heuristic screening criteria, not a confidence interval or causal proof**. Signed independent validation in `game_transfer_eval.py` remains the stronger acceptance boundary; these supplementary trials cannot authorize any model update or live game operation.
3. **Opt-in grounded gaze easing** in `star/stream_motion.py` and `star/stream_stage.py`: `natural_gaze=True` smooths actual, host-supplied focus cues without generating fake visual targets, delaying the eyes before an observed cue, changing audio, or allocating per-frame buffers. Defaults to `False`. Existing stage callers keep the exact previous behavior unless an owner-approved host enables `natural_gaze` at stage `enable()` / `configure()`. The new `StarStage.motion()` host-only `focus_target_x` accepts only bounded numeric positions; any nonzero position must carry `focus_host_verified=True`, and unobserved game events cannot drive it. Stage settings cannot change midway through an utterance. This is a rig target proposal, not an installed VTube Studio animation.

### Reproduced failures and bounded measurement

- Original gate: **one improved holdout case out of 24 => eligible**. Changed gate: **blocked** (`insufficient_repeated_improvement`, `improvement_not_cross_scenario`).
- Original gate: **cross-arm, mixed-mode seed exposure => eligible**. Changed gate: **blocked** (`invalid_evidence`).
- A synthetic focus target reversal at frame 21 (30 FPS): normalized per-frame gaze jump **1.625 -> 0.638** with opt-in easing; the cue is still reached promptly. This only measures a numeric jump, **not viewer-perceived realism**.
- On the connected Linux development PC: 120 offline plans of 15 seconds at 60 FPS took **1.658 seconds** with baseline gaze and **1.662 seconds** with opt-in easing in one sequential run. A 0.004-second difference is within noisy benchmark variation; **no robust speed gain is claimed**. No GPU inference, game, voice synthesis, livestream, real avatar output or OBS recording was run.
- No webcam data, visual scene, chat, audio or player data is stored by either change.

## Research basis: real-time game mastery under a live clock

**October 14, 2026:** Pan et al., *The World Won't Wait: Evaluating and Teaching Agents Under a Live Clock* (RealtimeBench, arXiv 2610.20665), tests 180 tasks across six continuously running game types. Their two-timescale approach keeps a fast player on the real-time path while a slower teacher studies errors between attempts. The reported benchmark improvements are **their** results, not measured results for STAR.
Source: https://arxiv.org/abs/2610.20665

**Recommended STAR architecture** (preserve existing implemented components):

- **Immediate loop (no language-model deliberation by default):** host-verified game frame -> existing `GameActionGate`, `RealtimeGameLoop`, and clock/worker lifecycle gates -> bounded, pre-authorized action. If stale, late, out of scope or uncertain: release held input and wait for a new observation. Never queue an expired action.
- **Tactical student (on deadline):** compact state estimate and a small, tested skill library. A symbolic reflex handles common hazards; an LLM receives only tasks whose worst-case measured p95 latency fits the remaining action window. Protect frame pacing and audio first.
- **Slow teacher (offline / nonlive):** collect host-verified failed or successful practice episodes, infer targeted hypotheses, propose a skill patch, rehearse the patch on public practice levels, and freeze it before an independently owned holdout evaluation. Do not let the teacher read held-out maps or their per-case results.
- **Practice progression:** continue using `GameLearningLadder` and `PairedGameStudy`. Include movement, platforming, aiming, camera control, navigation, UI inventory, multiplayer coordination, and recovery after unexpected physics. Increase difficulty only after bounded verified progress.
- **Independent generalization:** game version, objective, scenario, seed and paused-vs-continuous mode are part of case identity. Require multiple unseen maps and game types, matched initial state, time-window validity, fewer missed action deadlines and no deterioration in retained skills. STAR's signed game transfer gate and external scorer must remain outside the student's writable memory.
- **Source of truth:** game state or a trusted scorer, NOT text saying "I won". A screen capture alone might miss offscreen changes or ownership of a score. Persist only consented, curated skill and episode summaries; raw game/video/voice/chat data should be short-lived.

**Run order:** propose candidate -> offline practice -> repeated matched evaluation -> signed, frozen holdout -> human-reviewed comparison -> optionally promote with rollback -> bounded live rehearsal. This is a meaningful version of self-improvement without claiming the model rewrites its own neural weights.

## Research basis: believable, fast VTuber presentation

Official VTube Studio plugin API supports authenticated custom-parameter mapping and injection. Its `InjectParameterDataRequest` permits parameter values, but a custom input must actually be mapped to STAR's Live2D rig. Competing plugins can own parameters; do not blindly override them.
Source: https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md

**Proposed conversation architecture:**

1. Honor interruptions and speech-turn completion. LiveKit documents `v1-mini` as a CPU-local turn detector for self-hosted agents. It should be benchmarked with Star's mic/audio pipeline rather than assumed more natural.
   Source: https://docs.livekit.io/agents/logic/turns/turn-detector/
2. Compare **voice quality and first-audible-sample latency**, not just time-to-synthesize text. Kyutai's October 20, 2026 Pocket TTS v4.0.0 release (followed by v4.0.1 on October 21, which repairs small-model pronunciation bugs) includes 18.2M, 6.9M and experimental 1.9M English variants and a CPU-only Rust runtime; its developer numbers are *not* STAR latency measurements. A tiny TTS may sound less convincing than a larger voice, so require human listening tests before choosing one.
   Sources: https://github.com/kyutai-labs/pocket-tts/releases and https://github.com/kyutai-labs/pocket-tts
3. Ground expressions in real causes: observed threat -> short surprised glance; genuine win -> small smile + breath; question -> listening pose; concentration -> quiet eyes on the actual task. Avoid arbitrary laughs or fixed loops that repeat identically every clip.
4. Use sound-device-consumed PCM samples to drive lip movement. Keep avatar frames synchronized with **audible** speech, not pending TTS buffers. Continue relying on existing `AudibleAvatarSession`, `StarStage` and `VTubeLocalHost`; never send cues for an expired stage plan.
5. Reserve natural *silence* for difficult gameplay, let chat speak, avoid formulaic questions after every sentence. The stream persona should be explicitly presented as AI, with consistent fictional lore but no invented personal experiences or false memories.
6. Let Astro and Amber participate only via separately permissioned scenes; prevent simultaneous voice collisions and keep reduced-motion support. Avatar visual evaluation needs actual captured rig frames plus human preference judgments. A reduced numeric gaze jump is not a substitute.

**Human-likeness evaluation, proposed:** blind A/B footage scored for believable timing, expressiveness, voice prosody, natural pauses, repetition, eye attention, interruption handling and factual grounding. Include a reduced-motion variant and a no-avatar-audio-stall check. A `natural_gaze` toggle is worth keeping only if its visual evaluation beats the old path without increased speech/OBS/game latency.

## Research basis: faster reasoning without stealing game VRAM

The upstream `llama.cpp` SPEED-Bench tool supports matched qualitative workloads, prefill and decode timing, draft acceptance and baseline-vs-speculative comparison. Speculative decoding is not automatically beneficial with limited VRAM or an inaccurate draft model. Test the exact model, quantization and context profile with the game and voice workload present, not an isolated tokens/second number.
Sources: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md and https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

**Proposed compute plan for STAR's 8 GB GPUs and multiple computers:**

- Keep real-time game, OBS and avatar rendering on the gaming PC with **explicit VRAM headroom**. Heavy 8 GB resident models cannot share near-full VRAM with games; use the already implemented GPU snapshot/window preflight to fail closed before launching work.
- Move slower teacher reasoning, web research, large-context summarization, static game-build verification and nonlive asset generation to Brain 1/Linux when reachable. Keep fast action selection local to the game host in case the network is lost.
- Measure local-vs-remote p50/p95/p99 first-token, decode, network RTT, queue wait, game p95 frame time, OBS render/encode skips, actual PCM audible latency, avatar cadence and peak VRAM. Suppress optional teacher work immediately on gaming deadline or OBS pressure.
- Keep retrieval and verified skills separate from huge always-included prompts; cache stable trusted instructions, index project/API docs and store successful examples with provenance. Enable web research only with the owner toggle; retrieved pages and viewer text are untrusted.
- Reserve Rust work for profiler-verified hot paths (capture, audio buffers, image/geometry transforms and bounded IPC). A blanket Python-to-Rust rewrite will not make a fixed neural model inherently smarter.
- Benchmark prompt-cache safety: per-user/session isolation and no cross-user reuse of private context. Bound retries, concurrency and telemetry histories; replay-safe worker cancellation is mandatory.

## Better general knowledge, coding and game creation

Make STAR's answer quality depend on **measurable retrieval, execution and evaluation** rather than on raw context length:

- Curated lessons from official Luau, Roblox Creator Hub and APIs; provenance-tagged code snippets; conflict detection between versioned APIs and old examples.
- For game creation, use existing Roblox Studio scenes, run `luau-analyze`, lint/style tooling, StudioTestService's up-to-eight-client scripted multiplayer tests, `VirtualInput` for UI interactions, geometry/collision checks, FPS traces and before/after render comparisons. Source: https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/testing-modes.md
- Best-of-N only for risky tasks where verifier cost is smaller than unchecked failures. A result is promoted only after independent tests; keep a rollback and resource budget. Do not equate more agent messages or more tokens with higher intelligence.
- Expand knowledge beyond games via supported documents, web citations, code execution and safely scoped app tools; test factual accuracy, citation support and graceful uncertainty.
- Cross-domain benchmark matrix: real-time gaming, dialogue, Roblox coding/UI, 3D assets/animation, search/retrieval, desktop operation and general reasoning. A faster candidate cannot regress one category unnoticed.

## Proposed acceptance plan (none of these demonstrations were completed here)

1. **Offline:** all adjacent unit tests, lint and basic typing baseline pass; new split-contamination and singleton-win tests fail on the old implementation and pass on the changed implementation. Inspect gaze before/after frames with actual avatar mappings.
2. **Nonbroadcast Windows rehearsal:** use the opt-in GPU preflight/window, OBS local read-only host, host-verified game-frame presents, actual audible PCM, avatar render cadence and a bounded game action worker. OBS/recording/broadcast stays OFF unless separately authorized.
3. **Paired A/B:** >=20 matched, prespecified cases per comparison; nontrivial replicated skill gain across multiple unseen scenarios, no old wins lost, no latency tail regression, no gameplay frame regression, stable audio and naturalness. The supplementary `GameSkillVerdict` never authorizes promotion.
4. **Human rating:** ≥2 blinded clips per test condition; assess eye attention, natural pauses, laughter/expressions and honest factual storytelling. Disqualify mouth/eye movements that appear when audio/cue evidence is absent.
5. **Owner review:** verify the exact Linux/Windows executables and model/runtime hashes, record metrics and roll back any experiment that fails to improve quality within its measured compute budget.

**Integrity boundary:** This document and these Python changes do not install or run any streaming application, create audio output, play games, train models, deploy changes to Windows, grant game-input permissions, or prove intelligence improvement. All proposals must be evaluated with independent host evidence.
