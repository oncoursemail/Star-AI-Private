# STAR AI: Delivery Continuity, Playback Receipts, and Unified Intelligence

**Research date:** 2026-11-12  
**Implementation branch:** \`feat/delivery-ledger-20261112\`  
**Parent:** draft PR #1155 (\`fix/task-ledger-deadline-retry-20261112\`)  
**Scope:** add a bounded, content-free delivery ledger so completed work remains an outstanding obligation until each spoken segment has a trusted local playback acknowledgement. Translate current voice, workflow, observability, inference, gaming, and game-creation research into concrete STAR integration requirements.

## Executive summary

STAR now has a versioned task ledger that can tell whether work was queued, running, completed, failed, cancelled, or expired. That is necessary but insufficient for a voice-first assistant and VTuber.

A research task can complete while its result is still waiting to be spoken. A TTS request can finish generating while audio is still queued. Playback can be interrupted after only part of a response was heard locally. Treating any of those earlier events as "delivered" creates dropped explanations, duplicate speech, or false claims that STAR has finished communicating.

This change adds \`star/delivery_ledger.py\`, a separate control-plane primitive for ordered speech segments and playback receipts.

### Implemented now

- Bounded, thread-safe, in-memory delivery ledger.
- Idempotent creation for the same delivery contract.
- Versioned compare-and-swap transitions and generation-fenced playback leases.
- Ordered speech-segment progress; only fully completed, non-interrupted segments advance.
- Interrupted/partial segments remain pending; already acknowledged segments are not replayed.
- Stale playback receipts cannot complete a newer attempt.
- Expired leases are not automatically requeued; the host must confirm playback has stopped first.
- Playing audio cannot be failed or cancelled without host stop confirmation.
- Absolute delivery deadlines and deterministic reaping.
- Content-free records: opaque IDs, task/version references, SHA-256 digests and timing counters only.
- 34 focused regression tests, including concurrent claim contention.

### Explicit non-goals

This is not yet a durable SQLite outbox, a LiveKit/PortAudio adapter, a VTube Studio integration, or proof that a remote viewer heard STAR. The ledger is in-memory and trusts its host caller to authenticate playback callbacks and confirm worker shutdown. Those integration and persistence layers remain follow-up work.

## 1. Architecture: completion is not delivery

Keep four independent state domains:

1. **Task ledger** — whether the work itself completed and which task version is current.
2. **Delivery ledger** — which result segments remain to be communicated.
3. **Conversation/floor state** — whether STAR should speak, listen, yield, or wait.
4. **Playback host** — what audio was actually submitted, played, interrupted, or stopped.

Recommended flow:

\`\`\`text
USER REQUEST
    |
TASK LEDGER ----> verified result digest
                         |
                   DELIVERY LEDGER
                         |
                ordered short segments
                         |
                 SOCIAL / FLOOR POLICY
                         |
                  TTS + AVATAR OUTPUT
                         |
                  LOCAL AUDIO HOST
                         |
              playback-finished receipt
                         |
            acknowledge segment / retry tail
                         |
              delivery obligation closed
\`\`\`

Do not merge these states. A completed task is not a spoken result; generated TTS is not played audio; local playback completion is not proof of remote audience reception.

## 2. Implementation contract

### Delivery identity and privacy

A delivery record stores:

- opaque delivery ID;
- source task ID and task version;
- result SHA-256 digest;
- ordered segment SHA-256 digests;
- completed-segment count;
- state, version, and playback generation;
- monotonic timestamps scoped to one host clock epoch;
- active attempt/playback IDs and bounded timing values;
- optional absolute deadline and bounded failure code.

It never stores the result text, TTS audio, transcript, raw chat, viewer identity, speaker identity, voiceprint, prompt, or credential. The host must retain the actual speech payload in its separately protected short-lived queue and address it by the delivery/segment identity.

A repeated create with exactly the same contract is idempotent. Reusing a delivery ID with a different task version, result digest, segment list, or deadline is a conflict. This supports safe at-least-once enqueue without silently replacing an obligation.

### Ordered segment semantics

The delivery is split at semantic boundaries (normally sentence or short clause boundaries), not arbitrary byte counts. A host claims only the next unacknowledged segment.

- \`READY\`: waiting for a segment worker.
- \`CLAIMED\`: a worker owns a bounded lease; playback has not started.
- \`PLAYING\`: the host has reported the matching playback ID started.
- \`PARTIAL\`: the current segment was interrupted or did not reach its completion boundary.
- \`FAILED\`: an attempt failed but can be retried within the deadline.
- \`DELIVERED\`: every segment has a complete local playback acknowledgement.
- \`CANCELLED\`: explicitly superseded/cancelled.
- \`EXPIRED\`: the absolute delivery deadline passed.

Only a non-interrupted receipt whose playback position reaches the segment duration (within a small, explicit host-calibrated tolerance) advances the cursor. A partial segment is retried from its beginning; previously acknowledged segments are not replayed. This bounds repetition to the currently interrupted segment. The host should therefore use natural, reasonably short speech chunks and measure duplicate replay rate rather than choosing a universal fixed chunk duration.

### Lease and stop invariants

- Every claim increments a generation and task-independent delivery version.
- Every playback start returns the updated lease version.
- A receipt must match delivery ID, version, generation, segment index, attempt ID, playback ID, and clock epoch.
- An old callback cannot complete a newer attempt.
- A lease timeout alone never proves audio stopped.
- The host must confirm stop before a timed-out playing segment is retried, failed, or cancelled.
- A deadline can expire the obligation, but it does not terminate the audio process. The host must still enforce the stop deadline.
- The ledger is a coordination primitive, not an authorization token.

These rules prevent overlapping audio and stale callback races. The trusted host still needs authenticated, one-use playback receipts; a caller-provided boolean is not cryptographic proof.

## 3. Research findings applied

### LiveKit playback completion is a separate event

LiveKit's official voice I/O API exposes a \`PlaybackFinishedEvent\` with \`interrupted\`, \`playbackPosition\`, and optional \`synchronizedTranscript\`. The event reports how much audio actually played. Its guidance explicitly distinguishes final transcription from playback completion.

Sources:
- https://docs.livekit.io/reference/agents-js/interfaces/agents.voice.PlaybackFinishedEvent.html
- https://kb.livekit.io/articles/8142160213-how-to-detect-when-an-agent-has-finished-speaking

**STAR application:** wire the actual playback-finished event to \`acknowledge_playback\`; do not close a delivery when text generation or a final transcript event arrives. When interrupted, use the host's playback position and synchronized transcript as diagnostics, but only acknowledge complete semantic segments. Keep the existing playback clock's first-submission and first-playback measurements separate.

### Turn-taking and delivery must remain separate

LiveKit's turn documentation describes adaptive interruption handling, VAD-based interruption, backchannel filtering, false-interruption recovery, and truncating conversation history to the portion actually heard before interruption.

Source:
- https://docs.livekit.io/agents/logic/turns/

**STAR application:** reuse the existing causal turn-taking evaluator and held-out policy validation (PRs #1144–#1148). The Social Director decides whether STAR should yield or speak; the Delivery Ledger independently tracks what was actually played. A backchannel must not create a new delivery generation or replay a completed segment. A genuine interruption should stop the active playback, preserve completed segments, and leave the interrupted segment pending.

### Durable execution and retries need explicit event history

Temporal's workflow documentation explains durable event history, replay-based recovery, activity retries, timeouts, heartbeats, and cancellation delivery. Its design patterns include event accumulation, long-running activities, and bounded workflow history.

Sources:
- https://docs.temporal.io/encyclopedia/event-history
- https://docs.temporal.io/develop/go/activities/timeouts
- https://docs.temporal.io/design-patterns

**STAR application:** the new in-memory ledger is only the state-machine core. The next persistence adapter should use a local SQLite WAL transaction/outbox, append state transitions atomically, and recover from an explicit event journal. Never persist a monotonic timestamp as if it remained valid after reboot. Persist wall-clock metadata separately, issue a new host clock epoch at startup, and mark old active playback attempts as requiring host reconciliation before they can be retried. Use bounded exponential backoff for transient TTS/transport failures, but do not retry while the prior audio worker may still be active.

### Standardized agent tracing improves diagnosis

OpenTelemetry's GenAI agent conventions define spans for agent invocation, planning, and tool execution. They distinguish an agent/workflow run from individual model and tool calls.

Source:
- https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md

**STAR application:** add trace links between task ID, delivery ID, TTS generation, playback attempt, and host receipt using opaque IDs. Record durations and error classes, not raw prompts, transcript, chat, audio, or model output. Keep first-content, first-audible, playback completion, and full task duration as separate spans/metrics.

### Local inference speed must be tested against real concurrency

The llama.cpp SPEED-Bench client measures prompt throughput, generation throughput, end-to-end latency, and speculative draft acceptance. Its instructions say to match benchmark client concurrency to the server's configured slot count (\`--np\`) for meaningful throughput comparisons.

Sources:
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

**STAR application:** reuse the existing paired speed/quality evaluator (PR #1143) and read-only inference telemetry (PR #1131). Benchmark baseline and candidate with identical prompts, model, context, output limits, concurrency, and mixed stream workload. Compare first-useful-text and first-audible latency, not just tokens/sec. Include game frame-time p99, audio underruns, OBS render/output skips, RAM/VRAM peaks, and held-out answer quality. Do not change routing defaults based on a single throughput run.

### Game creation and gameplay require execution evidence

OpenGameEval evaluates stateful Roblox Studio work using both scene checks and simulated play. Its paper reports that inspecting relevant objects before editing correlates with higher task success. CEGame-Bench evaluates long-horizon game creation across five engines and uses real-input play to verify completion.

Sources:
- https://arxiv.org/abs/2610.02563
- https://github.com/Roblox/open-game-eval
- https://arxiv.org/abs/2610.26098

Voyager demonstrates a reusable executable skill library with environment feedback and self-verification for Minecraft.

Source:
- https://github.com/caixianzhou/voyager

**STAR application:** keep the reactive game controller separate from the strategic planner; promote skills only after held-out maps/seeds. For Creator, inspect before editing, run the real engine, play with reproducible input, verify save/reopen and ending paths, and replay regressions after repairs. Reuse the existing game-skill, creator-evidence, and rehearsal systems rather than adding duplicate schedulers or skill stores.

## 4. VTuber and social-intelligence integration

The next Social Director should consume:

- current floor owner and turn confidence;
- explicit/implicit addressee confidence;
- backchannel versus takeover classification;
- current speech generation and interruption reason;
- outstanding delivery count and age;
- active segment and local playback state.

The director should be allowed to choose \`SPEAK\`, \`YIELD\`, \`WAIT\`, \`RESUME\`, or \`REMAIN_SILENT\`. It should not be allowed to mark a delivery complete. Only the trusted playback host can provide the receipt.

The Avatar Director should subscribe to the same playback generation and actual playback clock. Mouth visemes should follow audio playback, not TTS text arrival. On interruption, stop mouth movement at the confirmed playback boundary and preserve the current expression/gaze state long enough to avoid abrupt visual snapping. The VTube Studio adapter remains owner-authorized and revocable.

A natural streaming persona is not simply constant talking or simulated emotion. It needs context, timing, selective silence, graceful interruption recovery, consistent character behavior, and honest disclosure that STAR is an AI. Viewer identities and raw voice data should not be retained by default.

## 5. Next integration plan

| Priority | Work | Acceptance |
|---|---|---|
| 1 | Connect TaskLedger completion to delivery creation | Only verified current task versions create obligations |
| 2 | Add authenticated playback host adapter | Receipt matches one active playback generation |
| 3 | Connect playback-finished event | Final text generation never counts as playback completion |
| 4 | Integrate interruption/floor control | Backchannels do not replay speech; true barge-in preserves completed segments |
| 5 | Add SQLite WAL event/outbox adapter | Crash recovery never trusts an old monotonic epoch |
| 6 | Connect Avatar Director | Visemes and expressions follow actual playback timing |
| 7 | Integrate OpenTelemetry traces | Task, delivery, TTS, and playback stages are correlated without content |
| 8 | Run private stream rehearsal | Duplicate replay, stale resume, first-audible, underrun, OBS and avatar-sync gates pass |
| 9 | Mixed-load inference experiment | Latency improves without answer-quality, FPS, audio, or OBS regression |
| 10 | Game/Creator integration | Held-out skill transfer and complete player journeys pass |

### Required acceptance tests

- Exact duplicate enqueue returns the original record; changed contract conflicts.
- Two workers racing to claim one segment produce exactly one winner.
- A stale playback receipt cannot advance a later generation.
- A partial/interrupted segment remains pending.
- A completed segment is never replayed when a later segment is interrupted.
- A short non-interrupted playback is not mistaken for a complete segment.
- An expired lease is not requeued until the host confirms the old worker stopped.
- Playing audio cannot be cancelled/failed without host stop confirmation.
- Deadline expiry prevents further retry; completed deliveries remain completed.
- Clock rollback and cross-epoch leases are rejected.
- No raw text/audio/transcript/viewer identity enters the ledger schema.
- A local playback receipt is never presented as proof that the audience heard the stream.

## 6. Current validation boundary

The new module is a pure, in-memory state machine. It has 34 focused tests covering idempotency, ordered segments, interruption, partial playback, stale receipts, lease recovery, cancellation, deadlines, privacy-oriented schema limits, bounded capacity, clock epochs, and concurrent claims. Local validation performed before commit: \`pytest -q\` (34 passed) and Python compile/smoke check.

The implementation does **not** yet connect to STAR's TTS, LiveKit, PortAudio, Windows audio, OBS, VTube Studio, chat, or agent runtime. It does not persist across process restarts and does not prove remote audience reception. No physical Windows, RTX, game, or livestream test is claimed. No model weights, routing defaults, runtime permissions, broadcast settings, or production \`main\` are changed.

## 7. Research references

- LiveKit playback completion: https://docs.livekit.io/reference/agents-js/interfaces/agents.voice.PlaybackFinishedEvent.html
- LiveKit turn-taking and interruption: https://docs.livekit.io/agents/logic/turns/
- Temporal event history: https://docs.temporal.io/encyclopedia/event-history
- Temporal activity timeouts/heartbeats: https://docs.temporal.io/develop/go/activities/timeouts
- Temporal design patterns: https://docs.temporal.io/design-patterns
- OpenTelemetry GenAI agent spans: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md
- llama.cpp SPEED-Bench: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- llama.cpp speculative decoding: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- OpenGameEval: https://arxiv.org/abs/2610.02563
- CEGame-Bench: https://arxiv.org/abs/2610.26098
- Voyager: https://github.com/caixianzhou/voyager
