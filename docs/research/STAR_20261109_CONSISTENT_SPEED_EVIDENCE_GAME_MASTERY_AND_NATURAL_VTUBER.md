# STAR AI — consistent speed evidence, real-time game mastery, and natural VTuber behavior

**Reviewed:** 2026-11-09. **Status:** draft engineering research + offline benchmark-gate patch, not deployment or measured model acceleration. **Applies to:** Star (and successor Litha where code is intentionally migrated). This document distinguishes implementation, reproducible simulation, and proposed experiments.

## 1. Concrete defect fixed this run: a speed study could be statistically positive but inconsistent

After PR #1091 added replay detection to `star/inference_stream_paired_gate.py`, the paired recommendation still relied on a bootstrap interval for the **mean** latency gain plus aggregate p95 checks. A large gain on most sessions can conceal a slower result on a different baseline: with five paired first-speakable gains of +100 ms and one of -10 ms, the deterministic bootstrap 95% lower limit is **+45 ms**, and aggregate candidate p95 improves. Under the original criteria this cohort could qualify for a private pilot, although the direction of effect is not convincingly consistent across six trials.

**Patch:** compute an exact one-sided sign test on the complete paired first-speakable gains. Ignore exact ties as non-directional, count improvements, and require `p <= 0.05` **in addition** to the existing minimum-pair, no-failure, per-trial regression, replay and bootstrap checks for `eligible_for_private_pilot`. Regressions still take precedence over significance; insufficient evidence remains `inconclusive`.

- Five improvements out of six non-tied trials: `P[Binomial(6, 0.5) >= 5] = 7/64 = 0.109375` -> **inconclusive**.
- Six improvements out of six: `P = 1/64 = 0.015625` -> may qualify **if every other gate passes**.
- Seven improvements out of eight: `P = 9/256 = 0.03515625` -> may qualify with sufficient paired gain and all other checks.
- All ties: exact one-sided p=1 -> **inconclusive**.

New diagnostics are `improved_speakable_pairs`, `non_tied_speakable_pairs`, and `paired_sign_test_p`. The offline tests include both rejection and acceptance examples. **This is a conservative consistency screen, not a guarantee of independence, causality, audio quality, gameplay success, or speed gains.** The existing bootstrap and sign tests have different assumptions and should be supplemented by randomized AB/BA sessions on actual hardware. A reproducible simulated measurement is not an independent hardware trial.

## 2. Why faster token generation alone is not enough

STAR has an 8 GB GPU budget while playing games and using OBS, an avatar, speech, and optional visual models. Approving a model config based on a single median token/s can make the *whole session worse*. Track, separately:

1. End-to-end first **audible** answer latency and p95 speech inter-turn silence; distinguish text streaming from native device output.
2. Game frame-time p95/p99, GPU memory saturation, OBS dropped/late frames, audio dropouts, and interruption leakage.
3. Coding/game reasoning correctness on frozen tasks, long-context retrieval accuracy, actual new-game wins and missed action deadlines.
4. Exact binary, GGUF, quantization, context/KV, slot state and host/driver hashes. Counterbalance experiment order and use fresh prompts so warmed caches do not masquerade as general throughput.
5. Paired continuous gameplay *while streaming*; reject any candidate that measurably degrades live-play deadlines, speech reliability or basic correctness even if it is faster in isolation.

Research to benchmark rather than blindly integrate:
- llama.cpp speculative decoding includes draft-model and n-gram cache approaches; extra draft-model VRAM may be counterproductive with games resident. Source: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- Kyutai Pocket TTS has CPU-first streaming and compact October 2026 English checkpoints; assess real first-audible latency, quality, CPU contention, and voice identity, not project-page claims as hardware results. Source: https://github.com/kyutai-labs/pocket-tts

**Proposed private experiment:** pin one unchanged quantized model, compare baseline against one speculative configuration with randomized AB/BA pairs, separate warm and cold strata, collect independent physical audio and OBS/frames, and use the paired gate as just one screening step. Never activate automatically.

## 3. A general-game agent requires two independent clocks

The paper *Gym-Anything-RT: Scaling Real-Time Environments for Vision-Language Agents*, released **2026-10-27**, runs equivalent minigames live, slowed and paused. It demonstrates a large gap between possessing a reasonable action plan and executing the action before the game state changes. Source: https://arxiv.org/abs/2610.37567

**For Star:** make the fast game action loop host-authorized and deadline-bound, with timestamped observations, verified input acknowledgements, and `UNKNOWN` state after staleness. Place longer VLM reasoning, exploration planning, and descriptive narration outside the critical path. Never infer wins/kills from model text alone.

**Practice curriculum:** (a) one-mechanic perception and uncertainty drills; (b) timed jump/dodge tasks with miss-rate measurements; (c) short tactical plans with explicit failure/replan triggers; (d) recovery, navigation and resource-use tasks; (e) untouched maps, camera angles, input latency and frame-rate perturbations. Preserve skills only with independent evaluation on held-out seeds and measured transfer; do not claim that a policy-memory update is a neural weight improvement.

**Real-engine gate:** move from synthetic test environments to authorized, local game instances and Roblox Studio test sessions. Roblox's **2026-03-05** Studio MCP announcement describes starting/stopping playtests and simulating player input; the **2026-04-15** Roblox announcement describes planning/building/testing as an agentic loop. Sources:
- https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic

Integrate the actual DataModel, Luau static checks, two-player replication, screenshot/recording reviews, test teleports if supported, and real HUD/mobile interaction checks. Use an independent verifier and keep automatic publish/commerce permission separate from autonomous local tests.

## 4. A more natural AI VTuber is selective, not continuously verbose

Microsoft Research's *Proact-VL* (ICML 2026) treats **when to respond, how much to say, and real-time video understanding** as connected problems in live gaming commentary. Source: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/

**Suggested integrated feature sequence, pending implementation:**
- A minimal perceptual event stream of **verified** wins, damage, danger, interaction, game phase, owner speech and viewer questions, with scene/session epoch and TTL.
- A speaking policy that can choose **silence**, brief contextual observation, answer, or owner interruption. Keep optional commentary behind the resource governor. Deduplicate only after actual audible output is confirmed.
- Separate textual content from prosody metadata (pause, emphasis, laughter context and energy). Drive lip sync from PCM and timed phoneme/viseme estimates, not arbitrary animation loops.
- Use a *per-session story memory* grounded in logged events; only consent-scoped non-sensitive details may persist between streams. Keep chat text outside the executable tool instruction channel.
- Rehearse for 60–90 minutes **offline, OBS local recording only**. Audit turn-taking, hallucinated events, repetition rate, voice drift, lip sync, owner interruption response, game FPS and dropped frames, and ask for blinded human naturalness judgments.

**Important limit:** human-like responsiveness and self-directed interests are engineering/creative goals. Star should identify herself as an AI, should not invent human memories or private relationships, and should not auto-stream or control third-party competitive games without approved access and compliance with rules.

## 5. Prioritized engineering follow-through

**P0 — native ground truth:** attach a Windows host recorder for independently observed worker exits, physical PCM timestamps, game observation/action acknowledgements, and OBS/game telemetry. Host receipts should bind monotonic clock, session UUID, scene epoch and relevant build hashes. Do not fake these with model-generated JSON.

**P1 — controlled quality + speed study:** execute six or more genuinely independent randomized paired cold/warm tests with voice+game load; require replay check, exact directional consistency, quality/correctness gates and no extra frame loss. Publish results and negative outcomes; never select runs after seeing the score.

**P2 — live game-skill proof:** integrate authorized input in a sandbox, measure advancing-clock success against paused control, add held-out levels and rollback to a baseline policy after degradation.

**P3 — authentic VTuber rehearsal:** coordinate audio, interruption, verified game events and avatar with owner-approved private recordings. Build an event-grounded naturalness scorecard and update the persona only after the experience is validated.

**Not established by this patch:** neural weight training, inference speedup, automatic game mastery, working physical audio capture, broadcast quality, OBS integration, or Star becoming biologically human. The only code change is an offline speed-study confidence gate.
