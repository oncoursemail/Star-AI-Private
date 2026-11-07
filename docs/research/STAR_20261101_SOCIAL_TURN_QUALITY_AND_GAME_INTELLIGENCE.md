# STAR AI — November 1, 2026: natural-turn proof, live gaming reliability, and next intelligence experiments

**Scope:** source-led engineering study and the two code changes on this draft development branch. No real stream, game session, model retraining, Windows benchmark, or demonstrated increase in intelligence or tokens/s occurred. This document is not a release announcement.

## 1. Concrete new implementation

### Independent natural social-turn quality gate

New files:

- `star/stream_social_turn_benchmark.py`
- `tests/test_stream_social_turn_benchmark.py`

The existing `stream_realtime_benchmark.py`, `stream_realtime_quality_gate.py`, and `stream_workload_quality_matrix.py` evaluate audio latency, game frametimes, GPU capacity, correct and grounded speech, and A/V capture. Those metrics alone do not establish that a streamer listens appropriately or avoids speaking over someone during the wrong moment.

The new *advisory*, offline-only evaluator consumes pre-registered, bounded, independently reviewed A/B cases in **five separate scenarios**, each with a baseline and candidate:

1. **Viewer question** — a question produces genuinely audible speech; report event-end-to-first-audio p95, unnecessary overlap, and groundedness. Missing audible speech is not a fast response.
2. **Optional game commentary** — purposeful silence is valid, but if Star comments, speech must be grounded and not inappropriately overlap.
3. **Authenticated owner barge-in** — measure event-to-actual-playback-stop latency; an interruption recommendation alone is not an actual stop.
4. **Incidental noise or backchannel** — false interruption must not stop Star's speech.
5. **Critical gameplay** — nonessential speech must not interrupt a time-critical action.

Records contain only opaque case IDs, scenario, timing durations, and reviewer flags: **no audio, viewer IDs, transcripts, actual timestamps, process credentials, or game frames**. A report can only recommend a *manual rehearsal*, never enable streaming or run a model. The code rejects duplicate case/variant keys, inconsistent paired scenarios, malformed timestamps, missing review, and attempts to omit a hard scenario. It compares candidate question p95 against its baseline (100ms maximum degradation by default) as well as an absolute 1500ms ceiling, requires owner audio stop within 350ms, and limits unintended audio overlap to 150ms. **All thresholds are preliminary engineering budgets, not empirically calibrated human-equivalence criteria.**

The committed suite supplies 13 deterministic, synthetic regressions for missed owner barge-in, false noise interruption, ungrounded claims, talking during critical play, speech overlap, false speed improvements, missing recordings, invalid fields, and cherry-picked scenarios.

**Integration plan:** have the owner-controlled Windows recorder produce case-level durations from actual *OBS captured output*, not from enqueue callbacks, and an independent reviewer provide `grounded` and scenario labels. Freeze scenarios *before* A/B. Run at least 20 paired cases per scenario on Windows (100 pairs / 200 recordings total), rather than trusting the four-per-scenario synthetic minimum. Fail closed on missing pairs or audio. The next integration should combine this social-turn gate with the existing audio/FPS/VRAM quality matrix, not replace it.

### Fixed verified-but-rejected streaming telemetry clock poisoning

`star/stream_load_governor.py` had a second clock-watermark issue: even after rejecting unverified submissions before touching its clock, a *host-verified but stale, duplicate or future-dated sample* could call `_clock(now_s)` and permanently advance the clock even though `ingest` subsequently returned False. A delayed duplicate with an extreme time could make later genuine readings appear to move backward. This is an availability problem, not proof of a real observed attack.

The updated ingest path validates its monotonic query time without committing it, checks replay/order/freshness, and **only commits the watermark for accepted telemetry**. Normal `recommend` calls still advance the independently supplied clock, and genuine backwards time is still rejected. Two new regressions verify that duplicate and stale/future malformed delivery cannot poison the session, while a real backward clock still fails. The existing pressure, immediate escalation, and multi-window recovery rules are unchanged.

### Actual verification performed

Using the exact published files downloaded from the commit on the authorized `starai` Linux development host:

- **13/13** new social-turn benchmark tests passed.
- **19/19** streaming load governor tests passed (including two newly added tests).
- Python bytecode compilation of these modules/tests completed.
- These are *synthetic offline tests*. They do not certify GitHub's whole-repository CI, Windows integration, real-time voice naturalness, GPU utilization, or a live broadcast. CI must be reviewed on the final head commit.

## 2. Primary research and what to learn from it

### AVTR-1 (2026): listening animations need both sides of the conversation

Avaturn Live's [AVTR-1 technical report and open stack](https://avtr-1.avaturn.live/) describes a 153M-parameter audio-conditioned motion model that incorporates both participants' speech for dyadic gestures and listening motions, with streaming frame scheduling and interruption-aware playback. Its important lesson for STAR is **not** to replace the entire local avatar renderer with generative video. Rather, let real-time owner/chat audio activity modulate **listening gaze, blinks, head tilt, and neutral nod gestures** while speech synthesis drives mouth animation. Always tie these gestures to playback/session epochs; discard cues from cancelled utterances.

**Practical 8GB RTX 4060 strategy:** begin with inexpensive deterministic Live2D/VRM state blending (gaze, eyelids, posture, mouth amplitude and jaw motion, wavy hair physics). Benchmark audio-conditioned learned motion only after OBS and game frametimes are healthy. AVTR-1 releases model, renderer and backend under component-specific licenses: independently inspect the license and performance of every artifact before integrating.

Sources: https://avtr-1.avaturn.live/ ; https://github.com/avaturn-live/avtr-1 .

### AITuber OnAir and Prometheus Avatar: study orchestration, not copy a whole application

[AITuber OnAir](https://github.com/shinshin86/aituber-onair) is a TypeScript open-source AI VTuber toolkit with separate chat/voice/memory/avatar packages, supporting PNG, VRM and Live2D. **Useful to STAR:** frontend integration seams, a fake Twitch event source, avatar contracts, browser-local fallback demonstrations, and isolated adapters. Software/docs are MIT; **bundled Miko character assets have separate terms**. Do not adopt those assets as Star/Astro/Amber.

[Prometheus Avatar](https://github.com/myths-labs/prometheus-avatar) offers a separate Live2D/3D SDK, lip sync, emotion tags, TTS and VTuber mode. Useful comparative study: separating LLM content generation from an independently cancellable avatar command stream. Its advertised low latency is *not a STAR hardware measurement*, and its cloud voice provider and third-party dependencies require a privacy/terms assessment. The repository reports MIT software license and separate third-party license disclosures.

**Avoid integrating either toolkit wholesale** until their behavior, dependencies, data handling, Windows packaging and license obligations are reviewed. STAR already has `stream_audio_avatar_session.py`, `stream_motion.py`, `stream_turntaking.py`, `stream_director.py`, and stage/host adapters. Prefer experiments with a narrow interface.

### RealtimeBench (October 14, 2026): world-clock matters more than raw reasoning

[The World Won't Wait / RealtimeBench](https://arxiv.org/abs/2610.20665) presents 180 real-time tasks across six game genres and a slow-teacher/fast-student method that improves the reported benchmark scores. The paper's model improvements do **not** transfer automatically to STAR. A correct delayed jump can be a fatal action. For STAR, enforce an age budget from scene observation through **real input dispatch**, with no expensive teacher inference during active play, and save failures for offline study after the attempt.

Connect the existing `game_deadline_router.py`, `game_action_freshness.py`, `game_skill_gate.py`, `gameplay_skill_bank.py`, `game_practice_curriculum.py` and local **Core Forge** candidate verification without merging untested model changes. A repeated win on one map is not generalization. Use unseen maps, control latency, hard opponents, and signed separate validation. Never expose held-out answer keys to the practicing agent.

### Roblox OpenGameEval (October 1, 2026): inspect before editing, execute afterward

Roblox's [OpenGameEval](https://github.com/Roblox/open-game-eval) measures agents in actual Studio tasks with executable validation. The [paper](https://arxiv.org/abs/2610.02563) reports 84 tasks and finds exploratory inspection strongly associated with success. It should change STAR's builder pipeline: **inspect scene tree and object properties → form a spatial/behavioral plan → implement a small change → execute playtests → compare rendered scene and check collision/attachment → repair or roll back**. Use [StudioTestService](https://create.roblox.com/docs/reference/engine/classes/StudioTestService/AddPlayers) for multiplayer join/leave, client/server replication and matchmaking tests, plus retained screenshots and actual gameplay validation. Code compiling is insufficient to certify that a level looks good.

### llama.cpp SPEED-Bench: performance claims need matched conditions

The official [SPEED-Bench client](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) measures latency, throughput and speculative draft acceptance for an already running `llama-server`. It supports comparisons across fixed prompt categories, output lengths and request concurrency. For STAR, never infer GPU performance from a paper's H100 or Apple Metal results.

On the 8GB RTX 4060, compare these **operator-controlled** experiments:
- CPU-only quick-path vs GPU-reactive inference, while OBS/game/avatar/TTS are actually active.
- Same quantization/model/prompts across KV caching on/off and different slot counts. Verify conversation isolation (existing `llama_cache_isolation_probe.py`) before enabling shared caches.
- Speculative decoding with draft model only if its VRAM overhead and acceptance provide an end-to-end benefit; disabling it must remain easy.
- Prompt prefill time, first token time, first **captured audio** time, action age at dispatch, 1%-low FPS, OBS skipped-frame rate, underruns, GPU memory peak and task correctness **together**, not tokens/s alone.
- For Rust experiments, profile first. Candidate hot paths include image ROI extraction, PCM envelope calculation, queue/delta processing and serializing large structured snapshots. Avoid a blanket Python-to-Rust rewrite without measured gain.

The graphics budget must protect OBS rendering and game frames before optional inference. Use the current advisor modules as guidance, not substitutes for actual host scheduling.

## 3. The proposed streaming personality and autonomy system

**A. Functional continuity.** Maintain verified, source-tagged game moments, hobbies, creator progress, character interests, and a consistent persona profile across sessions. Distinguish actual observed experiences from fiction, future hopes and viewer claims. Never invent childhood, human biography or real-world ownership. Genuine continuity is more compelling than scripted pseudo-memories.

**B. Attention and expression.** A host-controlled attention loop tracks whether Star is speaking, listening, gaming-critical, looking at UI, waiting on a loading screen, or in deliberate silence. Emotion tags are *performance controls*: amusement -> smile/soft laugh; surprise -> quick eyes/head; concentration -> reduced chatter/gaze at task. Do not equate expressive performance with evidence of feelings or consciousness.

**C. Low-latency interruptions.** Actual output audio and mouth cues stop together when an authenticated owner voice interrupts. A guest speaking should generally hold future STAR speech, not activate privileged controls. VAD backchannels, game sounds and synthetic audio echoes must be tested for false positives. Use only privacy-appropriate moderation, retention and consent.

**D. Self-directed learning.** Use bounded curiosity queues for game genres, original Roblox experiences, UI/animation/design, Rust, general knowledge and VFX. Choose an offline practice task from proven weakness; record a score before and after; validate on unfamiliar tasks; let Core Forge retain candidates and automatically roll back regressions. Public GitHub is a publishing mirror, not the essential self-improvement datastore.

**E. Creator quality.** Star should not claim game completion until geometry placement, wall connectivity, prop anchors, material/texture consistency, character grips, animations, lighting, UI layout and multiplayer behavior have passed both executable and visual checks. Capture mistakes into reusable lessons without overfitting to a single screenshot.

## 4. Concrete acceptance and deployment order

1. Run the existing Python, type-check and React CI on the **exact** updated commit; do not merge until green.
2. Windows host: attach **independently attested** OBS/output telemetry, actual audio loopback recorder, and current game/VRAM measures to current advice-only components. Reconnect/reset must invalidate stale evidence.
3. Freeze 100+ paired streaming moments across the five social scenarios before testing. No live viewer data in the public repository. Start with offline recordings and manual review of exact audible stop and overlap times.
4. A/B compare fast-path voice options with the existing workload/AV quality gates, the new social-turn gate and actual OBS/game FPS. An optimization is *rejected* if quality or frame stability regresses even when it generates tokens faster.
5. Enable a **private, operator-supervised rehearsal** only after threshold and permission gates pass. Then test a small authorized game with a deterministic input layer, synchronized vision, signed per-attempt outcomes and separate holdouts.
6. Reuse successful learning only after the game skill and transfer validators pass; record rollback versions in local Core Forge. Release externally only through explicit publishing review.

### Remaining unknowns

There are no collected, real paired audio/playback samples here, no Windows OBS GPU trace, and no quality-rated live conversation corpus. Neither passing synthetic tests nor any third-party demonstration establishes that STAR now sounds human, beats more games, learns faster, or runs faster on her hardware. Those are the next measurements. The repository currently has public visibility: exclude secrets, raw voice, private chats and identifying viewer data.
