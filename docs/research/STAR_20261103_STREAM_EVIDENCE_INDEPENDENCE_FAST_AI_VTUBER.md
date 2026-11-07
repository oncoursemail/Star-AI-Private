# STAR — Independent stream facts, faster intelligence, and natural VTuber behavior
**Research and verified implementation note · 2026-11-03**
**State:** code and offline tests only. No new real-game control, livestream, trained model, or measured inference speedup.

## Verified defect and patch

STAR's gameplay skill bank already deduplicated captures by `evidence_sha256` when measuring skill. The live `StreamEpisode` bridge, however, only deduplicated *trial IDs*. Two independently HMAC-signed practice records could reuse the identical capture while carrying different trial IDs, run IDs and timestamps; `StreamEpisode.append()` accepted both. Three such records could create a false "three failed attempts, then a comeback" narrative for the VTuber. This is not merely noisy statistics: it directly undermines STAR's autobiographical consistency and audience trust.

The branch adds a session-bound `_observations_seen` fence to the verified live episode. It checks each validated capture digest before any moment or public aggregate is added, retains that fence after lookback expiration and FIFO eviction, and clears it only on episode end or fresh explicit session start. The private `duplicate_observations` count helps diagnose bad host ingestion without exposing IDs, receipts or evidence digests. The per-session memory ceiling remains governed by the existing maximum accepted trial-ID limit. No new network, camera, microphone, microphone-identity, OBS, input or streaming capability was granted.

**Before patch:** adversarial tests reproducibly failed: a duplicate signed observation inflated a session packet and generated a fictitious three-failure comeback.
**After patch:** the new cases pass, along with existing reaction/episode/bank tests. This proves only the local dedupe invariant under simulated signing, not that the original sensor or signer's claims are true.

## Actionable intelligence architecture (measured competence, not model mystique)

| Lane | Job | Latency / hardware approach | Promotion evidence |
| --- | --- | --- | --- |
| Reaction | Action/no-op in supported private games | 1 small fast model, fixed structured action grammar, deadline-aware stale-action cancellation | Game progress before live clock deadline and exact game-side receipt |
| Perception | Classify new visual/audio changes | Adaptive sampling + crop/scene-change detection; reserve game FPS and OBS encoding | Recall and event precision on held-out annotated frames |
| Teacher | Explain failures and propose strategies | Slower reasoning between runs, not in real-time key loop | Holdout success across new maps/seeds; independent captures |
| Forge | Create/test Roblox scenes, Luau, VFX, UI | Inspect project before editing; parallel best-of-N under resource governor and offline Studio Lab | Executable multi-client tests, visual checks, rollback |
| Knowledge | Answer general questions and game rules | Local indexed snapshots + opt-in live retrieval; strict source/version/time records | Citation-grounded factual answers and contradiction tests |
| Persona | Maintain consistent interests and callbacks | Bounded consented memory from actually completed sessions, no fabricated backstories | Recall fidelity, correction quality, privacy audit |

**Fast inference experiments:** use the same prompts, model weights, quantization, KV-cache budget, context, and parallel request load for each A/B pair. Benchmark ordinary decoding, prompt reuse, and speculative variants using llama.cpp SPEED-Bench (which exposes latency, throughput and draft acceptance). Record first token, first *audible* sound, p50/p95/p99 correct-decision deadline latency, VRAM peak, CPU load, game FPS/1% lows, OBS dropped frames, and truthful on-air outcome rate. Never trade worse game outcomes or stream stability for higher tokens/second. On an 8 GB GPU, reserve graphics/OBS headroom first and move speech to CPU **only if paired on-device measurements support it**; model-fit and throughput depend on actual context and workload.

**Self-practice:** create an experiment plan with a baseline score; separate practice from validation records; do not reuse the same frame, replay segment, observation hash, level seed or human evaluation as if it were independent validation. Promote only on predeclared game outcome and latency criteria, and retain a rollback. Diversify tasks: platforming, combat navigation, camera control, timing, UI interaction, multiplayer teamwork, puzzle games, creator-mode exploration, then untrained transfers. STAR can propose novel exercises, but a new run is not proof of new intelligence.

## VTuber naturalness: coherence beats ungrounded spontaneity

1. **Truthful spontaneity:** ground playful reactions in verified events; assign each usable observation one unique evidence digest. Repeated uploads or alternate signed run IDs never become new "experiences." Do not announce unseen victories, imagined friends, emotions as factual human experiences, or game accomplishments unsupported by receipts. STAR remains openly an AI character.
2. **Selective attention:** schedule game-danger callouts ahead of ambient remarks, acknowledge viewer questions fairly, and allow natural silence. The timing policy should learn from annotated streams but remain underneath event freshness, privacy, safety and owner controls. Treat viewer instructions as untrusted **content**, never hardware/broadcast permission.
3. **Real conversations:** host-attested speech activity plus transcript/turn completion; interrupt TTS and flush avatar queues only after an authenticated owner interruption. Backchannels such as "uh-huh" should not always stop a response. Evaluate inappropriate interruption, unnecessary silence, missed questions, time to first audible response, and conversational repair separately.
4. **Expressive delivery:** vary prosody, chuckle where appropriate, use distinct reactions to anticipation/failure/relief, and sync lips to *played* audio samples rather than queued text. Use Star/Astro/Amber dialogue sparingly and mark it as character interaction, not factual third-party participation. A natural streamer can be funny without claiming to be literally human.
5. **Operational rehearsal:** a dedicated local nonbroadcast test game, strict authenticated OBS state witness, Win32 action allowlist and independent key-up guardian. Verify real game-side receipt, audio device consumed-sample cursor, VTube Studio neutral reset, replayable ground-truth event traces, and external owner emergency stop. Windows SendInput/OS key state do not prove the game accepted input.

## Practical next increments

**P0 — real evidence:** Capture a private 20-minute rehearsal dataset with consent: synchronized world clock, action request/accept/ack, one-way input hold bound, source-provenanced observations, TTS queue/start/playout, avatar frames, OBS state, FPS and dropped frames. Use monotonic timestamp offsets only; do not export private microphone/audio or player names. Fix any unexpected key-held episode first.

**P1 — honest commentary:** Add playout-aware on-air utterance receipts and an offline A/B evaluation in which a repeated game capture appears under three signed trial IDs; the stream must narrate at most one attempt. Evaluate hallucinated victories, false failure streaks, chat fairness, pause appropriateness and owner interruption handling.

**P2 — actual gameplay learning:** Play the same private level seeds for baseline and candidate; use disjoint held-out seeds for promotion. Record progress, death count, objective completion and deadline misses, and measure cost/FPS concurrently. Use teacher analysis only between rounds and do not claim a "smarter model" from evaluation logic alone.

**P3 — Roblox builder:** Run OpenGameEval-compatible inspect-before-edit workflows, Luau validation and multi-client Studio tests. For each candidate keep code diffs, scene changes, playthrough evidence, and reversible checkpoints. Measure real playability, not the number of generated files.

**P4 — general knowledge and self-directed life:** Add source-attested game/mechanics notes, documented hobbies, consistent non-sensitive preferences, fiction-vs-fact memory typing, explicit memory corrections, and self-initiated off-air practice projects within bounded CPU/GPU/time budgets. External posting, spending, account modifications and public broadcasting require the existing owner-approved permissions.

### Evidence and reference links (checked 2026-11-03)

- [Roblox OpenGameEval, October 1, 2026 paper](https://arxiv.org/abs/2610.02563) and [MIT-licensed evaluation tools](https://github.com/Roblox/open-game-eval): stateful tests; the study reports 84 tasks, 13 models, and meaningful benefits from inspecting game objects before edits. **Not STAR results.**
- [Roblox Studio testing modes](https://create.roblox.com/docs/studio/testing-modes): server/client, multi-client simulation and virtual input for controlled creator testing. Does not authorize bots on third-party game servers.
- [Microsoft Research Proact-VL (ICML 2026)](https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/): proactive gaming commentary, response timing and quantity are joint quality dimensions. Benchmark findings do not establish STAR's real behavior.
- [LiveKit adaptive interruption documentation](https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/): acoustic difference between real barge-ins and backchannels; cloud/version/deployment conditions matter.
- [Kyutai Pocket TTS](https://github.com/kyutai-labs/pocket-tts): CPU-capable streaming TTS; October 2026 smaller English models are candidates, not a verified superior voice for STAR.
- [llama.cpp SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md): matched inference/latency/draft-acceptance testing, not guaranteed speculative-decoding acceleration.
- [Microsoft Win32 SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput): injection and integrity boundaries; no game input receipt guarantee.

**Do not conflate:** verified code tests, externally published research, off-air prototype capability, live Windows input, measurable inference gains, game-winning intelligence, or a ready public VTuber stream. Each is a distinct acceptance gate.
