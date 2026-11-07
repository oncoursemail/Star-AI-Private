# STAR: consumer-side epoch safety, real gaming intelligence, and humanlike VTuber systems
**Research and implementation date:** 2026-11-07 (America/Chicago)  
**Scope:** draft branch stacked on PR #1041; OFF by default; main and production Windows app unchanged.

## 1. Finding: queue admission is not queue consumption

An asynchronous speech pipeline has at least two boundaries:
1. Model/TTS producer pushes chunks into a host-owned queue.
2. Playback or avatar transport later removes chunks and submits them to the native backend.

The existing StreamOutputEpochFence (PR #1041) checks producer enqueue. But a chunk
accepted at T=100 can remain in a private queue until T=130, while an owner
interruption revokes the epoch at T=110. An enqueue-only fence cannot guarantee
that the already accepted chunk is discarded.

**Implemented:** star/stream_output_consumer_queue.py is a short, capacity-bounded,
host-only queue with BOTH checks. Producer enqueue calls
StreamOutputEpochFence.dispatch; final native-consumer handoff calls dispatch
again on the same opaque ticket under the fence's existing serialized lock.
Revoked or retired tickets are rejected before native transport is invoked.
Expired/invalid clocks, failed backend submissions, invalid data types and
backpressure are fail-closed. On a bad consumption outcome the queue discards
remaining chunks from the same ticket. On owner shutdown it clears all queued
buffers and disables the fence. Only fixed privacy-safe counters leave the queue.

Hard ceilings: 64 items and 512 KiB by default; each text chunk <=8 KiB,
each PCM chunk <=256 KiB, avatar payload <=8 KiB. Byte counts are computed
from the actual immutable payload, not trusted metadata. Callbacks use a
small, nonblocking host handoff; never call from a WASAPI/render callback.

**Critical bound:** Both boundary checks are necessary but do not prove that
native PCM stopped after a chunk was accepted. The Windows device needs
explicit per-epoch flush/stop and independent PCM-drain confirmation through
NaturalTurnPhysicalHost. If the native callback blocks, a critical stop can
wait for the callback; use a dedicated control worker, hard callback latency
budget and an independent native watchdog. All user and viewer output remains
blocked pending hardware-verified quiet state. This change neither plays
sounds nor animates a model, and is not a broadcast authorization.

### Required Windows integration contract (next step)
- Instantiate StreamOutputEpochFence and StreamOutputConsumerQueue **only**
  on a trusted, local, private worker. Do not permit model or chat tools to
  call enqueue, consume, revoke or native output callbacks.
- Enqueue model text, immutable PCM bytes and prevalidated avatar motion data
  using the epoch ticket from a host-approved PhysicalTurnResult.
- Route actual final PCM/rig submissions exclusively through consume_one().
  No alternate audio, caption, or rig queue may bypass the consumer check.
- Upon barge-in, critical gameplay, session end or watchdog fault, revoke the
  ticket first; call discard_ticket() and the device's epoch-specific stop/
  flush; require independently verified model idle, TTS idle, PCM drained,
  neutral avatar, then settle. Re-arming needs explicit owner approval.
- A single queue must not substitute for separate model priority, mic
  capture, OS control, or sample-clock architecture. No stream key or
  broadcast permission belongs to this component.

### Explicit testable invariants
1. A forged ticket with copied serial/epoch fields cannot enqueue output.
2. An accepted chunk is blocked if revocation occurs before final handoff.
3. Native rejection forces cancellation and removes remaining stale buffers.
4. Capacity is enforced by actual bytes and bounded item count.
5. Cancel callbacks can clear the queue with no fence/queue lock inversion.
6. No transcripts, PCM, motion bytes, private paths or stream keys enter metrics.
7. A chunk accepted immediately before revocation still requires separate
   native device flush; a callback boolean is *not* proof of audible silence.

## 2. Research: turn-time decisions matter more than uninterrupted speech

A credible gaming VTuber needs human-like timing, not incessant commentary.
Star's turn manager should distinguish owner speech, viewer chat, game danger,
genuine events, quiet concentration, and recoverable silence. Prioritize
first meaningful audible response over first generated token; add silence
windows when a teammate speaks or the game becomes dangerous. Changes to
persona should be based on verified experiences, not invented claims of
having played games or experienced emotions.

Microsoft Research Proact-VL explores proactive timing for real-time AI
companions; NVIDIA DyaPlex explores simultaneous listening, speaking and
expressive motion. Both are promising research directions, **not**
prebuilt or production-validated Star integrations.

Sources:
- https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/
- https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md

Implementation route: observe-only video + game-event timeline -> turn
scheduler -> evidence-grounded reply -> speech-ready chunks -> bounded
consumer epoch gate -> local PCM output -> playout-clock-driven Live2D
expression -> device-verified stop and neutral frame. Support synthetic
private rehearsals and a manual kill switch before any real broadcast.
VTube Studio's WebSocket API is local by default and requires plugin access;
use per-plugin auth and keep viewer text completely outside its control path.
VTube Studio supports Live2D rather than direct VRM/3D rig control; use a
different backend if the final mascot is a 3D rig.

## 3. Research: playing games better must be evaluated in real time

Research into real-time game agents (Gym-Anything-RT, 2026-10-27) highlights
the gap between turn-based reasoning and environments that keep moving.
Avoid routing every frame through a large language model. Use:
- **Reflex:** pinned game focus, safe short actions, collision/hazard detector,
  action-release watchdog and strict reaction deadline.
- **Tactics:** targeted vision plus compact state snapshot, policy choice,
  retrieval of only verified game/version/situation skill hints.
- **Learning:** episode objectives, observable win/loss/damage and efficiency
  metrics, held-out levels, seeds and opponents, counterfactual candidate
  evaluation offline, retention only after independent improvement.

Measure success rate, deaths, time to objective, missed critical frames and
manual interventions, across unseen maps and opposing strategies. Maintain
matched baseline and candidate tasks. Never confuse game-window focus or
scripted simulator success with proof of performance in an actual game.

Sources:
- https://arxiv.org/abs/2610.37567
- https://github.com/Roblox/open-game-eval

## 4. Research: faster intelligence with an 8 GiB gaming GPU

The owner's Windows RTX 3060 Ti reported 8 GiB GPU memory in prior real
read-only probes. **Do not infer spare VRAM from total VRAM**; OBS, games and
voice have priority. Track snapshot-free memory, 1% low FPS, audio underruns,
inference time-to-first-speakable and wall-clock full-response time together.
Set a hard reserve for render + OBS; require fresh, stable GPU observations
before launching optional workers. When the real game is active, a remote or
CPU model may beat a faster GPU model after GPU-contention penalties.

Benchmark small local models under matched prompts with the existing
inference_stream_paired_gate; evaluate prompt-prefix caching, batching and
speculative decoding separately. The llama.cpp SPEED-Bench provides
throughput, latency and draft acceptance measurements, but speculative
decoding can regress on some model/hardware combinations: never assume
more sophisticated decoding is automatically faster. Explicitly compare
a GPU-resident 4B-class fast reaction model against a higher-quality larger
planning model running only during safe game downtime.

Source:
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

## 5. Research: game creation, general knowledge, self-improvement

OpenGameEval tests Roblox Studio agents against executable checks rather
than judging plausible generated code. Its 2026 material includes debug
tasks as well as generation tasks. Star should run a loop: inspect project
scene -> propose plan -> create Luau/assets -> run tests in Studio ->
playtest -> inspect visual/performance regressions -> repair -> preserve
verified lesson with source, timestamp and a reproducible test.
The November 4, 2026 Studio MCP expansion adds permission-controlled
Open Cloud operations for asset imports, analytics, settings and publishing.
Production publish and purchases still need owner-controlled permissions.

- https://github.com/Roblox/open-game-eval
- https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849

**New November 6 Roblox release-check:** Studio Test Teleports support
cross-place playtests without publishing. A Content property serialization
change is scheduled for November 11, 2026; projects using Rojo should
check compatibility with Rojo 7.7.1+ before exporting/publishing changes.
A November 2026 Early Access update also improves 2D AnimatedImages; treat
these as optional features, not proof of general availability. Source:
- https://devforum.roblox.com/t/weekly-recap-november-2-6-2026/4979364

Extend across Rust, Python, Blender, video and research, but with per-domain
executable or human-reviewable evidence. For general knowledge maintain
dated, source-linked retrieval and a calibrated uncertainty response;
do not train memory on generated guesses. Self-initiated experiments should
be local, reversible, resource-bounded and compare against holdout tests;
keep manual promotion gates for code touching personal data, live accounts,
payments, public posting or networking.

## 6. Private, nonbroadcast acceptance matrix

No step here authorizes broadcasts or live player inputs.

A. Queue adversarial tests: stale chunks, restarts, reversed clocks, full
   buffers, native failure, cancellation races and privacy counters.
B. Synthetic full-chain rehearsal: output fence + consumer queue +
   independent native mock + physical drain; assert stale output never
   reaches native mock after revocation.
C. Real Windows **read-only** readiness: pinned GPU UUID and headroom,
   pinned game PID+creation time, known model/OBS/VTS processes. Report
   unavailable rather than fabricate observations.
D. Owner-approved **nonbroadcast** recording: real game actions, local TTS
   and Live2D movement; compare FPS lows, audibility, response latency,
   lip-sync, interruptions and error-free recovery against baseline.
E. Promotion: only after independent CI, manual reviewed evidence,
   hardware-level stop confirmation and explicit owner approval.

**Verified in this draft:** only unit/integration tests on host-local
mocks, source linting and source inspection. This draft does not
demonstrate improved neural quality, actual FPS, spoken naturalness,
autonomous game mastery or Windows native-device integration.
