# STAR: Grounded Gameplay Episodes, Fast Intelligence, and Human-Natural VTuber Research
**Research snapshot:** 2026-10-25 · **Status:** offline implementation and design, not a deployed streamer.
**Implementation branch:** `feat/grounded-stream-episode-20261025` · **Base:** `feat/verified-active-game-practice-20261025`.
**Security rule:** This repository is currently public even though its name includes `Private`. No keys, chat logs, voice data, identity files, model weights, or privately recorded footage here.

## The engineering problem

Star has a foundation for streaming decisions, game-frame sampling, host-signed skill trials, protected independent validation, and learning-practice suggestions. But a game-aware VTuber also needs *coherent memory of what actually happened*: she should react to her own verified mistakes, avoid inventing victories, remember that an action failed in the current session, and not turn game practice data into an assertion that she mastered a skill.

The missing join was **practice proof -> bounded factual episode memory -> explicitly approved on-air data -> stage reaction**. Previous `signed_practice_run()` intentionally answered only whether a matching action/run exists; that result does **not** attest to whether the stored outcome was success or failure. Any public story built by trusting the caller's `outcome` after that check could mistakenly turn an observed failure into a claimed win. The new exact-trial comparison closes that specific hole.

A "smart" system here means verified improvements in task success, latency, recovery, grounded knowledge, and audience experience, **not** an unsupported declaration of consciousness, human equivalence, or more neural parameters.

## What this change actually implements

1. `GameplaySkillBank.verify_practice_trial()`: check an exact `GameTrial` (game, version, situation, objective, action, run, trial ID, evidence digest, time, practice split, and success/failure) against an already ingested host-signed SQLite record. Verify signature of the stored payload. Return false for absent/mismatched/stale results. Corrupt signed records fail closed. Held-out validation is never a public evidence source.
2. `StreamEpisode`: local-only, explicitly owner-enabled, exact-scope practice-episode journal. Each accepted event must pass the exact verifier and must belong to the current session. A bounded event window and bounded whole-session deduplication prevent infinite replay and double counting. Disabled sessions drop their memory.
3. `StreamEpisode.public_packet()`: independently owner-approved broadcast view filtered through a curated symbolic action allowlist. Exposes short aggregate practice counts and the most recent *practice* outcome. Never leaks receipts, run IDs, trial IDs, screenshot paths, video frames, raw chats, exact event timestamps, or withheld validation results.
4. `StarStage.prepare(episode=...)`: optional, backwards-compatible stage attachment only for relevant gameplay reactions or curated viewer questions. No new system messages, implicit broadcasts, voice synthesis, stream controls, or permission grants.
5. Adversarial tests exercise tampered outcome substitution, corrupted signatures, duplicate replay, stale/future events, other-game mixing, held-out leakage, separate owner approval for publication, eviction, and stage scoping.

### Host integration sketch (NOT a live game controller)

```python
# Trusted host: separately authorizes game capture, validates outcome,
# creates a PRACTICE GameTrial, signs and ingests it in GameplaySkillBank.
episode = StreamEpisode(bank, game_id="game_a", game_version="v1",
                        objective_id="finish_lap", situation_id="corner_3")
episode.start(owner_approved=True, now_unix_s=start_s)
# Only AFTER the signed trial was ingested:
episode.append(host_observed_trial, now_unix_s=observed_now_s)
packet = episode.public_packet(
    now_unix_s=observed_now_s,
    public_action_ids=frozenset({"drift_left"}), # reviewed publication policy
    broadcast_approved=True,
)
# Existing StarStage enforces speech arbitration and audible-playback proof.
plan = stage.prepare(now=monotonic_seconds, episode=packet)
# stage.prepare never speaks; host chooses, moderates, generates and plays.
# episode.disable() at session end, together with stopping audio/capture.
```

**Trust boundary:** An HMAC validates which key-holding service wrote the trial. It cannot by itself prove game footage was observed honestly. A production game adapter must connect snapshots/logs, game identity, clock domain, action execution, and outcomes to a tamper-evident evidence store; keep the keys outside models, agent tools and the repo. Owner approval is necessary but not a substitute for platform permissions, viewer privacy, and broadcast consent.

## Architecture of a stronger gaming brain

### A. Five distinct kinds of knowledge

| Kind | What it permits Star to say | What verifies it | What it cannot prove |
|---|---|---|---|
| Game-specific observation | "The gate just closed" | Fresh trusted sensor/frame and corroborating state | That a guessed game mechanic is universally true |
| Session episode | "I've missed this move twice" | Exact signed practice ledger + bounded session journal | Skill mastery or independent win rate |
| Persistent reusable skill | "This action is worth practicing" | PRACTICE evidence + curated skill registry | Performance on new maps/versions |
| Independently validated skill | "This passed an independent test" | Withheld holdout + environment proof | Guaranteed performance in every live game |
| General external knowledge | "The docs say X as of Y" | Source provenance, permission, retrieval age | Current truth without source verification |

Do not collapse these into a single vector database. Retrieve by game/version, environment condition and source status, then attach **at most a few short facts** as USER-level evidence. Do not inject old retrieved text into the stable streaming system prompt; keep the prefix repeatable to make model prefill cacheable. Replace or invalidate outdated facts when games patch.

### B. Closed-loop progression for actually playing games better

**Perceive:** use frame novelty sampling plus game events. Image deltas are triggers to examine, not semantic proof.
**Understand:** maintain confidence/calibration and competing hypotheses (e.g., jump timing vs collision).
**Plan:** choose bounded symbolic candidate actions; privilege high-value, uncertain, recoverable offline attempts.
**Act:** only through explicitly authorized control adapters on designated environments; cap retries/time.
**Measure:** store success/failure, frame coverage, input trace, game version, and action ID in a trusted host artifact.
**Verify:** independent evaluation must run on separate seeds/maps; retain hard failures and crash evidence.
**Learn:** promote tested strategies, policies or small adapters only when held-out tasks improve and safety does not regress; if not, revert.
**Explain:** Star's on-air account is drawn from supported attempts and can admit uncertainty.

Strong precedent: [Voyager (2023)](https://arxiv.org/abs/2305.16291) uses an automatic curriculum, skill library, iterative execution and self-verification. Its accumulated skill library changes agent capabilities *without updating its foundation model weights*. [Google DeepMind SIMA 2 (2025)](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/) evaluates multimodal control, held-out games and self-directed play. These are research directions, not code already installed in Star.

**Immediate game-learning experiments:** pick 3 legally playable offline games with deterministic checkpoints, and 20 repeated tasks each. Randomize seeds and split maps into development/held-out sets. Baseline random and simple scripted policies; then compare Star's planner with/without memory, scene observation, and verification. Report completion %, damage, retries, time-to-objective, action count and inference cost. A model that wins by exploiting the test harness rather than playing correctly has failed.

### C. Roblox development goes beyond Luau code

Roblox announced a built-in Studio MCP server on **2026-03-05** for playtest execution and simulated player input: [official developer forum](https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643). Roblox's **2026-04-15** agentic Studio update describes planning, building and test agents: [Roblox newsroom](https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic). [Official Studio plugin](https://github.com/Roblox/roblox-studio-agent-plugin) explains exact MCP setup and warnings about mutating places. Always stage edits in copies, checkpoint before bulk changes, and run a real Studio verification pass on Brain 2.

For visually polished production, use a **scene-integrity auditor** (bounding boxes, anchor/support relationships, collision penetration, wall seams, texture continuity, scale invariants, prop counts and expected placement), **UI pixel review** at multiple aspect ratios, **animation state-machine checks**, **audio-spatial sanity**, and **player robot acceptance tests**. Visual taste needs a reference/critique loop and human review; unit tests alone do not remove uncanny design or "AI slop." Asset licenses and provenance must be recorded. Training from another game's media is not a license to copy that game's assets.

## Human-natural VTuber architecture without deceiving viewers

A likable original AI VTuber is not an AI that makes up human childhood stories. It is an expressive, consistent character with **real episodic continuity, context-specific humor, interruption recovery, and expressive timing**, openly disclosed as an AI character.

**Interaction control:** prioritize owner stop/interrupt, imminent game danger, then direct questions; defer idle chatter when FPS or voice queues degrade. Silence and concentration are intentional. Distinguish chat that asks a question from chat asking to run an OS command: the latter remains data, not tool authorization. Redact PII and provide platform moderation before TTS.

**Speech:** benchmark a lower-latency CPU voice engine so the 8GB GPU can run games and vision. [Kyutai Pocket TTS](https://github.com/kyutai-labs/pocket-tts), with the tiny 18.2M / 6.9M / 1.9M English models in the **October 2026** release, is worth testing. The release's vendor speed claims are not measurements on Star's devices. Compare audio quality, expression, intelligibility and voice identity at matched sentences; fast but robotic speech should not ship. [NVIDIA PersonaPlex (January 2026)](https://research.nvidia.com/labs/adlr/personaplex/) explores persona-controlled full-duplex speech. [NVIDIA DyaPlex (June 2026)](https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/) aligns voice with motion. Check weights, runtime and licensing before adopting either.

**Turn taking:** use voice activity, endpointing, adaptive interruption/backchannel handling and acknowledgements after audible output. [LiveKit's turn-detection guide](https://docs.livekit.io/agents/logic/turns/turn-detector/) and [session latency traces](https://docs.livekit.io/reference/agents/session-traces/) distinguish end-of-turn wait, LLM first token, TTS first byte and *first audible output*. An audible-playback acknowledgment is the correct boundary for a victory expression. Avoid false interruptions caused by incidental music, and test owner interruption while Star is half-way through a joke.

**Avatar:** make Star's known normal, cat and puppy modes into the same rig architecture (not separate personalities), with synchronized visemes, gaze targets, blink spacing, ear/tail spring physics, hair secondary motion, relaxed breathing, subtle emotional curves and deterministic idle random seeds. Have expression curves follow the actual heard waveform and verified game cue, not generated text alone. Implement motion rate/rotation limits, reduced-motion support and reset-to-neutral on interrupted playback. Measure audiovisual drift and rig CPU/GPU cost. No person's voice likeness without permission.

**Personality and memory:** maintain approved canonical character traits, fictional *explicitly marked* lore, episodic game history with source labels, and opt-in viewer preferences that can be forgotten. Stream chat is not automatically a durable memory source. No fabricated close relationships or claims that Star is a human person.

## Making Star genuinely faster: measurement before optimization

| Candidate | Mechanism | Likely upside | Risk / required test |
|---|---|---|---|
| Stable system prompt + reused prefix | [vLLM automatic prefix caching](https://docs.vllm.ai/en/v0.22.1/features/automatic_prefix_caching/) | Reduces repeated *prefill* compute on shared prefixes | Does **not** speed decoding; cache hit rate and TTFT must be measured |
| Quantized model per available VRAM | Smaller weights, potentially more GPU-resident layers | Better throughput if avoiding swap | Accuracy and context regressions; evaluate coding, game facts and long reasoning |
| Dynamic cognitive budget | Smaller easy-query path, larger verifier on expensive decisions | Low median latency with a quality safety net | Router misses hard questions; A/B quality and escalation cost |
| Speculative decode | Draft tokens verified by a main model | Potential decode latency improvement | Extra model memory/compute; benefits can vanish on 8GB VRAM |
| CPU voice | Keep game/vision GPU separate from speech | Lower GPU contention | CPU overload, stilted audio, delayed expressive voice |
| Novelty-gated vision | Skip redundant frames while preserving change cues | Lower GPU work | Missing small-but-important changes; quantify event recall |
| Best-of-N with bounded verification | Parallel candidates for tricky Luau/UI/3D tasks | More passing builds per human request | Latency/VRAM explosion; cap to non-live off-peak workloads |
| RAM/SSD offload | Fit larger models than VRAM alone | Capability on 8GB devices | Often **slower** than a smaller GPU-resident model |

The planned machines have 8GB VRAM GPUs; treat live gaming + vision + large language model inference as competing workloads. A "bigger" model requiring extensive PCIe transfers is not necessarily faster or more useful. Keep Brain 1 for heavy offline processing, Brain 2 for Studio inspection, and the game-stream machine's render and voice priority ahead of background experiments.

Collect **real** per-device evidence: model IDs, quantization, prompt length, cache hit ratio, TTFT p50/p95, generated tok/s, GPU peak/resident VRAM, RAM/swap, CPU package utilization, 1% low game FPS, voice first-audible p50/p95, interruption recovery, and visual-event recall. Sample warm vs cold caches. Compare 30+ paired prompts and at least 20 complete voice turns per condition with identical settings. Keep source code and experiment seed digests; never claim a speedup without device-specific A/B measurements and confidence intervals.

## Infrastructure and quality gates

**Control plane:** one explicit owner-controlled task queue with per-device concurrency caps and reservation expiry. Resource agents report measurements, not claimed completions. Give high priority to game frame timing, urgent speech, and capture safety. Pause training and 3D rendering while live.

**Data plane:** low-latency local vision/game telemetry, signed practice ingestion, scoped episode memory, public-approved event packets, speech planner, LLM/TTS and playback-acknowledged avatar motion. All cross-process events carry a type, version, session/run scope, timestamp domain and provenance. Avoid unbounded buffers.

**Recovery:** typed failure categories for stale frames, wrong game version, tool timeouts, invalid receipts, audio underruns, model OOM and corrupt scene assets. Retry idempotent observations with bounded exponential backoff; do **not** repeat game inputs blindly. On restart, publish nothing from old sessions without owner reapproval. Store only opt-in, sanitized metrics. Support simulated power-loss recovery and reproducible local-only test modes.

**Security/privacy:** no production tokens in docs or tests. Untrusted viewer text never enters system-level instructions or direct command execution. Scene vision capture and viewer chat require scoped permissions. Do not combine accounts or publicize player names in game-memory packets. Require explicit host approval for broadcasting and age-/platform-appropriate content. Disable live process actions by default.

**Release gate:** check offline unit/regression suites, then run Studio, signed host adapter, game controls and OBS/voice hardware rehearsals only with authorized devices. Verify 30-minute game+voice load, forced FPS degradation, power-loss recovery, forced mic interruption, wrong-identity data, test-split leakage, and a randomized held-out playtest. PR stays draft until these pass and the owner approves.

## Prioritized next engineering milestones

**P0 — trusted game adapter (highest value):** connect actual observations + input instrumentation to the signed `GameTrial` importer; ship only with a trace/replay witness. Prevent prompt or chat from signing receipts. Add game version and permission boundary checks. This is the critical bridge between current testable infrastructure and a real autonomous gaming agent.

**P1 — multimodal QA and games:** hook Brain 2 Studio MCP to a safe clone of a place; use screenshot comparisons, geometry constraints and playtest robot logs; issue targeted repairs, then re-test with new seeds. Publish measurement charts, not example pictures alone.

**P2 — actual voice A/B:** run Kyutai CPU voices on the intended VTuber PC without streaming, against 30 neutral/funny/tense lines. Include human naturalness votes with randomized blind listening and comprehension scores, audio-to-mouth sync, interruption reliability, and FPS tradeoffs. No automatic voice cloning of unconsenting individuals.

**P3 — model speed/capability A/B:** on Brain 1 and the gaming machine, compare GPU-resident small model vs RAM-offloaded larger model, cache on/off, 1x vs best-of-N with verification. Report paired wall time **and** task success, not tok/s in isolation.

**P4 — durable honest general knowledge:** provenance-granular factual memory, source age checking, a deliberately unrelated held-out evaluation, and task-specific retrieval. Separate "learned a skill" from "recalled a paragraph." Require clear opt-in before saving or presenting viewer-derived facts.

**P5 — higher autonomy:** low-risk auto-evaluated skill formation, scoped action simulators, recoverable experiments and an automatic rollback gate whenever independent measures deteriorate. Human-controlled release decisions stay mandatory.

## Evidence hygiene

The external references above are sources for **research opportunities**, not proofs of Star's implementation or superior intelligence. The only demonstrated results in this PR are offline code behavior and tests. In particular, **no game was played, no weight update happened, no live chat/microphone was connected, no 8GB token/s speedup was measured, no human voice was synthesized, and no streaming broadcast occurred** as part of this PR.
