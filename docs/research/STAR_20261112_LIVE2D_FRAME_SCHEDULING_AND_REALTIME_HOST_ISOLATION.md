# STAR 2026-11-12 — Live2D Frame Scheduling, Playback Synchronization & Realtime Host Isolation

## Executive summary

STAR already has a useful playback-aware Live2D path:

- stream_motion.py creates bounded 15/30/60 Hz motion samples from host-supplied audio envelopes and semantic cues.
- stream_stage.py only makes a stage plan eligible after the host acknowledges audible playback.
- vtube_live2d_bridge.py rejects future, stale, duplicate, out-of-order, wrong-epoch, or revoked-stage frames.
- vtube_local_host.py authenticates to the loopback VTube Studio API and sends custom-parameter frames through a synchronous request/response WebSocket exchange.
- stream_interrupt_host.py revokes a stage, asks the physical audio host to stop, flushes animation, and only then sends a neutral pose.

The remaining scheduling risk is at the boundary between frame production and the synchronous VTube Studio transport. The transport is intentionally bounded and fail-closed, but a producer that calls send_frame() directly can wait on a WebSocket round trip. A 30 Hz animation cadence is 33.3 ms; a 100 ms socket timeout is three frame intervals. A slow local transport can therefore cause a producer to stall or deliver old work unless the host carefully isolates it.

This change adds VTubeFramePump: one dedicated sender thread, one pending-frame slot, latest-wins coalescing, strict audio-cursor freshness, playback-epoch fencing, and a flush barrier. It does not change model inference, audio capture, playback, VTube Studio permissions, or broadcast behavior.

## 1. Research findings

### 1.1 AVTR-1: fast motion is not enough

AVTR-1, submitted September 19, 2026, describes a real-time interactive avatar stack driven by an external voice agent. Its central systems insight is that an interactive avatar requires synchronized speech output, frame scheduling, and interruption handling—not merely a fast motion generator. The work uses a 153M-parameter audio-conditioned motion generator and a streaming runtime.

STAR should borrow the scheduling and synchronization principles, not blindly replace its existing Live2D model with AVTR-1. AVTR-1 targets generated 3D dyadic motion; STAR's current art direction is an authored Live2D character controlled through 14 VTube Studio custom parameters. A 153M motion model is a future optional experiment only after consumer-GPU memory, latency, licensing, and visual-style compatibility are measured.

Sources:
- https://arxiv.org/abs/2609.22913
- https://www.alphaxiv.org/abs/2609.22913

#### AVTR-1 streaming details that matter to STAR

The paper's serving layer separates three concurrent worklets: transport, conversation engine, and rendering. They communicate through a type-routed event bus with independent consumer queues. A shared session media clock schedules deadlines and accounts for overruns. The speech scheduler models each utterance as start marker, audio fragments, and end marker; on interruption it reports the admitted/heard prefix and discarded suffix so the voice agent can remove unheard speech from its dialogue state.

These ideas suggest two future STAR improvements beyond this frame pump:

1. A typed local media event bus separating voice transport, conversation state, avatar rendering, OBS status, and control-plane lifecycle.
2. Heard-prefix reconciliation: when speech is interrupted, feed only the playback-confirmed portion back into dialogue state and remove generated-but-unheard text/audio from the model's conversational history. DeliveryLedger already tracks acknowledged segments, but it does not yet rewrite the voice model's dialogue state.

Important queue distinction: AVTR-1's continuous audio/video media path preserves media timestamps and does not skip frames to catch up, because dropping encoded media frames can corrupt synchronization. STAR's latest-wins pump is deliberately narrower: it coalesces Live2D parameter-state updates sent to VTube Studio, not audio packets or timestamped WebRTC video frames. If STAR later adds a WebRTC avatar transport, it needs a media-clock/jitter-buffer scheduler rather than reusing this latest-wins mailbox.

The paper's offline five-frame request table reports 232 ms for 200 ms of output on an RTX 4060 (0.86x real-time factor) and 207 ms on an RTX 3060 Ti (0.97x). Those measurements are for AVTR-1's full rendering stack and its test configuration, not STAR; they show why this model should not become a default concurrent-stream dependency on STAR's consumer GPU. Keep it an optional isolated experiment until memory, quality, and mixed-workload latency are measured.

AVTR-1 also introduces Reference-Based Directed Granger Gain (R-DGG), an evaluation intended to test whether the other participant's speech contributes predictive information to the avatar's listening motion after accounting for the listener's own history and the speaker's motion. For STAR, this suggests a future transient listening-motion lane: use owner-authorized, short-lived voice-activity/turn-state and optional coarse direction cues to drive subtle gaze, head tilt, or nod behavior while a viewer speaks. Do not store voiceprints or infer identity from voice. Evaluate listening behavior separately from lip-sync and speech quality; a plausible idle animation is not evidence that STAR is actually responding to the other speaker.

### 1.2 VTube Studio's API is a parameter-injection interface

The official VTube Studio API supports plugin-created custom parameters and InjectParameterDataRequest. The model artist maps those parameters to Live2D inputs in the VTube Studio UI. This fits STAR's existing 14-parameter rig bridge.

Operational implications:
- Keep the WebSocket on explicit loopback only.
- Pair only after an explicit owner action and the native VTube Studio permission prompt.
- Store the returned token in OS-protected local storage; never in Git, telemetry, prompts, or logs.
- Do not create duplicate parameter names or exceed VTube Studio's custom-parameter limits.
- Treat a connected socket as insufficient readiness: the session must be authenticated and STAR's custom parameters registered.
- On transport failure, drop the frame and latch a fault; do not replay queued facial motion or silently re-pair.

Sources:
- https://github.com/DenchiSoft/VTubeStudio
- https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins

### 1.3 Why a one-slot latest-wins queue is correct for animation

A speech transcript or task result is durable work; every part may matter. An animation frame is a time sample. Once its intended presentation time has passed, replaying it is worse than dropping it.

For a 30 Hz stream:
- target cadence is approximately 33.3 ms;
- a 100 ms transport timeout spans approximately three frame intervals;
- a conventional unbounded FIFO can accumulate stale expressions and create visible lag;
- a one-slot latest-wins mailbox preserves the freshest pending sample while a prior network write completes.

This is not a general queue policy. Do not use latest-wins for speech segments, task events, gameplay actions, or durable delivery obligations. Those require their own ordered/idempotent semantics.

## 2. New component: VTubeFramePump

star/vtube_frame_pump.py adds a small host-side scheduling primitive.

### Contract

- One sender worker owns all VTube Studio frame writes submitted through the pump.
- At most one frame is pending; a newer valid frame replaces the pending frame.
- The producer performs validation and a short condition-lock update only; it never performs WebSocket I/O.
- Only the exact StagePlan object and playback epoch armed by the host may submit.
- The host must report ready=True, meaning authenticated and custom parameters registered.
- Frame timestamps must be strictly increasing within the epoch.
- A frame cannot be ahead of the audible output cursor.
- A frame more than 100 ms behind the audible cursor is rejected.
- A sample older than the configured freshness limit (default 100 ms) is dropped before dispatch and checked again by the existing VTubeLocalHost.
- A send exception latches a fault and discards pending work. There is no automatic retry or reconnect.
- Epoch IDs cannot be reused within the pump lifetime.

### Interruption barrier

flush_epoch(epoch) first revokes new submissions and discards the pending frame. If a send is already in progress, it waits for that send to finish. A successful return means no old-epoch send remains in flight.

The trusted host should wire it into the existing interruption sequence:

~~~text
stage.interrupt_if_current(plan)
    -> stop_epoch(playback_epoch)       # physical audio host acknowledgement
    -> pump.flush_epoch(playback_epoch) # no old VTS write remains in flight
    -> host.send_neutral(plan, epoch)   # release old rig parameters
    -> permit a later turn
~~~

The order is important. The pump does not stop audio and does not decide whether the old stage is valid. The existing StreamInterruptionHost remains the coordinator and must revoke the stage before the old frame can be accepted by VTubeLocalHost.

### Example host wiring

~~~python
bridge.bind(plan, playback_epoch=epoch)
pump.arm(plan, playback_epoch=epoch)

# Called by a host animation scheduler, not an audio device callback.
pump.submit(
    plan,
    playback_epoch=epoch,
    frame=frame,
    audible_cursor_s=output_cursor_seconds,
    sampled_ms=sampled_monotonic_ms,
)

# Existing StreamInterruptionHost callbacks:
flush_animation=lambda old_epoch: pump.flush_epoch(old_epoch)
avatar=the_same_vtube_local_host
~~~

Call pump.close() and wait for a successful return before closing the VTube Studio host. If flush_epoch() times out, keep the stream interruption faulted; do not send a neutral packet or arm another epoch until the host has independently recovered the transport.

## 3. Readiness state

VTubeLocalHost.ready is true only when:
1. the local socket exists;
2. authentication succeeded;
3. all 14 STAR custom parameters were registered.

This avoids arming an animation pump against a merely connected but not-yet-registered socket. The property exposes no token, endpoint, or permission details.

## 4. Performance and quality measurements

The pump's counters are aggregate-only:
- submitted;
- sent;
- replaced;
- stale_dropped;
- rejected;
- send_failures;
- flush_timeouts;
- running / active / pending / in_flight / fault.

The counters do not contain frame values, audio, transcript text, model prompts, playback IDs, viewer identity, or VTube Studio tokens.

Run a private host rehearsal at 15, 30, and 60 Hz with:
1. idle CPU/GPU;
2. local LLM generation;
3. Roblox Studio gameplay;
4. OBS capture plus game plus speech;
5. injected VTube Studio latency and socket disconnect;
6. interruption while a frame write is in flight.

Report:
- producer-call p50/p95/p99;
- sample age at actual dispatch;
- sent/replaced/stale-drop ratio;
- time from physical audio stop to successful frame flush;
- time from flush to neutral parameter response;
- stale-frame sends after a successful flush (must be zero);
- VTube transport faults and recovery count;
- game frame-time and OBS skipped-frame deltas;
- audio underruns and voice first-audible latency.

Do not claim a speedup until the same hardware, model, VTube Studio version, frame cadence, and workload are measured before and after. The intended benefit is isolation and freshness under a slow transport, not more LLM tokens per second.

## 5. Safety and lifecycle boundaries

- VTubeFramePump is a scheduler, not an authorization system.
- Only trusted host code may call arm, submit, or flush_epoch.
- The language model and viewers must never receive the VTube Studio socket, token, host object, or frame pump as tools.
- submit is not a hard-real-time audio callback API; call it from a dedicated host animation scheduler.
- The bridge remains responsible for validating every motion parameter and the actual audible cursor.
- VTubeLocalHost remains responsible for authenticated protocol exchange and closing a failed socket.
- The pump does not persist epochs across process restarts. Existing delivery/host recovery must stop old workers and establish a new host epoch before reuse.
- Do not automatically reconnect or re-pair after an API error.
- No broadcast, game-control, filesystem, or model permissions are added.

## 6. Validation status and limitations

The new pump has nine focused offline tests covering:
- latest-wins coalescing;
- producer progress while a transport write is blocked;
- flush waiting for an in-flight write;
- rejecting submissions after flush;
- stale, future, and unheard frame rejection;
- exact plan/epoch matching;
- duplicate and out-of-order frame rejection;
- fault latching with no retry;
- close behavior;
- authenticated/registered host readiness.

The pump itself does not prove that a physical VTube Studio model rendered a frame. That requires the owner's Windows host, the actual Live2D model, VTube Studio, and an instrumented local rehearsal. The GitHub Actions run on the exact PR head is the repository-level gate.

## 7. Related STAR systems to connect next

1. Have the Windows host own one VTubeLocalHost and one VTubeFramePump for the lifetime of the VTS session.
2. Feed the pump from the existing playback cursor and StarStage.motion() output.
3. Wire pump.flush_epoch into StreamInterruptionHost.flush_animation.
4. Record only aggregate pump counters and send-age histograms through the existing privacy-safe AgentTrace adapters.
5. Use actual playback-finished receipts to close DeliveryLedger segments; do not infer speech completion from model generation.
6. Run the same 60-minute mixed workload used by the stream quality evaluator, with and without background research/gaming work.
7. Keep the real-time voice/game lane ahead of background model work in the existing resource governor.

## Sources

- AVTR-1: https://arxiv.org/abs/2609.22913
- AVTR-1 project overview: https://avtr-1.avaturn.live/
- VTube Studio API repository: https://github.com/DenchiSoft/VTubeStudio
- VTube Studio plugin documentation: https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins
- STAR existing Live2D bridge: star/vtube_live2d_bridge.py
- STAR existing local VTS host: star/vtube_local_host.py
- STAR existing stage coordinator: star/stream_stage.py
- STAR existing interruption coordinator: star/stream_interrupt_host.py
