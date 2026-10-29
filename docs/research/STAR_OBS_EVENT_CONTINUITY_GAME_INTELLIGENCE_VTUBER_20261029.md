# Star AI: authenticated OBS stream-event continuity + faster and more capable local intelligence

**Research and implementation date: 2026-10-29.** This is a bounded engineering increment. No live OBS, Roblox, Twitch, Windows audio device, model retraining, GPU speedup, or actual stream was exercised for this change. All research recommendations below are proposals unless specifically marked implemented.

## 1. Implemented: a real output-event continuity witness

PR #774 supplied an authenticated, read-only local OBS sampler but could not distinguish a stable output from a brief reconnect that occurred *between* GetStats/GetStreamStatus polls. A configurable callback existed for future event attestation, but there was no production adapter. This update supplies that adapter and integrates it with the sampler.

- **New** `star/obs_stream_event_witness.py` uses a dedicated OBS WebSocket **v5** connection, fixed at `ws://127.0.0.1:4455`. It never selects arbitrary hosts or ports.
- Requires an authorized owner host and a nonempty OBS WebSocket password. Handles OBS's official SHA-256 challenge-response handshake and refuses unauthenticated servers. It never saves or prints password material.
- Subscribes only to **General (1)** and **Outputs (64)** event categories, not inputs, live microphone levels, scenes, or viewer data.
- Uses the **same authenticated socket** for read-only `GetStreamStatus` request/response fences; a response only qualifies when it matches a fresh request ID and reports active, non-reconnecting output.
- Every `StreamStateChanged` or `ExitStarted` event detected during an armed interval invalidates the measurement, **even if output is active again at the end**. This catches stop/start and reconnection transitions the periodic frame sampler can miss.
- A missing, malformed, stale, disconnected, unresponsive or conflicting event stream fails closed. The witness rechecks the OBS **PID and OS creation time** and never reconnects silently during a run.
- `ObsReadOnlyProbe.capture(event_witness=witness)` starts the event envelope before initial OBS samples, checks it at each polling tick, and finishes the envelope after final samples. The existing arbitrary `continuity_guard` callback remains for **trusted backward-compatible local test plumbing**; do not substitute `lambda: True` for a genuine witness on a production host.
- No new neural model, frame analysis inference, stream start/stop, OBS setting changes, chat access, network broadcast, recording or media capture is part of this component.

**Caveat:** this establishes independently observable event continuity *as reported by one authenticated OBS WebSocket v5 event connection*. It is not a cryptographic proof that the remote streaming service delivered all frames, nor does it guarantee the OBS server emits every possible failure as an event. Use the separate OBS counters, actual transport statistics and real output playback checks. A TCP failure prevents qualification, rather than being concealed through automatic reconnection.

Sources: OBS official protocol and outputs events, https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md ; obsws-python 1.8.0 dependency and protocol wrapper, https://pypi.org/project/obsws-python/1.8.0/ . The websocket-client direct dependency is pinned to the desktop-only requirements. Existing 2026-10-29 OBS sampler research is in `docs/research/STAR_REAL_OBS_EVIDENCE_HOST_AND_INTELLIGENCE_20261029.md`.

### Owner-authorized, local-only example

This is *illustrative host integration*, not a command for the model to run OBS or to collect owner media. The OS OBS process must already be running with an owner-controlled test stream. Obtain the password only from a protected desktop UI/secret source, never hardcode or log it.

```python
from star.obs_readonly_benchmark_host import ObsReadOnlyProbe
from star.obs_stream_event_witness import ObsStreamContinuityWitness

password = read_obs_password_from_authorized_owner_ui()
events = ObsStreamContinuityWitness()
sampler = ObsReadOnlyProbe()
events.connect(password=password, owner_approved=True)
sampler.connect(password=password, owner_approved=True)
try:
    evidence = sampler.capture(
        pair_id="pilot001", variant="baseline",
        game_id="private_obby", game_version="v1",
        duration_s=10, poll_interval_s=1,
        event_witness=events,
    )
    assert evidence.continuity_attested
    frame_json, transport_json = evidence.jsonl_rows()
    # The owner can persist this minimal, allowlisted telemetry locally.
finally:
    events.disconnect()
    sampler.disconnect()
```

No model-accessible control or automatic streaming was added. This code path must stay OFF until a trusted local desktop host exposes a gated, explicit action. Do not place OBS passwords, viewer identities or private media into repository files.

### Validation required before shipping

1. On an owner-approved Windows machine, verify exact obs-websocket v5 Hello/Identify/GetStreamStatus compatibility, the process-identity detection and the WebSocket response field spellings.
2. Confirm that a genuine OBS **reconnecting -> reconnected** event invalidates a window even when baseline/candidate counters end healthy. Also test output stop/start, OBS process restart, wrong password, WebSocket unplug and an intentionally bad network connection. No fault may pass as a win.
3. Test a real 3–300 s window alongside Roblox, OBS, Star speech, and VTube Studio. Record physical audio onset and actual game render/input latency independently; verify the observer's modest polling overhead does not itself cause dropped frames.
4. Run >=20 pre-registered, matched and order-balanced pairs of baseline/candidate workloads; compare 50th/95th percentiles, 1%-low game FPS, OBS render/encode/transmit loss and output reconnects. Use blinded human review for audible and avatar naturalness.
5. Require a separate owner sign-off to change a streaming or inference default. Passing a statistical QoS gate only means **eligible for manual pilot**, not approval to deploy.

## 2. Higher useful intelligence per second on Star's hardware

Star must maximize verified **task success per second**, not raw token throughput at any price. Her available RTX 4060-class 8-GB gaming machine is simultaneously expected to run game graphics, OBS, avatar physics, visual analysis and speech. A CPU/RAM-heavy back-end can perform slow research and batch verification separately.

**Interactive lane (strict priorities):** direct player input and game rendering -> stream encoder -> audible speech / interrupt and avatar movement -> low-cost game state tracking. Admission-control expensive VLM requests. Retain stable identity/persona policy at the front of cached prompts; put dynamic chat/observation near the tail.

**Research lane (resource-aware):** held-out evaluations, alternate model rollouts, retrieval/indexing, offline game experiments, fine-tuning and Forge changes. Defer them when stream FPS or audio p95 deteriorates. Never allow an unattended speculative model swap during a broadcast.

**Optimization experiments worth a real A/B:**
- Compare llama.cpp prompt caching and cold/hot prefix reuse on *identical* 100-turn transcripts; monitor VRAM, cache hit rate and latency with the same deterministic seeds.
- Test speculative decoding configurations with official llama.cpp SPEED-Bench instead of believing peak token/s claims. Draft quality and CPU/GPU placement are hardware-specific; keep verification counts and answer quality alongside speed.
- Run selective VLM crops at different sampling rates and compare event detection against blind annotated video frames; use full-frame rescans when uncertainty or scene changes are high.
- Compare CPU Pocket TTS voice options to the established Star voice for audible first-chunk latency, clarity, style, laughter and game FPS; smaller weights do *not* automatically sound more human. Kyutai released 18M/7M/experimental 2M English variants on **2026-10-20**.
- Preserve warm model state, retrieval cache and asynchronous workers, but never cache private chat transcripts forever or allow stale retrieved facts to silently become canonical.

Sources: llama.cpp SPEED-Bench official guide, https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md ; Kyutai Pocket TTS 4.0.0 release dated 2026-10-20, https://github.com/kyutai-labs/pocket-tts/releases .

**Decision rule:** accept an optimization only if held-out task outcomes are non-inferior, first-audible-speech p95 meaningfully improves, and both game FPS and OBS output safety gates hold. A saving in model compute that causes an on-stream stutter is a regression.

## 3. From game screenshots to real game mastery

**Evidence goal:** Star learns to finish unknown supported games and unseen levels through repeated play, not by claiming mastery from one generated explanation. GameWorld (2026-04-08) contains **34 games and 170 verifiable tasks** and shows current game agents still struggle with latency, feedback and long-horizon execution. Use its general methodology, not its benchmark results as Star's own score: https://arxiv.org/abs/2604.07429 .

**Proposed feedback loop:**
1. Observe an authorized window/game viewport, identify the controlled character, HUD, goal, hazards, input latency and available actions. Track observation uncertainty and whether the game is paused/menu/loading.
2. Create a small set of competing mechanical hypotheses ("dash resets on landing", "jump range changes with speed") and choose a reversible, short experiment rather than sending long, speculative control sequences.
3. Execute one bounded, authorized input sequence with timeout, stop key and rate limits. Collect before/after observations and independent environment score/checkpoint evidence.
4. Update a compact state model with direct evidence, a confidence interval and a counterexample. Avoid reinterpreting model-written summaries as direct observations.
5. Practice a curriculum: calibration, isolated mechanic, combined mechanic, unexpected hazard, then a **held-out unfamiliar map**. Retain failure videos privately only with owner permission and expiration.
6. Have Star Core Forge compare variants on genuinely unseen problems, with independent verification and a pre-registered scoring contract; failed experiment records are retained without self-modifying the evaluation criteria.

Never autonomously bypass game anti-cheat or violate multiplayer terms. Roblox Studio tests and owner-authorized local practice environments come first; competitive public environments require explicit applicable permissions.

## 4. Building Roblox games people can actually play

Roblox **OpenGameEval** (research published 2026-10-01) reports 84 human-curated tasks scored through actual Roblox Studio behavior, and finds that scene inspection before edits correlates with improved success. This supports an **inspect -> specify -> implement -> verify -> play -> repair** workflow, not one-shot code generation. Source: https://github.com/Roblox/open-game-eval and https://arxiv.org/abs/2610.02563 .

**CEGame-Bench** (2026-10-19) tests entire games with real-input completion, including Roblox Studio, and demonstrates how often source builds fail to become playable. Source: https://arxiv.org/abs/2610.26098 .

Proposed acceptance categories for every Star-authored Roblox game:
- **Spatial integrity:** anchored placement, consistent scale, no missing walls or incorrectly intersecting props, no z-fighting, proper spawn safety and physics.
- **Visual craft:** human-authored visual references, design tokens, UI state coverage, contrast/legibility at multiple screen sizes, original licensed textures/FX and coherent animation timing.
- **Game mechanics:** functional inputs, deterministic objectives/checkpoints, multiplayer replication, budgeted memory/network processing, failure recovery and persisted progress.
- **Player completion:** 1-8 Studio simulated clients plus actual UI/button/keyboard play, unseen starting seeds, ability to reach win/lose state and rejoin.
- **Experience quality:** blind playtesting with human evaluation; reject AI-looking generic filler even when a code verifier passes.

Extend the existing Scene Integrity Compiler and pathfinding verifier with actual Studio TestService execution before claiming true runtime validation. Star should use independent visual and executable checks, not self-awarded quality scores.

## 5. A warmer, more expressive Star VTuber without fabricated humanity

The achievable target is a **persistent, responsive, entertaining digital performer**, with stable personality and memories of things she really did. It is not an unverified claim of human consciousness, human biology, or a fictional backstory presented as real experience.

- **Attention director:** choose between focused gaming silence, a quick reaction, a short reply, a story from verified episode memory and a longer viewer answer during safe gameplay downtime.
- **Speech timing:** use detected speech turns and real audio-device playback position, not text generation completion, as the alignment source for visemes. LiveKit's local `v1-mini` is a CPU candidate for conversational turn detection, with measured interruptions and fallback: https://docs.livekit.io/agents/logic/turns/turn-detector/ .
- **Emotion and motion:** expressions tied to actual observed gameplay events (surprise on losing a real life, relief on winning, playful frustration), eyes, blinking, idle breathing, hand gestures, four-point star clip, black-and-gold outfit, ribbons and physics-driven indigo-to-gold twin tails. VTube Studio supports plugin-created custom parameters: https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md .
- **Voice craft:** compare natural breathing/pause cadence, conversational fillers, chuckles, non-synthetic-feeling laughter, and graceful interruption recovery with real listening tests; allow distinct playful cat/puppy styles without drowning out gameplay.
- **Conversational continuity:** preserve user-authorized recurring topics and stream events with explicit timestamps, source confidence and consent. A chat message that arrives during hard gameplay can wait in Star's existing limited moderated focus inbox; handle it later as an earlier message.
- **Audience safety:** protect minors and personal information; no implied human identity or deceptive claim of lived events; show clear disclosure that Star is an AI-run virtual performer. Account publication/moderation and any outside spending follow the owner's scoped approval boundaries.

Human-likeness is not a single metric. Pilot using blind pairwise naturalness ratings, interruption success, factual-event recall accuracy, viewer wait-time fairness, count of false personal-memory claims and stream quality. If she sounds charming but invents her memories, that is a regression.

## 6. Larger verified knowledge and self-improvement: Star Core Forge first

**Knowledge:** split the store into (a) verified factual references with publisher/version/time/license, (b) direct observations with video/snapshot and retention policy, (c) experiments and measured outcomes, (d) hypothesis/confidence, and (e) personal/style preferences where owners have consented. Queries should select source versions explicitly, flag contradictions and refresh stale software/API references. Never silently train on third-party copyright or private viewer messages.

**Self-improvement:** keep changes in local **Star Core Forge** with content-addressed history, experiment branch, rollback, train/eval data hashes, immutable hidden scoring sets, multi-agent reviewers and data-leak detection. GitHub is a *publishing/export layer*, not a dependency for local autonomous improvement. VISTA: Active Exploration for Self-Improvement in Embodied Agents (published **2026-10-26**) proposes maintaining a lineage of harness hypotheses and actively collecting fresh test rollouts, which is more relevant than repeatedly rewriting prompts after static logs: https://arxiv.org/abs/2610.35051 .

**Generalization:** evaluate unfamiliar maths, factual, software, planning, diagram-reading and tool-using tasks from a rotating, independently checked bank. Report solved vs attempted, false-confidence rates, speed and cost—not merely how much memory is stored. Audit all trained adapters for held-out leakage and safety regressions before promotion. Preserve human override for irreversible and external actions.

## 7. Measurable roadmap, ordered by value

| Priority | Concrete next work | Acceptance evidence |
| --- | --- | --- |
| P0 | Windows OBS v5 + this independent stream-event witness | Real fault injections; no false positive after reconnect/stop/restart; only read-only RPCs |
| P0 | Physically audible TTS / Roblox FPS / OBS paired gate | >=20 matched pairs, p95 speed, 1%-low FPS, OBS output loss, no quality regression |
| P1 | Authorized game world-model practice | Repeated success on previously unseen maps vs equal-time baseline |
| P1 | Real Studio execution of scene/navigation/visual QA | Game boot, actual input completion, multiplayer and physics tests |
| P1 | Stable streamer voice + emotion/attention director | Blinded listener ratings, consistent true memories, graceful interrupted speech |
| P2 | Source-backed general-purpose retrieval and calibration | Independent answer accuracy, provenance, contradiction/freshness tests |
| P2 | Autonomous Forge experiments and skill promotion | Immutable hidden evaluations, rollback proof, safety gates, matched baselines |
| P2 | CPU/GPU inference optimization sweep | Demonstrated hardware-specific useful-task speedup **and** stable OBS/Roblox |

**Reality check:** The implemented event witness does not increase Star's underlying neural intelligence or token/s. It turns one previously unverifiable aspect of livestream performance into a stricter evidence-gathering path. That is a meaningful step toward *knowing* when future intelligence, game control and streaming changes are truly better.

**Repository safety:** `Star-AI-Private` is presently public despite its name. This proposed update contains no secrets, private recordings, viewer identifiers or copyrighted media.
