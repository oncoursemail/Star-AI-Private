# STAR research: Faster AI without breaking the gaming VTuber
**October 29, 2026 — prototype, offline-only, default OFF.**

## What is new

Three previously independent checks are now joined in
`star/stream_output_qoe_gate.py`:

1. `stream_realtime_benchmark`: actually audible first speech, measured game
   frametimes and GPU memory; requires a preregistered paired baseline.
2. `stream_obs_qos_gate`: OBS render/output skipped-frame counters and
   process continuity under the same game/version experiment.
3. `stream_av_recording_host` and `stream_av_sync_audit`: **decoded OBS output**
   Star-only speech track versus the **rendered mouth pixels**, not sent
   Live2D parameter commands. This is stacked on the unmerged PR #798.

The join rejects duplicate/reused recordings, wrong games/versions,
missing pairs, mismatched OBS process/session IDs, clip periods not
inside the paired OBS window, mismatched media durations, and source
evidence without explicitly host-attested output and audio isolation.
For 20+ completed candidate/baseline pairs it guards against >40 ms
extra absolute mouth lag, >0.04 decrease in alignment F1, >0.025
increase in mouth movement during silence, and >0.06 loss of
speech-mouth coverage **in any valid pair**. These are provisional
conservative *engineering thresholds*, not a scientifically
established level of perceived naturalness.

A promising faster voice is only eligible for owner review when all
performance/OBS/AV checks pass. Missing, unverified or invalid clips
are never silently treated as wins. Observed degradation vetoes
a faster model. No models are switched; no real media or secrets
are read, stored or transmitted by this join; no broadcasting or
game permissions are granted. The digest prevents reuse but does not
prove the actual source of a recording. A trusted host must bind
clip timestamps and digests to owner-authorized OBS capture.

## High-value next improvements

**Natural and trustworthy streaming:** Add a single end-to-end
output timeline for audio playout, eye gaze, blinking, facial expressions,
head posture, hair spring physics, quiet concentration and interruptible
laughter. A VAD detects speech; an end-of-turn model decides whether
the person finished; an interruption classifier decides whether Star
should yield. These are distinct jobs, particularly when the game is
noisy. Test false interruptions, response latency and resumption
after a real audio interruption, rather than equating model output
with real spoken delivery. Star should tell truthful stories about
verified gaming experiences; she remains clearly an AI VTuber.

LiveKit turn tuning:
https://docs.livekit.io/agents/logic/turns/tuning/
LiveKit's 2026 turn/interruption explanation:
https://livekit.com/blog/turn-detection-and-interruption-handling
Official VTube Studio API:
https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md

**Speed and hardware:** Evaluate streaming on the actual 8 GiB GPU
with Roblox + OBS + VTube Studio + Star speech + model all running.
Protect game FPS and first-audible voice against heavyweight night
school, Blender renders, VLM batches and retrieval. Compare model routes,
KV cache reuse, concurrent inference slots, prompt prefix stability,
speculative decoding *acceptance* and CPU offloading. Optimize
successful tasks per second, not token/s while streaming is unstable.
llama.cpp server documentation covers slot batching and its shared
decode bottleneck:
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README-dev.md

Kyutai released six smaller CPU-focused English Pocket TTS models
in **v4.0.0 on October 20, 2026**, and updated them in **v4.0.1
on October 21**. Test the 18M/7M/experimental 2M families in blind
listening (intonation, proper nouns, laughter, natural pauses,
intelligibility, onset clicks) together with live game performance.
They are candidates, not measured speed improvements to Star.
https://github.com/kyutai-labs/pocket-tts/releases

**Actual game mastery:** Use a fixed trusted game state observer,
a limited authorized input host and progressively harder practice
scenarios. Predict the effect of an action, perform a short
experiment, compare to an independently verified baseline, store
proven practice-only lessons, then test *new games and unfamiliar
levels* without showing withheld success criteria to the planner.
GameWorld provides 34 games and 170 state-verifiable tasks across
runner, arcade, platformer, puzzle and simulation genres. Measure
objective completion, accuracy of predicted effects and cross-game
transfer, not number of hours played.
https://gameworld-bench.github.io/

**Game creation:** OpenGameEval covers 84 curated Roblox Studio tasks
with executable scene and play-session assessments. Combine
scene observation BEFORE editing with geometry/collision/path checks,
verified input, playthrough completion, save restoration, UI screenshot
review at multiple resolutions, and multiplayer checks. Failures
should trigger targeted reproducible repairs rather than a blanket
"perfect game" label.
https://github.com/Roblox/open-game-eval
https://create.roblox.com/docs/studio/testing-modes

**General knowledge:** Keep verified knowledge with canonical source,
revision/version, review date and evidence spans. Defer uncertain
current facts to retrieval; distinguish speculation from sourced facts.
Use mixed-domain held-out tasks covering Roblox/Luau, Blender, Minecraft,
UI, animation, science, math and practical software. Measure
answer correctness *and calibrated abstention*, not merely retrieval
volume. Use Star Core Forge for experiments, independent evaluation,
manual escalation and reversible rollbacks. GitHub remains optional
for release publication; local knowledge, self-improvement and backups
must not require GitHub access.

## Reproducible owner-approved pilot

Capture at least 20 balanced AB/BA experiments on one fixed private
Windows game/OBS/avatar setup. Use a Star-only speech track and
calibrated open/closed mouth stills per camera view. For each paired
run, retain *locally* a trusted common monotonic capture clock,
OBS GetStats before/after window, exact process/session ID,
recording SHA-256 and real decoded AV report. Feed that into
`OutputAVWindow.from_recording` and
`compare_stream_output_qoe`. Independently review any degraded
pair and do an anonymized blind listening/naturalness comparison.
A transport-loss evaluation remains separate from OBS render counts.
Never upload the recordings or viewers' messages to this publicly
visible GitHub repository.

### Verified versus unverified

The new joining tests are synthetic offline observations.
The stacked recording decoder tests can process real FFmpeg media
files containing *synthetic* A/V. No real Windows OBS recording was
captured in this update. No claim of faster inference, more intelligent
model weights, real autonomous gameplay mastery, human-quality
broadcasting, or actual human consciousness is warranted.
