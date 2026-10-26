# STAR: verified gameplay transitions, faster intelligence, and natural live VTubing
**Research snapshot: October 25, 2026.** Draft-only implementation, not a live deployment.

## 1. What this iteration actually fixes

STAR already had pieces of a game loop: a bounded game frame, a model-proposed symbolic action, a private-Studio keyboard gate, signed gameplay trial memory, and an opt-in streaming episode. These pieces were disconnected at the critical causal boundary: a successful key pulse was not bound to the *subsequent* independently scored game result.

This patch adds:

- A host-generated **DeliveredAction** for a private Roblox Studio input that was actually sent **and** confirmed released. This is not proof of gameplay success.
- A same-process **one-time proof claim**, tied to the exact `DispatchReport` object. Copies or forged reports cannot claim it; old proofs are invalidated on later deliveries or host revocation.
- A **transition digest** covering the pre-action observation, scope/version/run, action, ticket, released time, post-action observation, independently assessed outcome, and trial objective.
- A `StudioOutcomeBridge` that rejects stale/cross-run/low-confidence/mismatched observations, unverified post-frames, unsigned claims, and evaluation-split leakage. It stores only independently signed **practice** results in the existing `GameplaySkillBank`.
- Optional continuity in `StreamEpisode` after ingestion; that still **cannot** broadcast without a separately approved public event/action allowlist.
- Offline tests for successful actions, genuine failures, forged reports, replay, wrong versions/splits, stale frames, low confidence, bad signatures, lost focus, and unconfirmed key-up.

**Scope:** An offline-tested trusted-host adapter. No real Studio MCP call, direct OS key press, new model training, actual broadcast, or empirically measured speed increase in this PR. An HMAC proves possession of a key, **not** that an external game evaluator reported objective truth; signer independence is an operational prerequisite.

## 2. Highest-leverage intelligence architecture

### A. Real playable experience, not memorized text
```text
Trusted game capture -> perceived state + confidence + versioned scope
 -> bounded game-policy proposal -> host authorized action -> actual key-up
 -> NEW one-shot delivered-action record
 -> NEW fresh post-action frame + independent objective checker
 -> NEW signed before/after transition digest
 -> gameplay practice skill bank -> active practice + episode memory
 -> independently withheld evaluation before skill promotion
```
The most important missing production components are **host-side, independent objective scoring** and **actual Studio MCP connection**. A robust scorer should evaluate objectives from engine logs, checkpoints, collisions and scripted success counters rather than asking STAR whether she won. Distinguish actual terminal wins/losses from timeouts or interrupted trials; never score a truncated trial as a win. Store raw evidence privately outside GitHub, with short retention and explicit owner controls.

Use curriculum difficulty levels, seeded independent maps, delayed evaluation, and cross-game transfer tests. Record versioned game IDs, scene hashes, controller policy version and evaluation seed. Release only after measured gains on withheld games—not repeated practice runs.

### B. Better general knowledge and persistent autonomy
- **Three-tier memory**: transient game context; private verified long-term skill/fact knowledge with provenance; separately reviewed broadcast-safe excerpts. Retrieval is scoped, capped, source-dated, citation-bearing and owner-controllable.
- **Proactive learning**: schedule exploration when Star is idle; select knowledge gaps by uncertainty and downstream utility; generate harder tasks that test capabilities, not self-reported confidence. Retain negative results and reproducible code failures.
- **Evidence before promotion**: use a held-out evaluator that Star cannot inspect or influence. Require quality, latency, memory and regression gates before adopting changes. Run self-improvement experiments in disposable worktrees/containers.
- **Star Core Forge** should be the durable offline-first source of truth for provenance, experiments, proofs, retries, rollback and local backups. GitHub can remain an optional reviewed publication/export path, not a dependency for autonomous learning.

### C. Inference speed with 8 GB GPUs
Run **paired, same-hardware** tests—not unverified speed claims:
1. Compare quantized models under the same context, token sampling, cache configuration and gaming load.
2. Use prefix caching for stable system messages/tool schemas; version + permission-scope every cache key. Never mix private/public facts in a shared prompt cache.
3. Benchmark llama.cpp draft-model and n-gram speculative decoding against plain decoding. Report accepted tokens/draft, first-token latency, median and p95 token delay, total tokens/sec, peak VRAM, quality regression and game 1%-low FPS. Gains depend on workload/model compatibility.
4. Try bounded CPU-based speech independently from GPU inference to preserve frame rate; test quality and speech jitter, not just synthetic throughput.
5. Short-circuit obvious low-level actions using a deterministic local controller; invoke the large reasoning model for new mechanics, failures or uncertainty. Do not use high-cost reasoning for every frame.
6. Reuse observations when the scene is unchanged; invalidate caches on game version, camera, focus, UI or objective changes. Stale frames must not trigger input.
7. Allocate explicit frame/GPU/CPU deadlines to game rendering first, speech second, deep research last. Avoid memory overcommit and unbounded async queues.

**Acceptance criteria**: Better held-out game success at equal compute OR lower p95 latency at equal correctness; no material loss of game 1%-low FPS; no new key-up leaks; no private data contamination. An objective quality benchmark must always outrank raw token speed.

## 3. A human-*natural* VTuber, not a falsely human identity

STAR is a fictional 21-year-old character (birthday October 11), with a consistent personality, history, preferences, normal/cat/puppy modes, and an unmistakably cute star-themed look. She should be **clear that she is an AI character** when relevant; human-natural interaction does not require claiming human biology, real-world childhood, or genuine human consciousness.

**Live audio/behavior design**
- Use a full-duplex listening pipeline with echo cancellation and host-authenticated owner barge-in. Play audio streaming chunks as they arrive; ground lip sync in the audio actually **heard**, not generated text.
- A conversational state model should track: listener turn, speaker turn, interruption, quiet thinking, gameplay-critical concentration, and voluntary silence. Add brief self-corrections and varied prosody only when semantically appropriate; avoid canned giggles, repetitive jokes and unearned victory cries.
- Live2D needs anchored rig physics for layered hair, ribbons, ears/tail, blinking, head tracking, pupils, breathing and subtle shoulders. Animate smiles/surprise from verified events and speech rhythm, not random expression spam.
- Coordinate TTS, facial expression, body motion, virtual microphone, and OBS scene state by one **audible playback epoch**. Late or interrupted audio must never animate a completed victory or be counted as a fully delivered answer.
- Chat is untrusted and must be moderated and prioritized. Viewer requests cannot grant device permission, read private memory, or move Star out of her approved gameplay scope.
- Build viewer relationships with continuity for recurring public preferences, not covert surveillance of users. Strip identities from metrics. Privacy approvals for remembered chat and public responses are distinct.
- During hard gameplay, fewer words and good timing feel more natural than constant chatter. With RTX 3060 Ti / RTX 4060-class 8 GB cards, reserve GPU memory for the game/rig and measure CPU-TTS competing for CPU cores.

**Publishable streaming performance gates**: p50/p95 time-to-first-*audible* speech; number of interruptions correctly stopped; percent of speech synchronized with expression; silent focus compliance; no unverified wins; privacy incident count; GPU peak VRAM, voice underruns, and game 1%-low FPS.

## 4. Verified sources and practical implications

Official/research sources consulted October 25:
- Roblox's built-in Studio MCP (`user_keyboard_input`, `screen_capture`, `list_roblox_studios`, `start_stop_play`), with `studio_id` chosen explicitly: https://create.roblox.com/docs/studio/mcp ; https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/mcp.md . The built-in server is stdio; a real host adapter must validate session and focus immediately around each tool call.
- Roblox announcement March 5, 2026: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 . This confirms automated playtesting is a supported path, not a completed STAR integration.
- Farama Gymnasium `step(action)` separates `terminated` from `truncated`: https://gymnasium.farama.org/v1.0.0/api/env/ . This matters when judging game learning and excluding timeouts.
- llama.cpp speculative decoding: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md . Requires empirical accepted-draft-token and p95 latency tests.
- Kyutai Pocket TTS CPU streaming; October 2026 tiny 18.2M/6.9M/1.9M variants: https://github.com/kyutai-labs/pocket-tts . Fast generation alone does not guarantee human-natural prosody.
- VTube Studio local WebSocket/plugin API: https://github.com/DenchiSoft/VTubeStudio . Map model-specific parameters after a trusted plugin connection and do not open arbitrary remote ports.

## 5. Next integration, in order

1. **Trusted scorer in a private Studio fixture**: map `episode_id` to actual run ID; collect pre/post captures and engine-observed objective verdict; sign only *real*, auditable practice results, with independent validation signer for holdout.
2. **MCP-backed Studio input port**: connect exclusively to private test places, verify exact Studio instance, implement host-side hard key-up watchdog outside this Python process, test crash/disconnect recovery.
3. **Game mastery evaluation**: withheld unseen maps, temporal robustness, sample efficiency and calibrated uncertainty. Report absolute success-rate changes with intervals and realistic resource consumption.
4. **Realtime VTuber prototype**: mic VAD -> turn-taking -> game-aware intent -> generated audio -> actual playback acknowledgements -> VTube Studio Live2D parameters, all under OBS/game GPU pressure telemetry.
5. **Per-hardware benchmarks**: baseline and A/B results on Star's actual machines; default-OFF experiments with rollback, source/evidence logs and quality gates.

This implementation is a real proof-of-execution bridge with offline tests. It is **not** proof that the game was played, the objective was achieved, STAR has human consciousness, or the foundation model's intelligence or inference speed increased.
