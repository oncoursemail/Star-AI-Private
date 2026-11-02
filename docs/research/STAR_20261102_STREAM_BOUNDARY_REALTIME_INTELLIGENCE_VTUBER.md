# Star AI — broadcast-boundary safety, adaptive intelligence, VTuber engineering
**Research and engineering note:** 2026-11-02. This is a development proposal and one tested software change, **not** a claim of actual game skill gains, a live stream, faster weights, or human consciousness.

## 1. Reproduced issue and completed implementation

**Old behavior:** a game action suggestion was admitted at 1100ms while OBS was not live, or while it was live. Before the model returned, OBS switched state. At 1200ms, `RealtimeGameLoop.finish` checked only the NEW host-attested `stream_live` flag and NEW telemetry, not the state used to admit the inference. Both transition directions were accepted by the existing action gate.

**Why this matters:** a game inference allowed under an idle GPU/stream profile can no longer be treated as the same consent/resource context when broadcasting starts. Conversely, a reply admitted while live should not silently cross stream shutdown/recovery. A fast answer is only useful if its *lease still belongs to the current execution context*. This is especially important if the host has separate offline/live reasoning budgets or viewers can trigger an interruption.

**Fix:** carry the host-attested `stream_live_at_offer` on the identity-bound immutable `GameThinkLease`. At the **finished inference boundary**, refuse a state change before offering an action. Discard the consumed lease; return `stream_state_changed_during_inference`, with no action permit. Unchanged live and offline states preserve existing behavior. The hint remains untrusted; a new scene requires another admission, and actual key dispatch still requires a separate host recheck and identity-bound permit.

**Red/green evidence:** two transition scenarios (OFF->ON and ON->OFF) initially failed (each produced an unwanted offered permit). Both passed after the fix, alongside two unchanged-state controls. Dedicated real-time/deadline test group: 71 passed, with no external game or network interaction. Broad suite and CI evidence should be reported separately.

**Boundaries:** This does not instrument OBS itself; `stream_live` must come from the trusted host, not a prompt or model. A rapid OFF->ON->OFF cycle is not observable from two booleans; a future host-signed, monotonic OBS **stream generation** should close that ABA gap. Neither inference completion nor a timing advisory grants permission to press keys, broadcast, train, spend, or message viewers.

## 2. Intelligence architecture: one model is not the whole agent

Star should use a **fast, bounded realtime student**, a **stronger offline teacher**, and an **independent verifier**.

| Lane | Inputs | Responsibilities | Admissible outputs | Strict exclusions |
|---|---|---|---|---|
| Reactive gameplay | recent host-verified scene, scoped action allowlist, frame deadline | choose among safe symbolic actions within measured latency | advisory only, per-frame lease | no web browsing, large code jobs, self-training, direct keys |
| Interactive social/VTuber | host-attested audio playback, viewer-turn event, OBS status, game priority | decide speak/silence, short context-grounded response, emotion/animation envelope | queued speech and avatar hints | no invented viewer/game history or uncontrolled interruptions |
| Between-round teacher | signed losses, frozen game versions, independent reset/holdouts | diagnose mistakes, invent lessons, best-of-N action policies | versioned candidate strategy with uncertainty | no online weight changes, unverified promotions |
| Creator/developer | project snapshots, Roblox/Blender tooling, executable scene tests | inspect existing scene, build, simulate, repair, evaluate visual fidelity | proposed code/assets with tests and rollback | no direct production publishing |
| Long-term knowledge | licensed docs, provenance, dates, verified success receipts | retrieve context, cite, forget stale information, compress memory | task-relevant evidence | no unsourced permanent facts, viewer private data in memory |

The October 14 paper *The World Won't Wait* reported that a two-timescale teacher/student approach improved its own fast model's average progress score from 13.51 to 24.19 after two teaching rounds across six game types. **That result is not a Star benchmark.** The October 15 *Realtime-Bench* paper found a best wall-clock success rate of 44% on its tasks; the distinction between paused and running games is essential. Rather than increasing model reasoning indefinitely, budget thought based on remaining game-scene lifetime.

**Priority design:** attach the remaining scene/action budget to the host scheduler, not just to a text prompt. The October 7 *On the Clock* paper reports that explicit timing and enforcement hooks can improve time adherence, whereas merely asking a model to respect a time budget is unreliable. For Star, cap wall-clock inference per frame and cancel the actual worker if its lease is invalidated; discarded responses are not proof of worker termination.

## 3. Performance experiments for an 8GB gaming GPU

Do not assert a specific tokens/s or future model's fit without measuring the *actual* GPU, model checksum, quantization, context length, and KV-cache format. The same PC may be both a desktop game renderer and a local AI server.

1. Baseline on CPU and GPU independently with a fixed model/quant, fixed prompts and decode lengths. Measure **completed** p50/p95/p99 first-audible response (for voice) and p50/p95/p99 finished output; count truncations, wrong outputs and timeouts as failures.
2. In a preapproved offline experiment, vary llama.cpp `--np`, batch/microbatch, quantized KV cache, GPU offload, prompt cache, and then speculative decode. Benchmark each **paired** configuration under the same prompt set and game/OBS load profile. Larger batch or speculative decoding can be slower under contention; retain only measured gains.
3. Use the official llama.cpp SPEED-Bench for throughput, latency and draft acceptance; augment it with Star's downstream game-frame/OBS/audio quality gates. Speed is not independent of correctness or audience experience.
4. Try October 20, 2026 Pocket TTS 18m/7m/2m English variants on CPU in nonbroadcast rehearsal. Run an A/B against existing TTS while monitoring CPU saturation, first played PCM, intelligibility, expression fidelity and the game's 1% lows; do not assume the smallest model will be listenable.
5. Reserve GPU headroom for OBS rendering and game frame pacing. Use admission control for background training/indexing/asset renders; suspend work at stream start or critical OBS drops. Never blindly increase VRAM allocation just because nominal capacity is 8GB.
6. Persist a **host-attested workload fingerprint** (game version, GPU identity, stream generation, recording/live state, model checksum, context length, thread count). Latency samples from another fingerprint must not prove realtime admission. This goes beyond the initial live/off boolean fix.
7. Explicitly test GPU starvation, Windows device changes, OBS reconnects, restart after power loss, and staggered microphones/headphones. Mark unknown health as insufficient evidence, never "normal".

Acceptance for an inference profile: actual measured accuracy and completed p95 response improve or stay within guardrails; game 1% lows, OBS dropped frames, speech overlap, playback continuity and avatar sync do not materially regress; no new scene/stale identity failures. Reject any purported speedup measured only on idle hardware.

## 4. Natural, *consistent* AI VTuber behavior

Humanlike **presentation** is measurable; claims of human identity, literal emotions or consciousness are not engineering test results. Star can speak expressively and independently while clearly identifying herself as an AI VTuber.

- **Turn model:** separate "someone spoke" from "they addressed Star", "the utterance is complete", and "the current game moment permits a reply". Make silence a valid decision. A viewer's chat question, incidental microphone noise, and the owner's barge-in are different contexts, not interchangeable VAD triggers.
- **Speech:** generate short spoken clauses progressively, with interruption-safe punctuation, prosody and emotion tags; measure output-device PCM, not TTS enqueue time. Stop stale audio on game change, owner interruption or ended episode. Track audible pauses and false interruptions, not only first-token latency.
- **Embodiment:** VTube Studio plugin API can inject tracking parameters, activate expressions and hotkeys. Use a bounded emotion state (surprised/curious/concentrating/celebrating/disappointed), contextual gestures and synchronized mouth/eyes; do not let text alone override microphone, device clock or trusted scene facts.
- **Continuity:** versioned self-model and opt-in episodic memory grounded in actual game events and approved viewer interactions. Distinguish "I tried and failed" from "I won" using signed game evidence. Keep viewer identifiers and personal conversations out of training/long-term memory by default.
- **Social naturalness:** allow low-stakes self-directed topic changes, situational laughter, tiny interruptions, hesitation, curiosity and reactions to mistakes. Avoid constant monologues, fake achievements, simulated human private experiences and overreacting to every frame. Human listeners should judge naturalness *blind* on matched moments.
- **Safety:** auth-gate OBS WebSocket, restrict plugin permissions, never reveal stream credentials or internal prompts on screen. Private dry-runs first. Interactions with Astro and Amber should be scene-aware and easy to turn off.

The September 28 *HiThink Turn* research describes intent-aware full-duplex control with 240ms audio chunks; this is a research direction, not a drop-in Star model or proven improvement. Evaluate turn-taking with held-out interrupt/noise/viewer cases and actual recorded PCM.

## 5. Autonomous games: practice that produces durable knowledge

Collect authoritative, versioned game signals: objective status, checkpoint, deaths, inventory, frame freshness, and per-action outcome, with provenance and timestamp. From each failed attempt generate at least two candidate strategies; compare against a frozen baseline on preregistered map/seed splits. The verifier—not the same model that generated the strategy—judges success.

For games with only screen access, use capture/OCR/vision conservatively; confidence low means observe rather than act. Keep controls explicit, obey each game's rules and anti-cheat requirements, and prohibit multiplayer automation where disallowed. No unrestricted PC control is required for skill learning.

**Tests:** repeat the same level with variant seeds, then previously unseen levels; compare real-time and paused-clock performance; track input delay, deaths, normalized progress, win rate and model timeout rate. A high-scoring paused agent is not necessarily a high-scoring live player.

A signed, owner-approved `GameTrial` in Star's existing gameplay bank is a better learning signal than model self-report. Maintain practice/validation/holdout separation and statistical independence; revise strategy only after a preregistered independent gate. Future teacher should summarize failure causes, not inspect unseen holdout outcomes.

## 6. Roblox game creation: inspect -> implement -> execute -> visually review

Roblox's October 2026 *OpenGameEval* research uses stateful Studio sessions, observation/edit tools and executable checks. Its authors evaluated 13 models on 84 tasks with 16 runs each and found pre-edit exploration correlated with success. Star should copy this *principle*, not claim OpenGameEval scores without actually running it.

Workflow: discover hierarchy, enumerate dependencies, verify API availability, plan diff; produce 4–8 bounded alternatives for difficult Luau issues, run StyLua/Selene/Luau analysis/tests, execute Studio client/server playtests, inspect real screenshots and geometry/collision, then compare to requirements. Only propose publishing after a human reviews the approved build.

Also include Blender pipeline checks: mesh scale, hand grip, material consistency, UV/texture limits, bone deformation, animation rig continuity, performance budgets, and license provenance. Record screenshots only in consented local review, not private stream chat.

## 7. Concrete engineering sequence

**Now delivered (this change):** stop game inference permits from crossing *observed* broadcast start/end events; two previously failing regression scenarios, two unchanged-state controls, and no interface changes to existing host calls.

**Next 1 — full stream generation:** host-sourced monotonically increasing OBS status generation; bind offer/finish/latency samples and voice playback to generation, preventing OFF->ON->OFF ABA and stale callbacks. Require authoritative event source/reconnection handling.

**Next 2 — audio/game/OBS integrated rehearsal:** run **nonbroadcast** three-phase comparison on Windows: game only, game+AI, game+AI+avatar+OBS recording. Collect p50/p95/p99, game 1% lows, OBS drops, FPS, VRAM, PCM latency, A/V offset, interruption rate, and verified actions. Avoid producing a public stream during initial tests.

**Next 3 — verified fast learner:** enable bounded teacher-generated practice curricula between game rounds; compare 20+ independent unseen seeds across two or more scenario families, include failure-focused examples and guard against changes in game version. Nothing promotes automatically.

**Next 4 — creator pipeline:** run a reproducible OpenGameEval-style fixture in Studio Lab, including source-inspection coverage and real multiplayer execution. Report pass@k and actual artifact visual review separately.

**Next 5 — character quality:** blind paired clips of voice/expressions/turn-taking, including owner barge-in and no-speech conditions; use real playback and verified scene memory. Personality quality should never be inferred from latency alone.

## Sources checked for this note

- *The World Won't Wait: Evaluating and Teaching Agents Under a Live Clock* (Oct 14, 2026): https://arxiv.org/abs/2610.20665
- *Realtime-Bench: Can Frontier Models Solve Real-time Interactive Problems?* (Oct 15, 2026): https://arxiv.org/abs/2610.22155
- *On the Clock: Towards Punctual and Productive Time-Budgeted AI Agents* (Oct 7, 2026): https://arxiv.org/abs/2610.10833
- *HiThink Turn: An Intent-Aware Turn-Taking Control Module for Full-Duplex Dialogue* (Sept 28, 2026): https://arxiv.org/abs/2609.34096
- *OpenGameEval: Benchmarking Agentic Programming and Exploration in a Stateful Game Engine* (Oct 1, 2026): https://arxiv.org/abs/2610.02563
- Official OpenGameEval harness and Studio test integration: https://github.com/Roblox/open-game-eval
- llama.cpp official SPEED-Bench: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- Kyutai Pocket TTS releases (v4.0.0, Oct 20, 2026): https://github.com/kyutai-labs/pocket-tts/releases
- OBS WebSocket project and authenticated control interface: https://github.com/obsproject/obs-websocket
- VTube Studio plugin interface: https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins

**Every future feature remains opt-in and reversible, with narrow host-side authorization; a draft code review is not a live deployment.**
