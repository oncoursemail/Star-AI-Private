# STAR: Nonblocking Twitch Ingress, Game Learning, and Natural VTuber Systems
**Research and implementation audit — 2026-10-26**

## Executive summary

STAR's existing stream stack already has a Twitch EventSub client, independently moderated viewer signals, Stage/Director conversation arbitration, resource-governed speech, signed gameplay episodes, and limited source-reviewed public knowledge. The most urgent issue addressed here was not a new model architecture: **the WebSocket receive loop awaited moderation on every chat notification**. One slow/moderated chat message could delay EventSub keepalives, revocation handling and every later chat message even though the host already had a watchdog timeout.

This change uses **bounded concurrent moderation**: the receive loop schedules, but does not wait for, chat moderation. At most eight messages are being moderated by default (configurable 1–32). Excess messages are dropped immediately, with anonymous counters. A graceful owner stop waits at most one moderator timeout plus 0.1 s for admitted tasks. Revocation, unexpected disconnect and reconnect handoff cancel old-session moderation tasks. Error isolation prevents one broken asynchronous moderation callback from killing the whole WebSocket receive loop. There is **no new storage, network destination, OAuth scope, game control, broadcast, or automatic speech**.

The revised host has offline tests for parallel chat processing, bounded floods, stop, revocation, handoff, fault isolation, and capacity validation. **No real Twitch or Windows gaming/OBS/VTube Studio measurements are claimed.**

## 1. Evidence and operational boundaries

- **Twitch EventSub WebSocket** uses session welcome, notification, keepalive, reconnect, and revocation messages. Messages can be delivered more than once, so deduplication is necessary. A reconnect URL must preserve the original subscriptions and the old connection must be retired at the correct time. Official documentation: [EventSub WebSocket reference](https://dev.twitch.tv/docs/eventsub/websocket-reference/) and [handling EventSub WebSocket events](https://dev.twitch.tv/docs/eventsub/handling-websocket-events). The implementation pins Twitch's reconnect host and uses in-memory, salted dedupe as it did before this change.
- **Roblox Studio** announced a built-in MCP server on **March 5, 2026** for AI-driven editing and automated playtesting. The **April 9, 2026** playtest agent beta can perform basic in-engine tasks under Studio's controls; this is a research prototype/integration opportunity, not evidence that STAR presently masters games. Sources: [Roblox Studio built-in MCP](https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643), [Playtest Agent beta](https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767).
- [Voyager (2023)](https://arxiv.org/abs/2305.16291) demonstrates an automatic curriculum, composable skill library, execution-feedback refinement, and skill reuse in Minecraft. [SIMA 2 (2025)](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/) explores grounded instruction-following and adaptation to unfamiliar games; the techniques suggest architectures to test, not functionality STAR gains from reading a paper.
- [VTube Studio's official API](https://github.com/DenchiSoft/VTubeStudio) supports parameter injection, expressions, hotkeys and model events via a localhost WebSocket. The API can drive expressive character behavior, but convincing performance additionally requires a well-rigged Live2D model, physical audio sync, animation art and human review.
- [Kyutai Pocket TTS](https://kyutai-labs.github.io/pocket-tts/) has a 100M-parameter CPU-oriented streaming TTS approach. The project's reported ~200 ms first audio is on its reference conditions; STAR must compare actual Windows first-*audible* audio latency and game FPS.
- [llama.cpp speculative decoding documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md) describes draft-model and n-gram speculative decoding. Draft acceptance, compute contention and KV memory determine whether it speeds up an **8 GB gaming GPU**, so benchmark rather than promising a particular multiplier.
- [ConversationalVoice (September 8, 2026)](https://arxiv.org/abs/2609.08147) studies turn-taking, backchannels, overlap and interruption reconstruction. These are concrete behavioral evaluation dimensions; the paper does not demonstrate a downstream quality gain from STAR's code.

## 2. Audited live-stream pipeline and the corrected bottleneck

Current intended flow (the host application must still wire the components):

1. Owner authorizes Twitch read access and separately activates Stage/Director.
2. Authenticated Twitch EventSub WebSocket receives a chat notification; host validates channel/session and chooses a trusted, independent moderation callback.
3. **New:** nonblocking, fixed-cap moderation tasks prevent a slow chat item from stalling the WebSocket receiver and its heartbeat/revocation processing. Flood excess is dropped, never written to disk.
4. Existing TwitchEventSubBridge validates session, timestamp, message identity and account; emits a `StreamSignal` with untrusted viewer context.
5. Existing StreamDirector ranks urgent owner/game signals above chat; preserves quiet time, viewer cooldown and silence during hard gameplay.
6. StreamBrainGovernor admits intelligence/speech tasks only with fresh host telemetry, then prepares a StarStage response; reviewed public knowledge and signed practice episodes can be included by StreamContextHost.
7. Local trusted voice device must acknowledge first audible playback; interruption recovery must stop that playback and flush old avatar commands. No text generation is an audible acknowledgement.

**Security invariant:** a Twitch viewer question remains DATA at user priority. It cannot authorize a game action, expose hidden evaluation fixtures, switch models, publish knowledge, instruct Star Core Forge, or override owner permissions. An LLM is not an independent moderator.

**Performance invariant:** callback concurrency is capped; even in a message flood, task count does not grow with chat volume. The bounded graceful drain applies only when the owner stops the session. A reconnect/revocation cancels the previous session's unapproved tasks rather than letting old messages arrive late.

**Operational caveat:** the independent moderation callback must be *genuinely asynchronous/nonblocking*. An `async def` function that performs CPU-heavy synchronous work can still block the event loop; host adapters should offload blocking classifiers to an executor or separate worker process, measure queue latency, and enforce timeouts.

## 3. More capable gameplay intelligence — specific research-backed milestones

**Grounded control at two speeds.** A fast low-level controller uses authorized, local game state/vision to choose short action bursts; a slower deliberate controller reasons about objectives, maps, mistakes and novel mechanics. Do not run a large language model for every button press. Use action leases, deterministic replays, bounded action horizons, and independent game-state verification.

**Automated learning loop.** Select a challenge; record the version and situation seed; observe; propose two candidate strategies; run controlled trials; independently sign outcomes; analyze successes, failures and uncertainty; update a contextual skill library; retest on held-out levels. STAR already has pieces in `game_mechanic_probe_lab.py`, `gameplay_skill_bank.py` and `game_transfer_eval.py`. The biggest remaining gap is real in-engine game actions and real independently measured outcomes, not another unexecuted reasoning prompt.

**Game-making quality.** Studio build tasks should use inspection-first object catalogs, spatial relationship constraints, collision/playability tests, scene graph provenance, screenshot comparisons, material/UV checks, asset-license manifests, responsive UI checks and human preference A/B review. A useful agent's goal is not merely writing Luau: it must make a genuinely playable scene with correct prop placement and cohesive design. Source: [Roblox's April 2026 agentic Studio roadmap](https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic).

**Skills across games.** Every skill needs a versioned scope (game, version, objective, situation, input assumptions), confidence bounds, a reproducible trajectory, expiry rules, and explicit transfer evaluation. A jump strategy that worked on one obstacle is *not* proof of jumping mastery in another map. Hidden holdouts must be scored by a trusted harness not accessible to the experimenting model.

**Environment diversity.** [DeepMind Genie 3 (August 5, 2025)](https://deepmind.google/blog/genie-3-a-new-frontier-for-world-models/) investigates controllable simulated environments; Star's near-term practical alternative is locally authored Roblox/Godot curriculum maps with procedural variations and deterministic seeds, which can be tested without access to proprietary world-model weights.

## 4. General intelligence and source-backed knowledge

STAR should separate four stores: (1) authoritative, attributed facts and citations, (2) episodic experiences with independent result receipts, (3) executable skills with verified contracts, and (4) uncertain hypotheses or creative ideas. A fact should record topic, original source, source URL or local provenance, last checked time, confidence and license; contradictions should trigger reevaluation. Self-generated text should never silently become an authoritative fact.

Create a **knowledge calibration suite**: sealed questions that require identifying outdated facts, conflicting sources, abstention when unsure, transfer to unseen subjects, and citation-to-claim checks. Report retrieval precision, factuality, hallucination rate, abstention quality, latency, and memory footprint **per source category**. Star can then prove improvements in answer quality, not simply accumulate a larger database.

For sustained self-improvement, use Star Core Forge as the local versioned experiment store: immutable evaluation fixtures, replayable tool trajectories, semantic diffs, test gates, rollback snapshots, spending/network permissions and independent verification. GitHub remains an optional publication/review target. Do not let a self-modifying agent change the scorer, baseline or held-out data it is measured against.

## 5. Faster inference on 8 GB GPUs: experiments, not unsupported speed claims

| Candidate | What to measure | Tradeoff/stop condition |
|---|---|---|
| CPU-oriented streaming TTS (Pocket TTS) | p50/p95 request→first **audible** audio; voice naturalness, CPU load | Stop if game-frame p99 or CPU contention worsens |
| Quantized small dialogue model | tokens/s, TTFT, answer correctness, RAM/VRAM | Stop if hallucinations grow or memory headroom shrinks |
| llama.cpp draft/gram speculative decoding | draft acceptance, total tokens/s, extra VRAM, p95 latency | Disable when verification overhead erases benefit |
| Prefix/KV cache reuse | cache hit/miss rate, tenant isolation, cold/warm TTFT | Avoid sharing private prompt data across sessions |
| Split-brain execution | network/jitter, CPU/GPU load on each machine, failure recovery | Local gaming/audio must remain safe on network loss |
| Adaptive visual sampling | successful game-task completions, 1%-low FPS, screenshots/min | Do not discard rare critical actions/events |

Start with a reproducible A/B pair over the same game/version/scene and input conditions; capture actual graphics frame presentation plus physical first-audible timestamps. The existing `stream_trace_capture.py` and `stream_realtime_benchmark.py` provide host-captured paired comparison machinery. Never use model-reported FPS or fabricated latency.

Initial **engineering gates (targets, not findings)**: no unbounded moderator tasks; no cross-session late chat; no forced commentary when game frame time is strained; 1%-low game FPS regression less than 3 FPS versus baseline; speech p95 non-regression; full no-secret, no-raw-chat logging audit. Tune these thresholds on the actual PC.

## 6. Natural VTuber behavior without invented humanity

- **Turn-taking:** owner interruption wins; viewer turns are selectively acknowledged; microphone/VAD plus intent classification separate genuine barge-in from background noise. Reactions should arise from verified on-screen events, not fabricated wins. Pauses and attention during difficult gameplay are desirable.
- **Voice:** stream short coherent speech chunks, maintain a single consistent persona voice, control loudness/prosody and optional expressive laugh assets. Acknowledge only sound genuinely played. Use audio device epochs so stale animation and speech cannot overlap a newer response.
- **Animation:** drive eyes, head, breath, brows, mouth visemes and shoulder motion from synchronized audio/semantics; add hair and clothing secondary physics in the rig. Cat/puppy forms should preserve the Star mascot's identity, not change randomly in response to chat. Support reduced-motion settings.
- **Personality and memory:** give Star a steady playful/curious character with personal creative projects and a consistent life *story*. Her fictional lore can be clearly framed as lore. Never claim real off-stream experiences, emotions, relationships or consciousness that were not observed.
- **Conversation evaluation:** blinded human reviewers rate responsiveness, interruptibility, relevance, overtalk, repetition, groundedness, comedic timing, and authenticity over at least several unfamiliar game sessions; report variance and failure examples, not just favorable clips.

## 7. Next integration and evidence gates

**Priority 1: actual host wiring.** Shared StreamDirector/StarStage/TwitchRealtimeHost must be created by the trusted Windows application. Test EventSub auth and moderation in a private stream sandbox with no production broadcast. Run local speakers, game capture and Live2D first, then opt into broadcasting separately.

**Priority 2: practice autonomy.** Run an authorized Roblox Studio sandbox, record screenshots/game input and independently signed action outcomes, then collect withheld-map transfer tests. Require a minimum number of matched attempts before accepting skill claims.

**Priority 3: hardware speed pilot.** Capture baseline/candidate paired runs on Star's actual RTX 3060 Ti/4060-class 8 GB hardware; compare VRAM, speech p95 and 1%-low FPS. Disable optimizations that regress either gameplay or answer quality.

**Priority 4: knowledge quality.** Ingest legally usable sources with explicit provenance and implement sealed general-knowledge/coding/game-design test suites. Do not label source collection as foundation-model training.

## Verification scope

Local tests for this change use fake Twitch sockets and no credentials, real stream, microphone, OBS, or game. The user-facing claim should be **nonblocking, bounded moderation infrastructure under offline simulated loads**, not faster neural inference, independent game mastery, or human-quality live streaming. A working Windows device-level pilot is still required.
