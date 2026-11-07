# STAR — Measured-Latency Replay, Faster Gaming Intelligence, VTuber, and Generalist Roadmap

**Research and engineering:** 2026-11-06 (America/Chicago)
**Scope:** private/offline reference tooling and implementation plan. **NOT** a production game controller, OBS integration, real-streaming proof, model training, or measured model acceleration.
**Parent:** private signed-maze jitter rehearsal in PR #1008.
**New tested component:** `star/measured_game_latency.py`; tests `tests/test_measured_game_latency.py`.

## 1. A crucial measurement gap in our previous work

The existing signed-maze lab (#1003–#1008) independently scores synthetic game
outcomes under *invented* timing traces. This proves some timing-related safety
and test-engine properties, not responsiveness on STAR's computers. Claims
about actual LLM tokens/s, end-to-end gameplay latency, voice first-audio
latency, stream fps, or real-game wins would be unsupported.

The new local-only adapter consumes four same-clock monotonic timestamps per
frame: frame capture, inference decision ready, private action submission,
and host acknowledgement. It validates strict intra-frame event ordering,
increasing frame sequences and capture times, acknowledgement order, strict
integer nanoseconds, max 30s frame durations, and a maximum 256-frame window.
The caller must opt in with owner approval. No raw timestamps, screenshots,
chat, model prompts, account names, audio, or network data are emitted in the
duration-only diagnostic report. It reports phase-wise nearest-rank p95,
end-to-end p95/max/total, and a *conservatively rounded-up* synthetic schedule.

A 10ms–1s world-tick size must be explicitly calibrated: engine tick frequency,
simulator hazards and real game clock are NOT interchangeable by default.
The maze accepts at most 24 ticks of synthetic delay per captured frame; the
adapter rejects larger measurements instead of clipping to create an
artificially faster result. Sampled schedules loop in the maze simulator,
so the replay is a **cyclic stress-test**, not literal chronological replay
of unseen frames.

A timestamp from the host is **self-reported telemetry**, not authenticated
proof. A `host ACK` is not proof of actual game movement, and a duration-only
report is not an independently witnessed game outcome. Later, signed host
receipts and a separate game-state change verifier should establish that.

### Safe integration example (private only)

```python
from star.measured_game_latency import LocalFrameTiming, prepare_private_latency_replay
from star.signed_maze_lab import MazeScenario, run_signed_maze_trial

# Synthetic example values: NOT a measurement from Windows or Roblox.
sample = (
    LocalFrameTiming(1, 1_000_000_000, 1_040_000_000, 1_050_000_000, 1_060_000_000),
    LocalFrameTiming(2, 1_100_000_000, 1_180_000_000, 1_185_000_000, 1_240_000_000),
)
replay = prepare_private_latency_replay(sample, owner_approved=True, tick_ns=100_000_000)
scenario = MazeScenario("private_demo", ("#####", "#S.G#", "#####"))
baseline = run_signed_maze_trial(scenario, owner_approved=True)
with_delay = run_signed_maze_trial(
    scenario, owner_approved=True,
    decision_delay_schedule=replay.decision_delay_schedule,
)
print(replay.private_report(), baseline.reason, with_delay.reason)
```

Do not log `sample` or `repr(sample)` to Discord, OBS, public logs, or CI.
Do not convert clocks collected on separate machines without measuring and
accounting for skew. Prefer timestamps from the game host's monotonic clock.

## 2. Research: actual real-time game intelligence

**Gym-Anything-RT, Aggarwal & Welleck, Oct 27 2026:**
https://arxiv.org/abs/2610.37567

100 real-time minigames contrast "world keeps moving" against paused-game
versions; reported gap of 9% vs 75% for one evaluated agent shows why offline
reasoning quality is not a live-game success metric. This is a published
benchmark result, not STAR's score. Needed STAR design:

1. **Realtime lane** (bounded, deterministic, deadline-aware): use the most
   recent authenticated game observation; legal-action checks; priority for
   survival and interruption; interrupt or abstain when evidence is stale.
2. **Tactical lane** (slower, event-driven): inventory, quest, route selection,
   mechanics hypotheses, opponent timing, and risk budget. Its proposals do
   not override real-time safety checks.
3. **Learning lane** (background, strictly capacity-limited): reconstruct
   episodes, generate progressively harder challenges, compare A/B policies
   on holdouts, record verified successes *and failures*, and only promote
   skills that improve independent objective metrics.

Never use a long LLM generation to hold down a live movement key. Distinguish
private permitted environments from online games with anti-cheat or terms
limiting automation. Real input and broadcast remain OFF until approved.

Research areas next: partial observability, belief-state uncertainty,
predictive opponent trajectories, frame sampling under an explicit
compute budget, pre-emptive stop on capture expiry, goal/subgoal planning,
hierarchical options, and transfer from synthetic to authorized real games.

Measure paired trials on *identical held-out seeds* with frozen policies.
Report the distribution of failures, deadline misses, survival, and
objective success—not only cherry-picked completed episodes. Distinguish
observation errors, planning errors, and actuation errors.

## 3. Research: intelligence and Roblox game creation

**OpenGameEval, Roblox team, Oct 1 2026:**
https://arxiv.org/abs/2610.02563
https://github.com/Roblox/open-game-eval

The benchmark has 84 human-curated Roblox Studio tasks, 13 evaluated frontier
models, and executable checks for edit correctness and simulated play.
Inspections before edits correlate with higher success on comparable tasks.
The lesson: don't award STAR "coding intelligence" for plausible-looking code.
Test the actual place and user journey.

Recommended STAR development pipeline:

- Take project snapshot -> inventory affected objects, scripts, APIs, and
  permissions -> verify existing behavior and dependency graph.
- Produce 4–8 *bounded* candidate changes if available capacity allows,
  lint with selene/StyLua/luau-analyze, type-check applicable APIs, and run
  unit and Studio playtests in isolated places; the highest-confidence
  verified candidate wins, not the longest generated response.
- Run UI screenshots, rig/hand-grip/geometry checks, accessibility and
  input tests, multiplayer lifecycle and replication tests, bad-network tests,
  and frame-time profiling. Keep failing evidence as a regression case.
- Separate read-only Studio inspection from mutating operations, and do not
  blindly mirror a workspace onto published Roblox places.
- Gate asset publication and production datastore edits; use least-privilege
  permissions. Roblox's Nov 4 2026 MCP/Open Cloud expansion provides per-game
  scopes and explicit upload directory approvals:
  https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849
  https://create.roblox.com/docs/studio/mcp-open-cloud

For broader general knowledge, use provenance-tagged document retrieval,
time-to-live for volatile facts, source verification, contradictory evidence
tests, and calibrated uncertainty. Record precisely which capabilities STAR
verified by execution versus which facts she only read. Optional web access
must stay OFF by default per local-first policy.

## 4. Research: speed and constrained hardware

On an 8GB-class GPU, gameplay/OBS/avatar rendering compete with model KV
cache and inference. Highest-priority performance method is **admission
control**: reserve GPU frame/encode headroom, choose smaller fast models for
short reactions, schedule slower reasoning in background, and throttle
training/self-play and video generation during live play. Monitor VRAM,
GPU frame time, OBS render/encode lag, model TTFT, tokens/s, speech first
audio latency, and 1% low game FPS simultaneously. Measure *p50/p95/p99*
end-to-end outcomes on the actual target machine.

Bench before adopting speculative decoding or quantization; draft model
overhead and KV memory can reverse gains. Support prompt/KV reuse where
the local runtime supports it, but preserve independent validation.
Current source: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

**Kyutai Pocket TTS v4.0.1 (Oct 21 2026):**
https://github.com/kyutai-labs/pocket-tts/releases
CPU-oriented streaming TTS with compact English variants (18.2M, 6.9M and
1.9M parameters). Could preserve game GPU capacity, but voices, expressive
range, CPU load, audio quality and latency require A/B tests. Do not treat
repo-level speed claims as measurements on STAR's PC.

Important infrastructure finding during this change: the connected Linux
developer host's root filesystem reported **~98% utilization on Nov 6 2026**
(202 GiB of 218 GiB used, ~5.8 GiB available at the sampled moment).
This is not a streaming benchmark. Before new large model downloads,
dataset mirroring, or parallel worktrees, add a low-disk preflight
and inspect largest caches/artifacts. Do NOT delete builds or version
history blindly. Offload reproducible test data to approved storage and
retain rollback snapshots.

## 5. Research: making STAR more naturally expressive on stream

**Proact-VL (ICML 2026):**
https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
It studies the *when to speak* decision under continuous game video:
solo commentary, co-commentary, and guidance. Use a bounded event salience
gate, novelty checks, interruption priority and minimum silence periods.
STAR should sometimes say nothing rather than narrate every frame.

**PersonaPlex (Jan 15 2026):**
https://research.nvidia.com/labs/adlr/personaplex/
Explores full-duplex speech with interruptions, backchannels and persona
conditioning; its 7B class makes local deployment on 8GB GPU with a game
running nontrivial. Research does not imply STAR presently implements it.

**DyaPlex (June 2026):**
https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/
Studies streaming speech synchronized with expressive motion. STAR needs
grounded reaction events with timestamps, gaze focus, mouth movement aligned
to phonemes, short attention gestures, natural idle motion, and event-to-speech
delay budgets. Don't rely on huge canned gesture loops or fabricated emotional
claims. Humanlike presentation is an artistic/behavioral objective, not
a claim of consciousness or human identity.

Proposed **VTuber director** with separate queues:
- Safety/priority queue for interruption, user requests and live-game events.
- Speech queue for short, grounded, non-repetitive commentary with subtitle
  timestamps and explicit TTS playback acknowledgements.
- Motion queue keyed to *actual* speaking, gaze and observed game events.
- Memory queue retaining user-approved recurring jokes, favorite games,
  verified in-game milestones and style preferences; event data gets
  retention limits and viewer opt-outs.
- Broadcast guard: identity disclosed as AI; moderator/owner killswitch;
  no private token, desktop notification, password, friend DM or viewer
  personal data replayed aloud; no unattended live publishing without approval.

Measure 10-minute offline rehearsal quality by speech onset p95, speech
overlaps/interruption latency, false claims about game state, repetitions
per minute, actual gesture/phoneme alignment and stream frame drop rate,
scored by an independent rubric and optional human evaluation.

## 6. Minimum acceptance gates before saying STAR is faster/smarter

1. **Telemetry integrity:** versioned local schema, same-clock origin, app
   instrumentation, provenance, no raw media leakage, signed ACK receipts
   where possible, documented sample losses, calibrated conversion.
2. **Performance:** controlled Windows paired A/B workloads (game+LLM+TTS+
   avatar+OBS) with model identity, driver, VRAM, graphics presets, scene
   and duration fixed; report tail latencies as well as FPS.
3. **Gameplay:** unseen scenarios, precommitted pass/fail objective and legal
   action checks, controlled variants, aggregate failure rates.
4. **Development intelligence:** independent executable Roblox/Luau tests,
   project snapshots and rollback, real player journey checks.
5. **Social behavior:** voice/audio capture consent, AI disclosure, live
   moderation and offline-first default. Record personality continuity
   without falsely claiming human feelings or experiences.

**This PR ships only the safe timestamp-to-private-synthetic-replay adapter
and regression tests.** Windows capture hooks, host signatures, real-game
action/ACK bridge, OBS video/audio integration, bigger models, new voice
weights, and self-training are deliberately future work.
