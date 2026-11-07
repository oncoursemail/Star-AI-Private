# STAR Intelligence — Real Host Pressure Sampling and Next Intelligence/VTuber Experiments

Implementation and review: **October 29, 2026 (America/Chicago)**.
Scope: owner-authorized local Linux Star AI host, optional experimental component;
no live model, Windows, OBS, or Roblox session changes.

## 1. Delivered: close the previous host-integration gap

PR #813 introduced `MemoryStallGuard` and connected the existing
`StreamBrainGovernor` to it. The remaining operational gap was that no
long-running worker was actually feeding the guard real Linux /proc data.
A host could inadvertently leave the otherwise useful guard permanently in
its fail-closed warmup state.

`star/memory_stall_polling_host.py` now supplies a dedicated low-cost
`MemoryPressurePollingHost`:

1. Explicit owner opt-in and an already enabled `MemoryStallGuard` required.
2. Single-use daemon worker reads Linux `/proc/pressure/memory` and
   `/proc/vmstat` every second by default (configurable 0.25–2 seconds).
3. Each read is handed to the **existing** locked guard. Its existing
   stall/swap-hysteresis rules remain authoritative; this feature does not
   invent another conflicting memory-pressure policy.
4. Failed reads/reader exceptions clear readiness for **new optional**
   vision, research, training and rendering jobs.
5. Shutdown invalidates admission immediately and waits a bounded time for
   the reader to exit. A late read after shutdown is discarded.
6. The existing live voice/commentary path is not silenced by the PSI guard.
   All other realtime FPS/VRAM/queue QoS rules remain in force.
7. No model-server restart, OS priority alteration, GPU action, broadcast,
   webcam/microphone activation, or network operation is performed.
8. No viewer data, model prompts, media, keys, local file names, or
   per-process command lines are stored in the poller status.

The same guard object must be passed both to
`MemoryPressurePollingHost(guard=...)` and
`StreamBrainGovernor(memory_guard=...)`. This is an integration component,
not a new AI model and not automatic deployment.

### Host-side example, disabled until opted in

```python
from star.memory_stall_guard import MemoryStallGuard
from star.memory_stall_polling_host import MemoryPressurePollingHost

guard = MemoryStallGuard()  # inert until enabled
# A trusted local owner-controlled host, not the AI model:
guard.enable(owner_approved=True)
sampler = MemoryPressurePollingHost(guard=guard)
sampler.start(owner_approved=True)
# Supply this guard to the existing StreamBrainGovernor constructor.
# ... trusted host continues its normal game/GPU/audio sensor sampling ...
sampler.shutdown()  # e.g. in a finally block; no daemon left enabled
```

**Platform limit:** Linux PSI does not exist as this interface on Windows;
do not install the /proc worker on Star's Windows gaming machine. Continue to
use real GPU/frame/audio telemetry there. The two-host scheduler should
combine **host-specific** observations, not misrepresent Windows PSI as Linux.

### Verified read-only test on Star's Linux machine

With the current Linux kernel, a 30-read read-only microbenchmark recorded
**0.369 ms median** and **1.000 ms p95** for the counter reader.
An isolated 3.2-second real polling session produced **4 accepted samples,
0 failed samples**, guard state `healthy`, and an optional-work decision of
`memory_stall_clear`. After shutdown the same work was correctly denied as
`pressure_guard_unavailable`. The measured sample had **0.00% some/full
avg10 PSI** and **zero new swap pages per second**.

This is one short idle/ambient host observation, **not evidence of a
neural-inference speedup, reduced model latency, or a stable streaming FPS
improvement**. Readers must still compare foreground performance before and
after enabling pressure-aware admission.

The new offline tests exercise approval, startup warmup, actual independent
poll intervals, hot-pressure latching, recovery, sensor exceptions, blocked
reader shutdown, a real Linux kernel smoke check and full
poller → guard → StreamBrainGovernor → QoS admission flow.

Primary upstream reference:
https://www.kernel.org/doc/html/latest/accounting/psi.html
(Kernel PSI: partial and full memory stalls; absolute microsecond counters
allow per-window rates without relying only on long averages.)

## 2. Highest-value intelligence/speed experiment, not just tokens/sec

Star currently has multiple local inference services. The next engineering
sprint should run a **paired, fixed-workload study**, without altering the
production model processes: collect before/after p50 and p95 *task completion*
latency, time-to-first-audible-word, verified task accuracy, game FPS,
OBS dropped/skipped frames, queue wait, GPU/CPU use, RAM/PSI and swap rates.
Assign matching workload seeds and separate warmup periods; do not promote a
candidate that trades correctness or streaming quality for token throughput.

Use the existing `upgrade_evidence_gate`, signed receipt host,
`stream_output_qoe_gate`, memory guard, and StreamBrainGovernor. Do **not**
create another incompatible benchmark truth ledger. A successful experiment
can yield a profile by activity: fast chat while gaming, accurate deep code
repair, vision+control, asset generation, and overnight research.

llama.cpp's upstream server documentation exposes opt-in Prometheus metrics
covering requests processing/deferred, token rates and context usage.
A trusted local read-only collector can correlate these with PSI and game
performance; do not enable remote `--tools all` or unrestricted MCP commands
on a model server. Native tools run with the server's filesystem privileges.
Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

**New research worth prototyping, not promising:** UlaCache (October 21, 2026)
proposes shared logical GPU/CPU KV-cache addressing and reports improvements
on H200/B300 infrastructure, not on Star's 8 GB GeForce 4060. Its ideas
suggest comparing safe CPU-RAM offload and cache replacement in a separate
reproducible bench, **not adopting its headline speedups**.
Source: https://arxiv.org/abs/2610.29820

## 3. Genuine gameplay learning: connect real outcomes to strategy

Prior development provided a signed, private `StudioPracticeCycle`,
engine scene integrity checks, and visual quality testing. High-value next
work is obtaining **real private Studio outcomes** rather than writing more
synthetic validators:

* In a fresh permitted Roblox Studio place, construct 3 small mechanics:
  timed jump, moving target, and puzzle/button sequence. Version fixtures
  and map seeds; verify physical checkpoints via trusted engine state.
* For each attempt: image/scene observation → forecast → bounded permitted
  input → independent objective verdict → practice ledger → changed policy.
* Hold out unfamiliar maps, control inversion, speeds and camera positions
  so memorized scripts cannot pass as generalized game mastery.
* Test a slow planner against a small fast action policy under identical
  frame/action budgets. Measure goal success, failure recovery and p95 input
  latency, not merely movement counts or screen-recognition confidence.
* Any game engine input should be explicitly scoped to private playtests and
  have host-level focus and key-release safety. Do not autoplay public games.

Roblox announced its built-in Studio MCP and playtest/input automation on
**March 5, 2026**:
https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643

GameWorld (April 2026) has 34 games and 170 state-verifiable tasks, including
runners, arcade, platformers, puzzles and simulations. Its central insight is
to determine progress from the **environment**, not an AI narrator:
https://gameworld-project.github.io/

## 4. More effective general knowledge and creative quality

Star should index verifiable information as *provenanced experiences*:
question, source/content digest, timestamp, confidence, task scope, tested
behavior, failure variants and correction. Scope viewer chat separately
from owner-private memories. Retrieval should supply only the most relevant
trusted examples, with explicit stale-source and contradiction flags.

Priority evaluation set: 40 unfamiliar questions mixing Roblox APIs,
Luau, Blender geometry, animation, UI, audio, math/physics, game strategy
and general factual reasoning. Randomize questions and prevent test answers
from being indexed as new training evidence. A suggested answer cannot be
self-certified: evaluate with documentation checks, engine assertions,
unit tests, and blinded human art reviews when applicable.

For game creation: compare multi-view screenshots and a runtime clip, test
welds/attachments/collisions, camera readability, safe spawns, animated rigs,
VFX timing, UI interactions and actual end-to-end completion. Preserve scene
fixes as reusable *tested* skills in local Star Core Forge, rather than
blindly appending text to a long context window. No fictional benchmark
score should be treated as progress.

## 5. Humanlike gaming VTuber without fabricated human identity

A convincing Star is a coherent, expressive **AI character**, not a claim
that she has a biological childhood or consciousness. Build from genuine
recorded activity and a consistent persona; disclose that she is AI.

On-air director should prioritize: gameplay attentional demands, natural
pauses and interruptions, real chat priorities, speech budget, verified
game events, humor and occasional silence. Each selected interaction then
drives a shared timebase for speech, mouth, eyes, brows, shoulder motion and
indigo-to-gold twin-tail physics. Different avatar modes (cat, puppy, etc.)
should be expressive presets, not disconnected personalities. Measured
audio playback and final OBS output remain the truth for synchronization.

Use current `stream_brain_governor` to preserve speech/animation headroom.
The lightweight LiveKit `v1-mini` audio turn detector can run locally on
CPU; evaluate it on laughter, interruptions, casual overlap and game audio
before adoption:
https://docs.livekit.io/agents/logic/turns/turn-detector/

Measure three separate outcomes: (a) natural conversation and coherent
memories judged from authentic experiences, (b) time-aligned final recorded
audio/animation, and (c) uninterrupted game/OBS responsiveness. Protect
private content, age-restricted chat and creator/moderation policies; never
retain an unrestricted viewer history.

## 6. Follow-up integration milestones and acceptance

**P0 — This run:** actual Linux background polling, tested with real /proc,
existing guard and QoS. Verified but **not deployed into ongoing services**.

**P1 — Next:** 30–60-minute owner-authorized before/after inference load
experiment using existing model services. A success requires improved p95
latency or fewer stalled foreground turns with no loss in verified accuracy
or game/voice quality. Keep experimental features off if inconclusive.

**P2 — Private Studio truth:** capture genuine outcome receipts for three
simple games using the connected Windows Studio installation and require
measurable improvement on withheld levels before celebrating mastery.

**P3 — VTuber A/V truth:** actual Windows OBS capture with separate speech
track and aligned mouth landmarks, judged for natural turn-taking,
meaningful silences and subthreshold lip lag with game FPS protected.

**P4 — Broad intelligence:** closed-loop verified skill evolution, novel
challenge generation, and provenance-backed general knowledge, promoted
only after held-out evaluations. GitHub remains optional publishing;
Star Core Forge remains the local system of record.

**Security:** the repository named `Star-AI-Private` is currently reported
as publicly visible. The branch must not include keys, viewer data, recorded
voices, private screenshots, signing secrets, or OS credentials.

The present implementation makes background-pressure decisions *operable*
and testable. It does not add neural weights, autonomous gaming mastery,
human consciousness, or a completed live stream.
