# Star: real-output A/V capture, evidence-based gaming, faster local AI and natural VTubing

**Research and implementation date:** 29 October 2026.  **Status:** experimental, opt-in, offline validation only.

## The actual new capability

`star/stream_av_recording_host.py` connects Star's existing synthetic-only
`stream_av_sync_audit.py` to **decoded local OBS recordings**. The caller selects
an OBS MKV/MP4/MOV recording, a dedicated Star-only audio track, a mouth region
in rendered video, and owner-captured open/closed mouth reference stills.
FFprobe verifies media and frame presentation timing. FFmpeg decodes actual
track samples and a low-resolution avatar ROI. The host aligns these on the
recording timeline and sends aggregate output observations to the existing
A/V alignment evaluator. No video, audio, transcripts, game frames, personal
viewer content or source filenames appear in the returned report.

It rejects unexpectedly misaligned stream starts, large dropped-render-frame
gaps that 30 Hz resampling would otherwise conceal, missing/misaligned audio,
silent tracks, weak visual calibration, modified files, and overlong clips.
It is **read-only**, uses no network protocols, has no broadcast/game/device
controls and never changes the avatar on its own. The feature is inactive
unless an authorized local host explicitly supplies real files and confirms
that the chosen audio track is *isolated Star speech*, not full stream mix.

**Important boundaries:** FFmpeg decoding does not prove provenance or consent.
An owner-controlled trusted host must separately establish that media came
from the correct OBS recording, references match the exact avatar/camera,
the recorded speech is Star's audible output, and the host has permission.
The Boolean output attestation is NOT a cryptographic receipt. Without it,
results remain `insufficient_evidence`. Even a review-eligible report is not
proof of phoneme-perfect lip sync, human equivalence or actual live audience
experience. A simple closed/open pixel-template ROI is not a semantic mouth
recognition model; scene changes, expressions, lighting and occlusion may
confound it.

### Calibration / operational recipe

1. Inside an owner-approved private OBS session, create a 7–30s MKV recording
   with an isolated audio track for Star's physical playout output. No
   microphone, viewers, gameplay audio, music, or Discord conversation in
   that track. Do not publish or upload the raw media.
2. Export two still images with identical camera placement, crop and lighting:
   a neutral **closed** mouth and a representative **open** mouth, rendered by
   the actual avatar/OBS pipeline. Do not use model-commanded `mouthOpen`
   values as a reference for output verification.
3. Determine the rendered mouth rectangle `(x,y,width,height)` in whole-OBS
   recording pixels (at least 8x8). Both still images must use the same
   coordinate frame and crop. Run the opt-in `audit_local_obs_recording` API
   with the explicitly selected zero-based audio track.
4. Review sample count, lag, voiced mouth coverage, silent-mouth rate, and
   final verdict. Compare the actual output with raw footage *locally*; do
   not trust an impressive numeric score by itself. The host controls whether
   these summaries are retained. Remove raw scratch recordings under the
   owner's retention policy. Never auto-deploy a model based on this score.

```python
from star.stream_av_recording_host import MouthROI, audit_local_obs_recording

# The authorized local host first checks permission, path identity,
# separated output track, current avatar identity, and calibration provenance.
result = audit_local_obs_recording(
    "local-test.mkv", closed_still="mouth-closed.png", open_still="mouth-open.png",
    roi=MouthROI(410, 375, 42, 28), audio_track=1,
    host_confirms_isolated_star_audio=True,
    host_attests_actual_output=False,  # default until a trusted host validates it
)
print(result.report.verdict, result.report.estimated_mouth_lag_ms)
```

### Observed verification, not inference claims

In an offline synthetic fixture, independently encoded FFV1 video and PCM
speech were multiplexed to MKV and decoded using real FFmpeg/FFprobe. The
capture adapter aligned 240 rendered frames at 30Hz with the generated
isolated audio, recognized several voiced/quiet transitions, and rejected
an intentionally dropped video segment and a shifted audio stream. This
**tests the decoder**, not a real Windows OBS recording or improved
rendered speech naturalness. Windows OBS/VTube Studio and independent audio
identity evidence remain untested integration steps.

## Why this improves future humanlike gaming streams

Previously, the planned avatar parameters could appear correct while OBS
actually presented mouth motion late, left it open during silence, or never
rendered the event. Actual output measurements are needed for trustworthy
iteration. Star should coordinate her local speech playback cursor, expression
and facial motion, eye and body cues, and OBS presentation in one monotonic
capture session. Preserve real silence during concentration; match laughter
to audible laugh audio and specific verified gameplay moments. A stable
recognizable AI identity and genuine history are better than fabricated
human stories. This pipeline addresses one observable failure mode and does
not simulate consciousness or human subjective experience.

## Targeted intelligence / speed roadmap

**P0 — connect the output proof loop.** On the owner's Windows game PC, add an
explicit offline-only OBS recording session with isolated audio and a bounded
media-retention policy. Verify correct source and VTube model, and run a
paired human A/B review of mouth timing. Aim for <=100ms inferred lag and
very little silent-mouth motion, measured rather than promised. Prevent this
analysis from running while a live game/OBS session needs resources.

**P1 — CPU/GPU locality and real throughput.** A small 8GB gaming GPU is a
contended resource; give Roblox, OBS, avatar rendering and real-time vision
reserved latency/headroom. Allocate long reasoning, multiple draft candidates
and background knowledge indexing to CPU/RAM or the second machine while
streaming. Do not presume GPU-offloading or speculative decoding helps: use
llama.cpp's SPEED-Bench baseline-versus-candidate measurements on the same
prompts and batch/concurrency settings; track first-audible p95, useful task
success, game 1%-low FPS, OBS dropped frames and GPU peak MiB. Automatically
revert experimental configurations on regression; never route secrets into
model prompts. Cache reviewed project documentation only with explicit scope,
provenance and version TTL.

**P2 — voice Pareto frontier.** Kyutai's 20 October 2026 Pocket TTS release
includes English 18.2M, 6.9M and experimental 1.9M parameter options; this
makes CPU/off-stream speech an interesting candidate but does not prove that
smallest equals best voice quality. Perform blind, same-utterance voice
listening tests (timbre consistency, prosody, interruption, laughter, timing),
plus first-audible latency and compute during actual Roblox/OBS load. Preserve
Star's voice identity rather than changing models solely for raw throughput.

**P3 — actual autonomous gaming.** Use authorized Roblox Studio
`StudioTestService` / `VirtualInput` for controlled input, and distinguish
run/test environments from live public game anti-cheat and TOS. Each episode
must record versioned observations, action selection, trusted outcome and
failure diagnosis. Learn through controlled practice but evaluate on withheld,
unseen levels and games. Compare against pre-registered baselines. Build
multiplayer join/rejoin, camera, UI, objectives and save-restoration checks
for games Star creates. Publishing and irreversible account actions require
owner control.

**P4 — reusable general knowledge and quality.** A versioned knowledge graph
should store sources, timestamps, scope, confidence and corrections, not just
more token memory. Cite retrieved facts, expire stale software/game claims,
separate private memories from on-air facts, and independently test citation
validity. Learn what failed in Star Core Forge, but never let a model's own
explanation count as evidence of improved intelligence. Use actual gameplay
and engine diagnostics plus human visual review for Roblox UI, geometry,
lighting, animation, sound and game feel. The quality gate must be evaluated
on held-out material rather than only synthetic demonstrations.

**P5 — a believable continuing virtual life.** Give Star coherent interests,
projects, preferences, humor, expressiveness and memories *from recorded
experiences*, plus a persistent self-model of capabilities/uncertainty. A
stream director should let her play in silence, answer select moderated
questions, recover from interruptions, celebrate real wins and vary phrasing.
Only genuine, host-observed events should become autobiographical material.
Keep owner-facing disclosure that she is an AI; do not misrepresent simulated
feelings as verified consciousness or present fictional life events as fact.

## Sources and verification boundaries (as of 2026-10-29)

- **FFmpeg timestamp/filter and stream selection docs:**
  https://www.ffmpeg.org/ffmpeg.html ; https://www.ffmpeg.org/ffprobe.html
- **Roblox Studio testing, multi-client and programmable VirtualInput:**
  https://create.roblox.com/docs/studio/testing-modes
- **OpenGameEval** (1 Oct 2026, 84 tasks, real Studio evaluation):
  https://github.com/Roblox/open-game-eval
- **GameWorld** (8 Apr 2026, 34 games / 170 verifiable tasks):
  https://arxiv.org/abs/2604.07429
- **GameDevBench** (11 Feb 2026, feedback for visual game development):
  https://arxiv.org/abs/2602.11103
- **llama.cpp SPEED-Bench** (baseline/speculative evaluation):
  https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- **Kyutai Pocket TTS small models** (20 Oct 2026):
  https://kyutai.org/blog/2026-10-20-pocket-tts-small/
- **VTube Studio original programmable parameter API:**
  https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md

**Not measured or shipped here:** real Windows OBS + VTube Studio output,
true streaming QoE improvement, neural reasoning quality gain, inference speedup,
independent game mastery, or any self-modifying model weights. All require
separate real-environment tests before they can be claimed.