# STAR AI: Durable Delivery Recovery, Real-World Voice Evaluation, and Closed-Loop Capability Research

**Research date:** 2026-11-12  
**Implementation branch:** feat/delivery-ledger-sqlite-recovery-20261112  
**Parent:** draft PR #1156  
**Scope:** crash-safe voice delivery, restart reconciliation, natural VTuber interaction, local inference optimization, game-playing skill transfer, complete game creation, and practical general knowledge.

## Executive summary

STAR's in-memory Delivery Ledger distinguishes completed work from speech that was actually played. The next failure boundary is process restart. A process can crash after audio starts but before a playback receipt is committed. If STAR simply reloads the old lease and retries, she can talk over an orphaned audio worker or repeat speech that was already heard.

This change adds a SQLite WAL-backed SQLiteDeliveryLedger with a conservative restart protocol:

- Every state mutation is committed before returning.
- A database failure rolls the in-memory mutation back.
- Records and transition history contain only opaque IDs, state/version metadata, timing metadata, and SHA-256 digests.
- Monotonic timestamps are rebased at startup using persisted wall-clock metadata.
- Non-active deadline-bound obligations expire on restore if their wall deadline has passed or the wall clock moved backward.
- Old CLAIMED/PLAYING work always becomes RECOVERY_REQUIRED, even when overdue; the host must confirm the old worker stopped before deadline expiry can clear the fence.
- The host must stop and confirm old synthesis/playback workers before reconciliation.
- A claimed-but-not-playing segment returns to READY; a possibly partial playing segment returns to PARTIAL.
- Old leases are never accepted in a new clock epoch.

This is a durable state layer, not yet a connection to STAR's real TTS, LiveKit, PortAudio, OBS, VTube Studio, or agent runtime. The integration boundary is explicit.

## 1. Implementation: SQLite WAL delivery store

### Why this boundary matters

There are four separate facts:

1. The task completed.
2. The response was queued for speech.
3. The local audio device played a segment.
4. A remote viewer actually heard it.

Only the first three are observable by STAR's local runtime; local playback is not proof of remote reception. The durable store preserves the local delivery obligation and receipt history without claiming audience delivery.

### Storage contract

The database uses SQLite WAL mode, synchronous=FULL, a bounded transition table, a single-writer instance contract, and version compare-and-swap checks.

Persisted fields:
- delivery/task opaque IDs and task version;
- result and segment SHA-256 digests;
- completed segment cursor;
- state, version, generation;
- attempt/playback IDs when active;
- monotonic timing snapshot for diagnostics;
- wall-clock creation/update/deadline metadata.

Never persist:
- result text;
- prompt or model output;
- speech transcript;
- PCM, encoded audio, or waveform;
- viewer names, handles, IDs, or voiceprints;
- credentials or access tokens.

The database is local application state. Do not place it on a network share, sync folder, or removable drive with uncertain locking semantics. The WAL sidecar and database file must be backed up together only after a consistent SQLite backup/checkpoint procedure.

### Restart protocol

At startup, the store creates a new host clock epoch and converts all old monotonic times into the new epoch. Old lease expiry values are never compared against the new clock.

| Persisted state | Restored state | Required action |
|---|---|---|
| READY | READY | Can claim |
| PARTIAL | PARTIAL | Retry current segment |
| FAILED | FAILED | Retry within deadline |
| DELIVERED | DELIVERED | Immutable terminal result |
| CANCELLED | CANCELLED | Terminal |
| EXPIRED | EXPIRED | Terminal |
| CLAIMED | RECOVERY_REQUIRED | Stop old synthesis worker, confirm; reconcile to READY or EXPIRED if deadline passed |
| PLAYING | RECOVERY_REQUIRED | Stop old audio worker, confirm; reconcile to PARTIAL or EXPIRED if deadline passed |

A restart fence is deliberately not a timeout. The host must actually reconcile the old process tree/audio route. If the host cannot prove the previous worker stopped, STAR must leave the delivery blocked rather than risk overlapping speech.

### Deadline semantics

The in-memory ledger uses monotonic milliseconds. Monotonic clocks are not portable across reboot. The store therefore persists a wall deadline alongside the record and reconstructs a new monotonic deadline on startup.

If wall time moved backward relative to the last persisted update, a non-active deadline-bound obligation expires conservatively rather than receiving extra time. An active CLAIMED/PLAYING record remains RECOVERY_REQUIRED regardless of its deadline: the host must stop and confirm the old worker first, after which reconciliation applies the deadline and expires it if due. This prevents an overdue orphaned audio process from losing its stop-confirmation fence. A production host should also monitor time synchronization and record clock-health diagnostics. Wall time is used only for cross-restart deadline reconstruction; lease expiry remains monotonic and host-epoch scoped.

### Transaction and corruption behavior

- Each changed record uses a SQLite BEGIN IMMEDIATE transaction.
- The previous durable version is checked before update.
- The new snapshot and transition event commit together.
- If the transaction fails, the in-memory record map is restored.
- Future schema versions are rejected; no silent downgrade.
- Malformed snapshots fail closed with DeliveryStoreCorrupt.
- Event history is bounded; the current snapshot remains authoritative.
- integrity_check() and WAL checkpoint methods are exposed for diagnostics/maintenance.

The store is intentionally single-writer. A second instance that has stale state receives DeliveryStoreConflict rather than overwriting newer state. Multi-process ownership should be implemented later through a single host service, not by allowing arbitrary clients to write the same SQLite database.

## 2. New voice-agent evaluation: black-box audio truth

A newly discovered project, todoforai/voice-agent-bench, offers a useful evaluation complement to STAR's internal timing telemetry. It feeds byte-identical prerecorded human audio into a virtual microphone, captures the agent's actual speaker output, and derives metrics from the audio rather than trusting internal timestamps.

The repository currently documents:
- voice-to-voice latency;
- barge-in stop time;
- stalls and silent gaps;
- false barge-ins;
- echo leakage;
- self-interruption and truncated replies;
- median and p95 over repeated conversations.

Its examples show why speed alone is misleading: the benchmark reports latency together with whether the agent talks through a genuine interruption, cuts itself off, or mistakes its own echo for the user. It also cautions that a fixed mock LLM is used for cascaded systems, so those rows evaluate the voice pipeline rather than language-model quality.

Source: https://github.com/todoforai/voice-agent-bench

### STAR adaptation

Build a Windows-compatible black-box rehearsal lane using virtual audio endpoints or a loopback test driver. The runner should:
1. Replay deterministic scenarios through a virtual microphone.
2. Capture the actual output endpoint with a calibrated clock.
3. Run at least five repetitions per scenario.
4. Report median, p95, and sample count.
5. Keep pipeline latency separate from answer correctness.
6. Include clean speech, hesitation, backchannel, genuine barge-in, overlap, echo, noise, and long-answer interruption scenarios.
7. Preserve audio only in an explicit local test workspace with retention controls; default reports contain timestamps and metrics, not raw viewer audio.

Acceptance metrics:
- end-of-turn to first audible output;
- user interruption onset to actual agent silence;
- false barge-in count;
- self-interruption count;
- audio stall count and longest stall;
- echo leakage rate;
- spoken-content coverage;
- duplicate segment replay rate;
- local playback completion versus remote audience reception clearly distinguished.

Do not claim human-like from a low latency number. Naturalness also depends on floor control, selective silence, addressee understanding, recovery, and conversational relevance.

## 3. Full-duplex intelligence: Realtime-Venus as an architectural reference

Realtime-Venus describes a two-loop design: one loop handles live perception and speech, while another handles delegated background tasks and prepares replies for the same conversation. Its harness captures the context at request time, lets the interaction continue, routes the work to a model or registered skill, and returns a prepared reply to the frontend. Playback tracking is used to confirm local delivery.

The public report lists separate audio/video and interaction results, including a 97% continuation rate for user backchannels on Full-Duplex-Bench v1.5. These are the project's own reported benchmark results and must not be treated as STAR measurements.

Source: https://realtime-venus.github.io/

### STAR application

Use two coordinated loops:
- **Interactive loop:** audio/video perception, floor ownership, short responses, game reactions, avatar timing.
- **Delegated loop:** research, tool calls, coding, long-running game planning, memory retrieval, and creator tasks.

The interactive loop must never wait for a long research/tool job. Each delegated task captures the conversation/task version at dispatch; stale results return as artifacts for the current conversation state to decide whether to use, revise, or discard.

The Delivery Ledger remains the authority for local spoken progress. The Social Director chooses whether and when to speak; it cannot fabricate playback completion.

## 4. Faster local inference: benchmark the workload, not a slogan

A recently surfaced inference-optimization lab separates three evidence classes: measured CPU inference, extracted microbenchmarks, and simulated serving policies. It evaluates prompt prefill, decode, quantization, continuous batching, block KV allocation, exact prefix reuse, LRU eviction, TTFT, TPOT, p95/p99 latency, and SLO goodput.

The report explicitly labels an end-to-end comparison inconclusive when its paired confidence interval crosses zero, even though a microkernel improved. This is the right discipline for STAR: a faster isolated kernel is not proof of a faster user experience.

Source: https://github.com/200lz/llm-inference-optimization-lab

### STAR experiment matrix

On the target 8 GB VRAM / 32 GB RAM class, test one change at a time:
- prompt-prefix stability and cache hit rate;
- KV-cache memory format and residency;
- context truncation versus retrieval summaries;
- quantization by task class;
- speculative decoding with a compatible draft model;
- CPU/GPU layer placement;
- model residency and cold-start cost;
- continuous batching at the actual configured slot count;
- interactive-priority admission while OBS, audio, avatar, and a game are active.

Record p50/p95/p99 first-token latency, decode tokens/s, first-audible latency, peak VRAM/RAM, GPU utilization, game frame-time p99, OBS render/encode drops, audio underruns, answer quality, tool success, and task completion. Use paired runs, pinned model/runtime revisions, identical prompts and concurrency, warm/cold splits, and bootstrap confidence intervals. Do not promote a speed configuration unless quality and interactive SLOs remain within predeclared tolerances.

## 5. Game intelligence and game creation

### GameDevBench

GameDevBench provides 333 Godot game-development tasks across 2D graphics/animation, 3D graphics/animation, UI, and gameplay logic. The project reports that visual feedback improved one evaluated configuration from 41.1% to 52.0%; it also reports substantial difficulty on graphics-heavy tasks.

Source: https://github.com/waynchi/gamedevbench

STAR should therefore treat visual inspection as a first-class tool, not an optional screenshot after coding. A Creator task should capture a before-state, edit trace, engine output, post-state screenshots/video, and a reproducible playthrough.

### Gamer skill transfer

Keep a high-frequency reactive controller separate from the strategic planner. Skills should be executable, versioned, and scoped to game/build/map/control scheme. Promote only after repeated success on held-out maps or seeds. Record preconditions, action sequence, expected observations, recovery branches, and failure traces. Similar controls across two games do not prove transfer.

### Creator completion gate

A game is not complete because scripts compile or a scene opens. Verify:
- boot and menu path;
- core loop with actual input;
- objectives and progression;
- win/loss/ending paths;
- save/reopen and restart;
- multiplayer invariants when relevant;
- visual readability and performance;
- regression replay after repairs.

## 6. General knowledge and memory transfer

Use STAR's existing memory architecture rather than adding a competing vector store. Each reusable fact/skill should include provenance, observation date, last verification, confidence, scope/version, evidence, known counterexamples, and privacy/retention classification.

Build a knowledge curriculum across mathematics, physics, biology, computing, engineering, history, geography, languages, art, music, economics, and game design. Evaluate factual recall separately from current-information retrieval, reasoning, and practical transfer. A fact remembered but misapplied is not a successful learning outcome.

## 7. Next integration order

| Priority | Integration | Acceptance |
|---|---|---|
| P0 | Run SQLite store CI on exact PR head | Full offline tests, Pyright, React checks |
| P1 | Connect completed TaskLedger results to durable delivery enqueue | Current completed task version only; idempotent retry |
| P1 | Connect host process supervisor to restart reconciliation | No claim/replay until old worker is confirmed stopped |
| P1 | Connect real playback-finished callbacks | Stale generation rejected; actual local output timing |
| P2 | Add black-box audio rehearsal lane | Repeated audio-derived latency and interruption metrics |
| P2 | Connect Social Director and Avatar Director | Selective yielding; mouth follows actual playback |
| P2 | Add delegated-task conversation context capture | Stale result cannot replace a newer user request |
| P3 | Mixed-load inference A/B | Speed gains without FPS, audio, OBS, or quality regressions |
| P3 | Game skill held-out evaluation and Creator completion gate | Reproducible game success, not self-reported mastery |

## 8. Validation boundaries

The SQLite module uses only the Python standard library. The new tests cover WAL mode, restart/rebase, progress preservation, active-worker fencing, deadline expiry, wall-clock rollback, idempotency, stale-writer rejection, rollback on disk failure, bounded history, content-free storage, corruption rejection, and integrity/checkpoint operations.

No real Windows audio device, TTS engine, LiveKit session, OBS stream, VTube Studio model, GPU benchmark, Roblox Studio session, or game playthrough was executed in this change. The voice-agent-bench, Realtime-Venus, GameDevBench, and inference-lab results are external research, not STAR performance claims. No model weights, inference defaults, broadcast settings, permissions, or production main branch are changed.
