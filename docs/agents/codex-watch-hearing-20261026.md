# Codex continuation: hearing while watching

Continues issue #654 and `HANDOFF-CODEX-20261026.md` section 4's watch-hearing gap on
`star/next` at `0b171017`, reconciled with Claude's late Home changes at `8155f4c9`. Does not replace `star-cute`, the existing fast path, or
the separate `star/voice-natural-20261026` work.

## Behavior

STAR Home now supplies live loopback hearing to `watch_videos`. It opens capture
only when that activity runs, borrows an already configured hub when provided,
and restores the previous watch configuration on exit. Missing dependencies or
model files leave the established captions/picture path available. The activity
does not open the physical microphone.

The new `voicestack.watch_hearing()` reuses `_engines()`'s ASR. A lock prevents
concurrent first-use calls from loading the voice engines twice. The voice output
and watch hub share a playback reference, including standalone remarks, so the
existing echo canceller can exclude STAR's spoken reactions. Calls continue using
their established loopback/cable route.

Owned loopback capture and the transcription hub are closed in `finally`, on
normal completion, exceptions, owner STOP or the scheduler's friend interrupt.
Capture/hub thread joins are bounded; an already running ASR transcription may
finish after the activity exits. A borrowed hub is never stopped by the watcher.
STOP or a pending friend interrupt skips new audio/model initialization.

`FallbackHearing` notices dead live capture, switches once to captions when
available, and otherwise reports picture-only operation. Caption fetching stays
lazy until needed. Switching at a later video position does not replay the old
caption transcript. The activity summary reflects the final input mode.

Every video establishes its own hearing cutoff immediately after opening. Old
hub transcripts, an utterance that began before this video, and room microphone
lines are excluded from that video's notes.

## Validation and limits

Standalone regression check outside the repository's owned test harness:
`python scripts/verify_watch_hearing.py`: 22 checks passed, covering shared engines/reference, ownership/cleanup, borrowed
hub lifetime, missing engines, previous-video and microphone exclusion,
capture failure, caption replay prevention, one-time fallback, Home wiring,
configuration restoration and STOP. The real SensesHub was used with fake
silence capture, fake VAD and fake ASR; no real audio devices or model inference.

Existing suites: `tests/test_watch_videos.py`, `tests/test_home_wiring.py`, and
`tests/test_senses_voice.py` ran unchanged: 125 passed. The retained verifier also
covers reporting failures, activity exceptions and concurrent first engine load.

Real WASAPI recording, Discord audio, VB-CABLE, RTX 4060 performance, reference
echo rejection in a room, and subjective voice quality still require the owner
PC acceptance run. Loopback captures the default output's mix, so notifications
and other applications can also be heard; this is not per-browser audio capture.
The audio classifier remains a heuristic. No human consciousness or literal
emotion is established by these changes.

## Primary-source research checked 2026-10-25 (America/Chicago)

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper): CPU int8 and CUDA
  inference are supported. Its published benchmarks use other hardware and
  offline files; they are not a measurement of STAR's 4060 or live-turn latency.
- [Pipecat Smart Turn](https://github.com/pipecat-ai/smart-turn): audio-based
  endpointing runs with a lightweight VAD and provides a quantized CPU version.
  Reuse the installed runtime instead of adding a second endpoint model.
- [Kokoro](https://github.com/hexgrad/kokoro) and
  [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx): use the existing
  local stock-voice synthesis path. Current `star-cute` is an audition candidate;
  this change neither invents a new measured score nor replaces the voice.
- [NVIDIA NVENC](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.1/nvenc-application-note/index.html):
  hardware encoding is separate from graphics/CUDA cores. This does not promise
  that simultaneous gaming, local inference and avatar rendering fit the GPU.
- [VTube Studio API](https://github.com/DenchiSoft/VTubeStudio): authenticated
  local WebSocket control supports parameter injection; a custom model still
  needs separately authored/approved art, rigging and mouth shapes.
- [Official hololive voice page](https://shop.hololivepro.com/en/products/startingvoice_moricalliope):
  performer reference material was located, but no performer audio was played
  or listened to in this session. Reading a page is not an acoustic audition.
  No performer voice was cloned or used as training material.
