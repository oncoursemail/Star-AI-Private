# STAR: October 2026 inference regression watch, game-to-stream learning and acceptance protocol

**Date:** 2026-10-30. **Status:** researched, no deployment or hardware speed claim. **Owner intent:** local-first Star Core Forge; GitHub is an optional publication/review mirror, not Star's runtime database.

## Why this is different from adding another model or agent

STAR serves owner chat, speech, screen/game observations, generated Lua and longer-running game practice while competing for constrained compute and GPU memory. The dangerous optimization is one that raises a token/s benchmark but increases *actual first audible speech*, harms game FPS, drops OBS audio, or hallucinates game achievements. Existing `star.priority_proxy`, `star.stream_realtime_benchmark`, and `star.stream_realtime_quality_gate` provide a starting point for **paired, witnessed** measurements. This memo isolates *recently reported backend regressions* rather than repeating a generic speculative-decoding recommendation.

## Fresh primary-source failure cases to protect against

1. **2026-09-02, llama.cpp #28219 / canonical #28218:** on a reported Windows 11 RTX 5060 Ti system, enabling MTP/draft speculation under one MSVC CUDA build or providing explicit `-ts` made observed decode drop to ~2 tok/s; official Clang binaries were dramatically faster. This is *one reporter's reproduction*, not an RTX 4060 conclusion. Do not treat `n_gpu_layers` alone as a sufficient compatibility test. Source: https://github.com/ggml-org/llama.cpp/issues/28219
2. **2026-09-11, llama.cpp #28790:** another reported Windows MSVC+CUDA configuration showed an MTP-related ~57x prefill slowdown, absent from the author's official prebuilt binary. These are environment-specific reports and should be used to motivate **compiler/build identity** in performance manifests, not to ban all Windows compilation. Source: https://github.com/ggml-org/llama.cpp/issues/28790
3. **2026-10-16, llama.cpp #30695:** a Vulkan multi-device / large-context / speculative decoding report identified a ~3x decode regression, with acceptance rate unchanged. Restricting `GGML_VK_VISIBLE_DEVICES` to one compute device recovered performance in that environment. **Not applicable without validation** to STAR's NVIDIA CUDA configuration. Source: https://github.com/ggml-org/llama.cpp/issues/30695
4. **2026-10-09, llama.cpp #30204:** reported image requests failing when combining a multimodal projector with one draft-MTP configuration on Vulkan. STAR must test *image + speech + text* paths separately; a text-only speedup is not sufficient. Source: https://github.com/ggml-org/llama.cpp/issues/30204
5. **Official SPEED-Bench:** reports category-specific throughput, latency and draft acceptance for a running llama-server; it is not itself a test of OBS audio, gameplay FPS, task completion or visual-grounding accuracy. Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

All issue-based speedups/slowdowns belong to the authors' hardware and versions. Record the **exact SHA**, compiler, backend, driver, `--parallel`, context, prompt caching, KV cache quantization, GPU memory use and speculative flags before interpreting a STAR benchmark. A slowdown with identical draft acceptance suggests backend/scheduling overhead, not bad draft predictions.

## CPU/GPU resource strategy for a single 8-GiB gaming GPU

- Reserve a measured, game-specific GPU margin for the actual game and OBS. The existing quality gate's 6656 MiB default is an *illustrative candidate budget*, not safe proof that a game will fit. Detect actual peak usage and fail closed on over-budget.
- Keep deterministic movement, aiming inputs (in authorized/private tests), game-state polling, UI interaction and OBS capture isolated from expensive language-model requests. A missed 16.7-ms frame cannot be repaired by an excellent answer generated later.
- Preserve P0 speech/owner urgency over P3 night-school throughput, while keeping background practice checkpointable with bounded TTLs. Report p50/p95 *audio delivered to OBS*, 1%-low frame-rate proxy, A/V offset, and missed-event rate.
- Compare **no speculation** against **speculation** using matched prompts and scene loads; on Windows compare reviewed official CUDA build versus locally built binary if a compiler regression appears. Do not change drivers, engine builds or model quantization between members of a pair.
- Text, image understanding, coding, gameplay-commentary and long general-research tasks have different context lengths and entropy. Never infer one universal best configuration from a single throughput number.
- Star Core Forge should retain immutable local benchmark manifests and roll back automatically at the *offline experimental* level when correctness, OBS capture, or FPS regresses; no automatic change to the live stream is authorized.

## Reproducible, staged acceptance matrix

**Stage A — no game or OBS.** Fixed seeds, same prompts, cache state and model files. Record first token, first *speakable phrase*, total time, tokens/s, accepted/drafted ratio, RAM/VRAM, thermal/CPU pressure, timeouts, and crashes. Use at least three warm repeats per configuration. Check answer correctness on code, math, general-knowledge with source retrieval, and refusals under adversarial prompt injection. Reject a change that boosts tokens/s while breaking known holdouts.

**Stage B — approved private local game.** For each tested scene/version, preregister 20+ paired A/B observations with randomized order; ensure 120+ actual present-frame timings each. Test three *separate* strata rather than pooling them: (1) fast obby/platformer motor control, (2) puzzle/quest reasoning and mechanics discovery, (3) Roblox Studio building/playtesting, including a multiplayer join/leave case. Roblox's StudioTestService can automate multiplayer tests while built-in Studio MCP can support controlled editing and playtests: https://create.roblox.com/docs/reference/engine/classes/StudioTestService/AddPlayers

**Stage C — local OBS rehearsal.** Event -> visual observation -> inference -> speech plan -> voice synthesizer -> device output -> OBS recording -> avatar motion. Two independent witnesses: (a) observed game-state event or objective completion, not only model prose, and (b) audible/non-muted recorded output with A/V timestamps. Feed **only aggregate attestations** into `stream_realtime_quality_gate`; keep recordings and raw viewer IDs out of GitHub and shared memory.

**Stage D — generalization and humanlike streaming.** Have STAR practice unfamiliar levels, then measure first-attempt performance on held-out levels. Compare pre-practice to post-practice success rates, interventions, false claims, collision/prop defects in generated games, and transfer of mechanics to a different game. For a more natural stream, assess whether Star:
- stays quiet during high-focus gameplay, then recalls and answers deferred verified viewer questions;
- reacts to *observed* wins/losses, not invented accomplishments;
- times laughter, hesitations and eyebrow/eye/head movement with audible speech and actual events;
- manages interruptions without piling up delayed sound. LiveKit's documented interruption options distinguish adaptive speech barge-in, VAD, cooldown and false interruptions; do not assume a model alone solves conversational turn-taking: https://docs.livekit.io/reference/agents/turn-handling-options/

**Stage E — independent human review.** Blind-listen to randomized A/B 30–90-second clips for natural timing, voice prosody, character consistency, purposeful silence, humor, and social appropriateness; explicitly disclose that STAR is AI. Review includes **negative examples** (silent failed OBS tracks, false wins, interrupted speech, overexcited reactions) so that no pleasing but wrong result can qualify.

## Cross-task intelligence loop (offline-only proposal)

1. **Observe**: screenshots, structured Studio state, completion checks; minimize full-frame vision by scene-change detection and region-of-interest extraction.
2. **Hypothesize**: mechanics with confidence, expected outcomes, and clear falsifiers.
3. **Act and rehearse**: plan short private experiments; separate millisecond control from slower tactical/strategic reasoning.
4. **Verify**: exact engine evidence, timer, win state, tester verdict; label inconclusive experiments instead of silently turning them into successes.
5. **Compress experience**: preserve citations, game/build version, action sequence, failures, confidence and privacy-safe outcome. General facts require source/date/expiry; successful execution cannot validate unrelated facts.
6. **Transfer**: test acquired skills on an unseen level or game, store failures alongside successes, and compare against baseline.
7. **Self-improve safely**: Star Core Forge can propose candidate code, run offline tests, rank scorecards, maintain snapshots and roll back. Durable core changes require explicit quality gates; no autonomous public account actions or live deployment.

## Immediate implementation and review order

- **P0, currently addressed in the paired quality gate branch:** make the full offline CI green. An observed test failure in `test_solo_p0_pauses_every_background_stream` concerned the JSONL audit row appearing after the HTTP client had already consumed its final response. The corrected test must await *both* completed P3 audit rows instead of sampling the file once; it still requires two pauses, correct resumed slot identities and unbroken answers. This is a test synchronization repair; no inference speed increase is claimed.
- **P1:** run the actual benchmark + quality gate test suite on the real repository dependencies. Reject stub-only evidence as insufficient for merge.
- **P2:** connect independent host-attested OBS/game outcomes to the quality gate in a deliberately opt-in local rehearsal harness. Preserve existing pause/mute/stop controls.
- **P3:** sample a **small**, fixed matrix of current CUDA configurations against the same model/quant/seed before exploring new draft architectures; record regressions by build ID.
- **P4:** implement a held-out practice curriculum using StudioTestService and the existing game mechanic/probe lab. Star should improve measured game task success, not only report more notes.

## Safety, privacy and honest limitations

The GitHub repository called `Star-AI-Private` is publicly visible; do not store viewer information, audio, proprietary game screenshots, credentials or local PC information here. All listed experiments are **proposals** unless explicitly tied to tested code or a verifiable CI result. The current test synchronization fix does not increase inference speed or intelligence. AI-like human voice, expressive behavior and a persistent self-model are engineering targets, not evidence of literal human consciousness. No game input, streaming, spending or account action is enabled by this memo.
