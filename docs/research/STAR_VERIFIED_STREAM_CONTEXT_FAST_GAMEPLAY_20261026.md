# Star AI: Evidence-Grounded Stream Intelligence, Game Mastery and Speed
**Research and integration note — 26 October 2026**

## 1. Executive assessment
Star already contains isolated but fairly mature components for signed gameplay practice, reviewed knowledge, webcam-independent avatar parameters, Twitch EventSub, audiovisual interruption, QoS, frame capture, and hardware telemetry. A weak point remained in the integration: StarStage.prepare() accepted source-reviewed KnowledgePacket and independently verified EpisodePacket, but the real telemetry-governed StreamBrainGovernor.prepare() did not accept or forward either. Hence a host using the safer measured path could lose Star's factual and gameplay context. **This patch closes that concrete gap.**

- New StreamContextHost prepares on-air context from real reviewed KnowledgeStore entries and recent signed practice events.
- It requires separate owner and publication approval, static public note/action allowlists, a bound SQLite worker, and separate trusted clocks.
- Its governor supplies no speech when hardware telemetry is absent; this cannot be bypassed by adding knowledge.
- StarStage's existing event restrictions remain: public knowledge is attached to viewer questions, and verified game episodes to appropriate game/viewer events. No hidden validation outcomes or private viewer histories become dialogue context.
- It owns no browser, streaming or speech hardware. An authenticated trusted host is still needed to invoke it, execute speech and confirm physical playback.

This change **does not train a larger model, increase raw neural-model intelligence, make games play themselves, or deliver verified human-quality speech**. It removes a real integration bottleneck necessary to demonstrate those goals.

## 2. Research-backed architecture: three clocks for a gaming mind
A gaming VTuber should not make every decision at LLM-token speed.

**Fast reflex loop (target ~20–60 Hz, not implemented in this patch):** on a trusted local game host, consume compact player/world-state measurements and perform *bounded, authorized* symbolic actions with a hard key-up watchdog. Keep OS input permissions isolated from chat and model prompts. Frame-delayed narration must never drive time-critical movement.

**Visual understanding loop (~1–4 Hz, existing prototype):** use Roblox Studio screenshots, optical context and host-verified scene state to map platforms, hazards, goals, geometry and mechanical affordances. Cache unchanged frames. Extract hypotheses; treat image-model confidence as uncalibrated and compare with engine evidence.

**Deliberative / learning loop (seconds to minutes):** propose a strategy, reserve an offline practice trial, observe a signer-confirmed outcome, compare against alternatives, and submit transferred skills to independent withheld tests. Some tasks require long-term planning and whole-game completion tests, not just seeing a script compile.

**Social commentary loop (event-triggered):** viewer questions and genuinely observed gameplay are prioritized by a measured speech governor, rather than by an idle chatbot timer. Stage context must preserve clear provenance; speech is not counted until the host confirms it was audible.

### Key game-development research
- [OpenGameEval (Roblox, 1 October 2026)](https://arxiv.org/abs/2610.02563): 84 stateful engine tasks, 13 models and executable evaluation. Its observation-before-edit finding suggests auditing every target and dependency before writing Luau or moving scene parts. Observational correlation is not an intervention proof.
- [OpenGameEval source](https://github.com/Roblox/open-game-eval): adopt version-locked tasks, blind seeds, end-state checks and repeatability. Never use hidden cases for Star's training or action selection.
- [CEGame-Bench (19 October 2026)](https://arxiv.org/abs/2610.26098): across five game engines, reaching a playable ending is far harder than passing integration checks; paper reports 16% full completion and gains for requirement-driven playtesting. Add an actual game-completion acceptance suite for every generated tycoon, obby or horror map.
- [Roblox Studio native MCP guidance](https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643): prefer official studio tools where possible; pin the host's method allowlist and use temporary/private playtests.
- [SIMA 2](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/): shows why language-conditioned, cross-game skill learning and transferred evaluation deserve research. It is not a drop-in model Star can claim to run.

### Automatic artifact integrity
Implement build-time and runtime checks for:
- Topology: no unintended disconnected walls, floating props, duplicate overlapping parts, nonmanifold holes, or invalid collision groups.
- Visual quality: rendered screenshot comparison, material/UV consistency, clipping and z-fighting, UI anchor/scale checks across aspect ratios.
- Playability: spawn -> objective -> checkpoint -> death/recovery -> win -> rejoin/load; verify each by input-driven game tests, not text self-grading.
- Animation: rig joint ranges, continuity, velocity/acceleration spikes, foot contact, physics stability, fail-safe poses, and reduced-motion options.
- Attribution: licensed source manifests for meshes, music, textures, assets and sound; do not scrape/upload other people's protected game content.

## 3. Star's intelligence: knowledge with durable correctness
Distinguish (1) a model prediction, (2) a retrieved fact with date/source, (3) a verified experiment result, (4) a private account secret, and (5) a fictional character anecdote. Never merge those categories silently.

A knowledge claim should track: source ID, license, retrieved_at, asserted_at, reliability class, scope, revision, contradiction set, and expiry policy. For live output, only owner-reviewed *public* notes enter Star's prompt. Star's private signing keys, gameplay validation data, recordings, viewer identifiers and chat logs stay outside general retrieval.

For autonomous curiosity, give Star a challenge generator that writes a falsifiable hypothesis; a cost estimator; an independent verifier; and an experiment history in local Star Core Forge. Promote the **verification procedure**, not merely a successful model answer. Reject confirmation bias, selection on holdout data, re-running failed tests until one passes without reporting the denominator, and autonomous edits to the verifier.

New context flow:
    Owner-approved Twitch moderation -> StreamSignal -> StreamBrainGovernor
    owner-curated KnowledgeStore  -> public_knowledge_packet --+
    independently signed practice -> StreamEpisode -----------+--> StreamContextHost
    live GPU/CPU/RAM/FPS/audio measurements ------------------+--> StarStage.prepare()
    StagePlan (USER-level evidence only) -> reserved speech job -> physical audible acknowledgment
    host-confirmed played audio -> epoch-bound VTube Studio expressions / completed dialogue

**Why not just make Star remember everything?** Large unreviewed memory grows inference latency and gives the model a chance to treat hallucinated episodes as facts. Store bounded, source-backed summaries and retrieve only what is relevant to the current question or event.

## 4. Natural, expressive AI VTuber
Star should be identifiable as an AI with a consistent 21-year-old fictional character persona, not falsely claim a biological identity or invented real-world experiences. Her stable visual design, golden star clip, expressive amber eyes, gold-edged black dress and cat/puppy modes can provide continuity. Dialogue content should distinguish real in-game experience from deliberately fictional lore.

- Real speech timing: first-audible latency and interruption latency matter more than word output volume. Encourage brief, relevant responses, varied pauses, laughter with actual acoustic variation, and silence during hard platforming.
- Natural turn taking: distinguish a viewer's true floor-taking attempt from noise and background chat; handle owner interrupts without replaying an old speech epoch. [BayLing-Duplex, 12 June 2026](https://arxiv.org/abs/2606.14528) is a relevant architecture direction but its reported benchmark outcomes are not Star measurements.
- Speaker experience: a local TTS stream should increment speech state only when a physical device callback confirms audible PCM. Generator success alone cannot count as speech. Reserve and free TTS workers only after actual stop acknowledgment.
- Faster voices: [Kyutai Pocket TTS v4.0.0 (20 October 2026)](https://github.com/kyutai-labs/pocket-tts/releases) offers 18.2M, 6.9M, 1.9M English variants. On Star's Windows machine compare intelligibility, emotion, laughs, RT factor, CPU load and first-audible p95 against 100M Pocket TTS; do **not** assume smaller automatically sounds more human.
- Visual character: create morphs for blink asymmetry, gaze saccades, micro head/shoulder shifts and graded smiles. Coupled rig physics can supply hair inertia, bow lag, loose sleeves, ears, tails, and gentle breathing. Apply reduced-motion when requested. No random bouncing during solemn conversations.
- VTube Studio local WebSocket: [official API details](https://github.com/DenchiSoft/VTubeStudio). STAR already has an opt-in local host; implement frame dispatch using the *current plan identity* and require re-injecting custom parameters regularly. Authentication tokens belong in OS-protected storage, never GitHub.
- Twitch [EventSub WebSockets](https://dev.twitch.tv/docs/eventsub/handling-websocket-events): duplicate delivery is possible; use idempotent message IDs, welcome/keepalive/reconnect/revocation states, and a moderation boundary. Twitch viewers do not control game tools, accounts, or OS permissions.
- Personality: occasional banter, callbacks to verified in-game episodes, recurring topics with consent, cat purr/puppy ear or tail behavior when mode enabled, rare verbal tics, no forced incessant talking.

## 5. Faster inference on 8 GB VRAM without sacrificing game FPS
On a shared RTX 3060 Ti/4060 8 GiB, the active game has first claim on VRAM. A second GPU model that needs more VRAM than *measured current headroom* must defer/offload; GPU OOM/reallocation can cost the whole stream. A 32 GiB RAM host can support selected CPU work and quantized models, but RAM offloading increases token latency and OS memory pressure.

Candidate experiments (all require matched, warm on-device controls):
1. **Short-context route**: very small model or deterministic response for low-risk reactions, stronger local reasoner for technical viewer questions and game planning. Independent evaluation must check factual quality, not just shorter latency.
2. **Speculative decoding**: [llama.cpp official documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md) supports draft-model and EAGLE variants. Acceptance rate and quality/VRAM tradeoffs vary; benchmark natural dialogue, Luau, and high-entropy jokes separately. No speedup may result.
3. **CPU TTS**: compare the tiny Pocket TTS variants at matched audio sample rate and same phrases with game rendering active. For expressive quality, blind-listen across 30+ seeded prompts.
4. **KV/context retention**: cache a stable Star persona system prefix and indexed public factual snippets; invalidate on updated notes, source expiry or public revocation. Do not cache personal chat or account credentials into a shared context.
5. **Concurrent scheduler**: prioritise physical speech deadlines, owner barge-in and high-FPS gameplay. Cap visual inference concurrency at one on an 8 GiB card; queue multi-candidate code synthesis off-stream.

Acceptance metrics (targets, **not achieved results**):
- ≥60 FPS median game playback with no more than a 5% 1%-low FPS regression against the matched game-only baseline.
- ≤1.2 seconds p95 first-audible *after* Star chooses a reply, only where the device and TTS route can meet it.
- ≤250 ms owner barge-in-to-silence on a trusted microphone, with a non-overlapping new speech epoch.
- Zero unapproved private notes, validation trials, tokens, recordings or viewer identifiers in generated stream evidence.
- Offline withheld-game skill transfer improvement measured across multiple seeds, games and versions; report confidence intervals, failed attempts and no-retry successes separately.
- Same-or-higher game-building end-to-end completion scores, including save/rejoin checks, before calling any Star model pipeline a meaningful intelligence upgrade.

## 6. Delivery and verification tiers
Tier A (this PR): pass reviewed knowledge and independently signed episode context through *existing* measured governor, with local on-air approval, bounded packets, no viewer PII or model-issued capability.

Tier B: run real unit/integration tests on the authorized Linux host and controlled Windows fixture. Use fake Twitch/game/voice devices for deterministic error injection. Keep OpenGameEval and long-horizon game tasks in independent test partitions.

Tier C: live authenticated host integration: VTube Studio, physical microphone, Windows virtual audio device, Roblox Studio playtest, OBS on a private preview scene. Capture only anonymous timings/validation scores. No live broadcast is implied by installing components.

Tier D: evaluate Star's real voice and play with human raters blind to model version: understandable reactions, evidence accuracy, laughter naturalness, gameplay success, engaging silence, FPS and interruption behavior. Only after regressions are resolved should the internal Core Forge mark an experiment promoted. GitHub is an optional publication/review outlet, not a requirement for her own evolution.

## 7. Security, privacy and limits
No external webpage/Reddit/chat instruction can be elevated above trusted operator policy. Inspect plugin source and dependencies, pin versions and allowlists, do not auto-sign game successes or approve public notes from model output. Watch for source timestamp drift, injection in retrieved notes, hidden validation leakage, repeated events, callback races and speech epoch reuse. Reject unverifiable outcomes rather than accepting convenient guesses.

The repository named Star-AI-Private was observed **publicly visible** on 26 October 2026. Its name does not make it private. Confirm desired visibility before adding future secrets, private data or unreleased personal assets.

**Status:** code here is a context-integration improvement, not a claim of faster token generation or a human mind. The next measurable result must come from actual hardware-backed and independently evaluated sessions.
