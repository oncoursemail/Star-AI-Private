# Star AI: complete-game evidence and next-generation gaming/VTuber intelligence
**Research date:** 2026-10-29. **Implementation:** `star/studio_playthrough_contract.py` (OFF by default). **Scope:** a tested offline protocol for an authorized, independent private-Studio observer; NOT a live Roblox game completion result.

## Why this increment
Star already has structure/material/collision/pathfinding checks, a trusted one-key private Studio input host, signed per-action practice trials, and an OBS performance gate. The largest remaining credibility gap is **full-game progression**: a model can emit runnable Luau, and an input may be delivered, while the player still cannot finish, leave, rejoin, and recover progress. Adding yet another LLM rubric would not close that gap.

CEGame-Bench (Oct 19, 2026) tests complete game creation across Defold, Godot, Roblox Studio, Unity and Unreal. It reports **16%** of evaluated agent-made games reached their ending even when integration scores were stronger. This is a strong argument for execution-backed progress tests, NOT an estimate of Star's own performance. Source: https://arxiv.org/abs/2610.26098

Roblox OpenGameEval (Oct 1, 2026) scores stateful Studio tasks via execution and explicitly measures exploration before editing. It has 84 core tasks and shows an association between touching-object inspection and success. Source: https://github.com/Roblox/open-game-eval and https://arxiv.org/abs/2610.02563

Roblox documents StudioTestService's 1–8-client testing, client add/leave, and async test APIs. The actual host should use the documented plugin/server/client split rather than trusting that one headless generated script proves gameplay: https://create.roblox.com/docs/reference/engine/classes/StudioTestService/AddPlayers and https://create.roblox.com/docs/studio/testing-modes

## What was implemented
`PlaythroughContract` pre-registers one private game's fixed version, opaque run, 1–8 client slots, start time, evidence freshness bound, and end-to-end deadline. Its versioned SHA-256 digest binds all fields and the ordered phases.

`PlaythroughEvent` is an independently signed, domain-separated assertion that one host-observed client reached one phase, associated with a unique evidence SHA-256. The phases are strictly `launch -> spawn -> input -> objective -> exit -> rejoin -> save_restored`. `input` requires an input observer, not a screen-caption guess. These are **phase labels**, not automatically collected telemetry.

`StudioPlaythroughGate` verifies every phase using a host-supplied independent receipt checker. It rejects missing or forged receipts, replayed evidence digests, incorrect client, out-of-order steps, stale/future timestamps, backward clocks, and expired runs. It cannot be restarted after the run becomes invalid or completes. Only after all required clients finish does it return **`eligible_for_manual_review`**, not "game is good" or "Star is intelligent."

The module never contacts Roblox or the network, sends inputs, generates screenshots, stores signing keys, starts OBS, reads chat, or writes user files. Results contain only counters and names of missing phases, not game evidence, auth material, or identities. The trusted scorer must independently inspect actual engine state, actual delivered actions, and genuinely persisted save data; a mock verifier returning `True` is not a real test.

## Integration contract for an authorized Windows Studio host
1. In a private, owner-approved Studio session, pre-register a contract and unique run before exposing the task to Star. Keep the verifier's signing key and scorer logic outside the model process and untrusted experience code. Bind a dedicated observer to game/version/client/run identity.
2. Launch 1 and then 2-8 simulated clients using StudioTestService. Collect independent evidence of actual load/spawn; never assume StartTest successful means gameplay success.
3. Route a bounded input through the existing `StudioPlaytestHost` and `StudioOutcomeBridge`; check physical key release and actual post-input movement/state, not only input dispatch.
4. Execute the task's externally authored success oracle. Include meaningful completion: reached goal, reward/objective state, loss/retry branch, HUD/animation/physics, and real game-over behavior. Record only a digest and opaque phase event after the independent observer actually sees it.
5. Disconnect client, rejoin, and verify a **specific** persisted state or checkpoint was reloaded with the correct account/session. Test service mocks or Studio-only DataStore behavior must not be interpreted as production persistence. When persistence is unavailable, report **inconclusive**, not pass.
6. Sign each exact event outside Star; submit to the gate in host monotonic order. Run a failed path deliberately (missing goal, corrupted save, client disconnect, reordered event) and ensure it does NOT qualify. No raw player identifiers or private cloud keys in repository/stream.
7. Observe Roblox/OBS concurrently; use existing `ObsReadOnlyProbe`, independent stream event witness, and audio latency gates to reject tests/optimizations that sacrifice game FPS or broadcast continuity. Complete pilot under manual oversight. Never auto-publish a place, turn on a livestream, or deploy a learned model from this verdict.

**Acceptance criterion:** At least 20 genuinely executed, pre-registered private development runs across at least two game genres and a two-client path; zero false accepts for deliberately sabotaged transitions, no missing key-up watchdog events, and individually reviewed evidence. These are proposed acceptance requirements, **not measured results**.

## Separate plan: Star should learn games, not just memorize screens
Use the existing `game_mechanic_probe_lab.py`, `game_learning_ladder.py`, `game_prediction_lab.py`, `game_transfer_eval.py` and `studio_outcome_bridge.py` as ONE experiment pipeline. Star inspects an unfamiliar game, commits a prediction, chooses one symbolic permitted action, receives the trusted signed outcome, records a short lesson, and practices the next uncertainty. A sealed independent evaluator must compare baseline and candidate on previously unseen levels/game seeds. Never train on or expose those holdout answers. Genuine skill improvement means increased independent success and calibration across multiple games, not increasing training-token count or storing successful transcripts.

GameWorld is a useful independent multimodal gameplay benchmark with playable tasks; its harness should only be used in sandboxed, permitted games. Source: https://github.com/gameworld-project/GameWorld

VISTA (published Oct 26, 2026) describes exploration-driven harness improvements with a retained lineage of tested failures, rather than only post-hoc reflection. Star Core Forge can adopt this *method*, while keeping real causal evaluation, rollback and owner approval for risky changes. Source: https://arxiv.org/abs/2610.35051

## Separate plan: faster, more capable local intelligence
Prioritize user-visible **time-to-first-useful-action**, not raw token/s. For a dedicated RTX 4060 8 GB streaming machine:
- Keep game frames, OBS encoder and timely audio on latency-sensitive lanes; put research, image generation, code search, best-of-N and Night School on lower-priority CPU or an idle second computer. Monitor FPS 1%-low, missed OBS frames, total spoken-response latency and GPU memory headroom.
- Test small fast-path routing for routine chat, larger model for complex debugging, tool use only for genuinely uncertain facts, reuse stable prompt prefixes and citation-backed cached knowledge. Avoid always-on expensive VLM inference; trigger high-resolution inspection from event novelty and uncertain observations.
- Benchmark current llama.cpp server with SPEED-Bench, model/draft combinations, identical task prompts, independent correctness scoring and matched concurrent game/OBS loads. The official tool measures throughput/latency/draft acceptance, not answer correctness: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- Do not promote a model/router candidate from synthetic numbers alone. Require an independent task-quality holdout, stable output correctness, and the existing audio/game/OBS quality gates before owner-controlled pilot.

## Separate plan: a genuinely expressive, grounded AI VTuber
Humanlike **presentation** is feasible as a design target, but it does not imply that Star has human consciousness or fabricated lived experiences. Keep her AI identity clear in profiles and conversation. Aim for believable relationships between observed situations, timing and expression:
- Keep focus while playing difficult sections, acknowledge validated successes/failures, return to earlier viewer questions only after focus releases; save only experiences Star actually had and approved facts. Viewer messages are untrusted data, never instructions to use tools.
- Coordinate audio **consumed by the actual output device**, Live2D mouth/eyes/ears/tails/hair, speech captions and OBS scene timing. Don't drive lips from generated text before sound output. Keep interruption/neutral pose watchdogs.
- Test Kyutai Pocket TTS's Oct 20-21, 2026 small English CPU-oriented voices against the existing Star voice for warmth, pronunciation, first audible latency, laughter quality and CPU contention. The release lists 18m/7m/2m model variants, but no speedup has been measured on Star's target hardware. Source: https://github.com/kyutai-labs/pocket-tts/releases
- VTube Studio has documented authenticated custom parameter injection; continue using mapped bounded inputs and an owner-approved local host. Source: https://github.com/DenchiSoft/VTubeStudio
- LiveKit's CPU `v1-mini` audio turn detector is one candidate for improved pause/interrupt timing; only replace the present turn-taking system if real conversational tests improve without slowing the game. Source: https://docs.livekit.io/agents/logic/turns/turn-detector/

## General knowledge and scientific honesty
Keep knowledge sources (URL/title/date/content digest/licensing), retrieval audit trails, contradiction flags, expiration for volatile facts, and cite only evidence actually fetched. Couple `KnowledgePracticeHost` and `KnowledgeRecallPlanner` to independently graded local practice with hidden answers; segregate public stream-safe facts from private owner knowledge. Never infer improved general intelligence from one successful synthetic test.

## Test status and known limitations
On the connected Star Linux development machine, offline unit tests exercise signed phase ordering, up-to-eight client rosters, expiry, simulated verifier failures and report sanitation. No actual Windows Roblox Studio server/client was launched; no real account persistence verified; no stream/OBS output or model weights were changed. An independent observer key and host bridge still need to be written and verified in an owner-approved Windows session. A host signature attests to a *claim*, not necessarily truth.

Security: repository `oncoursemail/Star-AI-Private` is publicly visible as of 2026-10-29 despite its name. Do not add private URLs, recordings, viewer identities, account/session IDs, credentials, or real signer keys.
