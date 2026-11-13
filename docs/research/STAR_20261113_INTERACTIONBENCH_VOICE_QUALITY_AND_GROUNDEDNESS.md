# STAR 2026-11-13 — InteractionBench, Voice Quality, and Long-Conversation Groundedness

**Research date:** 2026-11-13  
**Implementation:** rehearsal schema v2, independent interaction outcomes, evidence-bounded diagnostics  
**Parent:** `feat/thinker-process-attribution-20261112-run11` (PR #1164)

## Executive finding

STAR's existing private-rehearsal evaluator already measures first content, first audible playback, game frame time, avatar synchronization, audio underruns, OBS render/output skips, turn precision/recall, task recovery, duplicate speech replay, and held-out game-skill transfer.

The November 2026 InteractionBench work exposes four evaluation dimensions that should remain separate:

1. Conversational timing.
2. Spoken-task accuracy.
3. Whisper and volume control.
4. Groundedness over long conversations.

STAR already has meaningful coverage for timing, interruptions, recovery, and delivery reliability. It did **not** have separate independent-score gates for spoken-task correctness, requested whisper behavior, requested relative volume control, or long-conversation groundedness. This change adds those four dimensions to the existing rehearsal evaluator and diagnostics rather than creating another voice pipeline.

## Research findings

### InteractionBench (November 2, 2026)

[InteractionBench benchmark page](https://www.fullduplex.ai/benchmarks/interactionbench) and [paper record, arXiv:2611.02430](https://arxiv.org/abs/2611.02430).

The benchmark reports 221 items per system across thirteen scenarios and evaluates seven voice systems over 1,519 runs. It separates conversational timing, spoken-task accuracy, whisper/volume control, and groundedness in conversations longer than twenty turns. Its client-heard timing includes network delay for hosted systems, which is the correct boundary for user-perceived latency rather than model-server timing alone.

**STAR implication:** do not collapse “sounds fast” and “answers correctly” into one score. A system can have good turn timing while failing the spoken task, mishandling a requested whisper, or drifting from established facts in a long conversation.

### Full-Duplex-Bench v3 (April paper; May 2026 code/data)

[Benchmark and paper/code links](https://www.full-duplex.ai/benchmarks/fdb-v3).

This benchmark uses 100 human-recorded spoken requests across 79 scenarios and twelve speakers. It includes self-corrections and chained tool calls, and scores tool-call accuracy, Pass@1, latency, and turn-taking. The reported benchmark analysis shows that current systems still struggle with mid-sentence corrections and multi-step tool use.

**STAR implication:** retain partial-ASR revision cancellation, final-only canonical commit, and interruption recovery. A partial transcript is not a safe final task instruction. The benchmark should include self-correction cases and verify that stale speculative responses never speak or execute tools.

### Full-duplex ecosystem snapshot (November 9, 2026)

[Full-duplex model, dataset, and benchmark catalogue](https://www.fullduplex.ai/).

The catalogue's W46 update shows a rapidly changing model and benchmark landscape. Treat it as a discovery index, not a leaderboard or proof that any particular model is best for STAR. Any candidate must be tested against the same local audio, language, device, and mixed-stream workload.

### Continuous batching evidence (November 1, 2026)

[Measured llama.cpp continuous-batching report](https://blogs.lamplitlabs.com/posts/continuous-batching-llm-serving-llama-cpp-measured/).

A third-party report on an Apple M2 Pro, llama.cpp, and a 3.1B model reported a large reduction in p95 time-to-first-token under its eight-slot continuous-batching configuration and nearly doubled aggregate throughput compared with its serial setup. This is **not** a prediction for STAR's RTX 4060 or CPU server: hardware, model, prompt mix, batch/slot count, and workload differ. It is a useful experiment hypothesis.

**STAR implication:** benchmark continuous batching only on a pinned local server build with fixed slots, identical prompt traces, and the actual stream/game/OBS workload. Report first-audible p95/p99 and game/audio quality alongside aggregate tokens per second. Throughput improvements that worsen the active speaker's tail latency are not a win.

### CEGame-Bench: full-game creation is a different capability from task-level code edits (October 19, 2026)

[CEGame-Bench paper, arXiv:2610.26098](https://arxiv.org/abs/2610.26098).

CEGame-Bench evaluates long-horizon game creation across Defold, Godot, Roblox Studio, Unity, and Unreal. Its task runs can average up to 295 steps and 65 million tokens. The benchmark treats the design document as a contract and accepts completion only through real-input play. The reported agents reached the ending in only 16% of runs; a requirement-driven Game Completion Boost skill improved execution-based scores by 14.1–24.3 points on the evaluated models. Engine rankings also varied materially, so a single cross-engine pooled score can hide important differences.

**STAR implication:** keep GameDevBench-style task correctness separate from whole-game completion. A game creator needs a separate acceptance contract: launch the built artifact, use real player input, complete all required objectives, reach the ending, save, close, reopen in a new process, and verify restored state. The repository has a separate whole-game journey prototype on a development branch; it should be reviewed and integrated as its own creator milestone rather than assumed to be part of this voice-quality PR.

### GameWorld: game-playing needs state-verifiable outcomes (April 8, 2026)

[GameWorld paper, arXiv:2604.07429](https://arxiv.org/abs/2604.07429).

GameWorld describes 34 browser games and 170 tasks with state-verifiable progress/outcomes. It compares direct keyboard/mouse control with a semantic action interface and highlights real-time interaction, context-memory sensitivity, and action validity as distinct evaluation challenges.

**STAR implication:** STAR Gamer should separate perception, semantic action planning, and low-level input execution. Score objective/state transitions from an independent game observer; do not let the agent grade its own screenshots or claim mastery from a paused-only rehearsal. Keep live-clock reaction tests separate from slower strategic planning tests.

### Evaluation-driven skill evolution (June 9, 2026)

[Agent Skill Evaluation and Evolution survey, arXiv:2606.11435](https://arxiv.org/abs/2606.11435).

The survey groups skill evolution into execution feedback, trajectory distillation, compression, and reinforcement learning, and argues for evaluation-driven skill evolution rather than isolated skill creation.

**STAR implication:** every reusable gaming or creator skill should carry its engine/game compatibility, version, provenance, resource cost, practice/holdout separation, and independent success evidence. Failed or stale skills should be demoted or quarantined; a successful practice run must not automatically become a promoted capability.

## Implementation in this change

### Rehearsal schema v2

The recorder now emits schema version 2 and adds aggregate counters for:

- Spoken-task trials and independently scored successes.
- Whisper-control trials and independently scored successes.
- Relative-volume-control trials and independently scored successes.
- Groundedness trials and independently scored successes.

The evaluator adds four separate metrics and operator-configured minimum-rate gates:

- `spoken_task_accuracy`
- `whisper_control_rate`
- `volume_control_rate`
- `groundedness_rate`

Schema-v1 snapshots remain readable. If a caller configures any new gate but supplies only a v1 snapshot, the new gate is **INCONCLUSIVE**, never a fabricated zero or a pass.

### Independent scoring boundary

Every new recorder method requires `independently_scored=True`. This is an explicit trusted-host contract, not cryptographic proof of the scorer's identity. The recorder accepts only an opaque event ID, a boolean outcome, and (for groundedness) a bounded turn count. It does not accept or persist prompts, transcripts, audio, viewer names, screenshots, claims, or model-generated explanations.

Groundedness trials require at least 21 conversation turns, matching the benchmark's greater-than-twenty-turn scope. The independent scorer should check:

- Consistency with earlier established facts.
- Correct handling of temporal updates and explicit corrections.
- Whether claims are supported by available evidence.
- Whether uncertainty is stated when evidence is absent.
- Whether stale memories are superseded instead of silently reused.
- Whether the model invents sources or attributes.

A model grading its own answer is not independent evidence and must not be used to authorize promotion.

### Diagnostics

The existing stream diagnostic planner now routes failures to separate candidate components:

| Gate | Candidate components |
|---|---|
| Spoken-task accuracy | Voice, model, retrieval, tools |
| Whisper control | Voice, TTS, audio |
| Relative volume control | Voice, TTS, audio |
| Long-conversation groundedness | Memory, retrieval, model, tools |

These routes are investigation hypotheses, not causal attribution. A trace may show correlated component timing, but a trace alone does not prove that a component caused a failed quality score.

## Recommended STAR evaluation protocol

1. Freeze the model artifact, quantization, system prompt, tool policy, audio device, TTS voice, and server build.
2. Prepare a sealed set of spoken tasks with independently verified expected outcomes.
3. Include explicit whisper requests and relative volume-change requests at multiple baseline loudness levels.
4. Include conversations of at least 21 turns with facts that are introduced, corrected, superseded, and queried later.
5. Include self-corrections, interruptions, side conversations, backchannels, and cases where STAR should remain silent.
6. Use blinded human scoring or a separately validated external oracle. Do not use STAR's own self-rating as the only quality label.
7. Keep timing, task accuracy, whisper, volume, and groundedness as separate metrics.
8. Run matched baseline/candidate trials with the same tasks and hardware.
9. Report sample counts and missing evidence. Insufficient evidence is INCONCLUSIVE.
10. Promote a candidate only when its predeclared quality gates pass and first-audible p95/p99, audio underruns, OBS skips, game frame-time p95/p99, and avatar synchronization do not regress beyond operator-approved limits.

## Speed and intelligence guardrails

- Measure server TTFT separately from client first-content and device-confirmed first-audible latency.
- Measure cancellation-to-confirmed-stop and barge-in recovery, not only generation speed.
- Keep turn timing separate from spoken-task correctness.
- Keep model self-evaluation separate from human or held-out evidence.
- Test continuous batching and speculative decoding one variable at a time.
- Do not add a resident draft model on an 8 GB GPU until process-level VRAM and non-local memory headroom are measured.
- Compare p50, p95, and p99. A faster median can hide much worse tail latency.
- Run the same test with the game, OBS, audio, avatar, and background workers active.
- Keep new runtime behavior opt-in until real Windows and device rehearsal passes.

## Broader capability roadmap

| Area | Next engineering step |
|---|---|
| VTuber social behavior | Use held-out direct-address, side-conversation, backchannel, and silence cases |
| Voice delivery | Add calibrated relative loudness/whisper controls and playback-confirmed tests |
| Conversation memory | Add long-horizon temporal contradiction and supersession trials |
| General knowledge | Require source provenance, freshness, and uncertainty calibration |
| Gaming | Evaluate skills on unseen maps and unfamiliar mechanic variants |
| Game creation | Combine code checks with visual inspection and full playthrough completion |
| Inference | Run paired server and first-audible benchmarks under mixed stream/game load |
| Resource management | Connect WDDM-aware per-process GPU measurements to the existing admission bridge |
| Self-improvement | Keep sealed holdouts, one-use evaluation evidence, rollback, and owner review for promotions |

## Acceptance criteria

- Schema-v1 snapshots continue to parse.
- Schema-v2 snapshots require the exact documented aggregate keys.
- New counters reject booleans, negatives, overflows, and successes greater than trials.
- New outcome methods reject non-independent scoring.
- Groundedness trials shorter than 21 turns are rejected.
- Missing new evidence produces INCONCLUSIVE gates.
- Diagnostic routing includes all new gates and remains bounded.
- Existing rehearsal, recorder, and diagnostic regression tests pass.
- No runtime model, voice, scheduler, broadcast, game-control, or release default changes.

## Limitations

This is an evaluation capability, not a claim that STAR has become more human, more accurate, or more intelligent. No audio is captured, no labels are generated, no model is run, and no OBS/VTube Studio/game process is controlled by these modules. The actual Windows streaming host must collect the measurements and obtain independent scoring before any capability can pass a real rehearsal.
