# STAR: sealed game-skill generalization, private VTuber rehearsal and real-time intelligence

**Research and implementation:** November 4, 2026. **Scope:** advisory, offline, opt-in game-skill evaluation. No live gameplay, voice, avatar or stream was controlled in this iteration.

## Finding: a high game-training score is not proof Star has learned to play

STAR already has a signed practice ledger, a prerequisite-based practice ladder, and paired holdout evaluation across games. The remaining integrity gap: a caller could compute a valid roster hash *after seeing the outcomes* and then say it had been preregistered. An ad-hoc SHA-256 hash does not attest chronology or signer custody.

### Implemented: independently sealed pre-run manifest

New module `star/game_holdout_seal.py` adds `GameHoldoutPrecommit` and `evaluate_precommitted_transfer`. This new entry point **adds** requirements; it does not silently change older evaluation APIs.

The coordinator must sign a versioned HMAC-SHA256 manifest **before either variant plays**, with a distinct 32+ byte key held outside STAR's model process. The immutable manifest binds the exact hidden roster digest, campaign ID, both symbolic action IDs, the baseline and candidate policy/build SHA-256 digests, and a bounded 60-second-to-seven-day evaluation window. A *different* independent evaluator key authenticates individual outcomes.

The audit rejects an altered roster, mutated seal, mismatched executable/model revision claims, wrong campaign, expired review, reused coordinator/evaluator secret, out-of-window signed trial timestamps and off-roster/suspicious trials via the existing paired scorer. Incomplete results remain inconclusive, not a success. The existing scorer additionally checks cross-game diversity, unique evidence captures, paired statistical significance and macro gains.

**Host invariants:** keep the sealed receipt in an external append-only, trusted-timestamp audit log; separately attest the actual model/worker executable and loaded weights, the game's build, fair randomized baseline/candidate run order, and real observed event provenance. A self-generated HMAC or fake clock is not independent evidence. Never expose raw holdout cases, keys, receipts or scores to the learning/planning agent.

**Security limits:** this API does not observe the computer, run a game, train an agent, make a policy more intelligent, prove authentic captures, guarantee generalization or grant gameplay/stream permission. The data supplied by independent hosts can still be wrong. An adapter must choose the sealed entry point for promotion review: the previous lower-level evaluator remains callable for other offline uses.

## Path to actual *higher game intelligence*

1. **Controlled learning:** choose 20–100 private practice maps per skill, not just a single repeated obstacle. Include navigation, timing, collision, teamwork, tactical decisions and UI discovery. Give STAR real authenticated action/outcome feedback, record failed attempts as well as successful ones, enforce max retries and pause training while live.
2. **Genuine holdouts:** a coordinator independently freezes at least 40 paired cases spanning five games, hides levels/seeds from the model, signs the sealed manifest, then evaluates the exact baseline and candidate under matched hardware and game versions. Use multiple sessions, counterbalanced run order and stable scoring. Compare skill at new maps, not memorized training maps.
3. **Learn from verified errors:** categorize action, vision, timing, physics and goal-planning failures. Build bounded skill-repair practice, train on practice only, then request an entirely fresh sealed holdout. Do not provide holdout-specific hints or report per-case validation scores to STAR.
4. **Game-building loop:** apply Roblox Studio's built-in MCP and playtest agent only to owner-authorized projects; inspect the hierarchy, make small Luau/UI edits, run Studio tests, verify changes via logs, visual captures and game objectives, and revert if independently verified quality regresses.

**Evidence:** OpenAI Procgen demonstrates that agents can overfit even large collections of levels and that unseen procedurally generated levels provide a better signal of learned skill. Farama Gymnasium documents reproducible seeded environment resets. Roblox's April 15, 2026 Studio update describes a plan–build–test agent loop and its beta playtesting agent. Unity ML-Agents documents curriculum learning, environment randomization and distributed environment instances.

## Fast intelligence on an 8 GB graphics card

Use a resource-aware four-tier controller: non-LLM reflex/safety rules for time-critical controls; small local model for brief reactions; deeper model or verified tool execution for strategy/code; nonurgent background research and learning only with spare CPU/RAM/GPU. On 8 GB VRAM, avoid claiming a fixed model speed or context length without runtime measurements.

Benchmark under *matched real scenes*: time-to-first-audible-PCM, p50/p95 action decision latency, prefill and decode rate, game p1 FPS, OBS missed frames, RAM pressure, current VRAM margin, and verified game-win gain. Compare same quality settings, same prompts, same scene and input hardware. llama.cpp SPEED-Bench compares baseline inference and speculative decoding and measures acceptance plus latency. More raw tokens/s does not mean more correct game actions.

## Natural, engaging, AI-transparent VTuber

Microsoft Research's Proact-VL (ICML 2026, May) studies whether real-time gaming companions should speak, what they should say, and how much to say. STAR should develop a *floor manager* that detects speech turn ownership, resists interruptions, budgets silence, and grounds commentary in authenticated game/chat events. Her existing parallel commentary and worker-identity guards can then feed a real TTS playback host.

Next private integration checks: spoken text really appears in the PCM track, mouth movement correlates to decoded voice amplitude/phonemes, avatar reactions match the visible event, no false claims of personal experience, no unauthorized speaker attribution, no public broadcast, and natural handoff after barge-in. Build a consistent persona (interests, long-term memories, hobbies, humor, persistent relationships with clear permission) from genuine interactions. Realistic expression is a behavioral design target, not proof of human feelings or consciousness. Always identify Star as AI.

## Concrete acceptance plan

- **Offline now:** verify all new seal/campaign/revision/clock/tamper adversarial tests plus existing paired scorer and game-learning regression tests; run static analysis.
- **Host integration:** attach independent timestamped precommit and policy-hash measurement to the game evaluator; do not put keys or unseen seeds in model context. Add a blinded review path where only aggregate transfer reports reach owners.
- **Windows private rehearsal:** follow the separate OBS private-recording gate and decoded-file proof. Then *actually inspect* audio, game/video FPS, frames and lip sync under a fully offline/nonbroadcast rehearsal. A decoded MKV alone is not proof Star spoke, played or animated.
- **Benchmarks:** paired A/B gameplay win rate on unseen maps, budgeted reaction-time p95, streamer-response relevance and interruption error rate, quality and proper disclosure. No claim of higher intelligence or faster inference without reproducible measured A/B evidence.

## Primary research and technical references

- OpenAI, **Procgen Benchmark**, Dec. 3, 2019: https://openai.com/index/procgen-benchmark/
- Farama, **Gymnasium reproducibility and seeding**: https://github.com/Farama-Foundation/Gymnasium/blob/main/docs/introduction/basic_usage.md
- Unity, **ML-Agents training / curriculum**: https://unity-technologies.github.io/ml-agents/Training-ML-Agents/
- Roblox, **Studio is Going Agentic**, Apr. 15, 2026: https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic
- Roblox, **Playtest agent Studio beta**, Apr. 9, 2026: https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767/1
- Microsoft Research, **Proact-VL**, May 2026: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- llama.cpp, **SPEED-Bench**, inspected Nov. 4, 2026: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
