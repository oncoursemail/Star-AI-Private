# STAR: independently verified gameplay learning + natural VTuber research
**Research and implementation checkpoint:** 2026-10-25  
**Status:** draft, offline-only experimental modules; no real-game or streaming activation.

## What this patch actually contributes

- **Implemented:** star/gameplay_skill_bank.py — per-game/per-version/per-objective/per-situation evidence memory; HMAC-signed host trials; different practice and independent holdout signing keys; replay/duplicate-run rejection; context and version isolation; expiring evidence; Wilson lower-bound evaluation; and explicit *non-executable* candidate suggestions.
- **Implemented:** tests/test_gameplay_skill_bank.py — synthetic adversarial and regression coverage.
- **Implemented:** examples/gameplay_skill_bank_rehearsal.py — synthetic, credential-free proof of protocol behavior.
- **Not implemented here:** screen capture, actual controller inputs, Studio connection, reinforcement-learning training, neural weight changes, TTS, WebSocket connectors, OBS, Live2D or an online broadcast. No performance or game-quality gains have yet been demonstrated on the owner's hardware.
- **Stacking dependency:** this proposal builds on the draft #612 VTuber stage and its parent #581. All require independent review and passing checks. Nothing should be merged or enabled directly.

## Why another memory bank?

"She learned it" must mean **a repeatable skill worked on unseen trials**, not that an AI generated a convincing explanation or memorized its own synthetic examples. Existing STAR has a bounded Studio self-play curriculum, a game-knowledge research path, and an evidence-aware VTuber director. The missing bridge was **signed, independently validated game outcome evidence** that can be queried without turning model claims into authoritative skill memory.

This is inspired by Voyager's iterative experience → executable skill library → repeated verification, but deliberately separates *knowledge of a symbolic action* from *permission to execute anything*. It also borrows the independent perceptual/functional review distinction from Luban for game-building evaluations.

Sources: [Voyager (NeurIPS 2023)](https://arxiv.org/abs/2305.16291), [Luban embodied verification](https://arxiv.org/abs/2405.15414), [SIMA 2 game-generalization research](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/).

## Architecture — where STAR should grow

    Authorized game/Studio test place
        → screen/audio/UI/game-state observation (captured by trusted host)
        → multimodal time alignment + uncertainty estimates
        → objective state/skill candidate planner (symbolic IDs; not raw macros)
        → owner-allowlisted action controller, scoped to approved game/test context
        → host-observed result + evidence digest (TRAINING signer)
        → repeated trials with varied maps/seeds/opponents
        → independent evaluator on untouched test levels (HOLDOUT signer)
        → GameplaySkillBank.suggest(...) → non-binding owner-reviewed advice
        → optional StreamDirector.game_success input *only for a live verified event*
        → audio playback acknowledgment → facial/ear/tail/lip/gesture cues

**Trust boundaries:** Model text, chat, websites, assets, scripts, and model-generated "proof" cannot obtain either signing key. A trusted game observer confirms whether a task was actually completed. Independent evaluation must use its own key and fresh levels. Store identifiers/digests, not private player chat, screenshots, faces, audio, location, or account IDs. The same event's run ID must not be counted twice. No key should be exposed to the LLM, sandbox, skill pack, logs, repository or streaming overlay. Neither HMAC nor a passing unit test proves that the observer is honest: it proves only that a properly held signing key approved the payload. Database deletion remains possible for someone with filesystem access; this is not a tamper-proof remote ledger.

**Current confidence rule:** Five or more training trials and eight or more separately signed independent validation trials in the same game version/context are needed to nominate a skill for host review, and the two-sided ~95% Wilson *lower* success bound on validation must be ≥ 0.55 (configurable review threshold). There is no statistical guarantee that this makes a move "good" or better than the baseline. Zero evidence, expired validation, observed regressions and version drift cause abstention. The module *never* authorizes live control.

**Avoid leakage:** Reserve unseen world seeds/maps for an independent harness; do not put expected answers or private evaluator prompts in candidate training memory. Capture the provenance of each host run, hash evidence, and count independent episodes—not multiple steps of one episode—as samples. Introduce model-generated tasks only to the practice partition. Backtest on new games, new maps, and adversarial distractor UI.

## Building more human-like streaming behavior without fabricating a human identity

1. **Natural conversational rhythm:** Streaming speech should be interruptible, allow silence, support short in-game reactions, and avoid monotonically replying to every chat line. Use Star's StreamDirector priority and explicit speech playback acknowledgment. Test p50/p95 *audible* response latency, interruption recovery, and talk-over rate—not just generated-text latency.
2. **Grounded reactions and public story continuity:** If the live game observer says the boss died, Star may celebrate; if it has only a screenshot guess, she should express uncertainty. Let her organically revisit *publicly approved verified stream highlights*. Her lore and invented life stories can be charming **fictional character canon**, clearly separate from real events. Do not claim she has real human memories, emotions or consciousness.
3. **Expressive full-body animation:** Map speech amplitude/phonemes, prosodic emphasis and emotion *cues* into lip/eye/brow/ear/tail channels; smooth velocities and phase-shift hair and ribbon physics. Preserve Star's fixed character reference, all-ages outfit, twin tails with golden tips, four-point gold clip, amber eyes, cat/puppy modes; never hallucinate extra geometry. Reduced-motion mode and frame pacing are first-class.
4. **Real-time awareness:** Separate an inexpensive game-state/event observer from heavier screenshots or VLM calls. Route game-critical reaction ahead of long research. Defer rendering, training and exploratory search during gameplay; let the streamer stay silent when attention matters. Instrument viewer moderation and owner pause/interrupt.
5. **Safety and transparency:** Viewers cannot send tool instructions via chat. Don't broadcast private knowledge or reveal genuine player identifiers; OBS, Twitch, and VTube Studio connections require individual explicit owner approval and host-managed credentials. Label Star as a virtual AI character rather than impersonating a real person.

Integration references: [VTube Studio API](https://github.com/DenchiSoft/VTubeStudio), [OBS WebSocket API and authentication](https://github.com/obsproject/obs-websocket), [Twitch EventSub reconnect and at-least-once message delivery](https://dev.twitch.tv/docs/eventsub/handling-websocket-events), [Pocket TTS](https://github.com/kyutai-labs/pocket-tts), [faster-whisper / CTranslate2](https://github.com/SYSTRAN/faster-whisper).

Twitch reconnect and duplicate message IDs matter: dedupe event IDs and re-establish subscriptions correctly. Audio playback acknowledgments (not enqueue times) must drive lip sync and completed-speech accounting. OBS WebSocket should stay loopback-bound and authenticated unless the owner configures a secured bridge.

## Faster cognition within 8 GB VRAM: independent benchmarks, not promises

| Technique | Mechanism | Best use | Potential failure |
|---|---|---|---|
| Model tier/router | Route short chat to small local model; escalate difficult gameplay reasoning | Lower median latency and cost | Quality drops from over-routing |
| Prefix/KV reuse | Skip duplicate prompt prefill | Reused persona/system context | Does **not** speed decode when output dominates |
| Speculative decoding | Draft tokens cheaply, verify with large target model | Decoding if acceptance rate high and memory permits | Second model consumes VRAM; overhead can make it slower |
| Quantized weights + KV | Fit useful models with RAM/VRAM headroom | 8 GB GPU | Quality or token/s regression, especially long context |
| Async CPU speech | Run compact TTS off the game GPU | Game+voice coexistence | Naturalness/voice identity may degrade |
| Streaming STT | Incremental speech transcription, VAD + selective turns | Chat and microphone responsiveness | Hallucinations from silence/noise; buffering |
| Screen novelty governor | Examine changed/important frames rather than every frame | Less GPU contention | Can miss offscreen/subtle cues |
| Hardware-aware scheduler | Protect FPS and voice; defer nonessential training | Stable streams | Arbitrary fixed VRAM thresholds do not replace telemetry |

Technical references: [llama.cpp speculative decoding](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md), [vLLM automatic prefix caching](https://docs.vllm.ai/en/stable/features/automatic_prefix_caching/), [Pocket TTS's CPU variants](https://github.com/kyutai-labs/pocket-tts), [faster-whisper benchmark and quantized modes](https://github.com/SYSTRAN/faster-whisper).

**Benchmark design:** On each actual hardware profile, measure end-to-end first-audible latency (p50/p95), accepted completed turns, factual/gameplay grounding, token/s prefill vs decode, VRAM peak, CPU utilization, GPU frame pacing, STT error rate, voice continuity, win rate, and intervention count. Compare A/B on *identical* tasks and game seeds with a protected evaluator; never optimize latency by dropping useful answers. No claim of "faster than all AIs" without independently reproducible measurements. A 3060 Ti 8 GB or 4060 8 GB cannot run every high-capacity model at full quality alongside a game; selective scheduling, offload and remote placement are realistic engineering tradeoffs.

## Better autonomous building and game design

- **Semantic geometry:** Before rendering a room, derive architectural constraints—door connectivity, wall adjacency, floor stability, legal collision clearances, prop anchors, material scale and lighting budget. Avoid random decorative parts. Track real units, pivot/origin axes, and repeated layout checks.
- **Visual verification:** Score screen renders from at least three camera angles at fixed resolutions. Inspect clipping, z-fighting, UV seams, collisions, scale inconsistency, legibility and missing objects. Use scene-graph/physics metrics alongside vision; neither replaces a human taste review.
- **Gameplay verification:** Studio's built-in MCP server (announced March 5, 2026) provides a research path for controllable playtests and reproduced bug reports. Keep STAR's guarded Studio Lab owner-allowlisted and private. Every repair must reproduce the original failure, pass the original test, and not break adjacent routes. No automatic publishing.
- **Generalization:** Collect multiple original maps, levels, enemies, control schemes, audio cues and game genres; don't reward copying a known benchmark. Pair human evaluation with deterministic code invariants. Use offline replay before real-game trial.
- **Learning receipts:** A skill learned from Studio game A cannot automatically be assumed valid in game B or in version B of game A. Revalidate and keep failure history.

Reference: [Roblox Studio built-in MCP and playtest automation (March 5, 2026)](https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643).

## Next engineering sequence (not completed here)

1. **Host evidence collector:** Build an explicitly approved, owner-operated private test adapter that hashes redacted observations and signs verified training results. On a different trust boundary, create a withheld-level harness and independent validation signer. Threat-test key access, duplicate runs, false wins, game-version drift, timestamp replay, and unsafe control paths.
2. **Action ontology:** Build an owner-curated inventory of abstract, portable game actions (seek_cover, aim_at_target, jump_to_waypoint, check_inventory) with state preconditions, reversible control sequences, and abort deadlines. Separate the *proposal* from an approved controller; no unbounded macros or chat-driven input.
3. **Multimodal world state:** Track time-aligned audio/video/game cues with confidence and evidence IDs; don't turn visual estimates into authenticated victories. Calibrate object/event detection on occlusion and false positives.
4. **Low-latency media loop:** Add approved VTube Studio/OBS/Twitch adapters and fallback CPU TTS. Measure audio-to-mouth sync, headset interruptions, game FPS and 30-minute thermal stability in an **offline local rehearsal**, not a public broadcast.
5. **Creator QA loop:** Use Roblox Studio Lab snapshots and before/after renders. Run scene-graph tests, robot collision tests and independent human quality ratings before advancing a build. Reuse verified modules, not raw generated prompts.
6. **Knowledge expansion:** Store human-approved sources with license, context and retrieval dates. Separate public stream knowledge from private owner notes; make uncertainty visible. Evaluate on novel science, creative writing, code, animation and game-design questions with held-out oracle checks; never report self-generated answers as externally graded.

### Acceptance evidence required before activation

- At least 100 *real*, independently evaluated cross-level gameplay attempts across varied seeds/maps, with an explicit unassisted baseline and confidence interval; measure completion and safe abort rate. Synthetic tests are not game-play proof.
- Independent subjective review of 30+ complete viewer/audio/animation sequences, including pauses, interruptions, subtle expressions, cat and puppy variants, with no false personal-life stories or secret leaks.
- Paired regression gate: response usefulness and factual grounding **non-inferior**, game FPS/talking-over not worse, streaming p95 audible latency improved by a measured target (suggest **≥10%**), and no new unaudited privileges.
- Reproducible deployment plan, scoped permissions, secrets outside GitHub, reversible feature flags default-OFF and clean rollback.

**Research interpretation:** Voyager/SIMA 2/Luban are design inspirations and published experiments, *not* downloadable guaranteed STAR abilities. Star cannot become conscious or unboundedly intelligent just by installing these libraries. The useful upgrade is a falsifiable, measured loop of perception → action → experience → independent evaluation → bounded reuse.
