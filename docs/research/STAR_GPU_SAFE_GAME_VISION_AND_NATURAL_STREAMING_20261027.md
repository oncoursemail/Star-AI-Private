# STAR: GPU-safe visual learning and human-natural gaming research
Date: 2026-10-27 (US Central)  
Status: implemented control-plane hardening + offline tests; research proposals are **not deployed**.

## Why this particular change matters

STAR's game-playing loop observes Studio through `StudioVisualObserver`,
passes a scoped, time-limited `GameFrame` to `GameActionGate`, and relies on
separate signed gameplay receipts for proof of winning or learning. An actual
screenshot is **not** evidence that an objective was completed.

A visual assessment can have a real GPU worker underneath an async Python
function. Python's `asyncio.wait_for` can cancel the *await*, but cancellation
may not stop a blocking native worker, nested subprocess, or detached GPU
request. Starting another assessor immediately can push an 8 GB GPU into VRAM
contention and raise game frame time or speech latency.

### Implemented here

- `StudioVisualObserver._assess` now bounds the async wait without waiting
  indefinitely for an uncooperative cancellation to finish.
- Timed-out / externally canceled still-running assessments receive an opaque,
  session-bound `VisualWorkerLease` and enter **quarantine**.
- More screenshot classification and rearming are blocked until the trusted
  local host confirms the physical worker is stopped and its async task done.
- A copied, stale, or replayed lease is rejected using identity, not just equal
  fields; a stop request or boolean from model text cannot clear quarantine.
- `disarm()` revokes observations but deliberately does **not** pretend to kill
  a worker. Late stale assessor results are discarded.
- Normal successful classification remains fast-path and unchanged; counters
  are anonymous and never contain screenshots, frames, audio, identities,
  transcripts, or credentials.
- Four targeted adversarial cases cover timeout ignoring cancellation, caller
  cancellation, stale lease replay, and the successful zero-quarantine path.

**Host obligation:** this is not a process killer. The embedding application
must join/terminate any native worker and call
`acknowledge_worker_stopped(lease, worker_stopped=True)` using the **exact**
lease obtained from `quarantined_worker()`. If it cannot verify termination,
keep admission blocked and alert the operator; never silently free VRAM.
The `StudioVisualObserver` and `StreamVisionHost` contracts are separate:
each must protect the actual worker path it owns. No OS privilege is granted.

## What current research changes about STAR's build priorities

### 1. Game intelligence: inspect before editing, test inside the world

The October 1, 2026 OpenGameEval paper evaluates 13 models on 84 core Roblox
Studio tasks with 16 trials each. It finds exploration quality predicts task
success. The paper reports a **13.4 percentage-point** association for
scene-only tasks and **9.8-point** association for script-only tasks when agents
inspect all reference-touched objects versus none, holding task and model
fixed. This is association, not a controlled causal guarantee.

STAR's next Roblox agent experiment should enforce a real host-provided
**inspect → propose → edit → playtest → review** trace:
1. Record all object IDs and scripts *actually* inspected with read-only Studio
   tools, not model-generated claims that inspection happened.
2. The plan names target object IDs and dependencies; if they were not observed,
   request additional inspection rather than guessing part locations.
3. Edit only a permitted workspace/sandbox; capture structured scene diffs.
4. Evaluate mechanical integrity (anchors, parent/child ownership, collision
   overlaps, missing attachments, off-map props, bad grip transforms), then a
   real playtest and visual before/after comparison.
5. Independently grade the result on a held-out place; include changes that
   passed syntax tests but failed visually or mechanically.

**Suggested acceptance:** >90% targeted dependency coverage before edit,
zero unauthorized edit calls, collision/attachment regressions not worse than
baseline, and higher actual playtest pass rate on unseen projects; do not
publish changes just because LLM self-critique says they look good.

References:
- [Roblox OpenGameEval paper, Oct 1 2026](https://arxiv.org/abs/2610.02563)
- [Roblox benchmark code and reproducible tooling](https://github.com/Roblox/open-game-eval)
- [Roblox announcement and test types](https://about.roblox.com/newsroom/2025/12/opengameeval-benchmark-agentic-ai-assistants-roblox-studio)

### 2. Faster 8 GB gaming AI: optimize measured end-to-end responsiveness

A speculative-decoding flag alone is not a speed improvement. Different prompt
types, decoding strategies, KV-cache sizes, and VRAM limits change outcomes.
The official llama.cpp SPEED-Bench client already reports per-category
throughput, latency, and draft acceptance.

**Recommended A/B matrix** (same game, model quality controls, and GPU):
- Baseline quantized GGUF vs n-gram speculative decoding; try a small draft
  model **only if it fits without paging or dropping game FPS**.
- Cache-on vs cache-off with reused verified references, measuring both first
  token and complete response; protect against stale documents and chat leaks.
- CPU TTS vs GPU TTS; track first audible phoneme, non-canceled audible
  completion, naturalness from blinded listener judgments, and game p1/p99
  frame times.
- Night-school queues get spare compute, while OBS/game/voice workers have
  separate resources. Abort or pause experiments on stale measurements or a
  falling FPS budget.
- Test 10+ different prompt categories with held-out tasks and repeated
  paired runs, not a single favorable code prompt.

**Do not deploy unless** median and p95 speech responsiveness improve *and*
usable spoken-turn completion remains >=95%, with game 1% low FPS and audio
underflow no worse than an explicit owner-chosen regression tolerance.
Report accepted tokens/s, VRAM peak, CPU utilization, and confidence
intervals. A faster system that drops speech or steals game FPS is worse.

Reference:
- [llama.cpp SPEED-Bench official server benchmark](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md)

### 3. More human-natural VTuber timing without pretending to be human

LiveKit's 2026 adaptive interruption work distinguishes barge-ins from
incidental backchannels better than naive speech activity alone. STAR already
has `TurnTakingGate`, `StreamDirector`, stage and audible-playback lifecycle;
the next step is an **optional host-authorized interruption classifier**
that outputs bounded intent (actual interrupt / listener backchannel /
uncertain) with false-interruption audit data. Streaming must be local-first;
LiveKit's hosted implementation is **not** an offline drop-in component.

Use expressive animation as a reflection of *verified* in-game events:
- Ground laughter and surprise in game/audio events and voice timing; avoid
  repetitive scripted laughter after every jump.
- Separate intentional silence for difficult gameplay from a voice system
  that stalled. Only host-confirmed audio counts as a completed interaction.
- Keep identifiable persistent fiction/character memories distinct from
  factual memory. Never invent real experiences, friendships or achievements
  as fact. STAR can be an appealing AI persona without claiming biological
  human consciousness.
- Live2D facial expressions are combinable; do not overwrite motion/physics
  parameters or allow a delayed expression from an old voice session to
  reset a newer facial pose.
- Viewer fairness, game danger, and authenticated owner interruption have
  separate priorities. Evaluate with simultaneous chat/gameplay rather than
  isolated text conversations.

References:
- [LiveKit adaptive interruption research, March 2026](https://livekit.com/blog/adaptive-interruption-handling)
- [LiveKit turn detection/interruption guidance, 2026](https://livekit.com/blog/turn-detection-and-interruption-handling)
- [VTube Studio official expression precedence, updated July 7 2026](https://github.com/DenchiSoft/VTubeStudio/wiki/Expressions-%28a.k.a.-Stickers-or-Emotes%29)

### 4. Build general knowledge via grounded practice, not unverifiable claims

STAR already has source-reviewed questions, a knowledge recall planner and
host-gated practice. The next real gain requires trusted local inference,
separate blind grading, expiration checks for changing sources, and held-out
questions created independently of the retrieval bank.

Retaining answers in a local database can improve *available knowledge*
without altering the base model weights; report those separately. An online
knowledge source should have provenance, licensing, timestamp, confidence and
scope. Never put private records or answer keys into public GitHub notes.
Periodically re-evaluate retention, transfer to new wording, calibration
and actual user-task quality, while pausing practice when streaming resources
are constrained.

### 5. Infrastructure integration milestones and measurement

- **Immediate (this PR):** merge only after offline CI and security review;
  verify both cooperative and non-cooperative assessor-worker cancellation.
- **Windows game-lab milestone:** instrument actual GPU/VRAM/frame presents,
  Studio capture, OBS capture, speech device and worker process lifecycle.
  Require a local operator-controlled worker stop before releasing quarantine.
- **Autonomous gaming milestone:** add host-owned inspection trace and
  randomized practice-versus-holdout separation; publish signed results only
  when externally verified. No game-wide auto-input permission implied.
- **Creative-game milestone:** challenge generation + scene/rig/collision
  checks + automated playtest + user-facing quality review. Fix errors in a
  sandbox and keep rollback checkpoints in STAR Core Forge.
- **VTuber milestone:** blinded listener ratings of voice/laughter timing,
  false-interruption rate, speech-to-face lip sync drift and stream QoE.
- **Runtime budget:** preserve live game input, speech and rendering ahead of
  offline inference/training. Each job declares memory/latency budget; a
  physical-worker lease persists across disable, timeout, crash or restart.

## Honest outcome

This change provides a *measurable safety and scheduling property*, not a
faster model, altered model weights, an autonomous game-playing success, or
a real stream. Tests prove the Python control-plane behavior using fake
workers. Windows GPU, real microphone, model-inference and OBS benchmarks
are still necessary before asserting actual human-natural streaming gains.

Security reminder: repository `Star-AI-Private` is publicly visible at the
time of this research. Publish only synthetic tests and public references;
keep keys, private accounts, raw recordings and hidden evaluations local.

