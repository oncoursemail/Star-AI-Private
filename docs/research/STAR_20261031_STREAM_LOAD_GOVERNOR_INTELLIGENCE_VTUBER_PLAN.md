# Star AI — evidence-driven streaming performance, game learning and believable VTubing
**Research and implementation note: October 31, 2026.** Status: code and synthetic regression tests committed to PR #845; not installed on the gaming PC, integrated into OBS, or benchmarked in a livestream.

## Executive finding

Star's next major bottleneck is **contention**, not simply model parameter count. The same 8 GB gaming GPU can be asked to draw a game, composite OBS scenes, encode frames, animate an avatar, perform vision inference, prefill an LLM, and possibly synthesize speech. Increasing standalone token throughput can make the *whole experience worse* if it disrupts frame pacing or the conversation. The next phase should use **measured priority admission**, then build fast-path gameplay and independently verified offline learning on that foundation.

This work adds `star/stream_load_governor.py`, a backward-compatible `StreamDirector.propose(load_advice=...)` pressure-aware speech filter, and two offline test modules (22 focused synthetic tests passed locally on the authorized starai host). It is an owner-opt-in, dependency-free, **advisory-only** resource gate; the director selectively reduces optional speech when explicitly given its advice. It does not operate OBS, change settings, interrupt speech, start game inputs, manage secrets, or implicitly enable background learning.

## 1. New implemented component: stream load governor

**Input:** independently host-attested, fresh telemetry snapshots, using a common monotonic clock. The host provides game frame p95, target FPS, the recent *interval percentages* of OBS render misses, encoder skips and network drops, observed GPU VRAM use/capacity, TTS p95 time-to-first-audio, and OBS connectivity.

**Output:** one of `disabled`, `warming`, `normal`, `constrained`, `critical`, or `telemetry_stale`, with a reason and bounded recommendations for optional narration, extra GPU inference, background workers, and possible CPU voice experiments. Recommendations are not executors and do not imply permission to act.

**Privacy/trust:** disabled by default; explicit owner approval required; reject unverified, stale, out-of-order, repeated, future-dated and malformed samples; never retain prompt text, audience messages, private viewer identifiers, GPU serial numbers, stream keys or audio. Reconnect handling and session-authenticated telemetry stay in the host.

**Stability:** a single severe load sample escalates immediately. Recovering toward normal requires three consecutive lower-pressure observations *per severity step*. Missing telemetry fails quiet rather than incorrectly reporting healthy status. A bounded sample-ID cache limits duplicate receipts; the controller uses a reentrant lock for simultaneous gaming/OBS/TTS callbacks.

**Safety reserve:** on normal snapshots the controller reserves at least 20% of reported VRAM (or 768 MB, whichever is greater) for the game/OBS and only advises extra GPU inference when the remaining estimated budget exceeds 1 GB. This is an *upper bound*, not a promise of physical allocation or protection from driver/allocator overhead. Under constrained or critical pressure it advises 0 MB of extra GPU inference. Background learning is always recommended paused during the streaming session.

**Initial thresholds are conservative hypotheses, not benchmarks:** critical if OBS render missed >=3%, encode skipped >=2%, network dropped >=4%, game p95 >=1.8x frame budget, VRAM >=96%, or OBS disconnected. Constrained if render/encode >=0.5%, network >=1%, game p95 >=1.25x frame budget, VRAM >=86%, or first-audio p95 >=900ms. Tune only against labeled real hardware data, keeping separate network, encoder and rendering diagnoses.

### Host integration sequence (OBS/host scheduler adapter NOT implemented here)

1. Authenticate to the local OBS websocket with its password, on loopback/private network. Record GetStats at regular intervals, and calculate *positive counter differences* divided by corresponding total-frame differences. Do not feed lifetime percentages as current load.
2. On OBS reconnect, counter reset, device restart or missing denominators: discard the previous baseline, mark `obs_connected=False` or telemetry stale, and require fresh stable samples. Do not silently turn a counter reset into 0% frame loss.
3. Use the same host monotonic clock for frame, voice and load snapshots. Only the trusted host may set `host_verified=True`. Call `enable(owner_approved=True)` only after stream/session consent.
4. Feed `StreamLoadSample` to `ingest`; call `recommend`. Map recommendations through *independently owner-approved* scheduler capabilities, never general text instructions from chat. On constrained/critical: pause night-school jobs, avoid optional commentary, retain owner-interrupt and danger handling, and consider limiting high-memory vision/LLM experiments. Keep necessary TTS and OBS alive.
5. On the trusted stream host, pass the fresh recommendation into `StreamDirector.propose(now=..., load_advice=advice)`. In constrained mode the director suppresses small talk, ambient observations and optional game narration, but preserves moderated questions and independently verified successes; in critical/warming/stale modes only host-verified danger signals and authenticated owner interruptions remain eligible. Omitted advice preserves the previous behavior, so this does not silently activate itself. Collect anonymized latency/quality metrics. **Never modify stream bitrate/resolution automatically** based on this advisory: network loss is not GPU overload, and abrupt settings changes can themselves break a broadcast.

The OBS websocket project's protocol exposes fields such as `renderSkippedFrames`, `renderTotalFrames`, `outputSkippedFrames`, `outputTotalFrames` and render time. OBS' own troubleshooting guidance emphasizes that scene complexity and output resolution affect resources. Do not assume the websocket Stats fields contain every network metric: combine with an independently verified streaming-output monitor, and validate semantics against the installed OBS version.

## 2. Inference intelligence and real speed

**Keep separate latency budgets.** Frame deadline responses must finish within their observation action window; chat responses may tolerate more deliberation; long-form coding/research is entirely separate. A 40 tok/s model can still feel slower than a 20 tok/s model with lower time-to-first-token, fewer re-prefills, tighter tool dispatch and less GPU contention. Audit end-to-end delays: observation capture, queue wait, inference prefill, generation, verified action dispatch, TTS first audio, actual playback, and avatar reaction.

**Three inference lanes:** (a) immediate game controller with strict deadlines and no external high-risk actions, (b) medium context for chat and OBS-safe dialogue, (c) slow teacher for game review, code generation and reasoning only when resources allow. Admit GPU jobs from host-measured headroom, not naive LLM token/sec estimates. Under stream pressure, use bounded short responses, CPU-safe operations and strict background admission; do not forcibly substitute a new TTS model without voice-quality and CPU profiling.

**llama.cpp experiments:** measure base vs prompt-prefix reuse vs n-gram/draft/EAGLE-style speculation with SPEED-Bench. Record p50/p95/p99 first-token latency, achieved tokens/sec, accepted draft-token rate, VRAM/RAM peaks, OBS dropped frames, game frame p95, speech delay and system stability. Speculation can be slower if acceptance is low or a second model competes for memory. Test slot/session isolation; a reported August 15, 2026 llama.cpp RAM prompt-cache issue describes unintended cross-conversation reuse under concurrent load. Treat it as a risk requiring local regression, *not* evidence that Star's current deployed version is affected. Pin and record the version, disable unsafe cache modes pending isolation checks, and never use cross-user caches for untrusted viewer prompts.

**Rust selectively:** use Python to coordinate system behavior. Profile and port high-frequency perception preprocessors, frame transforms or message serialization to Rust only if they dominate measured CPU time. Benchmark PyO3 call overhead, serialization copies, GIL contention, fallback behavior, packaging and rollback. Rewriting everything to Rust does not make model inference intrinsically faster or solve GPU VRAM limits.

## 3. Real autonomous gaming competence

Make game learning reproducible, not a narrative claim. Existing signed game-evidence, practice-curriculum, deadline-router and Core Forge components should be integrated under a single **play -> inspect -> explain -> test -> compare -> promote** cycle.

- **Live path:** only authorized games and permitted controllers; fast scene-to-action policy, confidence and deadline checks. No anti-cheat evasion, unrestricted access, or unapproved game-control escalation.
- **Offline teacher:** analyze independent trajectories after a game; identify the exact missed cue; generate a targeted drill with known starting state and scoring rule; compare candidate improvements on held-out maps and unseen opponents. Record deterministic seeds and task versions.
- **Promotion:** independent evaluator must show repeated success and no regression in previously mastered skills. Revalidate after retention windows; do not count old wins as current proficiency. Promote passing code/policy through Star Core Forge's signed local revision and rollback checkpoints. GitHub is for optional publication, not needed for internal learning.
- **Long-horizon skill library:** distinguish control mechanics, navigation, team strategy, social interactions and game-specific facts. Store observation/evidence, timestamp, source, license and confidence. Never turn viewer claims into verified game facts.
- **Self-play labs:** isolated, inexpensive custom games for motor/control learning; Star can generate new levels, play, inspect rendered evidence and create novel practice tasks. Evaluate novelty and usability externally, not solely with Star's self-assessment.

## 4. Humanlike VTuber experience without false autobiography

Natural expression is a **synchronization** and personality problem as much as a voice problem.

- **Attention:** select one conversational target (owner request, game emergency, moderated chat question, spontaneous observation) rather than narrating everything. Silence when concentrating is good behavior. Respect the existing stream director's fairness and bounded queue; use real platform IDs only at a trusted ingress, with session-local pseudonyms downstream.
- **Turn timing:** compare LiveKit's documented local CPU `v1-mini` audio turn detector with current VAD/turn handling using interruptions, laughter, short affirmations and speakers talking over the game. False cutoffs and awkward long dead air matter as much as model latency.
- **Truthful memory:** preserve Star's stable personality, her own interests and recurring jokes, but store real stream experiences separately from invented character lore. She can improvise fictional stories if presented as stories; she should not misrepresent herself as a human or claim events she never observed.
- **Coordinated expressive output:** playback timestamps should drive visemes, blinks, brows, eye gaze, torso/head gestures, ponytail spring physics and contextual expressions. When audio is interrupted or cancelled, cancel the corresponding gesture timeline rather than leave the mouth moving. Preserve reduced-motion options and keep animation CPU/GPU footprint monitored.
- **Creative companionship:** Astro and Amber can interact with Star in authored, consented scenes and play modes, but interactions should be context aware and bounded—not randomly interrupt important gameplay.
- **Safety and quality:** independently moderate audience text, keep viewer data ephemeral, avoid reading secrets aloud, preserve owner stop control, use soundtrack/assets with compatible licenses. Test perceived naturalness with blind human ratings, interruption success and actual latency, not by assuming a TTS brand sounds human.

## 5. Game creation and transferable knowledge

Replace "generated code appears valid" with verified project artifacts. Run Luau analyzers and style/test tooling, inspect existing scene hierarchy before editing, check geometry adjacency/overlap/grip locations, produce reproducible assets, verify interface layouts at multiple resolutions, and run real multiplayer paths. Roblox's StudioTestService supports automated tests with simulated clients and can cover join/leave, lobbies, replication and complete loops (up to eight simulated clients per instance per current documentation). Visual reviews should compare screenshots against an explicit target design and validate physics, lighting, textures, animation and UI, with licensed source tracking.

Expand general knowledge through structured, timestamped retrieval and targeted evaluations across software, engines, physics, design, music, animation and language—not unsupervised collection of every web page. Deduplicate, confirm provenance and licensing, measure whether retrieved lessons improve held-out tasks, and expire superseded tool/API facts.

## 6. Acceptance gates and measurement plan

1. **Offline unit tests:** run `python -m unittest tests.test_stream_load_governor -v` (or pytest's equivalent) and Python typing; cover severe/medium load, three-step recovery, chat-safe failure, 8 GB VRAM reserve, invalid/stale/replayed input, no double-acceptance under concurrency and disabled-by-default behavior.
2. **Synthetic OBS stress:** inject 0%, 0.5%, 3% renderer loss, independent encoder and network losses, 1.25x/1.8x frame delay, VRAM from 40% to 97%, dropped/late telemetry, host clock rewind, and test recovery. Verify no automatic OBS manipulation.
3. **Windows baseline:** with Star off, measure game frame p95/p99, OBS renderer/encoder/network losses, VRAM/RAM, CPU, voice first-audio and GPU power. Repeat with Star enabled. Compare identical scenes and game seeds; include a full stream-length soak and recovery after reconnect.
4. **Performance target:** no statistically meaningful worsening of OBS loss or game frame p95 from optional AI features. Test TTS first-audio p95 below the initial 900ms pressure threshold, but report actual measured baseline and usability ratings rather than promising a universal number.
5. **Learning target:** test held-out games/maps and multiple opponents. Compare old vs new gaming agent under identical time budgets and signed evaluation; keep any promotion reversible. Measure task success and error recovery, not only token speed.
6. **VTuber quality target:** human-rated dialogue appropriateness, correct interruption handling, face/voice sync, purposeful silence, chat fairness and stable persona over long streams.

**Do not mark these acceptance gates complete until hardware tests actually run.** The module and tests are committed, not integrated, not proven faster and not yet connected to OBS.

## Primary sources inspected

- OBS websocket repository and protocol: https://github.com/obsproject/obs-websocket and https://github.com/obsproject/obs-websocket/blob/master/src/requesthandler/RequestHandler_General.cpp (GetStats fields and authenticated transport).
- OBS official encoding performance guidance: https://obsproject.com/kb/encoding-performance-troubleshooting (render and encode overhead).
- llama.cpp SPEED-Bench: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md (latency, throughput, speculative acceptance).
- llama.cpp speculative decoding: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md (draft methods).
- llama.cpp cache contamination report, opened Aug 15, 2026: https://github.com/ggml-org/llama.cpp/issues/27148 (risk to reproduce, not demonstrated in Star).
- LiveKit local CPU turn detection: https://docs.livekit.io/agents/logic/turns/turn-detector/ (v1-mini endpointing).
- Roblox StudioTestService: https://create.roblox.com/docs/reference/engine/classes/StudioTestService (scripted multi-client tests).
- Twitch EventSub WebSocket reconnect and at-least-once messages: https://dev.twitch.tv/docs/eventsub/handling-websocket-events/ (session handoff and duplicate messages).

## Honest deployment state

The opt-in **planning layer**, backward-compatible speech-director filter, and 22 passing local synthetic tests were added this run. Do not claim verified inference speedups, better game wins, newly installed voice models, actual human consciousness, or a successful OBS/Twitch connection. Keep the PR draft, do not merge or deploy automatically, and avoid confidential recordings or tokens in this public repository.
