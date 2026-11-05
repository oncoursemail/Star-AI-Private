# STAR — Private OBS pressure, truthful GPU ages and a gaming VTuber validation plan

**Research and engineering checkpoint: 2026-11-05.** This document separates
implemented controls from research proposals. It does **not** claim improved
game FPS, network latency, speech realism or higher model intelligence.

## Three reproduced reliability defects, now addressed

1. **A private OBS recording was treated as immune to OBS overload.**
   `StreamAdmissionGate._bad` only checked OBS dropped render/encode rates when
   `StreamTelemetry.live` was true. In a host-authorized private VTuber rehearsal
   (`live=False, private_stream_rehearsal=True`), dropped frames could occur with
   plenty of VRAM and 60-game-FPS, yet the admission latch stayed healthy and
   1-Hz vision work remained advised. The corrected gate treats an explicitly
   marked private rehearsal as OBS-sensitive as well, while leaving ordinary
   nonrecording offline game practice unchanged.

2. **A delayed probe could make stale VRAM look freshly measured.**
   `RealtimeTelemetryHost.refresh_hardware()` previously stamped the timestamp
   *after* running three blocking probes. A late CPU probe could make earlier
   GPU measurements appear current at the end of the call. Capture the
   conservative timestamp **before** beginning probe I/O; downstream QoS
   freshness must use that actual age, not the finish time. This is especially
   important while TTS, OBS and a game contend for an 8-GB GPU.

3. **Aged private-rehearsal GPU measurements could still be wrapped as QoS.**
   The telemetry adapter applied a 250-ms realtime age ceiling only when
   `live=True`, although the downstream QoS governor already regards a private
   rehearsal as stream-protected. The adapter now also marks private-rehearsal
   QoS unavailable once its measured GPU/CPU age passes 250 ms.

**Reproduction:** first focused run produced three failing tests for defects
1–2, plus a separately failing test for defect 3. The focused tests pass after
the fixes. These are synthetic sensor tests; neither OBS nor real gameplay was
launched. The 1% OBS lag and 250-ms hardware-age cutoffs are existing policy,
**not** newly derived performance measurements.

### Explicit limitations

- `host_verified=True` and `private_stream_rehearsal=True` are attestations
  from an authenticated local host, **not** evidence provided by generated
  model text. The gate does not start OBS, approve a broadcast, or terminate
  workers. A host must report whether it is truly recording and whether OBS
  metrics refer to the active recording.
- A low reported OBS lag percentage is **not** proof that recorded audio is
  audible, the correct game window was captured, or the avatar lips synchronized.
  Those require the separate completed-recording/media audit.
- Probe-start timestamping can intentionally reduce inferred headroom after
  slow probes. It is safer, not inherently faster. If live polls consistently
  exceed 250 ms, the remedy is to optimize/consolidate asynchronous host probes
  or reduce competing load; *never* relabel old telemetry with the current time.

## High-leverage engineering sequence

### P0 — Produce one real, private Windows game+avatar+voice+OBS episode

Create an owner-authorized private calibration session. It must use an
ephemeral per-episode ID and a single monotonic host clock for game frame
presents, OBS frame/encode reports, TTS first audible PCM, avatar mouth
updates, game-state receipts and hardware probes. Keep broadcasting disabled.

Acceptance evidence should include: start/end epoch and window identity,
OBS recording artifact fingerprint, independently observed game input and
goal outcome, rendered game frame p50/p95/p99 times, OBS drop intervals,
CPU/VRAM time series, time to first audible speech, relative mouth/voice lag,
speech backlog, and pause/interruption success. A 5-minute session is an
**example test target**, not a completed result. Compare a matched control
with background research OFF against the proposed scheduling policy ON,
including thermal/warm-cache state and same level seed.

**Fail closed** for missing timestamps, clock reversal, old worker epochs,
recording track mismatch, untrusted game-success assertions, microphone
leakage, or an active public broadcast. Do not stream a calibration episode
publicly to gather data.

### P1 — Improve *correct game decisions per second*, not raw token rate

Separate the time-critical loop from heavyweight reasoning:

- **Game loop:** trusted game state + a small, bounded action policy; input
  only in authorized local test games with explicit output/permission gates.
  Prioritize navigation, camera movement, safe interaction timing and retries.
- **Tactical loop:** keeps short-horizon goals, predicted outcomes and
  failure classifications. Under frame pressure it yields to the game loop.
- **Reflective learner:** only consumes event/outcome receipts; creates
  curriculum tasks, retrieves ground-truth documentation and proposes
  reversible strategy changes *between* evaluations. It cannot sign its
  own success evidence or select its own held-out test after seeing results.
- **Game builder:** inspect Roblox Studio first, generate multiple Luau
  candidates, run static checks, use Studio MCP playtests on separate
  instances, review visual before/after and keep rollback artifacts.
  Compare successful implementations rather than judging the prose.

Training must use varied level seeds, input perturbations and previously
unseen levels. A no-op or randomly changing policy can appear strong on
memorized scenes; use paired baseline-vs-candidate evaluation and precommitted
unseen scenarios. DeepMind's SIMA 2 work indicates that language-grounded
multigame skills benefit from embodied demonstrations, but do **not** assume
its closed model or training data can be locally reproduced. Procgen makes
the generalization gap concrete: fixed or tiny training level sets are
insufficient to prove learning.

### P1 — Faster inference under real gameplay contention

Benchmark on **the exact Windows GPU and CPU used for streaming**. Keep a
stable manifest with model and quantization hashes, server build, context
length, prompt hash, input/output token counts, concurrency, n_gpu_layers,
cache hit conditions, GPU VRAM, committed RAM, power/thermals and game FPS.

Compare short conversation requests, tool-using planning and screenshot
reasoning separately. Measure p50/p95 first token, p50/p95 first audible
PCM, task correctness, frame-time spikes and worst-case GPU reservation.
Try speculative decoding with llama.cpp SPEED-Bench *only if* target/draft
KV buffers fit with the game + OBS + avatar. A 7M/18M CPU TTS may help
preserve GPU headroom, but quantify real Windows voice naturalness and
end-to-end latency against the current TTS rather than adopting it blindly.
Fallback to a smaller CPU speech model should preserve Star's consistent
voice identity; do not clone third-party voices without permission.

### P2 — Natural AI-VTuber presence without pretending to be human

Humanlike streaming is a **coordinated interaction loop**: observable events
→ decide whether speech adds value → formulate appropriate utterance →
play actual audio → synchronize face/eyes/gesture → record a grounded
episode memory. Use short backchannels, quiet attention, contextual humor,
self-correction, listener-aware interruptions and consistent persona tastes.
Guard against dead air by tracking spoken/queued output separately; never
report that Star said something until the playback device confirms it.

Speech focus arbitration should consider VAD, ASR utterance boundaries,
audio echo/speaker queues, and whether a viewer's message is actually
addressed to Star. Backchannels should not cancel the main speaker. Video
understanding should prefer sparse event-driven observations over blindly
processing every frame. DyaPlex (NeurIPS 2026), Proact-VL (ICML 2026) and
NeMo turn-taking designs offer useful **research patterns**, not turnkey
implementations for an 8-GB Windows machine.

Social/character continuity: store verified session highlights, voluntary
preferences and projects separately from fictional persona lore; allow
owner deletion/redaction and correction. Maintain creative interest in
games, drawing, friends, collaboration, learning and recurring activities.
Identify Star as an AI VTuber, preserve moderation/anti-spam rules and
never invent player histories, friendships or feelings as observed facts.

## Test matrix before any promotion

| Scenario | Trusted measurement | Pass requirement |
| --- | --- | --- |
| Offline game lab; no OBS | Frame-present + CPU/GPU probe | No private-broadcast policy accidentally triggered |
| Private OBS: render lag 2.5% | Host-attested OBS measurement | Vision deferred, overload latch set |
| Private OBS: encode lag 2.5% | Host-attested OBS measurement | Vision deferred, overload latch set |
| Actual live OBS: high lag | Host-attested OBS measurement | Existing protective behavior retained |
| GPU probe at t=1000, CPU completes t=1700 | Synthetic monotonic clock | GPU age not relabeled as 0 ms |
| Private session GPU age >250 ms | Host snapshot | No realtime QoSSnapshot constructed |
| Missing audio/game frame presents | Device callbacks | No optimistic stale snapshot |
| Healthy recovery after overload | Spaced, signed observations | Hysteresis prevents single-frame green |
| Real game/OBS/audio/VTube Studio | Recorded artifact + independent receipts | Completion verified; **not yet run** |

## Source links, checked 2026-11-05

- Roblox Studio's built-in MCP server (March 5, 2026):
  https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- Roblox autonomous playtest agent beta (April 9, 2026):
  https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767
- Roblox's plan–build–test announcement (April 15, 2026):
  https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic
- GameDevBench (ICML 2026): https://sethkarten.ai/papers/gamedevbench.html
- DeepMind SIMA 2 (November 13, 2025):
  https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- OpenAI Procgen generalization benchmark:
  https://openai.com/index/procgen-benchmark/
- Microsoft Proact-VL (ICML 2026):
  https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- NVIDIA DyaPlex (NeurIPS 2026):
  https://research.nvidia.com/labs/amri/projects/DyaPlex/
- NVIDIA NeMo voice turn-taking:
  https://docs.nvidia.com/nemo/labs-voice-agent/about/core-concepts/speech-pipeline/turn-taking-backchannels/
- Kyutai Pocket TTS v4 with English 7M/18M models (Oct. 20, 2026):
  https://github.com/kyutai-labs/pocket-tts/releases
- llama.cpp SPEED-Bench:
  https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
