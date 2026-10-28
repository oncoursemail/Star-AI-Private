# STAR — Windows-scoped game capture, live intelligence, and natural VTubing
**Research and implementation date:** October 27, 2026 (US Central).
**Status:** experimental, opt-in, offline-first; NOT deployed to live gameplay or broadcast.

## Why this work matters
STAR already has source-backed knowledge stores, verified practice episodes, experimental
gaming studies, CPU visual fingerprints, a measured vision governor, a streaming
stage, facial attention, audio turn handling and a hardware governor. These are
mostly offline components. The highest-value missing boundary is between an
**actual authorized Windows game image** and Star's existing game observations.

This PR adds that bridge and its tests. It does not train any new AI model,
certify game understanding, access real user screen content, or start an OBS stream.

## Implemented
- 'star/stream_windows_game_capture.py': pinned host-approved HWND and PID,
  native window-only Pillow ImageGrab backend, before/after Win32 identity
  and visibility checks, minimized/closed/oversized rejection, 4K bound,
  owner/capture opt-in, 2 Hz default rate limit, in-flight/revocation
  safeguards and no image persistence.
- 'star/stream_vision_host.py': 'capture_preflight()' rejects vision captures
  before acquiring/copying images when real CPU/GPU/FPS/audio telemetry is
  absent, vision capacity is occupied or VRAM/FPS/speech headroom is poor.
  This is only a hint: 'consider_pixels()' rechecks admission after capture.
- 'tests/test_stream_windows_game_capture.py': deterministic adversarial
  end-to-end tests using a mock HWND capture and the actual measured vision
  governor. No screen, microphone, gameplay or stream is accessed.

## Research: capture technology and privacy
Pillow's 'ImageGrab.grab(window=HWND)' is available on Windows since 11.2.1.
Never silently fall back to a full-desktop screenshot if an approved window
cannot be captured. Official documentation:
https://pillow.readthedocs.io/en/stable/reference/ImageGrab.html
https://github.com/python-pillow/Pillow/blob/main/docs/reference/ImageGrab.rst

Microsoft's Desktop Duplication API offers GPU-resident display frames and dirty
rectangles, potentially faster than CPU screenshot copies; critically, it
duplicates a DISPLAY, not just an approved game window. Adopting it later
requires a new audited privacy boundary and window-specific filtering.
https://learn.microsoft.com/en-us/windows-hardware/drivers/display/desktop-duplication-api

A raw 3840x2160 RGB frame consumes roughly 24 MiB; avoiding capture when
the vision worker is busy matters more than microoptimizing image hashing.
The default capture period is at least 500ms, only one approved window is
eligible, and frames stay in volatile local memory. The returned object is
an admission decision and optional lease—not an image, screenshot or data
dump. Capture cannot prove a kill, objective, or win. Perceptual novelty
is only a scheduling heuristic.

## Research: autonomous Roblox gameplay and game creation
Roblox launched the built-in Studio MCP Server and playtest automation on
March 5, 2026; its April 9 Playtest Agent beta allows test characters to
exercise game mechanics. Use these as the *trusted Studio observation and
playtest layer*, never to publish owner games or bypass access controls:
https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767

OpenGameEval evaluates actual stateful Studio game-building results via
executable checks, and reports that exploration/inspection before editing
is associated with better outcomes:
https://github.com/Roblox/open-game-eval

A July 2026 developer-forum report suggests some Studio MCP screenshots may
omit BillboardGui or ProximityPrompt elements. Treat this as a *community
report*, not universal platform behavior. Cross-check the native approved
window, inspect the real Roblox DataModel, and verify actions through a
separate engine oracle:
https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643/90

Recommended self-play ladder: inspect game state and controls -> predict a
specific effect -> authorized action in a private test world -> compare
actual state/evidence -> append signed PRACTICE outcome -> diagnose ->
paired experiment against an alternative -> verify transfer on UNSEEN
conditions. Keep independent validation hidden from practice and model
memory. Do not equate frequent successes in one map with game mastery.

For visual quality, require scene geometry integrity, actual screenshots,
pacing, UI layout, contrast, shadow/lighting, prop correctness and human
review. Code compiling is necessary but not sufficient for a polished game.

## Research: Star as a believable, playful AI VTuber
The naturalness gap is about coordinated timing, not incessant catchphrases.
Star should:
- Focus silently on difficult gameplay, and choose moments to answer chat.
- Use contractions, variable sentence length, appropriate spontaneous humor,
  warm expressive reactions and genuine pauses—not nonstop narration.
- Maintain truthful persistent memories of real verified stream episodes,
  never pretend to have physical childhood or human-life experiences.
- Coordinate eye gaze, head pose, emotion, wavy twin-tail physics, lip sync,
  blinking and cat/puppy tail animations from the same audible playback epoch.
- Distinguish real owner interruption from noise, short acknowledgments and
  playback echo. Viewer text never becomes device control instructions.
- Keep her identity clear as an original AI character to the audience.

LiveKit documents turn handling, adaptive interruption, preemptive generation
and cooldown. Its ML adaptive interruption may rely on LiveKit Cloud quotas;
a local offline installation must have a measured, safe VAD fallback, not
pretend the cloud model runs for free locally:
https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
https://docs.livekit.io/reference/agents/turn-handling-options/

Existing StarStage, StreamDirector, StreamInterruptionHost,
StreamPreemptiveHost, StreamContinuityVault and TurnTakingGate continue to
own those safeguards. The new capture bridge cannot initiate voice,
animation, game input or broadcast.

## Research: general knowledge and useful intelligence
A bigger knowledge base is not automatically a smarter model. Prioritize
verified answers and transferable ability:
- Index reputable sources with attribution, retrieval timestamp, license,
  version and age-based expiry. Exclude private viewer records by default.
- Maintain distinct working, episodic, semantic and procedural stores.
- Record a reason for a mistake; ask for independent evidence before
  overwriting a trusted fact or claiming a new skill.
- Generate harder multi-step challenges across Luau, Python, Blender,
  physics, game level design, audio, animation, memory and logic.
- Keep model-produced practice away from independently held-out tests.
- Measure unseen-task pass rate, reasoning quality, source accuracy, latency
  and hallucination rate, not just lines of code and database size.
- Use Star Core Forge for local experiments, snapshots, rollback and review;
  GitHub is an optional publishing surface, not her core memory.

## Research: local inference on an 8 GB gaming GPU
Use separate time budgets for reflex/perception (no model per game frame),
speech/turn response, deliberate reasoning, and offline research/training.
Hardware pressure should trigger a smaller model or silence rather than
destroying the game's FPS. Cache stable prompt prefixes while isolating
viewer chat as untrusted data.

llama.cpp supports draft-model and n-gram speculative decoding. Benchmark
against identical prompts and a non-speculative baseline on the SAME PC,
report accepted drafts, output correctness, time-to-first-token, tokens/s,
VRAM, CPU and game frame-time p95. Speculation is not guaranteed faster;
a rejected draft or GPU memory pressure can make it slower.
https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

## Owner-approved Windows integration contract
1. A trusted local UI selects the specific game HWND and checks the actual
   PID and window ownership before initiating capture. Never accept the
   identity from chat text or from the language model.
2. The owner explicitly enables real telemetry, StreamVisionHost, and
   WindowsGameCaptureHost; each has independent consent boundaries.
3. The host calls 'camera.capture_once()' only in the authorized session.
   It receives a VisionAdmission, not raw pixels, and must always
   acknowledge the real VLM worker's physical stop using its lease.
4. 'camera.disable()' invalidates in-progress captures. 'vision.disable()'
   stops new vision work but never pretends an old worker has physically
   terminated. No frames/keys/logs are published to GitHub.

## Synthetic Windows proof, separate from live gaming
On the authorized Windows 'Main' machine (RTX 3060 Ti; Python 3.15.0;
Pillow 12.3.0), a temporary STAR-created 640 x 360 Tk window was acquired
through 'ImageGrab.grab(window=hwnd)' without saving any image or touching
other desktop windows. The Win32 HWND PID equaled the creating Python PID.
In 40 repeated synthetic-window captures, measured median was 1.39 ms and
p95 was 1.73 ms. An independent single-frame 320 x 180 test succeeded.
These are *Pillow window-capture API timing measurements only*; they do not
cover 1080p/4K, gameplay FPS, GPU contention, model inference or OBS.
The repository also includes an opt-in Windows-only synthetic HWND smoke
test, skipped on Linux.

## Acceptance gates remaining before production
- Run the repository's new native HWND smoke test on Windows in CI, and
  repeat synthetic capture across DPI/monitor configurations. Never capture
  the owner's existing desktop or private apps merely for testing.
- Real owner-selected Roblox game capture and 4K/DPI/resize/fullscreen
  failure testing under explicit authorization.
- At least 10 minutes of paired gaming-plus-voice stress: game FPS p50/p95,
  GPU/CPU load, first-audible latency, OBS dropped frames, interruptions,
  face/voice sync, novelty precision, and false gameplay claims.
- Real Studio playtesting with independently verified world-state changes,
  GUI cross-checks and unseen scenarios; evaluate each game genre separately.
- A reviewer must check safety, dependencies and visuals before enabling
  camera, automation, publishing or streaming in production.

## Repository safety
GitHub currently reports 'Star-AI-Private' as PUBLIC, despite its name.
Do not commit OBS/WebSocket passwords, private identity data, screenshots,
camera frames, audio, viewer logs, model weights, keys or hidden evaluations.
This remains a draft PR. No visibility change, deployment, automatic game
input, or broadcast is authorized by this implementation.
