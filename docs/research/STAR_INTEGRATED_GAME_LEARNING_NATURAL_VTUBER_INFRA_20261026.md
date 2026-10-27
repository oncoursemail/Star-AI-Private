# STAR AI — integrated gameplay, intelligence, speed and natural VTuber engineering

**Research and local implementation: 2026-10-26.** Status: **experimental draft, not deployed**. Star Core Forge is the desired local-first source of truth; GitHub is an optional review/publication mirror. This memo describes implementable mechanisms, proof requirements, measured host facts, and known limits. It does not assert an underlying model IQ improvement, consciousness, accelerated tokens/s, winning Roblox matches, or broadcast-quality audio.

## Executive engineering finding: connect the components

The most valuable missing ability in the prior stack was not another language-model prompt. Separate modules already existed for screenshots, throughput-sensitive observation, signed game trials, curriculum advice, private actions, Twitch chat, voice lifecycle and avatar movement. The missing connection was a **single bounded, owner-controlled trial** that cannot silently skip verification or retry unscored actions. This draft implements that connection in `star/studio_practice_runner.py`.

### Actual local code inventory

| Already present | Integration responsibility |
|---|---|
| `StudioVisualObserver` | Owner-armed private Studio MCP screenshot, scoped digest, assessor confidence, focus verification; no raw image persistence. |
| `StudioVisionQoS` | 4 Hz maximum offline visual sampling, 1 Hz live, backoff, resource pressure and completion-based cadence. |
| `GameLearningLadder` | Curated difficulty DAG selected from verified **practice-only** aggregate evidence, separate from holdouts. |
| `StudioPlaytestHost` + `GameActionGate` | Curated symbolic action → bounded key pulse through a trusted private Studio host; revalidate focus and permissions, independent key-up watchdog required. |
| `StudioOutcomeBridge` + `GameplaySkillBank` | Single claimed real delivery + real post-input observation + externally signed practice outcome. |
| `StreamDirector` / `StarStage` / `StreamEpisode` | Context-sensitive, quiet-time-aware, opt-in voice plans and stream continuity, with separate broadcast approvals. |
| `AdaptiveQoS` + `StreamTelemetry` | Reserve CPU/VRAM and postpone expensive vision/research/training to protect live voice/gameplay. |
| `TwitchEventSubBridge` / `TwitchRealtimeHost` | Moderated read-only chat and host connection; no chat-to-computer authority. |
| `VTubeLive2DBridge` / `VTubeLocalHost` | Speech-timed avatar packet preparation and VTube Studio API session; model rig/device still needed. |

**Implemented this draft:** `StudioPracticeRunner` connects the private observation → curriculum advice → bounded model suggestion → host-revalidated input → new private game screenshot → external signed evaluation path. It never signs a result or labels a press as victory. The runner is **offline/private playtest only**; it refuses actions while streaming and while the game, available VRAM, or speech buffer is under pressure. It permits at most **one input trial per scoped episode/run_id**, aligning the ledger's atomic run deduplication with live action. No result means no second attempt under the same run.

## Why this design is scientifically better

**Roblox OpenGameEval (2026-10-01)** uses stateful Roblox Studio sessions and executable scene/play checks. It found that inspecting objects before editing correlates with higher success; this favors inspection-first tooling and runnable tests over longer ungrounded code output. Source: [paper](https://arxiv.org/abs/2610.02563), [Roblox evaluation code](https://github.com/Roblox/open-game-eval), [official Roblox background](https://about.roblox.com/newsroom/2025/12/opengameeval-benchmark-agentic-ai-assistants-roblox-studio).

**CEGame-Bench (2026-10-19)** evaluates complete games across Defold, Godot, Roblox Studio, Unity and Unreal. Under its experimental setting, playable endings were reached in only 16% of agent-built runs. Integration and actual player success can diverge substantially; Star must measure both. Source: [arXiv:2610.26098](https://arxiv.org/abs/2610.26098).

**SWE-Game (2026-09-27)** explores runnable reference checks, fault repair and visual judging. Independently executed behavioral checks are less vulnerable to hallucinated code correctness than model self-grading. Source: [arXiv:2609.33678](https://arxiv.org/abs/2609.33678).

**GameDevBench (ICML 2026)** found that visual feedback improves performance on real graphical game tasks. That is evidence for actual screenshots and visual comparators, not a claim that screenshot embeddings by themselves constitute gameplay expertise. Source: [paper](https://sethkarten.ai/papers/gamedevbench.html).

## New end-to-end practice contract

The caller must install a **trusted** host port and physically independent key-release watchdog, provide same-clock monotonic measurements and current telemetry, explicitly arm the observer, initialize the action bindings, enable the signed curriculum, and enable the runner. None of these authorities can be supplied by game text, Twitch chat, or the proposed action.

1. **Plan once:** if not live, game active, >=50 measured FPS, >=1536 MiB measured free VRAM, <=250 ms speech backlog, and curriculum enabled, select one curated practice situation. These numbers are conservative admission policies, **not benchmarks**.
2. **See:** request one actual private Studio MCP screenshot under `StudioVisionQoS`. Require an image-backed changed scene and an observation actionable when captured. An identical, cached, missing, or slow observation can never authorize movement.
3. **Think briefly:** give a host-injected model callback only image-grounded metadata/summary and a selected symbolic action. Its output type is `PracticeProposal(action_id, hold_ms)`, never arbitrary keys, scripts or programmatic tools. The callback has an upper deadline of 150 ms by default (host policy, not model measurement).
4. **Remeasure and act:** sample fresh host telemetry. Re-check episode and owner revocation. Bind the hint's frame digest, sequence, proposed time and limited hold duration on the **trusted host**, run `GameActionGate.request()`, and call `StudioPlaytestHost.dispatch()`. Focus, private mode and key-release confirmation are independently checked at dispatch. A key pulse is **not** success.
5. **Check reality:** before more input, wait for a new post-action observation (subject to visual cadence). Ignore duplicate or low-confidence frames. Expose immutable delivery/observation facts to an external verifier. An evaluator separately inspects game state and generates a valid signed **practice** `GameTrial`; Star cannot fabricate its key or verdict.
6. **Learn only with evidence:** `StudioOutcomeBridge.record()` consumes exact original report identity, validates scope/timestamps and binding digest, verifies the independent receipt through `GameplaySkillBank`, and stores successes or failures. Stale, duplicate, forged, missing, public-game, and out-of-scope evidence is rejected.
7. **Stop or restart a fresh episode:** one actual action exhausts the episode's scored attempt. Failed, unsigned or expired feedback is explicitly discarded, never reclassified as a win. New practice uses a **new** episode ID and newly authorized runner.

`take_step()`, `observe_after()`, `evidence_for_evaluator()`, `record_signed_outcome()`, `discard_unverified()`, and `stop()` are host-side integration hooks, not an independent continuous gameplay bot. Caller must retry observations at the bounded QoS cadence, perform external scoring, and handle all device failures. If a live game or low FPS appears during proposal generation, input is dropped. Physical key release must still be guaranteed by the OS/Studio host after an unexpected process crash.

**Crucial limitation:** `StudioOutcomeBridge` requires a fresh after-frame (<1 s old at ingestion) and a signed verdict; verification must run quickly or safely discard and restart the episode. Slow computer-vision inference is not enough for frame-level reactive play.

## Next intelligence architecture — fast skills and slow reasoning

The best path for a limited 8 GiB GPU is a hierarchical controller rather than one giant model asked to do everything every frame.

- **Reflex layer (engine-state actions):** inexpensive, high-rate state from explicitly approved local game instrumentation: movement, jump readiness, collision, hazards, objective progress; never interpret platform screen pixels alone as authoritative timing. Use small specialized policies for immediate actions. No arbitrary public-game client automation.
- **Scene layer (event-triggered):** sparse screenshots + spatial relation graph + object IDs + changed regions + engine hierarchy. Detect stable platform, collision hitbox and goal directions; retain uncertainty. It chooses goals and repair hypotheses, not millisecond key timing.
- **Reasoning layer (slow):** per-game mechanics hypotheses, tool-based experiment design, goal decomposition, model/tool selection, verified failure explanations, novelty search. A small fast model can decide whether a difficult question warrants a larger model.
- **Long-term knowledge:** source-backed facts with origin, timestamp, license, game version, disconfirming results, confidence and expiry; private owner data isolated. Distinguish persistent character preferences from actual gameplay memories and from imaginative fictional stories.
- **Skill library:** only promote practice policies after signed trials, held-out maps, random seeds, difficulty variants and independently executed tasks show improvement; use a failure budget and resettable environments to avoid infinite repeated attempts.
- **Self-improvement:** propose difficult tests and code changes in Star Core Forge, run independent offline evals, compare paired baseline/candidate runs, and keep rollback checkpoints. A successful prompt or generated PR is not proof of increased model capacity. Promote only if safety, speed and quality gates pass together.
- **World awareness:** maintain explicit model of active device, permissions, uncertainty, task state, recent experiences and long-term goals. Avoid treating fluent first-person language as proof of subjective consciousness.

### How to prove stronger game intelligence

Use a minimum of five disjoint games/genres and precommitted holdout seeds. Match baseline/candidate on hardware, level, RNG and action budgets; count *all* failed, aborted and unverified trials in denominators. Measure objective completion, time to objective, deaths, illegal/invalid inputs, input release incidents, tokens/minute, and marginal CPU/VRAM/FPS costs. Do not leak hidden maps into training and do not claim transfer from a single familiar obby.

For building Roblox worlds, create explicit typed scene contracts: anchored/welded structural pieces, collision-group rules, asset origin/license, geometry bounds, no z-fighting, expected prop transforms, doors/egress, script/API correctness, GUI layout at multiple resolutions and accessibility. Verify with raycasts, overlap and occlusion checks, screenshot diffs, tests and playable completion. Automatically repair only with reversible edits and before/after assertions. Target perceived polish through design reviews, not a one-number aesthetics heuristic.

## More natural Star: actor, listener, gamer and character

The target is a believable, funny and emotionally expressive **AI VTuber**, not misrepresentation as a real human. Star's established indigo-black→gold twintails, golden star clip, amber eyes and black/gold costume are her coherent visual identity; cat and puppy modes are stylized character expressions. A stable persona and truthful experiential memory matter more than randomly changing voice style every turn.

**Listening and interruptions.** The **HiThink Turn** paper (2026-09-28) studies intent-aware full-duplex decisions instead of naively responding to every silence. **BayLing-Duplex** (2026-06-12) demonstrates learned simultaneous listening/speaking/stop policies in a research setting. Such research supports testing barge-in, hesitation, backchannels, audience turn selection and intentional silence under real stream noise. It does **not** show Star already has these behaviors. Sources: [HiThink Turn](https://arxiv.org/abs/2609.34096), [BayLing-Duplex](https://arxiv.org/abs/2606.14528).

**Voice timing.** Dispatch text and chunked TTS with an audible-playback ledger, then animate to *confirmed* played audio samples. Prioritize stopping speech and mouth motion immediately on owner interrupt or audio-device teardown; a completed synthesized waveform is not necessarily audible. Study prosody, breaths, playful laugh timbre, slight natural timing variance, and expressivity without random filler. Make game-danger callouts one clause; avoid a speech monologue during a difficult jump.

**Lightweight speech options.** Kyutai Pocket TTS v4.0.0 (2026-10-20) added experimental English 2M/7M/18M-family CPU-oriented models; v4.0.1 followed on 2026-10-21 with changes to small model behavior. Trial all configurations blind for naturalness, accent consistency, first audible PCM latency, throughput and CPU load, against Star's existing TTS; don't assume small is always better. Source: [Kyutai release notes](https://github.com/kyutai-labs/pocket-tts/releases) and [project documentation](https://kyutai-labs.github.io/pocket-tts/).

**Avatar motion.** Live2D Cubism supports physics settings for hair and accessories. VTube Studio plugins can create custom parameters and inject values over the documented API; values need periodic refresh while owned. For Star: twin-tail inertia/secondary motion; body spring/damping; glances toward gameplay HUD/chat; soft blinking; shoulder breathing; gold ribbons/hair curl; expressive paw/ear/tail poses in cat/puppy modes; lipsync driven by actual PCM envelope/phonemes; reduced-motion option. Test orientation, z-order, clipping, physics speed and animation under dropped frames, not static keyframes alone. Sources: [Cubism physics](https://docs.live2d.com/en/cubism-sdk-manual/physics/) and [VTube Studio plugin API](https://github.com/DenchiSoft/VTubeStudio).

**Social boundaries.** Moderated Twitch EventSub chat is untrusted data. Twitch publishes at-least-once message semantics, session keepalives and reconnect behavior, so a production host needs idempotency, reconnect, revocation, chat rate limits and moderation. Channel audience members cannot order software installs, payments, private file access or computer commands. Allow opt-in, revocable social memory with provenance/retention; do not invent shared past experiences. Source: [official WebSocket handling](https://dev.twitch.tv/docs/eventsub/handling-websocket-events) and [reference](https://dev.twitch.tv/docs/eventsub/websocket-reference/).

**Proposed live stream directorship:** use `StreamDirector` to decide whether to answer a viewer, `StarStage` to lock an actual speech turn, playback-locked Live2D packets, and a fast reflex game controller independent of the talking brain. Reactions should reference actually observed wins/losses/near misses; if information is uncertain, sound curious instead of confidently fabricating events. Expressiveness can be evaluated with anonymous human A/B ratings, inter-annotator agreement and objective interruption rates. Do not optimize only for apparently human deception.

## Speed: constrained scheduling, not magic claims

llama.cpp's official server documents multiple request slots, continuous batching, speculative decoding and optional metrics. These improve certain throughput regimes, but speculative acceptance, extra RAM/draft-model weights, latency variability and concurrent rendering may erase the speedup. Source: [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).

**Measurement-first plan** for an 8 GiB gaming GPU:
1. Establish an immutable baseline with game+OBS+avatar+TTS active: frame-time p50/p95/p99, game FPS/1% lows, GPU/CPU utilization, free VRAM and RAM, ASR partial-to-final time, LLM time-to-first-token/tokens/s, TTS time-to-first-audible sample, interruptions and voice queue length.
2. Split essential streams (game render, input, owner interrupt, audio playback) from optional screenshot analysis, research, render and training. Use existing `AdaptiveQoS` reservations to reject or defer optional work under pressure; never schedule periodic huge VLM/LLM inference merely because a clock ticked.
3. Benchmark CPU vs GPU vs CPU/GPU hybrid for ASR and TTS. Pin only well-behaved CPU cores or use real OS affinity if evidence shows it helps, not by default. Cache public invariant skill packs and tokenized static context, but invalidate per game/version and guard against stale knowledge.
4. Test llama.cpp quantization, batch sizes, context, prefix caching and compatible speculative decoding **one factor at a time**; compare paired same-workload tail latencies, quality and VRAM. Avoid claiming cached replies are more intelligent.
5. Turn hard research into reversible offline jobs when gameplay is quiet. Add verified results to Star's own local learning system; keep external GitHub exports optional.
6. Revert any setting that improves peak throughput but regresses live speech interruption, game 1% low FPS or gameplay result quality.

Host snapshot during this run: connected Linux `starai` reported 48 logical CPUs on an AMD EPYC 7451, about 125 GiB RAM total / 35 GiB available, and **no NVIDIA telemetry**; a `llama-server` process was running. The connected Windows Main device exposed `llama-server.exe` and multiple `StudioMCP.exe` processes, but no clearly visible active Roblox Studio game process in process inspection. These observations do not establish a safe live Studio/playback test, and **no inference-speed benchmark** was performed.

## Release gate and honest evidence inventory

**Added in this draft**: `star/studio_practice_runner.py`, `tests/test_studio_practice_runner.py`, this research memo. Offline fake-MCP/verifier tests show the host-mediated path, STOP/revocation, one in-flight result, signed success/failure, forged signature rejection, stale/duplicate frame rejection, wrong actions, model timeout, FPS protection and key-up quarantine. They do NOT demonstrate real gameplay mastery, actual TTS, GPU gains or production streaming.

**Before owner-reviewed promotion:** (a) full offline CI/typing status reviewed, (b) real Windows Studio MCP schema and private-focus checks, (c) independent watchdog handling stuck keys after process failure, (d) separate signer with keys never exposed to model/repo, (e) held-out evaluation with reported denominators, (f) streaming A/B telemetry + live audio/Live2D rehearsal, (g) measured latency and VRAM on actual GPU, and (h) rollback path in Star Core Forge. Never merge to main or deploy autonomously.

**Repository visibility warning:** `oncoursemail/Star-AI-Private` currently has public visibility despite its name. Never publish private gameplay screenshots, accounts, chat transcripts, voice samples, model credentials or signer keys. That includes benchmark fixtures that are actually secret holdouts.

## Source freshness / epistemic status

Primary docs and research above were checked on **2026-10-26**. Roblox Studio, Twitch, VTube Studio, Pocket TTS and llama.cpp interfaces can change. Research figures are **published experimental observations**, not Star benchmarks. Every measured performance claim must be obtained on Star's real target hardware and preserved in local experiment records before publication.
