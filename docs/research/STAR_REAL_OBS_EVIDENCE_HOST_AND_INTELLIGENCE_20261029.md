# Star AI: real OBS evidence host, next-generation intelligence and believable VTuber architecture

**Research: 2026-10-29.** This document separates implemented software from research proposals and unverified claims. No broadcast, OBS connection, account access, game control, audio capture, model retraining, or hardware benchmark was performed as part of this PR.

## 1. Concrete implementation: live read-only OBS capture that can feed existing quality gates

Earlier Star modules `stream_realtime_benchmark.py`, `stream_obs_qos_gate.py` and `stream_network_qos_gate.py` can **reject** apparent AI speed improvements when speech latency improves but Roblox frame pacing, OBS render/output frames, or stream delivery regress. Their inputs previously required an out-of-tree capture host. This change supplies one important missing host-side building block:

- `star/obs_readonly_benchmark_host.py`: optional **OBS WebSocket v5** sampler through the existing `obsws-python` desktop dependency. It asks only for `GetVersion`, `GetStats`, and `GetStreamStatus`.
- `ObsReadOnlyProbe.connect(..., owner_approved=True)` requires an explicit authenticated **localhost** OBS WebSocket password and one verifiable local OBS process. It will not infer credentials, connect to a remote endpoint, start or stop a stream, switch scenes, save clips or turn microphones on.
- OBS process identity is `(PID, creation_time)` from `psutil`, rechecked before and after each pair of requests; any restart or ambiguous process invalidates the sample.
- `capture(..., duration_s=3..300, poll_interval_s=0.25..2)` samples an **already active** output. It fails if the stream is inactive/reconnecting at any sampled point, a counter resets, the session changes, the host clock stalls, or a response is invalid.
- It projects only four frame counters and seven transport fields. No arbitrary OBS metadata, stream key, chat, raw audio, screenshot, or network URL is stored. The caller receives typed `ObsFrameWindow` and `ObsTransportWindow` objects.
- `CapturedObsEvidence.jsonl_rows()` produces the EXACT allowlisted JSONL representation consumed by the two existing offline OBS gates. The caller decides whether/where to save the minimal records.
- **Crucial honesty:** periodic polling cannot prove an event didn't happen between samples. Unless a separate trusted OBS **event continuity guard** attests to an uninterrupted interval, `reconnect_observed=True` is set conservatively. Thus default observations are descriptive **and automatically ineligible** for a model-performance "win".
- No model settings are changed; even the existing combined benchmark's `eligible_for_manual_pilot` verdict is never approval for unattended production deployment.

**Why this matters:** there is now a testable path from a Windows OBS process to the measured OBS gates, instead of another proposal to connect one. It is a step toward a real machine acceptance test, not evidence that Star's models have become faster.

### Installation and owner-controlled pilot

Use an owner-authorized Windows machine already running OBS Studio with the WebSocket server enabled, authentication configured, and a **test stream you intentionally started**. The optional desktop requirements include `obsws-python` and `psutil`.

Illustrative host usage (do **not** check actual passwords into Git or log them):

```python
from star.obs_readonly_benchmark_host import ObsReadOnlyProbe

# The desktop host obtains this through its protected UI/secret store.
password = obtain_password_from_authorized_ui()
probe = ObsReadOnlyProbe()
probe.connect(password=password, owner_approved=True)
try:
    evidence = probe.capture(
        pair_id="ab001", variant="baseline",
        game_id="obby_private", game_version="v1", duration_s=10,
    )
    # Without independently observed full-interval stream events:
    assert evidence.transport.reconnect_observed is True
    frame_json, transport_json = evidence.jsonl_rows()
    # Store only when the test owner approved local telemetry capture.
finally:
    probe.disconnect()
```

Do not copy `obtain_password_from_authorized_ui` verbatim; this is a placeholder for an existing trusted owner UI function. An event source can supply a `continuity_guard` callable returning **True only when the exact interval was monitored continuously**. Never set it to `lambda: True` in production; tests deliberately use mocks to demonstrate the gates.

A real A/B experiment also needs the separately verified game FPS, GPU peak and **first physically audible PCM** evidence in `RealtimeRun`. OBS metrics alone cannot make a full-speed claim.

### Necessary next hardware validation

1. Confirm the Windows host actually detects OBS with both PID and process creation time. Check the OBS version and `obsws-python` response naming on that Windows installation.
2. Implement and independently test a resilient event monitor (including its own disconnect detection, stream stop/start, process restarts and reconnect transitions). A poll-only result must remain inconclusive for promotion.
3. Couple OBS sampler intervals to pre-registered, randomized/alternating baseline/candidate Star speech tests running the same Roblox map/build, OBS scene, encoder and resolution.
4. Ensure a separate game-present telemetry source and real audio playback clock share the same host-monotonic timebase. The AI may propose, but not certify, its own results.
5. Run >=20 matched pairs, and report p50/p95 actual audible speech time, 1%-low FPS, OBS renderer/output/stream drops and reconnections, actual game task outcomes and resource load.
6. Measure false-positive rate: intentionally restart OBS, disconnect network, reset counters and inject a long VLM reasoning job. No trial must be promoted under those faults.
7. Owner reviews the recording and audio naturalness before manually accepting any production switch.

## 2. Higher useful intelligence per second: where engineering effort pays

### Put a strict latency boundary around streaming

On an 8-GB-class gaming GPU, the principal problem isn't maximizing GPU occupancy: it is sharing it with Roblox, OBS compositing/encoding, a Live2D avatar, vision inference and speech. Continue using the existing `StreamBrainGovernor` and `AdaptiveQoS` admission flow:

- **Reflex path (milliseconds):** input deadline, immediate voice interruption, stop/flush speaker, gestures, blink/idle animations, and emergency "quiet focus" gameplay decisions. Do not route every frame through a text model.
- **Tactical path (short budget):** cropped HUD analysis, game mechanics prediction, recent experience retrieval, one- to two-step plan. Fall back to older verified state or silence when vision is late; never represent a stale frame as fresh.
- **Strategic path (off-stream/high headroom):** deep game design, Blender scene optimization, UI review, Star Core Forge experiments, extensive web/knowledge research and personal project planning.

Max throughput is not maximum responsiveness. Compare end-to-end p95 request-to-audible latency, **tool success rate**, game FPS and OBS health, not only token/s. Server changes can be slower for some prompt types or memory layouts.

### Benchmark existing llama.cpp before changing flags

SPEED-Bench documents consistent comparisons of server decoding, latency and draft acceptance under matching prompts. Use paired configurations, fixed quantization/context, exact model/version checksums, same prompt mix, and cold/warm variants; log only nonprivate performance metrics. Experiment with:

- prompt/KV reuse for stable context and approved project retrieval (avoid mixing tenants/viewers, stale sessions and private memories);
- chunked prefill/continuous batching only when it reduces latency at interactive concurrency;
- speculative decoding (ngram, draft model, MTP) with speed/accuracy checks; draft token overhead and VRAM contention can make it slower;
- quantization/offload routes chosen by real VRAM headroom, not an unmeasured belief that one model is always faster;
- CPU speech fast path only if real **audible** responsiveness and subjective expressiveness survive.

Official benchmark: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

**Promotion gate:** any quality regression, stale/reconnect telemetry, missing held-out skill evaluation, or OBS frame/transport loss causes a rejected or inconclusive result. Do not auto-tune a live computer on unverified evidence.

## 3. Make Star actually learn games and create games better

OpenGameEval's October 1, 2026 study uses **84 curated Roblox Studio tasks** with executable checks and repeated attempts, finding substantially stronger results when agents inspect relevant objects before editing them. This is directly aligned with Star's existing scene-integrity, navigation and visual-evidence work; a code patch or screenshot narrative is never equivalent to a working game.

GameWorld provides **34 games and 170 independently verifiable tasks**, using serialized game state instead of an AI judge's opinion. It demonstrates the value of long-horizon outcome measurement instead of counting guessed game events.

Sources:
- https://arxiv.org/abs/2610.02563 (OpenGameEval, October 1, 2026)
- https://github.com/Roblox/open-game-eval
- https://gameworld-bench.github.io/

Integrate Star's existing `GameMechanicProbeLab`, `GamePredictionLab`, `GameLearningLadder`, `GameplaySkillBank`, and scene-integrity compiler in this sequence:

1. **Observe** a legal private test environment, HUD, collision and game-state changes with timestamped actual sensor data.
2. **Predict** a measurable result *before acting*: jump range, button mapping, cooldown, hitbox or checkpoint.
3. **Probe** a bounded one-variable experiment through an authorized game controller; do not use game automation to break rules, anti-cheat or harm other players.
4. **Verify** with an independent scorer reading actual state and complete objectives; do not let Star mark her own result as victory.
5. **Store** signed outcome and uncertainty in the practice bank; keep genuine memories apart from model speculation and fictional character lore.
6. **Practice** a skill curriculum with recovery from death, mistakes and new physics; avoid infinite loops or reward hacking.
7. **Transfer** to unseen levels/seeds, different map layouts and novel tasks that were never part of her practice database.

Add external human playtesting as a separate axis: spatial correctness doesn't guarantee interesting gameplay. Human judges should assess fun, clarity, animation timing, UI readability, input responsiveness and novelty. Evaluate visual defects at multiple camera distances and device resolutions. Store scene screenshots only if an owner authorizes them.

Star Core Forge should generate progressively harder challenges from *observed failure modes*, not from a model's imaginary success narrative. Keep independent test partitions private and run every candidate through rollback-capable sandboxes.

## 4. Broader knowledge and autonomy with provenance

A larger vector database is not automatically a smarter assistant. Star needs independently verified recall, trusted citations and task-relevant retrieval. Each knowledge entry should distinguish:
- what was directly observed (sensor/tool/result), what is documented by a source, and what is merely a hypothesis;
- timestamp, version compatibility, scope/owner of the data, copyright/license, confidence, and expiration policy;
- whether it is approved for long-term reuse, whether it contains private conversations or viewer data;
- expected action, tested conditions, failure modes and transfer limits.

For general knowledge, build a lightweight **research librarian** that searches reputable primary sources when online search is opted in, checks freshness and contradictions, creates source-linked summaries, and queues disputed facts for review. Do not import entire websites or copyrighted libraries without licenses; aggregate quality beats indiscriminate scraping.

For creative independence, give Star self-chosen, bounded personal projects and interests: building an original Roblox minigame, making a song or sprite sheet, practicing movement in a private test level, or designing her own stream scene. She can choose plans within a known budget and approvals; irreversible, money-moving and external-account actions retain explicit owner limits. Her self-model must report **what she has evidence for**, not claim biological consciousness or human history.

## 5. Humanlike streaming: natural does not mean deceptive

A strong virtual performer needs a **causal** expression system, not merely scripted chatty dialogue:

- Game state -> attention state -> authentic reaction -> voice intent -> audible playback -> synchronized facial animation -> observed stream quality.
- A verified near-miss triggers short surprise; a known boss defeat triggers congratulations; an uncertain event prompts investigation. Do not hallucinate achievements just to fill silence.
- Distinguish intentional interruptions from short acknowledgments; keep silence during precision controls; return to earlier moderated viewer questions afterward.
- Give Star consistent tastes, friendships, goals and a continuous **fictional VTuber persona**. Past events she actually experienced can be recalled; fictional origin stories should be framed as character lore, not fake lived human history.
- Blend expressions rather than jump-cutting: tiny eye saccades, blink variability, micro-head tilts, fluid breathing and spring/damped hair and ribbon physics. Star's established black-and-gold twin tails, star clip, amber eyes and companion modes should remain recognizable.
- Let emotion influence prosody, pause timing and gestures, but preserve intelligibility, game focus and viewer boundaries. Laugh tracks or canned reactions are not proof of natural behavior.
- Enforce synchronized interruption epochs: an interrupted TTS chunk must not continue to drive mouth shapes after its sound has stopped. Use the existing audible-clock and Live2D components.
- Provide clear controls for reduced motion, quiet mode, chat moderation, pet modes, and whether short-term audience memories may be retained.

LiveKit documents local VAD and adaptive interruption handling as building blocks for natural turn-taking, while VTube Studio allows authenticated plugin injection of custom animation parameters. Kyutai's October 2026 Pocket TTS small CPU models are promising candidates *only after subjective voice testing against Star's established voice*.

Sources:
- https://docs.livekit.io/agents/logic/turns/vad/
- https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
- https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins
- https://github.com/kyutai-labs/pocket-tts
- https://github.com/kyutai-labs/pocket-tts/releases

### Human-perception test plan

Have consenting testers (not an AI judge alone) blind-rate **naturalness, appropriateness, response timing, personality continuity, voice warmth and game-task focus** on short clips under normal play, surprise, failure and interruptions. Collect only opted-in nonprivate clips; disclose synthetic nature of the performer. Target improvements on actual metrics rather than claiming she "is human".

## 6. Highest-priority feature work after this PR

1. **OBS event continuity observer and Windows adapter acceptance.** This unblocks reliable real-world gates; the present polling component *intentionally fails conservative* without it.
2. **Actual physical-audio / game-FPS / OBS synchronized A/B capture on Brain 2.** Ground speed claims in measured simultaneous operation.
3. **Closed-loop private Roblox test-room controller** joining Star's signed gameplay outcome bank with observed game inputs and repeatable state checks.
4. **Game builder quality harness** combining independent scene/pathfinding checks with screenshot-based visual difference and human-rated art/UI aesthetics.
5. **Expressive performance director** using actual gameplay evidence, short-latency TTS, audio-true mouth/hair motion and controlled attention shifts.
6. **Robust cross-domain skill library** for Roblox, Blender, music, 2D sprite art and video editing with versioned sources, licensing and transfer tests.
7. **Dynamic compute orchestration** scheduling free CPU/RAM for retrieval, prewarm and introspection while reserving GPU capacity for gameplay and speech.
8. **Autonomous internal Forge experiments** with human-reviewable evidence, staged deployments, independent holdouts and guaranteed rollback.

## 7. What this PR cannot establish

- No actual OBS/Windows/Roblox test was run: the new capture tests use simulated responses and clocks.
- No real TTS voice comparison, on-stream viewer evaluation, new model weights or internet-scale knowledge acquisition was performed.
- Stream QoS is not the same as packet loss or viewer-side buffering quality.
- Polling without independently trusted event continuity always yields a veto/inconclusive transport result.
- No claim of general superhuman intelligence, consciousness, genuine human emotional experience, or autonomous mastery is supported by this code.

**Security:** A GitHub repository titled "Private" may not actually have private visibility. Keep source documentation and tests free of passwords, game accounts, viewer identities, voice prints, model weights and raw recordings until true repository permissions have been verified.
