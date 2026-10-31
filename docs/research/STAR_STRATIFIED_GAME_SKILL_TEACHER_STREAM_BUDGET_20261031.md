# STAR AI — Balanced real-time skill evidence, teacher–student learning and expressive streaming
Date: 2026-10-31. Status: **research and code-level diagnostic changes**. No claim of a real-play, OBS, GPU, TTS or human-likeness benchmark. All deployment/model/stream actions remain host-approved.

## Verified project starting point
I inspected the October 31 draft PR #845 and production modules:
- `game_skill_gate.py` compares same-seed, same-mode held-out game runs and guards individual failure/progress regressions, but until this update a scenario with ONE holdout could count as a second map, and scenario-specific latency degradation could disappear below the GLOBAL latency p95.
- `stream_qos.py` and `stream_brain_governor.py` already gate real telemetry, CPU/GPU inference reservations, live-game pressure and audio-stage coordination. Do not introduce a parallel scheduler.
- `stream_stage.py`, `stream_turntaking.py`, `stream_focus_inbox.py`, `stream_episode_journal.py` and `stream_realtime_quality_gate.py` already supply consent-scoped speech, interruptions, delayed questions, grounded game memories and OBS-measured quality criteria. A new conversational persona engine must integrate here rather than bypass their safety checks.
- The code base is extensive; adding unconnected feature stubs is **not** equivalent to usable intelligence. Prioritize end-to-end exercised flows and real-world tests.

## This commit: stronger game-learning evaluation
1. Require **multiple matched holdouts in every preregistered game/scenario group**, not merely a count of two distinct map IDs. Threshold is min(4, max(2, configured minimum holdouts / 5 rounded down)), so the default 20-case study needs 4 observations per scenario. This is an evidence sufficiency rule, not a statistical proof.
2. Calculate **paired p95 action latency per scenario**. Reject local >10% AND >20 ms latency regression, even when overall p95 remains unchanged. Keep global p95, extreme-case latency and progress/win safety gates.
3. New synthetic tests cover an otherwise hidden 50→95ms map regression, an imbalanced 23+1 map evaluation, and a genuine cross-map improvement. All evidence here is synthetic. The outcome remains **manual-review advice**, never authority to swap an active model or operate a game.

Why it matters: in continuous games a student can learn a superficially better strategy that becomes too slow in a specific encounter. Aggregate success or latency can mask lost responsiveness. A performance gate must be stratified by meaningful game contexts as well as measured end-to-end. Per-scenario evaluation itself must be preregistered before tuning; never choose map groupings post hoc.

## Next intelligence architecture: two timescales, with proofs
RealtimeBench was posted **2026-10-14** and contains 180 tasks over six continuously running game types. The TORSI work reported that a slow teacher studying failed attempts offline and producing compact instructions for a fast student improved the student score from 13.51 to 24.19 in that study. It is **not** evidence that STAR would achieve those scores. Primary source: https://arxiv.org/abs/2610.20665

Implement the teacher in Star Core Forge (offline-first). Allow it to inspect only **PRACTICE** traces and independently witnessed outcomes. Let it propose narrowly scoped, short, versioned skill instructions, and enforce one change per experiment. Run a rapid student in the real game without synchronous teacher calls; cache an approved skill card by game/build/scenario. Pin the tested student, model hash, tools, prompts, and random seeds. Reserve holdout tasks before modifications, collect fixed-size matched trials and independently sign the outcomes. Reject regressions, uncertainty and slower real-time reactions. Review approved changes before shipping; rollback on hidden holdout failure. Never expose validation tasks or evaluator secrets to the teacher.

Upgrade path:
1. Integrate `game_action_freshness.py`, `game_action_gate.py`, the signed GameplaySkillBank and `game_skill_gate.py` in a private allowed game harness. Require monotonic capture times, input acknowledgements and objective receipts.
2. Record end-to-end **capture → first decision → keypress acknowledged → game feedback** p50/p95, misses, stale-action rate, success, progress and unseen-scenario transfer. Keep trial IDs, scenes and game versions stable. Stop measuring only abstract token throughput.
3. Introduce teacher-generated **candidate** skill cards with hash/version and a replay manifest. Preregister same-seed A/B comparisons; cross-evaluate on unseen maps. No hidden holdout exposure in learning, broadcasts or Discord reports.
4. Move to a portfolio of unrelated legal/permitted games to test generalization, not repetition on one obby or one game seed. Avoid unauthorized game automation and competitive cheating.

## Faster inference on 8 GB GPU, without making gaming worse
Live gaming/OBS/renderer time is the highest-priority reservation. Audio should have a short queue and CPU fallback where viable; bound VLM observations by scene novelty and *observed* cost; research, image generation and heavy student training should defer during live streams. The present QoS and stream hardware telemetry modules are a starting point. Never infer free VRAM from the model's own claim. Keep the fast response model resident if the game fits, and use background CPU/RAM/off-stream teacher runs rather than swapping large weights each turn.

Experiment with llama.cpp prompt caching, dynamic batching and speculative decoding **one at a time** on the target Windows machine; keep cache isolation tests enabled as a prerequisite. Report VRAM peak, RAM peak, Windows game p1 FPS, OBS dropped frames, first-token latency, first-audible PCM and long-tail latency, alongside answer correctness and game outcome. A faster tokens/second value with worse frame pacing is a regression. Speculative decoding is not guaranteed faster on limited 8 GB systems; the draft model also consumes capacity. Primary upstream documentation: https://github.com/ggml-org/llama.cpp/tree/master/docs (check the pinned tested revision).

Use Rust only if profiles show Python overhead in capture/PCM scheduling or data transforms and the FFI boundary is measurable. Prioritize efficient buffers, warm model processes, bounded queues, zero-copy host→worker IPC, context-prefix reuse and testable policies before a wholesale rewrite.

## Natural and entertaining VTuber personality
A believable, funny streamer should react to **verified game events**, choose meaningful silence during fights, show context-appropriate gaze/eye motion and hair dynamics, remember genuine episodes, and allow viewers to finish speaking. Do not synthesize fictional real-world memories as facts or claim that a text model has human feelings. Persona can be charming and self-directed while transparently an AI.

LiveKit's turn-taking guidance distinguishes VAD (speech activity), end-of-turn decisions and adaptive interruption classification. Its adaptive mode has cloud availability constraints; self-hosting may need simpler VAD with tuned thresholds rather than assuming the adaptive service is local. Reference: https://docs.livekit.io/agents/logic/turns/tuning/ . STAR already has a local `stream_turntaking.py`; benchmark false interruption rate, missed genuine owner barge-ins, recovery after false triggers and audio/face resynchronization before replacing it.

Kyutai released Pocket TTS **v4.0.0 on 2026-10-20** (18m, 7m and experimental 2m English families), followed by **v4.0.1 on 2026-10-21** fixing pronunciation/behavior for the smaller models. This is a CPU speech candidate, not a proven improvement for STAR's voice: https://github.com/kyutai-labs/pocket-tts/releases/tag/v4.0.1 . Test 7m and 18m in blind listening versus the existing Star voice, including spontaneous laughter, whispers, clipped game shouts, interruptions, CPU saturation and lip-sync. Preserve actor/model voice provenance and consent.

Streaming acceptance suite: at least 30-minute OBS recording on the intended Windows game PC, with real game FPS and GPU load, at least 20 authenticated owner interruptions, measured mouth/audio offset from recording, quiet gameplay focus, occasional game-grounded excitement, a mix of factual viewer answers and declined unsafe requests, and zero invented game victories. Disable background research when FPS/p95 or audio backlog breaks bounds. Confirm reduced-motion preference and mascot character-sheet fidelity.

## Roblox game-making intelligence
Use the official OpenGameEval executable scene/play session checks as inspiration for agent exploration and evaluation, rather than judging Luau diff quality alone: https://github.com/Roblox/open-game-eval . Add mechanical invariants: no anchored/unanchored structural mistakes, consistent scale, correct pivot/hand grips, no floating/penetrating props, correct collision, readable UI at mobile resolutions, working networking and server authority, deterministic mechanics, meaningful sound/light/animation and visual review from multiple camera angles.

StudioTestService can run scriptable multiplayer tests with up to **eight simulated clients** (and client joins/disconnections): https://create.roblox.com/docs/reference/engine/classes/StudioTestService . The Studio plugin/host must drive it; a written plan is not a passed game test. Keep one game instance/version per validation run. Include actual screenshots with independent scene visual-diff judgments before packaging.

## Knowledge, interests and broader capability
Separate factual reviewed knowledge, source-linked retrieval, ephemeral personal streaming episode lore, and uncertain hypotheses. A curated bank should track source date, relevance, licenses and confidence; games/videos become observations only after permitted capture and tested summarization, not because the model says it watched them. Evaluate with unfamiliar general-knowledge and design tasks plus counterexamples/abstention tests. Use spaced retrieval on mistakes, not unlimited raw transcript ingestion.

Star Core Forge should control experiments, semantic diffs, sandboxed offline tests, resource cost accounting, owner-approved permission boundaries, rollback and snapshot retention locally; GitHub is only an optional publication mirror. Track improvement as error reduction/transfer at constant or reduced wall-clock and hardware budget. No system can guarantee universal superhuman intelligence from more tools or memory.

## Acceptance and limits for this revision
Code-level changes: paired scenario evidence counts and p95 latency regression gating, plus synthetic tests. All fresh capabilities and dependencies above are **recommendations**, not installed or benchmarked implementations. The GitHub repository called `Star-AI-Private` currently reports **public visibility**; no secrets, private recordings, signed keys or nonpublic examples belong in PRs. Keep PR #845 draft/unmerged until CI and authorized Windows rehearsals are complete.
