# STAR · Native Audio Abort, Gaming Intelligence and Generalist VTuber Roadmap
**Research and implementation note — 2026-11-07 · Owner-local draft, OFF by default**

## What actually changed

PR #1043 introduced `LocalEpochPCMSink`, which queues validated PCM into
the existing `SoundSpeaker` interface after a trusted output-epoch check.
But `SoundSpeaker.stop()` only clears a Python buffer. PCM already passed to
PortAudio may continue playing after cancellation. The new strictly opt-in
`NativeAbortPCMSpeaker` transport and the small public `SoundSpeaker`
methods `abort_pending_output()`, `restart_after_abort()` and
`native_output_state()` provide a *real PortAudio abort request*, not an
application-only stop. The transport is safe to use only with a **dedicated,
already started SoundSpeaker under exclusive owner-host control**; it should
never share a speaker with another live call. It refuses automatic restart,
fails closed on untrusted native state and requires an independent host quiet
attestation for recovery. No Windows audio or live game was operated here.

**Critical nuance:** PortAudio `abort()` stops promptly without waiting for
pending buffers. This is stronger than clearing a Python buffer but DOES NOT
prove sound has been silenced at the physical DAC, Windows mixer, an OBS
monitor, an HDMI capture device or a virtual microphone. It also does not
certify that anyone heard the sound. Strict `ignore_errors=False` is required
because python-sounddevice defaults to ignoring native abort errors.
References: [python-sounddevice 0.5.3 stream API](https://python-sounddevice.readthedocs.io/en/0.5.3/api/streams.html);
[PortAudio abort documentation](https://files.portaudio.com/docs/v19-doxydocs/portaudio_8h.html).

## Why this is the highest-value VTuber fix right now

Star's rapidly expanding modular controls already distinguish model
generation, TTS production, queued PCM, the native speaker and avatar rig.
A convincing stream requires *one coordinated cancellation chain*:
owner interruption/game danger -> invalidate the production epoch ->
cancel generation/TTS -> reject already queued PCM/rig frames ->
request strict native audio abort -> flush pending rig animations ->
independently verify output quiet and neutral avatar ->
explicitly authorize the next distinct epoch.

This work replaces the last weak link (application-only PCM stop) with an
abort-capable opt-in bridge. It does **not** bypass the existing
`StreamOutputEpochFence`, `StreamOutputConsumerQueue`,
`LocalEpochPCMSink`, or `NaturalTurnPhysicalHost`.

### Integration order for a trusted Windows host

1. Open and start a dedicated `SoundSpeaker` on an explicitly selected owner
   local output device. Confirm the application queue is initially empty.
2. Wrap it in `NativeAbortPCMSpeaker(..., owner_approved=True)`. Pass the
   wrapper into `LocalEpochPCMSink`; enable the sink locally and bind a
   freshly authorized output epoch after independent quiet verification.
3. Deliver only `tts_pcm` via the existing output-consumer fence, with its
   latest trusted epoch; `play()` is never an authorization boundary by itself.
4. On authenticated interruption, revoke and drain software queues **before**
   calling `LocalEpochPCMSink.request_stop(epoch)`; this invokes
   `SoundSpeaker.abort_pending_output()` through the wrapper. Never call it
   from the PortAudio audio callback or pass stop authority to viewer/model
   text. Keep all native operations off the frame-critical/render threads.
5. Verify quiet with a separate trusted device/loopback watchdog. An
   application-buffer-empty flag, `RawOutputStream.stopped`, a successful
   `Pa_AbortStream` status or the absence of the first callback is **not**
   sufficient. Verify that avatar motion is neutral, too.
6. Acknowledge `LocalEpochPCMSink.observe_quiet(epoch,
   native_output_flushed=True)` only after that independent observation.
   Then call `NativeAbortPCMSpeaker.resume_after_flush(independently_quiet=True)`
   from the owner-host only, and bind a **new, never-reused epoch**.
7. On any failed abort, restart, audio probe, lost epoch identity, or
   unsupported device, hold output disabled and require explicit local
   recovery. Do not silently fall back to draining `stop()` in an emergency.

**Open engineering risk:** The generic `SoundSpeaker` still supports direct
`play()` from unrelated callers. The transport only serializes *its own*
submissions. The Windows host must prove exclusive speaker ownership and
must not route unrelated audio into the same object; otherwise neither the
epoch fence nor the native abort boundary covers those writers.

## End-to-end acceptance experiment (private, nonbroadcast)

- Owner explicitly selects physical or virtual output, starts offline game,
  avatar, speech engine and OBS *recording only*. Confirm streaming outputs
  are disabled; never use `StartStream` in the test harness.
- Produce controlled 24 kHz mono PCM with identifiable short bursts and issue
  an authenticated stop midway. Record: epoch-revoke time, producer cancel,
  consumer last admission, native-abort-return, output loopback last nonzero
  sample, avatar return-to-neutral, independent host quiet approval.
- Use a trusted OS audio loopback/capture stream with precise common
  timestamps, account for capture buffering and noise floor; report the
  measurement uncertainty. A pre/post spectrogram or an app queue count is
  insufficient by itself.
- Test barge-in and game danger while OBS + avatar + inference contend for
  compute, not only at idle. Simulate loss of native device, backend
  exception, route change and a new PCM arrival racing an interruption.
- Targets to validate, **not measured claims**: very low stale-audio rate,
  strict no-replay of revoked epochs, bounded p95 speech interrupt latency,
  no stale avatar frames, no broadcast, negligible frame-time regression.
  Publish actual distributions and trial counts before choosing thresholds.
- Do not use the currently installed Windows services, microphone, or active
  streaming configuration without a separate owner-reviewed rehearsal gate.

## Intelligence architecture — verified improvement rather than more prompts

**Tier A: microsecond/millisecond local reflexes.** A small deterministic
policy handles input release, focus loss, jump/dodge deadlines and input
rate caps. It never awaits a generative model to avoid imminent hazards.

**Tier B: tactical planner.** A compact vision-language/game-state model
runs only when the scene is stable enough and budget permits; outputs a
versioned, bounded action intention with a confidence and expiry.
Policy updates must be rejected after a focus change, new episode or
camera scene transition.

**Tier C: slower learning and reflection.** Episode traces contain privacy-
minimized observation/action/outcome evidence, never guessed rewards.
Compare strategies under heldout maps/opponents, blocked random seeds
and human-reviewed safety constraints. Store skills only if outcome checks
actually improve. Use the existing verified skill bank and O(1) scene-scoped
cache instead of adding SQLite calls to frame-critical paths.

*Gym-Anything-RT* (2026-10-27) motivates deadline-based evaluation:
gameworld keeps moving while the agent thinks; paused-world results
overestimate interactive skill.
[Study](https://arxiv.org/abs/2610.37567).

For Roblox game creation, couple Studio MCP/Open Cloud/Rojo workflows to
small executable tests, property assertions, playability checks, visual
capture, rollback and cross-place regression tests. Use
[OpenGameEval](https://github.com/Roblox/open-game-eval) as an evaluation
model, not as proof Star already creates complete playable games.

## Speed: optimize *speech-ready* latency and system QoE

On an 8 GiB RTX GPU, peak model token throughput is the wrong end goal.
GPU time and VRAM must remain available for game rendering, VTube Studio,
OBS encoding/scene transitions and visual perception. The relevant
measurement is **p50/p95 from incoming observation/viewer speech to
first intelligible TTS playback**, plus stale output after interruption,
lost input frames, game FPS, speech glitch count and OBS frame drops.

Experiment in matched A/B episodes (same game, scene, prompt mix, model
quantization, seed when possible), with explicit model warmup and
confidence intervals:

- Prefix/KV prompt caching, compact grounded state summaries, retrieval of
  *verified* project facts and bounded tool results instead of blindly
  growing context. Show citation/source provenance for fresh general facts.
- Speculative decoding and draft-token lengths, with paired end-to-end
  latency and audio-first-token benchmarks; draft model memory may cost
  more than it saves on an 8 GiB GPU. Use the real
  [llama.cpp SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md)
  rather than an assumed tokens/sec value.
- Low-VRAM routing: quick-response model for commentary, stronger model
  for offline game building and hard planning, CPU TTS when quality is
  acceptable, VRAM reservations and nonblocking admissions. Degrade
  gracefully by delaying background work, not dropping the realtime game.
- Assert no performance improvement until paired on-device measurements
  pass and regression tests establish that quality has not worsened.

## Making Star *feel* more human, without pretending she is human

The main gains are timing, continuity and agency—not unbounded
talkativeness. Star needs to notice a narrow in-game event, react
appropriately, briefly comment, fall silent during intense play and
resume naturally when asked. Mix unscripted moment selection, expressive
but restrained voice/prosody, eye direction, micro-expressions, reaction
animations, and clear turn-taking. Prevent repetitive jokes and
hallucinated in-game events.

[Proact-VL](https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/)
(ICML 2026) evaluates commentary, co-commentary and guidance and
explicitly studies *when* to speak.
[Realtime-Venus](https://realtime-venus.github.io/) (September 2026)
studies full-duplex backchannels and background speech, showing why
not every sound should interrupt an active response.
[NVIDIA DyaPlex](https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/)
addresses synchronized listening/speaking/motion. These are research
directions, not drop-in validated local models.

Develop an identity model with consistent lore/personality, an episodic
memory store of **verified moments**, evolving individual game goals,
friendship context with consent/expiry, hobbies and self-directed game
practice. Mark uncertain memories and allow owner review/correction.
Provide an explicit AI disclosure, no claims of literal human sentience
and no impersonation. Separate trusted owner instructions from viewer
chat: protect local files, tokens, purchases and game account state.

## Next milestones ranked by measurable benefit

**P0:** attach the new abort transport to a private Windows host only after
ownership checks; verify output loopback quiet + rig neutral on actual
hardware. Full model/OBS integration is blocked on this test.

**P1:** run a scored baseline gaming+OBS+TTS rehearsal under a fixed resource
budget; track p95 speak-ready time and game FPS while idle/background
learning pressure varies. A fail-safe should always stop new optional AI
work ahead of audio stutter or frame drops.

**P2:** implement heldout episodic gaming skill practice with comparable
outcomes; develop progressively harder self-play curricula and save only
validated improvements. Preserve portable skills without leaking private
gameplay or personal viewer data.

**P3:** studio game-building loop with property tests and visual reviews,
plus controlled autonomous art/music/Blender/UI experiments; schedule
longer tasks off-stream. Evaluate correctness, originality and usability
against human-reviewed acceptance examples.

**Current status:** Offline opt-in code and deterministic fake-device tests
are not proof of physical speaker quiet, faster neural inference,
human-like awareness, autonomous game mastery or better stream quality.
The feature is not merged to `main`, and streaming remains disabled.
