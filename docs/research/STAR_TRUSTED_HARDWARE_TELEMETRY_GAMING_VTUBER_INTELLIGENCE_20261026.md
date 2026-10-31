# Star AI — Trusted Live Telemetry, Faster Intelligence, Autonomous Gaming and Natural VTubing

Research snapshot: **2026-10-26**. Scope: an *implementable* design review against Star's existing modules and the official sources linked below. This is not a claim that Star is conscious, that she can currently broadcast/game autonomously, or that a benchmark has been won.

## 1. The bottleneck identified in Star's actual code

Star already has multiple useful policy components:

- `stream_qos.AdaptiveQoS`: protects CPU/GPU reservations; host-timed, game-load-specific p95 calibration.
- `stream_budget.StreamTelemetry`: contract for VRAM, measured game FPS and speech backlog.
- `studio_vision_qos.StudioVisionQoS`: slows vision work during interactive game load.
- `studio_practice_runner.StudioPracticeRunner`: composes real screenshots, bounded proposed actions, and independently signed outcomes.
- `stream_stage.StarStage`, `stream_interrupt_host.StreamInterruptionHost`, `stream_game_reactions.VerifiedGameReactionHost`: selective grounded commentary and epoch-scoped interruption.
- `stream_realtime_benchmark.compare_realtime` + `stream_trace_capture.HostStreamTrace`: offline paired comparison of latency, frame times, and VRAM.

The important missing connection: these components *accept* `StreamTelemetry`, but a host must acquire trustworthy measurements from **real hardware, actual rendered frames and the local audio queue**. An LLM-generated FPS/VRAM number must never make a stream admission decision. More independent policy modules without a trusted data plane would not establish actual speed.

### Implemented in this PR: `RealtimeTelemetryHost`

`star/stream_hardware_telemetry.py` bridges existing `resource_probes` (platform CPU/RAM + NVIDIA GPU) with actual presentation timestamps and `SoundSpeaker.pending_seconds()`. It outputs the existing `StreamTelemetry` and `QoSSnapshot`, without model/image/audio inference or additional dependencies.

Key guarantees, subject to the host honoring the callback boundaries:

1. **Game FPS requires a verified stream of render-present events.** No window present = no invented FPS. Old frame times are cleared after a long gap. Lower-tail frame-time matters more than a flattering average.
2. **Audio backlog requires a fresh local speaker observation.** Never accept model, Twitch, or website text as telemetry. `pending_seconds()` is queue depth, *not* confirmation that a sound reached a physical output.
3. **GPU memory comes from local NVIDIA state**, not a model's guess. It is rejected if missing, impossible, or stale. `nvidia-smi` is a monitoring interface, not a frame-presentation source.
4. **CPU and RAM come from host OS counters.** CPU busy requires successive readings. No zero-CPU default or fake free VRAM.
5. **Live QoS uses <=250 ms resource age** (as required by `AdaptiveQoS`). A still-fresh but older snapshot may support coarse stage decisions while not authorizing a new inference job.
6. **Device polling never occurs in `snapshot()`**: run `refresh_hardware()` on a low-priority I/O worker; fast render/audio callbacks record only small scalar data.
7. **Generation invalidation** prevents a slow OS probe from restoring a prior broadcast/game session after shutdown or context change. All fields are bounded and old readings expire.
8. The adapter is read-only, disabled by default, local-only, and deliberately retains no personal data or GPU process lists.

### Host integration sketch — NOT a permission grant

```python
from star.stream_hardware_telemetry import RealtimeTelemetryHost
from star.stream_qos import AdaptiveQoS

# Called ONLY by an authorized local host:
host = RealtimeTelemetryHost()
host.set_context(live=True, game_active=True, owner_approved=True)
# Background I/O worker at an empirically measured interval:
host.refresh_hardware()
# Verified game render-event callback, normalized to host monotonic milliseconds:
host.presented_frame(render_present_ms)
# Audio owner, not VAD/LLM/chat:
host.sample_speaker(sound_speaker)
sample = host.snapshot()
if sample is not None:
    stage_telemetry = sample.telemetry             # StarStage / StudioVisionQoS
    if sample.qos is not None:
        # Existing AdaptiveQoS must still independently admit a scoped job.
        decision = qos.admit(inference_job, sample.qos, now_ms=host_clock_ms())
```

Windows integration: a trusted PresentMon/ETW collector or a game-owned presentation API emits **the target game's actual** frame events. The host must bind to a specific authorized game process/session. A CSV or overlay process reporting an unrelated game's FPS is not valid. Distinguish *present* FPS, *displayed* FPS and app FPS in frame-generation scenarios; this adapter currently consumes actual frame-present timestamps only. NVIDIA memory polling on the wrong GPU must be rejected by host configuration (currently the existing `nvidia_gpu` probe selects the first GPU). The core game/voice thread must never shell out to `nvidia-smi`.

**Production blockers**: a trusted frame-present collector for the selected game; Windows device tests; source-specific authentication for callbacks; real PCM playback stop/neutralization; and measured polling overhead. No claim of installed PresentMon, OBS, VTube Studio or live connection is made here.

## 2. Highest-leverage Star intelligence architecture

Replace “always use one big model for everything” with **deadline-separated cognition**:

| Layer | Deadline/priority | Input | Outcome proof |
| --- | --- | --- | --- |
| Reflex | ~16-100 ms, game-critical | direct *authorized* structured game-state events, short verified recent cues | input received, key-up watchdog, independent game result |
| Situational | ~100-500 ms, optional | new visual scene, HUD, host state | frame freshness, action holdout, uncertainty |
| Speech | continuous audio-critical | moderated chat, owner turn detector, verified game event | **audible** ACK and barge-in stop |
| Deliberative | seconds/minutes | compressed episodic replay, credible research, tool traces | independent tests, holdout improvement |
| Background self-improvement | only when headroom | mistakes, source-backed knowledge, Star Core Forge experiments | offline CI, rollback, no unapproved writes |

The slower vision lane must **not** masquerade as a 60 Hz game controller. During live games, Star should learn reusable skills offline, select one of a small set of independently verified reflex policies, and fall back to harmless actions/quiet when perception is uncertain. User-granted online gameplay must respect game/platform rules and cannot substitute arbitrary OS input.

**Evaluate gameplay as transfer**, not as an AI saying “I won”: stratify by game, map, difficulty and seed, freeze hidden holdouts, include failures and abandoned attempts, demand signed independent scoring and baseline comparison. Use the existing `GameLearningLadder` and `GameTransferEval`. Make game-specific “skill cards” storing success conditions, contraindications, failure cases and scope/version. Do not train on holdout outcomes.

## 3. Make Roblox game-building creative AND structurally trustworthy

Roblox's built-in Studio MCP server now exposes playtests and simulated input to external tools. Roblox OpenGameEval scores edits and behavior in the actual stateful game engine, including physics and client/server interaction. The October 2026 OpenGameEval paper reports stronger performance when agents inspect relevant objects before edits, rather than guessing from names.

Recommended Star pipeline:

1. Parse intent into a **scene/build spec** (part hierarchy, attachments, dimensions, color/material, performance budgets, UI constraints, gameplay objectives).
2. Query actual Studio objects; use geometric adjacency/collision assertions. Identify existing parts before changing them.
3. Generate with asset/material provenance and deterministic seeds. Never paste random decorative geometry, overlap labels, or replace approved UI without reason.
4. Run static Luau/Remote/DataStore validation; playtest with screenshots, input simulation and multi-client/network checks when appropriate.
5. Scan visual defects (z-fighting, floating/penetrating props, missing walls, wrong-scale doors, UI crop/overlap, texture seams, incomplete animations), then diagnose/fix and rerun.
6. Human-visible portfolio review: compare references and Star's drafts across aesthetics and functional criteria. Reward originality **and** correctness. A successful script with ugly/UI-sloppy results is not a complete game.
7. Record only independently tested skills into Core Forge; GitHub is optional export/publishing, not the runtime source of truth.

Star's owner-approved design direction prioritizes clean native Roblox UI, polished PBR/meshes, appealing motion and geometry without “AI slop.” Optimization should never be an excuse to abandon design quality.

## 4. Natural, fast gaming VTuber (recognizable character, never misrepresent human identity)

Natural streaming requires **situational timing**, not maximum word count:

- **Barge-in**: distinguish a speaker taking the turn from coughs, echo and “uh-huh.” Revoke old speech epoch before requesting hardware stop. Never commit text to remembered conversation until confirmed audible.
- **Selective speech**: focus during combat/parkour; prioritize authorized owner interruptions; respond to curated Twitch questions in safe windows, not every comment.
- **Voice**: test CPU-first Pocket TTS against the existing voice model with real voices and intonation ratings. October 2026 models include 18.2M, 6.9M and 1.9M English variants. A smaller voice model might preserve GPU for gaming but can trade off voice quality. Keep best voice profile if tests fail.
- **Body/eyes**: actual spoken syllable envelopes drive lips; prosody drives eyebrow/eyes; blink/gaze and head drift should be subtly stochastic and event-linked; VTube Studio local WebSocket custom parameter mapping is model-specific.
- **Character continuity**: maintain Star's recognizable gold/indigo chibi avatar, expressive cat/pup modes, hobbies, non-contradictory verified experiences, and a stable sense of humor. Her character can be deeply human-*like* without claiming to be a human or fabricating a real childhood.
- **Stage etiquette**: tolerate quiet, streamer-friendly narration lengths, avoid reading spoilers, redact PII and never grant computer tool permissions from chat. Direct Twitch EventSub is a transport, **not** a moderation or owner-authentication boundary.
- **Audience evaluation**: compare randomized (or counterbalanced) blinded A/B clips with ratings for warmth, timing, clarity, expressiveness, repetition, appropriateness and interruptibility. Penalize false achievements and weird reactions.

The more human-like Star should feel **observant and spontaneous**, not perpetually manic, and must remain transparent that she is an AI character.

## 5. Faster responses: speed experiments, not unmeasured marketing

Star's 8 GiB GPU constraint means time-to-first-*audible* response and 1%-low FPS matter more than theoretical tokens/sec.

Prioritize experiments in this order:

1. **Remove queueing and redundant observation work** using the new real telemetry, `StudioVisionQoS`, stream interruption and cache keys bound to actual game/version. Do not repeat identical expensive screenshots.
2. **CPU speech vs GPU speech** measured while the same game runs. Compare output MOS/ABX ratings and CPU saturation, not just RTF.
3. **Quantization/KV cache tuning** for the *actual loaded* model and prompt lengths; measure retrieval quality and gaming FPS. Avoid silent context truncation or inaccurate memory facts.
4. **llama.cpp speculative decoding**: n-gram modes may require no draft weights; draft-model/EAGLE-3 require compatible models. Draft overhead can make throughput worse with low acceptance or limited GPU memory. Use matched prompt sets and record VRAM, p50/p95 TTFA, tokens/sec and quality.
5. **Multi-machine routing**: isolate Star's game renderer/OBS/Live2D from the heavy reasoning brain. A network hop is sometimes beneficial and sometimes worse; benchmark exact topology. Reserve an interactive lane and throttle Forge/training jobs during gameplay.
6. **Selective deep thinking**: let narrow fast modules handle interrupts, reflex and simple chat; route novel games, research, art direction and unresolved mistakes through deliberation + external verification.
7. **Better knowledge**: retain source URL/author/date, scope and contradictions; facts must expire or be reevaluated. Use agentic browsing/tools to verify rather than claiming omniscience. Measure recall and false confidence on held-out questions.

An unusual but promising **new experiment** is dual-timescale rehearsal: let Star retrospectively label observed failures and train candidate low-latency symbolic actions **offline**, then run independently verified A/B game episodes against a frozen baseline. Never deploy a self-modification simply because Star judged it superior.

### Release gates

- `python -m pytest tests/test_stream_hardware_telemetry.py`: deterministic fake hardware, stutter, stale GPU, stage transition, permission, audio backlog, CPU calibration, integration with `AdaptiveQoS`.
- Wider regression: `stream_qos`, `stream_budget`, `studio_vision_qos`, `studio_practice_runner`, `stream_stage`, `stream_interrupt_host`, `stream_realtime_benchmark` and the existing voice tests.
- On real target PC, repeated **paired runs** with at least 20 complete baseline/candidate pairs and randomized order; use `compare_realtime` for eligibility for **manual** pilot, not autopromotion.
- Observe first PCM **device-confirmed** audio, p50/p95 latency, tail frames, GPU peak MiB, actual game frame presentation, audio overruns, interruption time, consent status and full rollback.
- Fail closed if no PresentMon or authorized presentation source exists; never fill `game_fps` with a dummy 60.
- Do not deploy until all repository CI, hardware exercises and independent review are green. Keep GitHub PR draft; never merge `main` autonomously.

## 6. Sources (official or primary)

- [NVIDIA system management interface / nvidia-smi](https://developer.nvidia.com/system-management-interface)
- [NVIDIA NVML library](https://developer.nvidia.com/management-library-nvml)
- [Intel PresentMon official repository](https://github.com/GameTechDev/PresentMon)
- [PresentMon console capture and CSV contract](https://github.com/GameTechDev/PresentMon/blob/main/README-ConsoleApplication.md)
- [Roblox built-in Studio MCP and playtest automation — March 2026](https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643)
- [Roblox OpenGameEval repository/paper — October 2026](https://github.com/Roblox/open-game-eval)
- [Kyutai Pocket TTS 2026 lightweight English models](https://github.com/kyutai-labs/pocket-tts)
- [llama.cpp speculative decoding implementations](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md)
- [Twitch EventSub](https://dev.twitch.tv/docs/eventsub/)
- [Twitch EventSub chat authentication, updated October 2026](https://dev.twitch.tv/docs/chat/authenticating)
- [VTube Studio plugin API](https://github.com/DenchiSoft/VTubeStudio)
- [Voice-Light: full-duplex voice agent with causal turn taking, September 2026](https://arxiv.org/abs/2609.20995)

**Non-claims:** No real computer-game FPS, audible-device ACK, model speed gain, autonomous game win, model IQ increase, or audience naturalness study is produced by this code. The upgrade makes authentic host telemetry *possible*, tests its invariants, and provides a safe integration boundary.
