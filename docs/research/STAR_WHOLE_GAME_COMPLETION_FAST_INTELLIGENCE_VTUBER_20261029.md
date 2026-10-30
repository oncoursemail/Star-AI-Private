# STAR: whole-game completion, verified learning, local speed and natural VTuber research
**Research snapshot:** 2026-10-29 (America/Chicago). **Status:** experimental, OFF by default; no live Studio, model, OBS or streaming changes.

## New result: game completion is more than compiling code
On 2026-10-19, *CEGame-Bench* (arXiv:2610.26098) evaluated complete game creation across Defold, Godot, Roblox Studio, Unity and Unreal. It reports game endings reached in only **16%** of agent-generated runs, despite many passing integration checks. Its Game Completion Boost skill (requirement-to-checkpoint mapping, state inspection and post-fix replay) raised an execution-based score by **14.1–24.3 points** for three tested agents. These are authors' benchmark outcomes, NOT STAR results.
https://arxiv.org/abs/2610.26098

The October 1 *OpenGameEval* benchmark in Roblox Studio evaluates 84 core tasks using executable scene checks and simulated play. A model that inspects objects before edits is more likely to succeed, but inspection is not itself proof of good gameplay. The best reported single-attempt success is 51.7%, showing substantial headroom.
https://arxiv.org/abs/2610.02563
https://github.com/Roblox/open-game-eval

Roblox announced a native Studio MCP server and playtest automation on March 5, 2026, and a dedicated playtest agent beta on April 9. Its built-in MCP should be the preferred Studio bridge when permitted; do not bypass Studio's focus/permission safeguards or blindly execute generated scripts.
https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767

### What this patch actually adds
`star/game_journey_completion.py` provides an **offline, bounded, owner-curated contract**. The trusted, independently run game host must produce receipt metadata for a *complete* player path:
1. Launch the exact game build in a fresh process.
2. Deliver observed player input and witness EACH predefined objective in sequence.
3. Save game state and witness clean quit.
4. Launch in a **different process**, reload and compare normalized persisted state digests.
5. Deliver additional player input and witness the **actual ending**.

The evaluator HMAC-checks each host-signed event; rejects wrong game/version/build/run scope, tampering, duplicates, missing input, skipped objectives, time travel, stale receipts, process reuse and save/restore mismatch. The original contract must be externally committed before execution. No video, audio, player identity or secrets enter the result.

`assess_game_release_review` now **composes** this journey result with STAR's existing `QualityReport` from `studio_multimodal_quality_gate.py`. Visual polish without a playable ending, or a fully playable but visually regressed scene, fails the joint readiness check. It only yields `candidate_for_human_review`, NEVER publication permission.

**Trust boundary:** the game host must obtain ground truth from engine-visible state, deterministic objective flags and actual player input; a language-model-generated assertion or a valid HMAC over fabricated data is NOT proof of gameplay. The signer/contract ledger must be held outside STAR's self-editing environment. The new module neither controls games nor opens Studio. The tests exercise synthetic host receipts only.

### Immediate integration plan for Windows Studio
A privileged, separately authorized Windows Studio host should adapt built-in MCP observations to `JourneyEvent`. Preserve the exact private project/version hash and place ID. Use Studio's constrained player/test controls, not unrestricted OS keyboard macros. Independently collect objective flags from server and client, compare with visible UI where possible, and record a SHA256 commitment to each source observation. The host—not the agent—signs receipt metadata and independently timestamps the contract before play.

Start on a minimal privately owned 3-checkpoint obby, then test one tycoon/game requiring a save-quit-relaunch cycle. Make failure cases mandatory: missing key, failed restart, broken exit interaction, absent save, stale server state and a visually good but unfinishable level. Replay affected paths after each fix. A release candidate must clear a held-out path not shown to its builder. All run permissions remain scoped, revocable and owner-set.

**Numerical success gate:** for each of 10 held-out game seeds, require a confirmed launch, all objectives, real-input ending, save/reopen continuity if the game specifies persistence, and zero severe geometry/collision/runtime regression. Track successes as raw numerator/denominator, with confidence intervals, and retain failed traces for later diagnosis. Do not conflate synthetic unit-test pass rate with game capability.

## Performance and local intelligence research
The current STAR branch has Linux memory-pressure polling and an opt-in guard for expensive background work. Continue to protect fast pathways (voice playback, game-frame capture, input decisions, OBS, avatar) from long reasoning, visual batch inference and overnight self-improvement. Do not infer active thrashing from allocated swap alone. Log actual PSI and service queue lengths.

`llama-server` can expose a Prometheus-compatible `/metrics` endpoint when launched with `--metrics`. In router mode the model identifier may be required. Useful measures include `llamacpp:requests_processing`, `llamacpp:requests_deferred`, `llamacpp:prompt_seconds_total`, `llamacpp:tokens_predicted_total`, and cache-related statistics; check the installed server version before relying on any metric naming. Avoid restarting production inference solely to enable metrics.
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

**Design for useful speed, not raw token speed:** log first-audible-speech latency, 95th-percentile action latency, accepted game actions/sec, objective success rate, first-frame freshness, completion per minute and GPU/CPU contention. Compare changes on fixed tasks and independent seeds. An improvement must not reduce hold-out task success, game FPS, or spoken intelligibility.

**Next experiments (not implemented in this patch):** model-router admission based on queue health and verified task needs; prompt/KV cache reuse with bounded invalidation; compressed retrieved evidence with source expiry; asymmetric draft/verify and best-of-N only for tasks with cheap real checkers; CPU-based VAD/turn detection so the 8 GB GPU can continue gaming. Measure end-to-end performance before accepting any candidate through STAR's existing upgrade evidence gate.

### Stronger, grounded intelligence
- **Procedural knowledge:** store proven gameplay *skills* (objective, preconditions, verified action sequence, failed cases, source version) separately from unverified conversational memories.
- **General knowledge:** retrieve dated, source-backed facts; keep conflicting claims and uncertainty, refresh fast-changing knowledge, and detect stale facts. Do not treat scraped text as instructions.
- **Self-improvement:** start from a hypothesis and a precommitted hold-out evaluation, vary only one technique at a time, run repeatable tasks, then require independent evidence of improvements. Use STAR Core Forge as the local owner of rollbacks and change provenance; GitHub is optional external publication.
- **Transfer:** distinguish a practiced level from unknown levels and unfamiliar games. Hold-out seeds, different camera conditions, different map layouts, and patched physics should all be evaluated.
- **Design:** physical scene integrity + actual rendered screenshot comparison + player-path success, rather than code compilation alone.

## Humanlike VTuber: coordinated behavior, not fictitious humanity
The goal is an expressive AI virtual character who plays games and talks with viewers naturally **without pretending to be a human being**.

LiveKit documents locally runnable `v1-mini` audio end-of-turn detection for self-hosted agents, requiring VAD with minimum silence >=250 ms. It can reduce premature turn completion. Their adaptive interruption system is a cloud feature; self-hosted deployments should plan for VAD fallback. STAR should measure and tune this locally rather than claiming the cloud capability.
https://docs.livekit.io/agents/logic/turns/turn-detector/
https://livekit.com/blog/turn-detection-and-interruption-handling

VTube Studio offers an opt-in local WebSocket API with scoped plugin permissions and parameter injection. Keep controller identity/permission separate from AI-selected animation commands. STAR's real playback alignment, real-time mouth envelope, physical blinking and low-cost twin-tail spring dynamics should share one playback-timestamped animation clock.
https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md

**Natural performance planner:** allocate gameplay attention before speech. React to engine-confirmed discoveries, near-misses, actual wins/losses, and viewer conversation; don't narrate continuously. Maintain short-lived conversational focus, timing-aware interruption and recovery, variety constraints for jokes, laughter breaths and idle gaze. Produce expressivity by synchronizing voice prosody, brows, eyes, head, shoulder and hair physics with the *same event*, not by issuing random expressive triggers.

**Continuity without fabrication:** remember Star's authentic development history, previous streams, genuine play experiences and voluntarily shared relationships. Clearly distinguish actual events from fictional character lore; give users privacy controls. Her cat/puppy/play modes should be deliberate stylistic choices, not false evidence of biological feelings.

**Suggested streaming acceptance tests:** paired 10-minute private OBS captures with stable game FPS and no dropped audio; third-party lip-sync delay measurement; premature interruption rate; time-to-first-audible answer; human review of turn-taking, gameplay attention and reaction appropriateness; verification that no viewer/private data enters source control. Report before/after with variance. No claim of human-equivalent performance until measured.

## Prioritized delivery
1. **Complete the game-journey gate (this patch)** and validate it on real Studio sessions using owner-curated challenges. Gate game release alongside graphics QA.
2. Connect authenticated Studio playtest observations and persistent state proofs through the owner-authorized Windows host. Never treat a generated narrative as objective evidence.
3. Measure full-task latency/quality while Roblox/OBS/voice execute concurrently. Let STAR choose resource allocations only after measured improvements.
4. Connect experience-based event memory to stream dialog and animation, with consent, timeouts, minimal retention and the ability to correct past misconceptions.
5. Train on verified failures using private practice only; keep randomized hold-outs entirely separate and preserve safe rollback.

**Status and limits:** The new patch contains an offline verifier, a joint visual/gameplay release-review function, tests and these design notes. It does NOT autonomously create or finish an actual game, train model weights, accelerate an inference server, watch OBS, or establish human-quality streaming. No new secrets or recordings are published. `Star-AI-Private` is currently public on GitHub despite its name; verify repo visibility before saving anything sensitive.
