# STAR — Fresh Studio Identity Proof and the Next Verifiable Gaming/VTuber Frontier
**Research checkpoint:** 2026-11-05 UTC. **Scope:** source review + narrow, tested offline Studio-guard change; no live game, OBS, voice, model training, or publishing performed.

## 1. Concrete defect, threat model, and remediation

Star's remote Studio adapter checks that a target Studio has either the specified owner-operated test place/universe or a blank, unsaved place before allowing changes. The old `PinnedSession.pinned()` used `if answer in text` for two fixed success strings. This is insufficient when the MCP result contains logs, echoed output, a quoted old reply, or a stale response: any such string could be mistaken for a successful current pin. The problem is not a theoretical model-quality concern; new offline regression tests reproduced acceptance of erroneous "Permission denied: STAR_PIN ok 0 0 ..." as a valid permission to edit.

**Patch:** the adapter generates a new random 128-bit challenge with `secrets.token_hex(16)` for each pin query; embeds it in a fixed, read-only Luau return expression, and accepts *only* an exact response containing the approved place/universe and the matching challenge. Any error, extra output, wrong ID, missing challenge, or replay fails closed. The challenge is **not** authentication of Studio or an authorization grant: it is a fresh proof-of-response for the already authenticated MCP session. There is still no absolute guarantee against a compromised endpoint that can execute/read and forge arbitrary responses. This is defense in depth; final mutating Luau also retains the separate engine-side `PIN_GUARD` and Studio edit/session binding.

Risk/compatibility: a real MCP server that decorates valid Luau return values with additional text will now fail closed rather than guessing. Confirm the response envelope on the target Windows Studio with a **read-only** query before accepting this change in live workflows. Never loosen matching to a substring merely to accommodate a wrapper; write a separately tested, narrowly scoped envelope decoder when evidence demands it.

## 2. What currently matters for Star's capability—not vanity benchmarks

A stronger assistant is measured by **verified work completed per hour** and calibrated uncertainty, not raw reasoning-token volume. Four independently scheduled lanes make a measurable architecture:

| Lane | Role | Deadline class | Proof |
|---|---|---|---|
| Reflex | timestamped game observations, VAD/interrupt, neutralize held controls | frame-to-100-ms range, profile-specific | no stale frame, grounded input, safe release |
| Interaction | decide to answer/silence, short Star voice response, lipsync/event routing | p95 first audible chunk; report actual device time | speech matches heard audio and current viewer/game context |
| Planner | map exploration, puzzles, combat strategy, Luau/Rust development, tool orchestration | seconds/minutes | verified external outcome and meaningful rollback |
| Learner | generate practice curricula, verify before/after skills, update retrieval, offline experiments | opportunistic / off-stream | preregistered holdout skill improvement on unseen scenarios |

Do not put GPU-intensive planning on the critical audio/game loop. Admission controller should keep an operator-configurable GPU VRAM reserve for game, OBS, avatar, and inference context; overload should defer background experiments, reduce nonessential screenshot frequency, and fail silent if event evidence ages out. Prefer deterministic timers and bounded queues over unbounded background threads. Never invent a speedup: compare matched cold/warm and mixed-workload conditions on the actual PC.

## 3. Roblox Studio development: build-test-repair with independent identity

**Official live capability, rechecked November 2026:** Roblox Creator Hub documents the built-in Studio MCP server for reading/editing the data model, executing Luau, running playtests and more. Roblox's **August 19, 2026** announcement requires explicit `studio_id` for multi-Studio calls; stateful `set_active_studio` routing is no longer the model to imitate. The **April 15, 2026** Roblox announcement describes the plan/build/test loop and automated playtest-agent beta.

Source links:
- https://create.roblox.com/docs/ai/accelerated-workflows
- https://create.roblox.com/docs/studio/mcp
- https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic
- https://devforum.roblox.com/t/studio-mcp-multi-agent-improvements-and-connected-ai-clients/4820583/1

Proposed end-to-end loop: (1) discover Studio instances; (2) select **explicit studio_id** and verified place/universe; (3) read the relevant tree and source; (4) generate minimal reversible edits; (5) run Luau checks plus an actual playtest; (6) capture console/errors and bounded screenshots; (7) evaluate gameplay result **independently**; (8) produce semantic diff + rollback; (9) stop testing and release all inputs. Each independent agent requires an instance-scoped lock. Treat all unrecognized MCP tools as unavailable until reviewed. Never infer that a successful HTTP/MCP reply means a game state change succeeded.

OpenGameEval (October 1, 2026) evaluates 84 Roblox Studio tasks with executable scene and simulated play checks, and explicitly measures exploration. Recreate the *principle* for Star: require meaningful project inspection before edits, and score repeatable gameplay/code outcomes rather than self-reported success. Study the released harness but keep live owner projects out of tests.

- https://arxiv.org/abs/2610.02563
- https://github.com/Roblox/open-game-eval

**Real-time acceptance gate:** two simultaneously open Studios with different place IDs; a tool result containing a stale or embedded `STAR_PIN ok` must never unlock an edit. A request for the wrong `studio_id` or switched engine session must fail closed. Live test should be read-only first, then on an owner-approved disposable place, not public projects.

## 4. Learn games like a skilled player rather than memorize a script

Adopt a standard experience interface: `reset(seed)` -> observation + info, then `step(action)` -> next observation, reward, termination/truncation, independent evidence. Gymnasium is a reference for reproducible RL APIs; Procgen (16 procedurally generated environments) is a reference for testing generalization and preventing fixed-level memorization.

- https://github.com/Farama-Foundation/Gymnasium
- https://github.com/openai/procgen

Training curriculum:
1. Perception calibration: locate playable character, HUD, map, obstacles; measure timestamp age and camera motion.
2. Safe motor skills: move, stop, rotate, jump, pick up, press-and-release; measure input-to-state latency and stuck controls.
3. Mechanics probing: estimate ability cooldowns, enemy patterns, damage and object affordances through reversible actions.
4. Tactical play: estimate threats, path selection, goal progress, risk-sensitive replanning.
5. Cooperation: recognize teammate intent, communicate concisely, yield turn, avoid griefing.
6. Transfer: change maps, game seeds, visual themes and input layouts; no training access to held-out trials.

Use verified, signed attempts in the practice bank, blinded holdouts chosen before outcomes, counterbalanced baselines and candidates, and report confidence intervals with sample sizes. Reward hacking and outcome leakage must be treated as failures; a prettier stream isn't evidence of stronger control. Limit per-attempt input budget and maintain emergency neutralization. For commercial multiplayer games, respect permissions/anti-cheat rules and avoid unsanctioned automation.

## 5. More natural, openly AI VTuber behavior

Proact-VL (ICML 2026) models *when* to speak, *what* to say, and *how much* to say in gaming companion settings. Don't simply narrate every HUD change. Ground commentary in fresh events, then suppress low-salience repeats, chatter during danger, and unverified dramatic conclusions.

- https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- https://proceedings.mlr.press/v306/yan26c.html

Humanlike **function and presentation**, without claiming Star literally has human emotions or consciousness:
- Persistent consensual persona facts, interests and long-term show arcs, not a fabricated childhood or false viewers.
- Stream episode memory: verified events and source timestamps, non-sensitive running jokes; delete private chat when retention is disabled.
- Natural spoken turn-taking: detect genuine owner/guest speech, keep appropriate silence, support host-authorized interruption, and avoid AI talking over people.
- Emotional **expression** mapped from observed context: disappointment after a verified failed attempt, anticipation before a challenge, joy at a verified small success; never fake having beaten a game.
- Voice-to-avatar synchronization, blinking/saccades and expression variety; human-scored coherence and accessibility, not frenetic animation.
- Viewer interaction: moderation, rate limits, pseudonyms, consent boundaries, no accidental disclosure of private source paths or chat histories.
- Keep **transparency**: Star is an AI VTuber; interaction design can be humanlike without impersonating a real human.

Kyutai Pocket TTS's upstream repository now offers CPU-focused small English model variants released in **October 2026** (18.2M, 6.9M and 1.9M parameters including decoder) plus a larger ~100M-parameter version. This makes a measured CPU/GPU trade-off worth testing while OBS and games use an 8 GB NVIDIA GPU. Claims for other hardware are not Star's measurements.

- https://github.com/kyutai-labs/pocket-tts

**Real audiovisual acceptance test:** private owner-approved Windows game + avatar + synthesized voice + OBS capture; check encoded audio exists, is audible, matches recorded speech, avatar mouth motion is aligned, all commentary references an observed event, the scene remained local/private, and no dropped inputs or surprising external actions occurred. Existing offline audit/OBS telemetry components alone cannot establish these things.

## 6. Speed experiments tied to Star's actual hardware

Measure configurations *on the same hardware under the same load*:
- 8 GB card: GPU inference resident vs partial offload; 2K / 8K / 16K / 32K context; fixed and evolving retrieval; steady-state VRAM margin.
- Prompt processing pp vs generation tg, p50/p95 first-token time, total turn latency including dispatch and speech; cold and warm cache behavior.
- `llama-server` 1 vs 2 workers, prompt caching/slot reuse, speculative n-gram vs small draft model, bounded concurrency; discard optimizations that create stalls under simultaneous game/OBS loads.
- CPU Pocket TTS small vs full versions: first audible chunk (not first emitted byte), quality, real-time factor, speech intelligibility, interruption delay, game FPS and OBS lost frames.
- Mixed workload priority experiment: idle, game only, game+OBS, game+OBS+voice, plus background reasoning. Report both successes/hour and tails (p95/p99).

The llama.cpp `llama-bench` guide distinguishes prompt-processing and generation and explicitly excludes tokenizer and sampling time; use an end-to-end harness for VTuber latency. SPEED-Bench reports category latency and draft acceptance for a live server; neither tool proves gaming performance alone.

- https://github.com/ggml-org/llama.cpp/blob/master/tools/llama-bench/README.md
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

## 7. General intelligence and trustworthy autonomy

Use a source-indexed, timestamped knowledge store with provenance, automatic freshness checks, retrieval calibration and contradiction detection. Distinguish **facts**, **hypotheses**, and **preferences**. Store summaries with links back to trusted project artifacts; avoid learning private game state from a leaked holdout. Code tasks require runnable test cases, static analysis and rollback. Hard unsolved tasks should trigger deliberate decomposition and cheaper verifier-assisted candidate generation, not endless speculative thought.

Self-improvement should live in Star's local, versioned experimental forge; GitHub can remain a publication/review mirror. Require objective comparator before a change is promoted. Never let Star approve its own secret signatures or treat a self-authored score as independent evidence. For autonomy: owner-defined scope/budget, maximum blast radius, per-project game permissions, durable recovery, and reversible actions by default.

## 8. Experiment register / release criteria

| Priority | Experiment | Required evidence | Status at checkpoint |
|---|---|---|---|
| P0 | Studio pin response freshness | offline forged-log + stale-replay tests; read-only real Studio compatibility probe | **offline tests added and pass**; real probe not done |
| P0 | Private Windows VTuber rehearsal | real game + OBS + audible Star voice + lipsync and input evidence | **not run** |
| P1 | Inference mixed-load speed | matched p50/p95 latency, FPS, VRAM, OOM count | **not measured** |
| P1 | Game skill transfer | precommitted unseen attempts, paired baselines, effect size | **not measured** |
| P1 | Naturalness | blind human ratings, measured overlap/interruption and grounding | **not measured** |
| P2 | General knowledge/complex coding | held-out source-grounded QA and executable Luau/Rust tasks | **not measured** |

**Boundary of this patch:** response freshness and strict identity receipt parsing in the remote Studio adapter. It does **not** train a new model, increase actual FPS/tokens/sec, start streaming, operate a game, teach gaming skill, or prove humanlike speech. Keep the pull request draft and run independent CI plus a Windows read-only compatibility probe before integration.
