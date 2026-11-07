# STAR — Auditable game intelligence, fast local inference and natural VTuber architecture
**Date:** 2026-10-26. **Status:** research plus owner-only offline evaluation, not live gameplay, deployed streaming or a demonstrated increase in underlying model intelligence. **Base:** draft PR #661 (stacked on #660). No main-branch merge.

## 1. Verified learning that cannot grade itself

Existing GameplaySkillBank, ActivePracticePlanner and StudioOutcomeBridge provide exact signed practice outcomes and private action reports. Their signed PRACTICE evidence cannot establish mastery on unfamiliar games or new game versions. The same agent grading its own generated actions also risks overstating success. Replaying memorized game situations can inflate the score without teaching transferable mechanics.

**Implemented in this change: star/game_transfer_eval.py.** This module compares baseline and learned policies against the same hidden game/level/seed cases. It is called only by an independent, owner-controlled evaluation host; it does not control games, store secret keys, or invoke a model.

1. The independent host selects 40 or more held-out situation IDs across five or more games, including different scene layouts and objectives. Compute the versioned roster_digest and seal it in a timestamped, external append-only audit record BEFORE either policy plays. The evaluator verifies its supplied roster against this digest, but cannot prove when the digest was sealed.
2. Run baseline and learned candidate on identical cases with randomized run order, fresh game versions, and separately recorded outcomes. No candidate may see baseline results or held-out identifiers during practice.
3. An independent scorer checks objectives from game state and executable logs, then signs a VALIDATION GameTrial receipt with a host-owned key separate from the practice signer. Keep keys, raw case-level results and held-out seeds out of Star's prompt/context, public GitHub and gameplay memory.
4. Verify HMAC receipt, exact trial identity, duplicate run prevention, preregistered scope, freshness, split and pair proximity. Missing any side of a pair means INCONCLUSIVE without releasing partial success rates. Rejected/failed cases must not disappear from the roster.
5. Count paired discordances and use the exact one-sided McNemar/sign test. Default **manual-pilot-only** promotion requires 40 complete pairs, at least five games, three cases per game, >=10 percentage-point paired success gain, p<0.025, and no loss exceeding 20 percentage points on an individual game. This is not an automatic deploy or model-weight promotion.

**Study limitations:** HMAC authenticates the scorer, not objective truth; the host can still lie or leak holdouts. Matching situation identifiers cannot prove every engine state is identical. A small significance p-value is not proof of superhuman intelligence; sequence dependence and unrandomized orders can invalidate the statistical assumptions. Retire each held-out set after it has influenced development.

## 2. A true Observe → Act → Verify → Learn Roblox loop

Roblox shipped a built-in Studio MCP server on March 5, 2026. First-party documentation covers selecting a specific Studio instance by studio_id, playtests, screen capture, DataModel inspection and user_keyboard_input/user_mouse_input. Prefer that integration to unrestricted global keyboard injection. The host must confirm game focus, current frame, explicit permission, short key pulses and an independent key-up watchdog.

To learn a mechanic: observe game state; label uncertainty; choose a bounded experiment (e.g., jump timing on an unfamiliar obby); observe a *new* frame; check position, damage, completion, and retries from trusted game state; record a verified outcome; form another hypothesis; re-test on held-out levels. A model's written narration cannot substitute for objective completion.

For game creation, add **automated scene QA**: PBR/UV and texture overlap, collisions, missing walls, floating/unanchored props, accessible routes, remote/data-store integrity, UI legibility and hitboxes, plus screenshot and animation consistency. Compare unfamiliar briefs, not regenerated favorite templates. Roblox OpenGameEval's stateful executable scene/game checks and its findings on pre-edit inspection are useful external guides; never train on your hidden evaluation fixtures.

## 3. Live AI VTuber: believable behavior without deceptive personhood

Goal: a disclosed AI character with a consistent playful personality, not a claim that she literally has a human childhood or real memories. Authored backstory must be labeled fictional if asked. Maintain a separate ledger for fictional lore, host-verified gameplay experiences, viewer-directed promises and public facts.

**Realtime pipeline:** authorized game/audio/chat observations → salience and interruption detection → short grounded speech intent → streaming expressive TTS → host-confirmed audible PCM samples → playback-locked mouth/gaze/blink/emotion and cat/puppy ear/tail/hair motion → authenticated local VTube Studio → private OBS quality rehearsal → optional owner-approved public stream.

Star should often choose silence during important combat. She should vary utterance length with gameplay urgency and chat pressure; avoid reading every message. Have subtle blinks, head and shoulder movement, spontaneous but grounded self-correction, silence, wit and laughter with temporal connection to events. Gaze should point to actual UI or game objects, not random fake attention. Use artist-rigged Live2D hair secondary physics; the VTube Studio API adapter is not itself an artistic rig.

**Natural voice experiments:** blind-test at least 100 varied conversational utterances, laughter and interruption cases. Compare quality reference with CPU Pocket TTS 100M and the October 20, 2026 compact models. Record perceived naturalness, pronunciation, emotional expressiveness, audibly confirmed speech p95, interruption-stop latency, lip-sync offset and game 1%-low FPS. A smaller TTS may run faster but sound worse. Do not train on unconsented voices.

## 4. Faster inference without dropping game frames on 8 GB VRAM

Do not assume that four parallel inference agents outperform one on a gaming GPU: VRAM contention, cache overhead and bus stalls can make both rendering and speech slower. Benchmark **idle**, **game-only**, and **game plus speech/avatar** modes on actual RTX 3060 Ti / RTX 4060-class hardware. Measure tokens/sec, first-token time, first-AUDIBLE speech, audio underruns, gameplay p99 frametime, CPU RAM, GPU VRAM and correctness. Record independent failed runs rather than reporting only winners.

**Candidate experiments and corresponding risks:**
- CPU Pocket TTS: frees game GPU resources, but may reduce speech expression or saturate CPU; audition and measure playback.
- llama.cpp n-gram/draft speculative decoding: can accelerate repeated code/context patterns, but low draft acceptance or extra VRAM can hurt throughput; use SPEED-Bench against a no-speculation baseline.
- Quantized KV cache and layer offload: permits greater context under VRAM limits, but stalls and quality loss are real; compare paired end-to-end prompts and held-out reasoning tasks.
- Versioned retrieval/cache: reuse stable public documentation and project knowledge, but invalidate on changed scene/version and prevent stale facts from becoming confident narration.
- GPU-aware QoS: prioritize frame rendering and the first audible TTS chunk, reserve headroom, and defer research/self-play during active streaming; promote settings only on paired host measurements.
- Best-of-N verified builders: spend extra agents on hard game-building tasks with executable validators, not on simple prompts where parallel cost exceeds gains.

These are hypotheses, not hardware benchmark results from this PR.

## 5. More general knowledge, reasoning and autonomous development

Separate reasoning/model weights, licensed searchable world knowledge, episodic verified practice and short-term working context. Downloading large volumes of data cannot automatically increase foundation-model intelligence. Store retrieval provenance, source versions, licenses, evidence timestamps and contradictory claims. Include science, mathematics, coding, art, UX, video/audio understanding, foreign languages and calibrated abstention in a frozen held-out evaluation set.

Further build candidates: bounded hypothesis-driven mechanic discovery, spatial graphs for structural/pbr QA, a verifier-cost router that chooses when to spend extra compute, temporal state uncertainty for gameplay, and an observed-episode-based humor/callback planner. Each improvement needs measured correctness or speed gains and a reversible draft PR; never treat fictional self-description or self-reported victory as model improvement.

## 6. Test gates, device status and security

The new evaluator passed **10 isolated Python stdlib unit tests** against a test-local minimal duplicate of the actual GameTrial signing contract. These are synthetic simulations, not a full-tree CI pass, real game practice, inference benchmark, speech audition or proof of transfer.

The connected Desktop Commander devices were **offline when checked on October 26, 2026**. The actual VTube Studio Live2D rig, Windows PCM callbacks, Roblox Studio MCP controls and GPUs were not accessible. Before activation, run this new test plus existing gameplay skill bank, active practice, Studio outcome, avatar and stream regression suites on the full repository. No setting automatically changes and no test scorer/key is added as a model tool.

GitHub currently reports repository Star-AI-Private as **public**, despite its name. Never commit player identities, audio, stream keys, full recordings, game secrets, private evaluator seeds/keys or private knowledge to it. Publish only vetted code/research and keep owner-managed merge/deployment gates.

## Primary engineering sources

- Roblox Studio built-in MCP announcement, 2026-03-05: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- Roblox Creator Studio MCP tool catalog: https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/mcp.md
- Roblox OpenGameEval executable game/scene tasks and exploration findings: https://github.com/Roblox/open-game-eval
- Kyutai Pocket TTS technical report and source: https://kyutai.org/pocket-tts-technical-report/ and https://github.com/kyutai-labs/pocket-tts
- Kyutai's smaller Pocket TTS paper, published 2026-10-20: https://kyutai.org/blog/2026-10-20-pocket-tts-small/
- Kyutai full-duplex Moshi speech research: https://github.com/kyutai-labs/moshi
- VTube Studio public plugin API and parameter injection spec: https://github.com/DenchiSoft/VTubeStudio
- llama.cpp official speculative decoding and SPEED-Bench: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
