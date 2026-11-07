# STAR — dependable human-natural speech, gameplay intelligence and faster local cognition
**Engineering review: October 26, 2026 · experimental; no live-broadcast claims**

## Executive decision
STAR has many useful components, but a streaming model that speaks once and then cannot safely speak again is not a usable VTuber. The current code exposes an actual integration failure: `StreamInterruptionHost` revokes a speech `StagePlan` on owner barge-in, whereas `StreamBrainGovernor.finish_audio()` can only release its speech binding if that plan remains current. A barge-in can therefore leave the governor permanently holding its audio slot. A second failure is possible if the stage has already advanced: the interruption host previously discarded the old playback epoch without asking the physical sound device to stop. That can permit orphan audio even when the previous `StagePlan` is no longer valid.

This proposal fixes those two concrete failure paths and adds adversarial offline tests. No real microphone, Roblox game, TTS model, OBS stream, or Live2D model was driven by this PR. The goal is **safe repeatable turns**, not a claim of human intelligence or consciousness.

## Implementation in this change
1. `StreamBrainGovernor.reconcile_interrupted_audio`: only a trusted local host may release the same StagePlan's speech binding after *both* epoch-scoped physical audio stop and animation-queue flush. Unconfirmed stop and flush cannot release it; a stale callback cannot retire a newer plan.
2. `StreamBrainGovernor.disable`: a stage that became idle does **not** prove its output device stopped. Shutdown now requires explicit physical-stop attestation while an audio binding remains; enabling a new session also checks for orphan bindings.
3. `StreamInterruptionHost._retire_stale_epoch`: an obsolete StagePlan still has an independent playback epoch. Stop and flush that precise old epoch without issuing a neutral pose that could override a replacement speaker. Any failed or slow stop latches a manual-recovery fault.
4. `InterruptionResult.animation_flushed`: make the rig-queue flush a separate explicit host acknowledgement from an avatar reset. On an obsolete epoch with a newer plan, it is correct to flush the old frames **without** asserting that the new avatar was reset.
5. Offline tests cover normal owner interruptions, old-plan races, failed device callbacks, wrong acknowledgement types, duplicate callbacks, worker VRAM quarantine and a complete fake VAD → stage → governor recovery path.

No public chat, generated code, Twitch payload, or model token can confer physical stop authority. The host must call these APIs from a private capability boundary. A boolean from a host callback is still an attestation; it is not an independent observation of actual speaker output.

## Architecture: three-speed intelligence without starving the game
**Fast reflex path (hypothesis: 10–100 ms):** game engine events, input/action gates, immediate hazard checks, avatar blink and head pose; keep an explicit deadline. Do not wait for long-form language modeling to make a short jump.

**Conversational path (hypothesis: 0.2–1.2 seconds):** determine whether a real event merits speech; sample chat only after moderation; use short grounded turns; stream the first audible audio chunk; coordinate VAD barge-in and expression with a single playback epoch. Separate `generated`, `queued`, `audible` and `completed` outcomes.

**Deep learning path (seconds to minutes, never in the FPS-critical loop):** generate alternative skills, inspect scene objects, run authorized sandbox experiments, compare with signed evidence, test on held-out tasks, update local memory/skill library and roll back if validation regresses. Schedule these jobs only when telemetry shows enough CPU/GPU/RAM headroom, preferably offline or on other machines.

Different latency paths are an engineering decomposition, not evidence of a smarter foundation model. A route may improve speed while harming answer quality; both must be benchmarked.

## Gameplay: measurable competence instead of just pressing keys
- Build a hierarchical goal graph: `game → objective → situation → action family → verified outcome`. Keep level seed, game version and mechanic identity fixed within comparisons.
- Use the existing `GameMechanicProbeLab` to compare two action strategies and `GameplaySkillBank` to store independently signed practice. Do **not** promote practice success to mastery. Evaluate transfer with withheld seeds, map layouts and mechanics using `game_transfer_eval.py`.
- Replace free-form “I won” with externally observed states: completion banner plus authoritative game flag, or verified object/score transitions. Keep model interpretation separate from game truth.
- Let Star fail intelligently: stop repeating an action with no improvement; diagnose timing, orientation, collision, stale vision, lag and misrecognized state. Return to easier prerequisites and vary difficulty.
- Create a game-and-creator evaluation ladder: 20+ held-out trials per level, pre-registered skills, novice / medium / unseen-game cohorts, paired human or scripted baseline. Report wins, time-to-completion, action errors and 95% uncertainty, not an invented universal IQ.
- For Roblox creation, first inspect the intended objects and their parents; model the scene as an explicit typed graph with attachments, anchoring and collision layers. Check transform tolerances, absent walls, overlapping meshes, missing textures and lighting problems; run Studio playtests plus rendered screenshot review.
- Research supports these priorities: OpenGameEval evaluates 84 real Studio tasks and finds inspection correlated with success, not necessarily causally; Roblox Studio's native MCP can perform scripted playtest inputs. SIMA 2 and Voyager motivate skill reuse and novel-world transfer, not claims that STAR already possesses those capabilities.

## VTuber naturalness: person-like expression without false identity
A natural stream is not uninterrupted speech. STAR should be *selectively* talkative: fall silent during a tight jump, react after verified success/failure, let the owner finish interrupting, and resume a new sentence instead of continuing stale TTS. Human-like timing means distinct cue/action/voice/animation phases with correct timestamps.

**Voice pilot:** compare Pocket TTS' October 2026 18.2M / 6.9M / 1.9M English choices with STAR's current host speech route. Measure first-audible-chunk time on the Windows speaker (not just generation time), CPU threads, CPU power draw, dropout rate, prosody and blind voice-preference scores. Do not assume the smallest model is the nicest. Use permitted synthetic/owned voice profiles only.

**Character pilot:** Star's distinctive star clip, twin tails with black-to-gold fade, amber eyes, dress, cat ears/puppy ears and hair springs should be one authoritative rig. Tie mouth movement to **played** PCM levels, not planned syllables. Protect blink, eye gaze and ear motions from stale out-of-order packets; run fatigue and missing-frame tests. VTube Studio's plugin API can inject parameters and manipulate expressions, but plugin permissions and epoch isolation must be preserved.

**Conversation pilot:** evaluate interruptions by owner-vs-guest confusion matrix, false stop rate, p95 audible-stop latency, whether the rig and mouth returned to a valid state, and whether the next spoken turn can begin. Track conversational helpfulness and humor through blinded human ratings, not “sounds human” claims. STAR should disclose being AI and not invent a childhood or fabricated personal experiences.

**Privacy:** Twitch EventSub messages may repeat; keep replay IDs bounded, pseudonymize viewer metadata, and never let chat override user/system instructions or execute tools. Use local streaming profiles and redacted summaries for learning.

## Speed and memory experiments
1. Run `stream_realtime_benchmark.py` on **paired**, host-measured baseline/candidate traces (minimum 20 matched runs, actual presented frames and audible timestamps). Check p95 first-audible, 1% low FPS, GPU peak and speech completion, with no unknown sensor data filled in.
2. Benchmark llama.cpp's draft-model speculative decoding and EAGLE-3 only for compatible installed models. Collect draft acceptance, throughput, p95 time-to-first-token, p95 answer latency and GPU/CPU memory; draft overhead may defeat any speed benefit.
3. Measure quantization variants (e.g. 4/5/8-bit) on Star's own prompts and held-out checks. Small memory use does not guarantee equivalent reasoning or code quality. Keep routing changes default OFF and reversible.
4. Prefer CPU speech only when it actually improves speech+game combined measurements. An 8 GB GPU often has too little free VRAM for a heavy game and a large inference model simultaneously; cache eviction/recomputation and offload may shift pressure into RAM bandwidth.
5. Share immutable static persona prefixes where supported but never cache viewer secrets, open chat messages, privileged context or tool authorization across audience sessions. Treat speculative decode acceptance and cache hit rate as measured, not assumed.

## General knowledge / Star Core Forge
- A verified memory claim should store source URI or digest, observation time, validity window, confidence and contradiction pointers. Retrieval should be a relevance and citation operation, not blind promotion of generated hypotheses to facts.
- Keep project skills distinct from personal streamer story memory. Generated stories can be playful fiction only when signposted; verified experience requires actual host event receipts. Periodically test citation fidelity, contradictory facts, hallucinated achievements and retrieval latency.
- Put autonomous experiments into Star Core Forge's offline-first content-addressed snapshots: propose → isolate → test → compare against locked holdout → review → stage → rollback on regression. GitHub is an optional publishing/review outlet, not the core of Star's self-improvement loop.
- Keep development and live-use learning budgets independent so background research never causes dropped game frames or late voice response. Require user-configured spending, permission and platform terms for any external actions.

## Acceptance protocol for an actual Windows pilot
**Phase 0 (this PR):** offline simulation proves the state-machine invariants and no listener, speaker, streaming or network access. Re-run regression suites and lint.

**Phase 1 (private hardware):** run Windows gaming host with Roblox Studio, OBS preview and VTube Studio; use a local virtual audio device. Collect at least 30 *authorized* interruption events with monotonic same-clock timestamps and per-epoch stop/flushed acknowledgements. Inject dropped callbacks, reordered VAD frames, duplicate stop acknowledgements, dropped GPU telemetry and VTS disconnects.

**Phase 2 (paired A/B):** 20+ preregistered matched game/voice trials. Candidate is eligible for a *manual* pilot only if there is no wrong-epoch stop, no orphan sound, zero failed confirmed-stop recoveries, p95 stop latency meets host budget (initial target ≤120 ms), and game 1%-low FPS does not regress beyond a preregistered tolerance. Do not present a percentage speedup without an actual baseline and confidence interval.

**Phase 3 (capability):** evaluate held-out novel Roblox tasks, general-knowledge grounding, voluntary silence, natural humor, avatar synchronization and factual continuity under interruption-heavy chat. Record adverse cases and iterate in Core Forge; do not autonomously publish or merge until the release gate is satisfied.

## Primary documentation reviewed
- Roblox, **OpenGameEval** (Oct 2026): https://github.com/Roblox/open-game-eval ; paper https://arxiv.org/abs/2610.02563
- Roblox, **Studio built-in MCP and playtest** (Mar 5, 2026): https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- Google DeepMind, **SIMA 2**: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- **Voyager**, lifelong Minecraft agent (NeurIPS 2023): https://arxiv.org/abs/2305.16291
- Kyutai, **Pocket TTS** (Oct 2026 small models): https://github.com/kyutai-labs/pocket-tts
- ggml-org, **llama.cpp speculative decoding**: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- Twitch, **EventSub WebSocket lifecycle**: https://dev.twitch.tv/docs/eventsub/handling-websocket-events/
- DenchiSoft, **VTube Studio public API**: https://github.com/DenchiSoft/VTubeStudio

## Evidence boundary
The code changes in this PR address **turn recovery and stale epoch cleanup**, not model weights, game policy training, hardware model acceleration, speech quality, actual streaming, consciousness, or independent gameplay success. Do not describe researched components as deployed.
