# STAR AI — Quality-gated model routing and the real gaming/VTuber frontier
*Research and implementation notes — November 5, 2026. Experimental; no live gaming, OBS broadcast or model weights were used for this change.*

## The bottleneck that matters

Star already has several admission gates, inference timing benchmarks, streaming speech timing, scene-scope and gameplay evidence filters. But **choosing a fast inference model is not the same as choosing a correct one**. Token/second alone can select an agent that answers quickly but plays worse, misunderstands chat, or miscodes Luau. A 2026 llama.cpp issue describes speculative decoding being slower for high-entropy creative writing even while helping some coding prompts; real gains depend on workload and draft acceptance (see [per-request specdec discussion](https://github.com/ggml-org/llama.cpp/issues/23052), opened May 14, 2026). [llama.cpp SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) supports per-category and per-concurrency throughput/latency checks; it is **not** a verified correctness or game-FPS benchmark.

### Working change in this branch

New `star/stream_quality_route_selector.py`:

- Requires exact **deployed route identity** (hash of weights, runtime and voice config via `HostInferenceCatalog`), not an untrusted name supplied by a model or viewer.
- Compares a preregistered **same-suite, same-workload, same-trial-count** baseline with alternatives; accepted evaluations require a trusted independent host scorer, a minimum of 30 trials, freshness within seven days, and a 95%-Wilson **lower bound** above the configured correctness floor. If an alternative fails even one more task than the baseline, it is not substituted.
- Filters candidates by **measured end-to-end p95 latency**, total game/OBS/GPU peak, route reservation and latency gain. Fast but lower-quality, stale, idle-only, mismatched or unmeasured alternatives cannot win.
- Returns **an advisory only**. The new `StreamBrainGovernor.admit_quality_pilot` offers a separate explicit-owner-approved admission path, which checks the exact same catalog object and then applies normal realtime QoS. It reserves compute but still cannot launch a model, move a player, start OBS, auto-retrain, broadcast or self-modify. Default is no pilot without explicit authorization.
- Adds adversarial offline tests for unknown model digests, mismatched holdouts, small samples, weak scores, stale results, false host verification flags, resource overload, bad numeric types and deterministic choice.

**Important limitation:** An aggregate with `host_verified=True` is not cryptographic proof. The scoring host must be isolated from Star's generated text and chat, independently record every task identifier and outcome, and protect the preregistration manifest. A reused suite may leak into training or prompt memory. Wilson intervals assume roughly independent binary trials; correlated game outcomes overstate effective sample size. This policy is a conservative **screening heuristic**, not formal noninferiority evidence or causal proof. A stronger future gate should use balanced paired trial-level discordance with independent holdouts, task-family stratification and separate failure/severity analysis. Never train on sealed test outcomes.

## Priority 0: Prove an actual private Windows gaming rehearsal

A reliable stream must connect real devices and trace their timestamps, not assert success from generated text. Use the Windows host and Star's existing private-rehearsal code:

1. Start **private recording only**; authenticate the host, scene and game scope. Capture the real game viewport and player input acknowledgement without exceeding game terms or other players' privacy.
2. Connect VAD, speech synthesis, actual first PCM audible, Star's existing avatar animation playback, and OBS recording progress. Keep physical stop/flush capabilities and interruption checks independent of the LLM.
3. Record both monotonic per-stage timings and OBS rendered/encoded missed frames. Use a continuous 30-minute rehearsal (then 2 hours after reliability is established) before any live stream.
4. Evaluate **real** game outcome on holdout maps, conversational turn-taking (pauses, backchannels, interruptions), voice/face synchronization, misleading observations, recovery from mistakes and natural silent attention.
5. Abort or degrade gracefully when GPU VRAM, CPU pressure, frame pacing, audio backlog, or fresh telemetry violates measured limits; do not degrade the game to chase model tokens/sec.

The previous PR #992 passed its independent GitHub offline checks, but offline tests **do not** establish this milestone. Never claim a functioning live VTuber without recording-level evidence.

## Priority 1: Intelligence that improves game performance

Build a measured 3-level control system: (<100 ms where feasible) rule/skill fast actions based on trusted current scene, (<1 s) tactical planning using navigation and game state, and off-stream teacher analysis + retrieval. Only skill-bank outcomes that were independently observed, bound to the exact game/map and have not leaked from holdouts may update future policies. Practice should progress through simple movement/aim/inventory/interaction to map navigation, multiplayer teamwork, resource management and unfamiliar mechanics.

Use **paired baselines**: same holdout maps, comparable starting seeds, randomized order, matched latency/FPS and genuine score/reach-goal metrics. Separate game **playing** from game **creation**: coding quality needs Luau analyzer + executable Studio playtests, multi-client state and performance budgets. Official Roblox's [built-in Studio MCP](https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/mcp.md) can inspect scripts, edit code, execute Luau and control play mode. It is not game-skill evidence by itself. Use bounded sandbox experiments with rollback, no permission bypass, no autonomous public publishing.

## Priority 2: Real-time speech and believable on-screen behavior

- [Microsoft Proact-VL](https://proact-vl.github.io/) studies *when* a gaming companion should comment, not just what words to generate. Evaluate useful vs redundant commentary, silence appropriateness, interruptions, missed owner questions and hallucinated game achievements. Keep viewer messages untrusted.
- [NVIDIA PersonaPlex](https://research.nvidia.com/labs/adlr/personaplex/), published January 15, 2026, explores expressive **full-duplex** speech with role and voice conditioning, backchannels and interruptions. Its approximately 7B-parameter architecture is a research reference, **not** an 8-GB GPU deployment recommendation.
- [NVIDIA DyaPlex](https://research.nvidia.com/labs/amri/projects/DyaPlex/), NeurIPS 2026, researches causal synchronized speech/motion; compare with Star's current lightweight avatar rig instead of assuming a large new model can coexist with game rendering.
- [Kyutai's October 20, 2026 Pocket TTS mini-model release](https://kyutai.org/blog/2026-10-20-pocket-tts-small/) describes 18.2M, 6.9M and 1.9M parameter variants; 18.2M was reported to match prior model quality in its tests and run about 9.9× real time on one CPU thread. **These are Kyutai's benchmark conditions, not Star's measurements.** Compare Star voice quality, cadence and the **actual time to first audible sample**, CPU thread pressure, interruption stop time and audio/OBS lag on the owner PC.
- A persistent persona should be **consistent, not deceptive**. Ground jokes, opinions and stream memories in verified events, explicitly represent uncertainty, avoid fake claims of human consciousness, and transparently identify Star as an AI VTuber. Let her have continuity, habits, hobbies, initiative, favorite games and natural expressive movement.

## Priority 3: General knowledge, self-improvement and local infrastructure

Use permissioned retrieval with cited documents plus **confidence and expiration**. Route short factual questions to low-cost verified models, Luau debugging to tool-using coding paths, and ambiguous questions to extended analysis. Build a tested micro-benchmark suite with general factual QA, math, code edits, Roblox APIs, game control and conversation quality, including adversarial negatives and unseen problems. Prevent chain-of-thought or raw chat from entering durable personal memory without privacy filtering.

For better utilization on 8-GB cards, test dynamic CPU/GPU admission, KV-cache privacy/isolation, prompt-prefix reuse, quantization, draft decoding vs no drafting, and CPU-resident TTS. Benchmark **end-to-end workload** (game 1%-low FPS, OBS drop rate, p95 chat-to-first-audio, action deadlines, task accuracy), not just synthetic generation speed. Automatically roll back locally after failed verification. Keep GitHub as export/review infrastructure, not the required engine of Star's future internal development forge.

## Concrete experiment to run next

In a private authorized Windows rehearsal, preregister 50 matched, independently scored stream-commentary tasks and 50 matched game-observation tasks. Evaluate baseline and candidate with exactly the same prompt inputs and scoring, no model-generated grading, randomized order and real OBS/game contention. Record per-worker model/runtime/voice identity, end-to-end p95 latency, verified correctness count, total GPU peak and task-suite SHA256. Feed only validated aggregates into `QualityGatedRouteSelector`. If a candidate wins, treat the returned alias as a **manual pilot suggestion**, bind through the host catalog, run repeated live-load tests and revert if FPS, voice quality or game success declines. Never automatically promote based only on one suite.

**Status (2026-11-05):** implementable and offline-testable selection policy; not installed on the gaming host, not enabled for live inference, and not proof of a faster/smarter model.
