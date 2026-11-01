# STAR AI: trusted timing, realtime intelligence, learning, and VTuber quality
Date: 2026-10-31 (America/Chicago)
Status: code fix implemented and focused offline test suite passed; integration and hardware performance measurements are outstanding.
Repository: oncoursemail/Star-AI-Project, draft PR #845, unmerged.

## Executive result: a genuine host-clock denial-of-service weakness was fixed

The existing stream load governor decides when optional commentary and GPU work are too risky for a live game plus OBS and speech synthesis. Previously, ingest() advanced the internal monotonic host-clock watermark before deciding whether an incoming sample was authenticated or even had the correct type. A rejected packet claiming a very large host time could therefore make future authentic samples appear to be from the past. Subsequent ingests could fail on a clock-backwards exception, and the advisor could not recover without restarting the session.

The fix checks enabled state, strict host verification, and the sample type first, while holding the existing reentrant lock. Only the verified, structurally correct candidate may advance the host-clock watermark. Existing checks for freshness, ordered timestamps and replay IDs still apply. In particular, this change does NOT make measurements from chat, a language model, or a remote viewer trustworthy: the caller must authenticate the producer before using host_verified=True.

Regression: one new test injects a million-second timestamp with host_verified=False, a backwards unverified timestamp, and a wrong-type sample carrying a claimed verified flag. It then submits a legitimate subsequent reading. The session continues normally, and accepted/rejected counts are correct. A focused 17-test Python unittest suite passed on Star's authorized Linux development machine against exact GitHub commit e798ec8cb8f51a96c85be7382ee375a3087143e0. This was an isolated download of source and dependencies, not a full repository, GPU, Windows, OBS, or broadcast test. The GitHub Actions full-suite result is separate.

Files: star/stream_load_governor.py; tests/test_stream_load_governor.py.

## Engineering principle: optimize outcomes, not claims about intelligence

STAR's optimization objective is a measured multi-objective quality score: task success, generalization on held-out cases, time to action, first-audio latency, video frame consistency, factual grounding, and recoverability under errors. Higher token throughput or a new model name is not proof of smarter behavior. For streaming, worse frame pacing is a regression even if text decoding accelerates.

Existing components include StreamLoadGovernor, StreamBrainGovernor, AdaptiveQoS, GameDeadlineRouter, GamePracticeCurriculum, GameplaySkillBank, OBS window and stream-health bridges, an audio/avatar session, VTube Studio host, local game vision, and Star Core Forge. Integrate and test these rather than starting another competing scheduler.

## Evidence: slow teacher plus fast player

RealtimeBench (2026-10-14) evaluates 180 tasks across six continuously running game types. The authors' Two-Timescale Offline Recursive Self-Improvement approach teaches a fast student using a slower teacher between attempts. Their reported improvement belongs to that research, not to Star.

Design:
1. A reactive controller consumes fresh, timestamped game observations and selects a policy within a host-enforced action deadline. Missed deadlines cause a safe skip, not a late stale button press.
2. Between authorized matches, a stronger teacher reviews failure traces and proposes a versioned skill card: cues, applicable states, actions, predicted outcome, confidence, and known failure modes.
3. Run the candidate against the previous baseline on matched seeds and independent holdouts. Record environment/game version, controller code hash, agent version, timings, crashes, wins and failures.
4. Promote only when paired performance improves without unacceptable latency or stability regressions. Keep known-good rollback and never learn a production policy solely from its own score estimates.
5. Tests must include unfamiliar maps, mechanics changes, different opponents, low-fps modes, and failure recovery. Humans approve irreversible/public/high-risk actions; routine approved practice does not need repeated prompts.

Avoid unfair real-world games: no anti-cheat evasion, prohibited automation, or unsanctioned multiplayer interference. Prefer Star-owned training environments and games whose rules allow automated players.

Primary: https://arxiv.org/abs/2610.20665

## Continual knowledge and cross-domain skill growth

SkillLearnBench (2026-04-22) evaluates externally verifiable agent skill learning and finds that self-feedback by itself may drift. SkillShift-Bench (2026-10-24) tests skills after context, perceptual and execution shifts; learned recipes can fail without adaptation. SkillRet (2026-05-07) studies retrieving relevant skills from large libraries, a useful warning against stuffing every skill into the main prompt.

Implement a five-layer system:
- Epistemic store: citations, source URL, retrieval time, version/date applicability, uncertainty, and contradictions. Public facts are distinct from Star's own observations and fictional character lore.
- Episodic memory: consented and privacy-filtered gameplay attempts and streaming events with time/source; bounded retention. No raw viewer identifiers in model memory.
- Skills: small executable, validated, scope-bound recipes with prerequisites, failure patterns and confidence; retrieve by intent, do not preload all skill descriptions.
- Practice laboratory: self-generated increasingly difficult challenges plus independently sampled held-out evaluations. Search failure modes instead of rewarding repeated easy victories.
- Core Forge: semantic diffs, sandbox isolation, tested promotion, rollback and signed evidence. GitHub is optional publication, not a dependency for local learning.

Accept a new skill only if an independent task outcome improves. Record how frequently the skill is correctly retrieved, not merely whether it exists.

Primary: https://arxiv.org/abs/2604.20087 ; https://arxiv.org/abs/2610.33528 ; https://arxiv.org/abs/2605.05726

## Speed on the 8 GB GPU: testable, not theoretical

Profile the full pipeline: capture -> perception -> skill retrieval -> policy/inference -> game input -> observed outcome, and independently chat event -> turn completion -> first audible sample -> playout -> avatar mouth movement. Report p50/p95/p99, not only averages. Sample CPU, RAM, GPU memory, power and frame times while a demanding game, OBS, live speech, and an animated mascot run together.

Benchmark these configurations one at a time on the same prompts, scenes and temperature/seed where possible:
- A compact reactive model for live gameplay, a stronger teacher outside gameplay. Live inference must never call the teacher for every frame.
- Cached stable system prompts and small retrieved skill cards versus full-context reprocessing. Do not confuse a warm cache benefit with overall model reasoning quality.
- llama.cpp speculative decoding: no speculation, n-gram speculation and compatible draft model; compare effective tokens/s, first token, acceptance rate, energy and memory reservation. SPEED-Bench is designed for such comparisons.
- Separate CPU-based TTS versus GPU TTS, testing audio quality and both game/OBS frame pacing. CPU TTS can be slower or contend with the game CPU; benchmark rather than mandate it.
- Concurrency and CPU allocation: admit only bounded extra work, then stop/preempt through actual acknowledged worker termination. A recommendation cannot release VRAM for a worker still running.
- Rust only for hot paths verified by profiler (frame transforms, geometric checks, audio DSP, tokenizer-adjacent operations). Retain Python orchestration until a Rust/PyO3 implementation wins end-to-end and preserves testability.

Critical security caveat: upstream llama.cpp prompt-cache reports in August and September 2026 described cross-conversation restore and slot-specific cache correctness problems. Reproduce cache isolation before sharing cached prompts across users, roles or sessions. Until qualified, partition or disable cross-session caches, use explicit identity scopes, and prefer private per-stream stable prefixes.

Sources:
https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
https://github.com/ggml-org/llama.cpp/issues/27148
https://github.com/ggml-org/llama.cpp/issues/28139

## Natural and truthful AI VTuber: actual behavioral quality

Goal: expressive, funny, socially responsive, and reliably grounded in what Star truly observed, while transparently remaining an AI streamer. A compelling character does not require false claims of human childhood, past employment, feelings as medical facts, or other invented real-world experience.

Architecture:
- Turn detector distinguishes completed requests from pauses; evaluate local LiveKit v1-mini on CPU against the current VAD/turn-taking system. Do not assume adaptive interruption uses the same deployment availability as the local detector.
- Dialogue planner prioritizes host events and meaningful chat questions; enforces chat fairness, replay protection and response deadlines. It may deliberately stay silent in high-focus game segments.
- Speech synthesis must yield streaming PCM chunks with actual playout acknowledgements. A generated sentence is not proof it was heard. Measure first played audio, skipped chunks, resumption and cancellations.
- Audio-reactive mouth, eyes, expression and body motion are driven by actual playing audio plus grounded gameplay cues, with tight clock alignment. Add nonlinear smoothing, eyelid blink variation and purposeful gaze shifts; avoid random, disconnected movement. Reduced-motion mode and an OFF default remain supported.
- Physics: indigo-black-to-gold twin tails should sway and settle with inertia; gold bows and dress have plausible secondary motion. Avoid excessive spring motion during still speech. Star, Astro and Amber need independent identity/pose control.
- Emotional expressivity is a character performance: surprise after observed danger, relief after real success, attention while listening, playful teasing with social context, and occasional gentle laughter. The system should not claim unobservable emotions or invent achievements.
- Live audience: sanitized chat is lower trust than authenticated owner commands. Do not persist unique viewer identifiers or private messages in training traces. Disclosure that Star is AI should remain clear.

Source evaluation:
LiveKit local v1-mini: https://docs.livekit.io/agents/logic/turns/turn-detector/
Kyutai Pocket TTS v4.0.0 (Oct 20) and v4.0.1 (Oct 21): https://github.com/kyutai-labs/pocket-tts/releases
VTube Studio plugin parameter API and cautions against 60+ FPS list calls: https://github.com/DenchiSoft/VTubeStudio

## Games built by Star: geometry and interaction integrity

Before editing any scene, inspect the exact hierarchy, existing attachments, pivots, collision groups, constraints, UI scaling, and intended reference design. Roblox's OpenGameEval evaluates executable gameplay, not just plausible scripts. Its 2026 repository documents 84 human-curated tasks and stronger outcomes associated with pre-edit exploration. Use its public evaluation scripts where licensing and Studio access allow.

A build-quality acceptance gate should cover:
- No misplaced or floating props, intersecting surfaces, visible texture seams, broken doors or detached structures.
- Correct pivot, body attachment, hand grip, animation state, player scale, and camera framing.
- Visual tests at multiple viewport sizes, lighting conditions and graphics settings, with before/after screenshots and human-reviewed examples.
- Multiplayer state, replication, join-in-progress, disconnect/reconnect and adversarial latency conditions.
- Task completion from a clean Studio session, not from a scene the agent manually staged to pass.

StudioTestService can execute up to eight simulated clients and supports scripted multiplayer tasks. Keep API credentials out of GitHub and never promise that a CI unit test substitutes for a graphical Studio pass.

Sources:
https://github.com/Roblox/open-game-eval
https://create.roblox.com/docs/reference/engine/classes/StudioTestService

## Proposed acceptance scorecard and prioritization

P0 — directly wire independent trusted host telemetry and replay-safe OBS status into a single provenance-aware QoS decision. Acceptance: a genuinely closed/reconnecting OBS session never looks normal, and forged/unverified timing cannot poison a healthy session. Match source session IDs and device clocks.

P0 — paired Windows 8 GB GPU benchmark on fixed game scenes, with OBS active. Log game p95/p99 frame time, capture age, route skips, utterance first played audio, OBS render/output skipped frame rates, GPU/CPU utilization and peak resident memory. Promotion requires no regressions on these safety metrics and a statistically credible gain in the targeted metric.

P1 — two-timescale teacher/student offline practice on two Star-owned games and one unfamiliar holdout game. Compare against frozen baseline; promote only with fresh signed results and an explicit rollback trigger.

P1 — naturalness evaluation set of at least 100 consenting/fictional synthetic conversations: interruptions, viewer backchannels, silence under gameplay pressure, paired audio/avatar onset and stopped-audio cleanup. Manually rate timing, groundedness, voice quality and expression cohesion.

P1 — learn/use general-purpose skills with scoped citations and verified outcomes, distinguishing source knowledge from witnessed experiences, hypotheses and roleplay canon. Add contradiction resolution and cache TTL.

P2 — Rust hot-path experiments and alternate TTS models; promote only after reproducible benchmark wins on target Windows hardware. Maintain a stable, safe fallback.

An especially useful release dashboard should display baseline versus candidate with absolute timings, confidence intervals, test count, hardware configuration, dates, regressions, a rollback handle, and whether results were simulated, offline-on-host, or real gameplay. No model or scheduler should declare itself 'smarter' based on its own evaluation alone.

## Implementation status / limits

Completed in this revision: untrusted clock-watermark poisoning fix and regression test. Isolated offline test evidence: 17/17 Python unittest cases passed against the precise GitHub test revision e798ec8. Owner-controlled development machine ran only local tests and downloaded public code; no streaming credentials were accessed.

Not completed: cross-module telemetry wiring, measured gains to inference or game ability, new TTS or avatar deployment, autonomous game play, Roblox Studio visual acceptance, full CI, production stream, or PR merge. Do not describe these proposed features as already installed.
