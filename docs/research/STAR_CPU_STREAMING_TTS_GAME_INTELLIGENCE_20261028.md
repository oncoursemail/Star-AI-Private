# Star AI: CPU streaming voice, game intelligence and autonomous learning
**Research date:** 2026-10-28 · **Status:** experimental draft, no deployment · **Audience:** Star Core Forge / Star AI engineers

## Why this change, instead of another isolated planning module

Star has a measured cognitive governor (`star/stream_brain_governor.py`),
trusted hardware telemetry, a verified Studio practice runner, a signed game
skill bank, a viewer chat adapter and an interruptible Stage. These are
valuable control-plane pieces but do **not** actually synthesize speech or
execute inference in the Windows gaming environment. In the current main
voice engine, Kokoro ONNX can use GPU or CPU, but a responsive CPU-native,
**chunk-streaming** model is not selectable. That leaves an avoidable gap
between VRAM-aware scheduling and real audio generation.

This branch adds an **opt-in executable CPU TTS candidate** to Star's
existing voice engine, not another simulated controller. Existing Kokoro
settings and Star's established voice remain the default. It makes a
testable hypothesis possible: *Can streaming a 2M/7M/18M model on CPU lower
first-generated-chunk latency and game GPU contention, while preserving
intelligibility, personality and game frame consistency?* It does not assume
that the answer is yes.

### Evidence checked against original projects

* Kyutai Pocket TTS official documentation: https://kyutai-labs.github.io/pocket-tts/
  Official API: https://github.com/kyutai-labs/pocket-tts/blob/main/docs/API%20Reference/python-api.md
* Kyutai **v4.0.0 (2026-10-20)** shipped six ~18.2M/6.9M/1.9M English
  regular/reward-finetuned models. **v4.0.1 (2026-10-21)** fixed small-model
  verbalization behavior and selected `english_2026-10` as English default:
  https://github.com/kyutai-labs/pocket-tts/releases
* The upstream Python stream accepts a `threading.Event` stop token,
  yields one-dimensional float PCM chunks, has a configurable language
  model, and warns that the model is *not thread safe*:
  https://github.com/kyutai-labs/pocket-tts/blob/main/pocket_tts/models/tts_model.py
* Roblox announced built-in Studio MCP and automated playtest input in
  March 2026: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
  and expanded Plan → Build → Test in April 2026:
  https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
* **OpenGameEval** (Oct 1, 2026) evaluated 84 curated engine tasks in
  actual reproducible Studio sessions, separating inspection actions from
  edits. The paper reports stronger success when relevant objects were
  inspected before editing, a direct rationale for Star's inspection-first
  building system: https://arxiv.org/abs/2610.02563
  Project: https://github.com/Roblox/open-game-eval
* llama.cpp implements draft-token and EAGLE-3 speculative decoding:
  https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
  Such techniques increase throughput only when their acceptance rates
  justify memory and compute overhead; they must be profiled on Star's GPU.
* Twitch's EventSub documentation specifies at-least-once notifications
  and WebSocket reconnect semantics (deduplicate message IDs and handle
  lost events): https://dev.twitch.tv/docs/eventsub/handling-websocket-events
  https://dev.twitch.tv/docs/eventsub/websocket-reference/
* Full-duplex speech turn-timing studies in October 2026 show that merely
  transmitting audio continuously is **not** human-natural turn prediction.
  Anticipatory end-of-turn models and acoustically grounded interruptions
  matter: https://arxiv.org/abs/2610.08683

## What was coded here

1. `star/voice/pocket.py`: `PocketStreamingTTS` with lazy opt-in import,
   language/model whitelist, named built-in voices, one reusable conditioned
   voice state, serialized upstream model use, PCM16 chunk conversion,
   explicit cancel signal and release of completed streaming iterators.
2. `star/voice/engines.py`: `make_tts("pocket", ...)` with model selection,
   without changing the default `KokoroTTS`.
3. `star/voice/settings.py`: `tts_engine="pocket"` and a curated model ID.
   Reject unsupported speed/pitch/language and mixed Kokoro catalog IDs.
   No arbitrary path or voice URL is accepted from settings/viewer text.
4. `star/voice/runtime.py`: optional model selection reaches real voice
   calls. `star/voice/bridge.py`: selection reaches real read-aloud; the
   availability check requests `pocket_tts` instead of Kokoro weights and
   generation stops on interruptions. `star/voice/call.py`: active Pocket
   CPU generation is cancelled on barge-in; the speaker is still physically
   stopped even if cancellation callback raises.
5. `star/voice/pocket_benchmark.py`: manual, deterministic-prompt,
   no-media-retention benchmark for first *generated* chunk, generation
   duration, output length and real-time factor. Tests contain fake model
   outputs and never download weights or capture voices.

**The sampler does not yet provide Star's established Kokoro voice.** Built-in
Pocket voices have different sound/expressiveness; changing the engine is
an audible persona change. Human listening tests with consent and a licensed
voice source are required before any selection for public broadcasting.
Actual voice cloning, human imitation, personality replication or synthetic
"memories" are not added.

## Optional installation and test run

Install in a dedicated **owner-approved voice environment**, not the default
dependency set. Pin tested packages; the baseline research uses
`pocket-tts==4.0.1`. On Linux, explicitly use PyTorch CPU wheels so the
small TTS engine does not silently download gigabytes of unnecessary CUDA
packages. The upstream project's CPU-only installation instructions are
authoritative; use its documentation rather than assuming all package
resolvers honor the extra-index priority.

After explicitly obtaining weights, configure an opt-in voice call or
read-aloud with all four settings:

```json
{
  "tts_engine": "pocket",
  "pocket_model": "english_18m_2026-10",
  "voice": "alba",
  "voice_id": "",
  "speed": 1.0,
  "pitch_semitones": 0.0,
  "tts_lang": "en-us"
}
```

These settings do not start a microphone or Twitch stream by themselves.
Avoid automatic swapping of voice settings based solely on GPU pressure:
a sudden vocal identity change during streaming is distracting and harms
character consistency. Only compare models/voices in private offline trials.

Manual **generated audio only** benchmark after owner-directed model setup:

```sh
HF_HUB_OFFLINE=1 python -m star.voice.pocket_benchmark \
  --model english_18m_2026-10 --voice alba --repeats 6
```

Run on the dedicated CPU while OBS/game remain on the same real hardware.
The output intentionally contains no PCM, captions, viewer chat, model
prompts or user identifiers. It cannot measure voice naturalness, model
intelligence or first-audible timing by itself. Use physical sound-device
ACKs and paired `star/stream_realtime_benchmark.py` sessions for those.

## Evaluation gate: quality *and* speed

**Baseline** is the pre-existing Star Kokoro voice. **Candidate** is a
specific Pocket model and named stock voice. Freeze game map/build, GPU
driver, exact speech lines, microphone arrangement and model configuration.
Use paired ABBA order across ≥20 reproducible matched sessions per game,
with two or more representative game loads and a no-game control.

Record from the authorized local host, on one monotonic clock:

* **First generated PCM chunk** (candidate's generator start to chunk).
* **First physically audible PCM** (speech request to actual device ACK),
  including model queueing, chunking, device buffering and playback.
* p50/p95/p99 interruption-to-silence timing and stale-speech incidents;
  the interrupt host must stop the physical device and Live2D epoch.
* Frame present p95/p99 milliseconds, **1%-low actual game FPS**, GPU VRAM
  headroom, CPU scheduling impact, memory peak, speaker backlog, dropouts.
* Human blind ratings for intelligibility, warmth, humor, prosody,
  intelligible laughter, exaggerated tonal shifts, and recognizable
  personality. Include sample rate clicks at chunk boundaries.
* Whether interrupt works during a long-running chunk on Windows, with
  the real `sounddevice` playback path. Test background game load,
  streaming OBS encoder load, Discord call load, and avatar rig movement.

The new benchmark only reports CPU first-generated metrics. **Do not
translate that into first-audible, FPS, quality or "human" gains.** A faster
tiny voice might sound worse or stall the CPU when gameplay is CPU-heavy.
Choose a slower-but-clearer model if blind voice quality fails.

Keep PR **DRAFT** until real Windows proof, full CI, independent review and
rollback to Kokoro all pass. Never automatically change live hardware
permissions or start a stream from chat text.

## Next intelligence improvements ranked by measured impact

### 1. Full gameplay learning and skill transfer

Integrate existing `StudioPracticeRunner`, `StudioVisualObserver`,
`StudioVisionQoS`, `GameLearningLadder`, `GameTransferEval` and
`RealtimeTelemetryHost` in a real private Studio session. Private,
repeatable curricula should cover camera motion, obstacle timing, moving
platforms, enemy AI, navigation, physics, recovery and latency compensation.
Keep a fast reflex/engine-state controller separate from slower vision/LLM
semantic deliberation. Use independent signed success/failure checks,
uncertainty from observation, skill provenance, held-out map seeds, and
new-game transfer. Don't count action emission as a win. No public-game
computer control is implied.

**Metric:** success rate on unseen levels, deaths/minute, time-to-clear,
action latency and measured inference/game FPS, with paired baselines,
uncertainty intervals and strict invalid-trial reporting.

### 2. Game creation with build integrity

Before generating any scene, create a structural manifest with explicit
object locations, anchored/attached relationships, sizes, material choices,
scripts, collisions, expected paths, UI constraints and gameplay tests.
The agent must inspect scene hierarchy and dependencies **before** edits;
make changes in an isolated Studio sandbox; run Luau/physics/gameplay
checks; capture render screenshots from multiple cameras; check object
overlap, missing walls, Z-fighting, texture stretching, clipping, nav
accessibility and UI overlap. A code-blind screenshot evaluator and real
human visual feedback should independently reject "AI slop." Only ship
when deterministic tests and human visual gates pass. Specialized
parallel asset designers may contribute but only one scene manifest owns
coordinates and consistency.

**Metric:** playable build success, collisions/misplacement counts, object
inspection coverage, open-game-eval holdout pass rate, human blind scene/UI
rating and elapsed seconds to a tested good build.

### 3. Smarter general knowledge and reflective self-model

Maintain versioned, date-aware source provenance; trace every claim to
original sources or actual firsthand tool observations. Distinguish
verified fact, hypothesis, character lore, and the AI's generated story.
Keep speculative notes separate from checked knowledge, expire transient
facts, and resolve contradictions with a fresh research pass. Use
`general_knowledge_benchmark.py` and blind holdouts, not just the
count of documents read, as the success indicator. Star's ongoing
functional self-model can track her last activities, confidence, interests,
personality, failures, plans and lessons—without claiming subjective
consciousness was scientifically demonstrated.

**Metric:** held-out factual accuracy, citation auditability,
cross-session memory precision, temporal recall, corrected-error rate,
time-to-source and unchanged baseline skills.

### 4. Faster inference with fewer wasted cycles

Combine existing hardware-aware admission and the new CPU speech
alternative with targeted speculative decoding, KV caching, quantization,
shorter working contexts, CPU vs GPU model placement, batched offline
jobs, duplicate detection and explicit task deadlines. Keep urgent
voice and player reflexes in the fast path; queue research, asset
generation, training and build validation opportunistically while idle.
Memory-offload helps larger models *fit*, but can make them slower via
PCIe bandwidth; benchmark load, prefill and decoding separately.

**Metric:** TTFT, audible speech latency, tokens/s, requests completed at
quality threshold, joules/task, held-out answer correctness, VRAM usage,
peak RAM, 1%-low game FPS and failures. Performance improvements are not
established by architectural complexity or speculative documents alone.

### 5. More human-natural VTuber performer, without pretending to be human

The runtime should have a game state-aware attention controller: intense
combat → quiet, quick status; surprising event → short spontaneous
reaction; lull → playful chat; viewer interruption → owner-priority
barge-in; downtime → actual hobbies, art or remembered **verified**
events. Blend spoken content, timing, expressive eyes, ear/tail physics,
hair spring movement, idle fidgets, breath/blink and the identity's
cat/puppy modes. Separate short emotionally colored barks from longer
intentional conversations. Support spontaneous social interactions and
stable personality while accurately identifying Star as an AI if asked.
Distinguish fictional character backstory from real experience.

**Metric:** paired blinded naturalness ratings, turn overlap rate,
meaningful silence percentage, audio↔mouth sync, eye gaze accuracy,
emote appropriateness, coherent continuity, chat comprehension accuracy,
p95 response latency and measured FPS with VTube Studio/OBS loaded.

### 6. Star Core Forge as the local source of truth

The owner's intended Star Core Forge remains the offline-first code,
verification, experiment, provenance and rollback backend. Independent
agents submit typed change plans and atomic diffs; reviewers evaluate
hidden trials; only successful objective improvements are promoted.
Store benchmark receipts, known regressions, and rollback snapshots on
the user's machines; publish vetted code to GitHub as an **optional**
review/export surface. Draft PR branches are not deployment permission.

**Important repository state (2026-10-28):**
`oncoursemail/Star-AI-Private` currently has **PUBLIC** visibility
despite its filename. Treat every artifact here as public. Never commit
API keys, personal communications, private recordings, usernames of
viewers, screenshots, private evaluation or private model assets.

## October 28 verification and integration notes

Existing Star infrastructure now includes audio-sample-bound AudibleAvatarSession
and authenticated local Live2D bridge (draft PR #761). The optional Pocket engine
is integrated into real voice call and read-aloud routing, not a second
parallel audio output architecture. Both modules still require a trusted Windows
audio callback to connect physical playback time to avatar motion.

The selected Pocket model runs on the CPU and does not honor GPU-only mode.
A missing model cache is an explicit configuration/runtime failure, not
permission to download weights or select another voice during a live stream.
Keep the voice selected by the owner fixed across a broadcast. A model's
first generated PCM is not proof of audio reaching the audience.

Backend iterator cleanup must clear its generation epoch even when closing
the stream fails; errors are surfaced to the host. The new regression suite
covers this teardown failure and rejects GPU-only requests to the CPU adapter.

**New source checks:**
- Official Pocket API, models and cancellation contract:
  https://kyutai-labs.github.io/pocket-tts/API%20Reference/python-api/
- Official v4.0.1 October 21 small-model corrections:
  https://github.com/kyutai-labs/pocket-tts/releases/tag/v4.0.1
- Roblox Oct 1 OpenGameEval 84-task executable benchmark:
  https://arxiv.org/abs/2610.02563
- Oct 19 CEGame-Bench completion gap and playability:
  https://arxiv.org/abs/2610.26098
- Oct 26 VISTA self-exploration harness lineage:
  https://arxiv.org/abs/2610.35051

**Rollout gates:** owner-only private rehearsal, optional package installation,
no raw-voice retention, benchmark matched real Roblox+OBS loads, compare to
existing Kokoro with blind listening ratings, independently verify spoken
gaming facts and game actions, and stop/rollback immediately on FPS or
first-audible regressions. This adapter does not demonstrate real CPU speed,
a new learned game skill, or subjective consciousness.

## Concrete release checklist

- [x] Offline-selectable CPU streaming TTS adapter implemented.
- [x] Opt-in config, clear unsupported knobs, cancellation, bounded PCM.
- [x] Deterministic fake-backend tests and non-recording CPU benchmark.
- [ ] Real Pocket weights installed in a vetted owner-selected env.
- [ ] Audio hardware callback and Windows speech stop verified.
- [ ] Real private Roblox Studio gameplay and VTube Studio avatar loaded.
- [ ] A/B first-audible, game FPS, CPU and GPU telemetry under OBS load.
- [ ] Human blind voice/personality evaluation vs existing Kokoro.
- [ ] Full offline repository CI and security review.
- [ ] Rollback plan validated; draft PR approved before merge.
