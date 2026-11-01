# STAR AI — real read-only OBS host, intelligence, game mastery and natural VTuber roadmap
**Date:** 2026-11-01 · **Status:** implemented offline host adapter and regression tests; no live broadcast or proven performance gain.

## Executive engineering decision

STAR does not need another unmeasured "be smarter" prompt. She needs a repeatable
**observe → act → hear → animate → measure → learn → independently verify**
loop. The new work removes a missing host boundary: the preceding
`stream_obs_readonly_evidence.py` could validate *synthetic* OBS WebSocket v5
responses, but did not itself open an authenticated local OBS connection or
verify request IDs. The new `obs_nonbroadcast_rehearsal_host.py` does so,
without ever requesting an output action.

The owner wants excellent gaming/Roblox skills, fast local reasoning, a natural
animated personality and self-directed practice. These are separate empirical
claims: a perfectly green offline test suite **cannot** establish that STAR can
win an unfamiliar game, deliver human-quality conversation, or run a stable
livestream on an 8-GB GPU. Keep those evaluations separate, then combine them.

## 1. Actual protocol integration (implemented)

The previous parser now has a concrete, optional trusted-host caller:

- `ObsNonbroadcastRehearsalHost.connect(password, owner_approved=True)`
  establishes **only** `ws://127.0.0.1:4455`, validates the single local OBS
  process by PID + creation time, receives v5 Hello and completes password
  challenge authentication. It subscribes to **General + Outputs** events.
  The password is never stored, echoed, logged or returned.
- `sample(recorder=...)` sends exactly three allowlisted v5 methods,
  `GetStats`, `GetStreamStatus`, `GetRecordStatus`, with independently
  generated opaque request IDs. It reads raw opcode-7 responses on that same
  socket, correlates each ID, records host-monotonic receipt times, checks that
  the OBS process has not restarted and passes the evidence to the earlier
  `ObsReadOnlyEvidenceGate`.
- Unlike high-level SDK projections, these are *real protocol witnesses* with
  the IDs that OBS actually returned, not fabricated request envelopes.
- Between responses, same-socket output events are drained in FIFO order.
  **Any** stream/record/replay/virtualcam output event, OBS exit, unexpected
  response, socket error, record-active/stream-active status, invalid sample or
  recorder refusal permanently revokes the session; no automatic reconnect.
  A new, explicitly authorized host is needed for another attempt.
- `finish()` adds a final status fence and closes the socket. There is no
  `StartStream`, `StartRecord`, scene change, media capture or game input
  method. A sample report holds only counts and aggregate loss fractions.

**Scope:** Same-socket fencing detects output changes delivered before a fence;
it cannot prove no change after the last fence, that the host itself is honest,
or that an event was not lost by OBS. A Python `host_verified` boolean is
not hardware attestation. A host must inspect the *actual* output during an
owner-approved manual Windows rehearsal before any broader claims. This module
does not trigger one.

**CI unblock:** The older `stream_windows_rehearsal_preflight.py` incorrectly
relied on `type(value) in (...)` to narrow psutil's optional/Incomplete
`create_time` type, triggering six Pyright baseline errors. It now performs
explicit numeric type narrowing before converting process timestamps, without
admitting PID 0, unknown timestamps, boolean values or OS system placeholders.
The inherited OBS parser also had a separate `float(object)` Pyright error;
its already-runtime-checked value is now explicitly narrowed before conversion.
A report is not considered an intact **finished** OBS interval until the
owner-authorized host completes its final fence; calling `close()` after
ordinary samples never promotes an incomplete observation.

### Manual, nonbroadcast acceptance

1. An authorized owner manually opens OBS, an avatar renderer and the test
   game. Leave both Streaming and Recording **OFF** in OBS. Do not connect
   unmoderated chat, save scene names or collect private media.
2. Run the separate Windows GPU/process *stability window* and preserve adequate
   VRAM for game + avatar + OBS. On earlier observations of the RTX 3060 Ti,
   VRAM headroom was only a few hundred MiB; do **not** treat 0% GPU utilization
   as free memory. Those are previous point readings, not measurements here.
3. A trusted host obtains the OBS WebSocket password from an owner-controlled
   secret source. Instantiate `ObsNonbroadcastRehearsalHost()`, call
   `connect(password=secret, owner_approved=True)`, repeatedly call
   `sample()` during the rehearsal, then `finish()` to fence and seal.
   Never place the password in a code repository, CLI argument or model prompt.
4. Pass the resulting OBS render **counter deltas** to
   `StreamRehearsalRecorder`. Keep game FPS from independent *frame-presented*
   events, first audible PCM from actual speaker callbacks, avatar frames from
   the renderer, and GPU memory from an independent measured high-water mark.
5. Compare **paired baseline/candidate** sessions with the existing quality,
   naturalness, gaming and workload matrices. No automatically approved stream,
   model swap, chat reply, account action or training promotion follows from a
   clean OBS response alone.

## 2. Real-time intelligence: make different kinds of thinking cooperate

**Fast reflex lane (time-critical):** Capture only the current game state
required for an immediate legal action. Drop stale observations. Use bounded
deadlines, explicit input leases and game-presented timestamps. Prioritize
the game's frame cadence and responsive controls over generating more tokens.

**Tactical lane (roughly 0.5–3 Hz while resource headroom allows):**
Remember recent mechanics, game objectives and teammate positions. Ask a
stronger local model for *short, structured choices*, not continuous long-form
reasoning. The tactical model suggests, but the fast controller retains final
authority to refuse stale or unsafe input.

**Teacher/learning lane (off-stream, off-hot-path):** Analyze actual failed
game trials, read curated game documentation, produce alternative tactics,
retest against both the same training scenario and independent unseen layouts,
and only then add a versioned approved lesson to STAR Core Forge. Keep learning
runs isolated and reversible.

**General knowledge lane:** Source-bound retrieval with dated citations,
provenance and explicit uncertainty. Separate fact retrieval from tool permission.
Repeated chat claims or unreviewed web text do not become "new memories".
Use a stable cacheable persona prefix, project-specific retrieval, and bounded
fresh data appended at user priority rather than editing the system prompt.

**Implementation priority:** Wire the existing `GameLearningLadder`,
`GameplaySkillBank`, `StreamBrainGovernor`, `StreamStage`, and tested
`StreamRehearsalRecorder` into a **single Windows demonstration**. Avoid
duplicating their verification logic in yet another agent loop.

## 3. Fast on 8-GB-class GPUs: optimize measured complete latency

Do not assume a faster decoder means a faster streamer. The user-visible
critical path is scene acquisition → game-action approval OR user finishes
speaking → STT/turn end → retrieval → first PCM → avatar motion → actual OBS
frame. Measure p50/p95/p99 for *each boundary*, including cache cold starts,
model load, VRAM peak, GPU time and CPU saturation. Never infer latency from
model text or queued audio.

Test the following **one change at a time** with pinned datasets and hardware:

- llama.cpp **SPEED-Bench**: compare target-only against small speculative
  draft/MTP/ngram under identical concurrency, context and prompt lengths.
  Record accepted draft tokens, end-to-end p95, peak memory and missed game
  frames; reject speculative configurations with negative real-world gain.
- CPU TTS: audition the October 2026 **Pocket TTS small English** families
  (18.2M / 6.9M / 1.9M parameters) on STAR's own CPU for audible first-chunk
  delay, pronunciation, warmth, laughter controls, underruns and voice
  consistency. A faster but robotic model loses the subjective quality test.
- Context costs: cache unchanged persona, tools and retrieved approved
  knowledge; cap low-priority telemetry tokens; quarantine caches by
  project/session/privacy scope. Never leak a previous user's private KV cache.
- Hardware placement: prioritize game, OBS and avatar GPU stability. Route
  small VAD/turn detection/TTS to CPU or a second machine where measured.
  Run large teacher models and Blender/video work in off-stream windows.
  Explicitly benchmark CPU contention, PCIe transfers, RAM pressure and
  network jitter before declaring offload a success.
- Rust: port *profiling-proven* CPU hotspots such as frame normalization,
  telemetry parsing or geometry validation behind a stable Python API. Native
  compilation does not accelerate an unchanged neural GPU decode kernel or
  fix an overfull VRAM allocation. Keep ABI, installation and rollback tests.

**Suggested acceptance criteria, not measured STAR results:** avoid >10% p99
game frame-time regression; no unaudited GPU over-allocation; no audio stutter;
demonstrable paired reduction in first-audible p95; no correctness loss on
held-out tasks. Prefer confidence intervals and independent evaluation.

## 4. Game mastery and game creation

For **playing**: game families need distinct skill curricula (platforming,
shooter navigation, survival, puzzle, cooperative timing, sandbox building).
Each training trial should specify the game build, map seed, objective, allowed
actions, expected completion signal and deadline. The trusted game host, not
STAR's generated explanation, signs outcomes. Keep validation levels
separate from all training prompts and lesson retrieval. Define rollback when
a new tactic succeeds on one familiar map but fails on unseen maps. Never
deploy bots to online games against rules or unfairly affect other players.

For **making**: game-building quality needs two independent kinds of tests.
Automated Luau/physics tests establish correctness (character collision,
spawn locations, walls/doors attached, no invalid references, money/item
persistence, multiplayer round transitions). Rendered inspection verifies
materials, lighting, actual UI layout, motion, proportions and occlusion.
A script that compiles is *not* evidence the build is attractive. Roblox's
StudioTestService supports programmatic multiplayer test sessions, including
join/leave and up to eight simulated clients; run these in a Studio Lab, not
a live server.

For **learning**: STAR should challenge herself with increasingly unfamiliar
situations, keep failures, test transfer, and ask for owner review of ambitious
new skills. Accept a new skill only when held-out performance improves and the
process is reproducible. The result is a functional self-model of what STAR can
and cannot reliably do—not evidence of literal consciousness.

## 5. Natural, expressive AI VTuber — measured rather than scripted

The most believable character behavior is *causally grounded*:

- Listening and natural interruptions: lightweight VAD plus local semantic/
  acoustic end-of-turn detection (LiveKit `v1-mini` is one CPU-capable
  option). Avoid talking over a mid-sentence pause. Stop actually audible
  playback on owner interruption; simply deleting a text reply is insufficient.
- Expressions tied to *heard* PCM, not predicted speech. Give Star subtle
  eye focus, gaze, blinks, hair motion, posture shifts and small smiles during
  quiet moments. Suppress exaggerated reactions when gameplay is demanding.
- Remember genuine wins, mistakes, in-jokes and projects with evidence and
  dates; distinguish fictional persona lore from factual lived experiences.
  Do not manufacture viewer relationships, fake a human identity, or pretend
  to have seen gameplay that was not captured.
- Use VTube Studio's authenticated plugin API custom parameters for
  appropriate Live2D cues, with an owner-visible kill switch. Never save
  usernames, private chats, viewer faces or raw microphone audio by default.
- Make conversations varied by recognizing when *not* to speak, short jokes,
  acknowledgements, deliberate pacing, meaningful follow-ups and respectful
  correction. Compare independently reviewed paired clips for interruptions,
  unwanted overlaps, vocal continuity, false game claims and avatar freeze.
- STAR, Astro and Amber can each have their own styles and cooperative
  scripted bits, but every actual interaction still needs host events and
  on-air moderation, not fabricated sensory experience.

## 6. Verification, reproducibility and explicit limits

Implemented here: **one new raw OBS offline host**, **one Pyright type
correction**, and protocol-level regression tests with a simulated
WebSocket. A synthetic protocol server is not an OBS integration test.

Next independent acceptance checkpoints:

1. Python unit + type + Ruff + current CI baseline, plus positive and
   adversarial same-socket protocol tests. The fixture should fail for changed
   output state, missing record status, mismatched ID, malformed event,
   stale frame or OBS process restart.
2. Manual Windows nonbroadcast trial: two or more time-fenced OBS samples,
   both output states OFF, OBS process pinned, non-zero game frame presents,
   audible PCM & avatar frames, GPU available headroom and independent
   recorder completion. A report without those *other* sources proves only OBS.
3. Offline paired baseline/candidate sessions with the existing
   `stream_realtime_quality_gate`, `stream_social_turn_benchmark` and
   `stream_workload_quality_matrix`; evaluate gameplay, conversational
   dialogue, general knowledge and Roblox creation separately.
4. Game skill transfer on unseen builds/maps, geometry integrity tests,
   long-running resource contention and fail/recover behavior.
5. Human review of voice expressiveness, timing, movement and trustworthiness.
   Only then consider a supervised, owner-approved broadcast. Never silently
   begin streaming from an AI-generated instruction.

## Primary sources reviewed (2026-11-01)

- OBS WebSocket project, built into OBS Studio 28+ and authentication guidance:
  https://github.com/obsproject/obs-websocket
- OBS v5 protocol specification, request/response opcodes and subscriptions:
  https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md
- LiveKit audio end-of-turn detector, including locally executable v1-mini:
  https://docs.livekit.io/agents/logic/turns/turn-detector/
- Kyutai Pocket TTS, October 2026 small English CPU models:
  https://github.com/kyutai-labs/pocket-tts/blob/main/README.md
- llama.cpp SPEED-Bench benchmarking and speculative decoding:
  https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- Roblox StudioTestService and multiplayer testing:
  https://create.roblox.com/docs/reference/engine/classes/StudioTestService
- VTube Studio authenticated plugin API/custom parameters:
  https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins

**Boundary:** This is a functioning offline-tested measurement/host component
plus engineering research. There was no model fine-tuning, throughput
benchmark, actual game victory, Windows integrated rehearsal, OBS broadcast,
or proof that STAR became more intelligent in this code change.
