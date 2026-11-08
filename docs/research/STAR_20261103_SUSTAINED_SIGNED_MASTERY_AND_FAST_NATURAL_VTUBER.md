# STAR AI — Sustained Game Skill, Faster Local Intelligence and Natural VTuber Roadmap
**Research and engineering checkpoint:** 2026-11-03. **Branch:** `feat/star-sustained-game-mastery-20261103-auto42`.
**Status:** implemented offline signed-evidence correctness improvement; other items are measured experiments or design proposals.

## 1. Concrete problem found and fixed
Star's curriculum previously required a fresh, signed latest success after a failure, but **one fortunate retry** could immediately unlock the harder level again because 20 earlier wins kept the Wilson score high. That is not convincing evidence of recovered skill.

**Implementation:** The trusted `GameplaySkillBank.practice_evidence` now computes a bounded *trailing practice-success streak in distinct observed Unix seconds*. Three consecutive nonambiguous signed success buckets are the default prerequisite for `GameLearningLadder` mastery, in addition to its current seven-day window, minimum sample size and Wilson lower bound. A failure clears the streak; a failure sharing a timestamp with a success wins the tie; multiple successful attempts in the same second contribute only one recovery bucket. Earlier victories still contribute to honest aggregate statistics, but not to the *recovery* proof. No validation/holdout observations, signing keys or private evidence leave the bank.

**Boundary:** This only improves the quality of a practice-only recommendation. It is not game-controller authority, a measured intelligence increase, a real win-rate increase or authorization to stream. A signed event authenticates the host's statement, not the truth of the game world; independent game instrumentation must remain in charge.

**Additional CI repair:** GitHub Actions on upstream draft #946 reported a Pyright basic type narrowing regression in `game_capture_to_action_benchmark._number` (converting an `object` to `float`). This branch narrows the numeric type explicitly before conversion, without changing runtime validation or benchmark semantics.

**Required follow-up evaluation:** Sign and replay test histories covering 20 wins -> failure -> one/two/three successes, duplicate captures, ambiguous same-second outcomes, old evidence, signature corruption and cross-game isolation. Also measure false-stall rate for games with >1 legitimate attempt per second; if excessive, use independently authenticated subsecond engine sequence IDs rather than weakening the evidence policy.

## 2. Architecture: faster actions, deeper learning, persistent verified skills
The performance objective is not to maximize raw tokens per second. Star must maximize **verified success before a game-state deadline** while preserving OBS frame pacing, TTS audibility and input release. Keep three lanes:
1. **Live reactive lane:** a small fast model or verified symbolic controller for a small allowlisted set of game actions. Fresh perception, confidence, deadline check, scope check and output verification are mandatory. Skip late actions; never run an unbounded chain of model requests while a game advances.
2. **Tactical lane:** short-horizon planning for navigation, combat positioning, dialogue, puzzle reasoning and build/edit decisions when a measured pause or state allows it. Recheck world state after every plan; do not assume previously observed frames are current.
3. **Offline teacher lane:** independent expensive analysis of genuine failures, proposing alternative strategies and reusable skill contracts. Use sandboxed rollouts and paired tests. Never start this lane merely because a livestream's GPU looks idle; the stream load governor and owner opt-in both remain binding.

**Verified skill artifact design:** versioned game ID, engine/Studio version, preconditions, environment/seed class, input constraints, expected visible effect, last positive evidence and failure counter. Separate practice history from pre-sealed holdout cases. Never promote a skill solely on self-generated narration. Voyager's automatic curriculum, skill library and iterative execution feedback are useful inspiration; AutoSkill further argues for explicit reusable skills rather than expecting parameter updates for every experience.

For **general knowledge**, maintain source/provenance/last-checked metadata for retrieved material; prefer retrieval from approved references before inference. Skills and factual memories need expiration and contradiction handling. Keep public general information separate from private game accounts, chat logs and signing material. Do not present unverified player details as fact.

## 3. 8 GB GPU: benchmark matrix instead of model hype
The tested Windows Main host has an RTX 3060 Ti with 8,192 MiB total; in this inspection OBS, Roblox Studio and local `llama-server` were not active, so no real gaming+streaming latency comparison was possible.

A practical benchmark matrix should keep constant prompt, context, model quality threshold, OBS scene, game route and episode seeds. Compare small quantized reactive models, CPU/GPU layer splits, response-length caps, prompt-prefix locality, slot count and prefill under concurrent OBS/voice load. Collect p50/p95/p99 **capture-to-action** time, true OS-input acknowledgment, accepted world-frame advancement, task success, game frame p99, OBS render/encode/network losses, VRAM headroom, CPU load, first audible PCM and memory-policy errors.

Use the upstream llama.cpp SPEED-Bench for server timing and speculative-draft acceptance. Never automatically assume speculation helps: it costs draft compute and has varying acceptance by workload. The September 2026 llama.cpp discussion clarifies that prompt-cache reuse should be examined through `cache_n` and `prompt_n`, not inferred from a "cache enabled" checkbox. Recent upstream reports document **cross-conversation prompt-cache contamination** (issue #27148, August 2026) and **idle-slot caching stalls** (issue #30252, October 2026). Those are issue reports, not a claim about Star's exact installed build. Before enabling multi-slot caching, run concurrent isolation and tail-latency tests on the *exact binary* with cache features separately switchable and default off until passing.

**Desired promotion rule:** no optional latency optimization is accepted unless quality is unchanged, matched success/deadline misses do not regress, p95/p99 end-to-end latency improves, OBS drops do not increase, and cached contexts cannot leak across sessions. Record actual before/after numbers and binary SHA.

## 4. Real game-playing curriculum
Begin in owner-controlled, automation-permitting environments with authoritative telemetry. Each game episode needs: game/version/seed identity, initial frame hash, continuous engine tick count, legal action roster, independently observed transition, outcome scorer, signed receipt and synchronized monotonic timestamps.

Build adaptive difficulty in stages: simple locomotion -> basic hazard response -> movement under camera changes -> timed jump/aiming -> multiple objectives -> other maps -> other games. Keep a genuine holdout unseen by the planner. Cross-game transfer must be judged with balanced per-game results, not many seeds of one easy game. Preserve fallback and emergency key-release validation on the host.

Roblox creation should follow **inspect -> plan -> make isolated code changes -> static Luau checks -> Studio playtests -> multiplayer StudioTestService -> record video/screenshots -> inspect regressions -> accept/rollback**. Gameplay code correctness does not imply visual/animation quality. GameDevBench's multimodal tasks show why visual evidence and graphics-specific checks must be part of the loop.

## 5. Natural AI VTuber: character fidelity without fabricating experiences
Star should be compelling through *behavior*, not pretending to be a human person. Her on-air character may have recognizable hobbies, preferences, expressive sounds and continuity, while honestly identifying as AI when relevant.

A conversation director must control **when not to speak** as carefully as what to say: stay quiet in critical gameplay, never interrupt a speaking viewer just to fill silence, treat background noise separately from real barge-ins, avoid repeating identical success lines, and time each comment to an authenticated recent game event. The Proact-VL paper studies commentary, co-commentary and guidance under real-time requirements; use it as a timing/turn decision reference, not proof that any proposed policy is human-equivalent.

The expression stack should be `verified game event -> short grounded intent -> speech style/prosody -> first audible PCM -> visemes/eye/ear/hair/tail motion -> confirmed playback complete`. A subtle idle rig, natural delayed gaze, correctly timed blinks and sentence-length variation help more than nonstop random animation. Respect the user's existing mascot proportions, palette, motion toggle and reduced-motion choice. No model-written event may claim a match win without the independently verified victory signal.

**Voice comparison:** benchmark Kyutai Pocket TTS v4.0.1 (released 2026-10-21), particularly its CPU-oriented 18.2M/6.9M/1.9M English variants, against Star's currently selected voice on the *same* Windows host. Measure actual first audible chunk, continuity/stutter, audible naturalness by blind human review and game FPS. Smaller model = lower compute, not automatically better voice. Model and voice licenses must be reviewed; use only voices authorized for use and never misrepresent a real person's speech.

## 6. Execution priority, realistic sequence
**P0 — merged correctness & risk controls:** review this PR and the stacked parent PRs in dependency order; require clean CI and inspect any open type errors before merging. Secure independent game-state source and OS all-keys-up test. Verify stale signed observations cannot re-enable controls.

**P1 — private Windows rehearsal:** choose one owner-controlled mini-game, start the model+avatar+OBS in nonbroadcast mode, pin processes with creation times, capture frame/voice/OBS measurements, rehearse one symbolic action with explicit owner grant, exercise simulated telemetry loss and emergency-stop, and prove the final OS state is released. An off-air dry run never grants permission to go live.

**P2 — model/timing A/B:** benchmark under identical gameplay+OBS pressure, choose the best *verified* route per deadline and retain a CPU-safe fallback. Trial CPU voice separately to protect scarce GPU memory.

**P3 — autonomy and game building:** recurrent but bounded practice curriculum; signed learning memory, independent seeded holdout, self-generated difficult exercises, StudioTestService multiplayer and visual QA; transparent Discord summaries of actual passed challenges.

**P4 — streaming personality:** proactive but sparse commentary, responsive viewer turn-taking, synchronized avatar behavior, honest memories and interests, controlled off-air rehearsal and quality evaluation before any live launch.

## Sources reviewed (as of 2026-11-03)
- Voyager (2023): https://arxiv.org/abs/2305.16291
- AutoSkill (2026-03): https://arxiv.org/abs/2603.01145
- Proact-VL (Microsoft Research, ICML 2026): https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- Roblox built-in Studio MCP (2026-03-05): https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643/1
- Roblox StudioTestService: https://create.roblox.com/docs/reference/engine/classes/StudioTestService/AddPlayers
- GameDevBench (ICML 2026): https://sethkarten.ai/papers/gamedevbench.html
- Kyutai Pocket TTS releases: https://github.com/kyutai-labs/pocket-tts/releases
- llama.cpp SPEED-Bench: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- llama.cpp completion cache discussion (2026-09-16): https://github.com/ggml-org/llama.cpp/discussions/29001
- llama.cpp cross-slot contamination report (2026-08-15): https://github.com/ggml-org/llama.cpp/issues/27148
- llama.cpp idle-slot stall report (2026-10-09): https://github.com/ggml-org/llama.cpp/issues/30252

**What this update does not do:** no neural-network training or model switch, no real gameplay control, no OBS broadcast, no TTS audio generation, no proven faster inference, no claim that Star is literally human. This is a tested evidence-integrity improvement plus a technical action plan for real hardware trials.
