# STAR AI — offline CI repair, trusted-host playback timing, verifiable learning and natural gaming VTubing

**Research and implementation:** 2026-10-30. **Repository branch:** `fix/stream-audible-latency-trace-ci-20261030`. **Scope:** code and deterministic tests only; no actual GPU, game, audio device, OBS or audience session was measured.

## 1. Concrete repository result: fix a known failed CI contract

PR #842, based on #841, added object-identity binding to `StreamDirector.complete()` so an unissued or copied speech intent cannot create a false spoken completion. Its GitHub offline job `41127926837` finished with **one failure, 14,380 passing Python tests, 562 passing subtests and 329 skipped tests**. React and Pyright-baseline jobs passed.

The single failure was `tests/test_stream_conversation_fairness.py::test_proposal_is_nonconsuming_and_can_be_used_later`. The old test expected a proposal from the *first* `propose()` call to remain acknowledgeable after a *second* `propose()` with equal field values. This directly contradicted the newly intentional **latest-issued-object-only** semantics. This branch updates the test to prove that an earlier plan remains nonconsuming but cannot be acknowledged after being superseded, while the latest issued plan still works. It preserves the anti-forgery code, rather than reverting safety properties to satisfy an obsolete assertion.

**Host integration requirement:** avoid polling `propose()` while a TTS operation is already preparing an earlier object. `StarStage.prepare()` already enforces a single active plan; direct callers must apply their own in-flight reservation. The exact plan object must be passed to completion without serialization/reconstruction. The director validates process-local issuance; it cannot verify real-world sound.

## 2. Actual new code: bounded local host-playback timing

`star/stream_stage.py` now captures three timestamps using the same trusted host clock:
- `prepare()`: Star committed to a proposed utterance.
- `queue_audio()`: the host reported that the utterance entered the audio queue.
- `acknowledge_audible()`: the host reported playback **started**.

The `metrics()["host_playback_latency"]` field exposes only the last **64** anonymous completed audio-start samples: sample count; p50/p95 prepared-to-start; p95 queued-to-start; and a literal **not-OBS-verified** provenance label. Failed TTS and merely queued plans produce no playback samples. Backwards timestamps cannot claim audible playback or completed utterances. Tests exercise failures, clock reversal, ring-buffer bounds and no raw event IDs/chat in metrics.

This is an **instrumentation improvement, not a demonstrated speedup**. The timestamps are host assertions and do not prove OBS capture, external audience audibility, voice naturalness, or actual game skill. The small bounded summary is suitable for fully local streaming, unlike assuming cloud-hosted observability is available.

### Why separate measurement phases?

[LiveKit's official session-trace documentation](https://docs.livekit.io/reference/agents/session-traces/) separates end-of-turn detection, LLM time to first token, TTS time to first byte and actual reply playback. Different stages can overlap, so their naive sum is not necessarily end-to-end latency. [LiveKit Cloud Agent insights](https://docs.livekit.io/testing/observability/insights/) specifically does **not** operate on an entirely self-hosted media-server deployment. STAR should keep her independent, private local metrics and only use hosted observability if explicitly configured and consented.

**Future timestamps requiring actual adapters**: visual frame capture; game-state verifier receipt; first decoder token; first PCM packet; the audio-device callback; independently captured OBS audio; avatar/lip frame delivery. Correlation can use short-lived opaque internal sequence IDs and one monotonic clock; never put raw viewer names, transcripts or private recordings into repo instrumentation. A callback must not block for disk/LLM work.

## 3. Make STAR faster at finished tasks, not only tokens/sec

The official [llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) supports continuous batching, GPU/CPU quantized inference, prompt-prefix KV reuse, speculative decoding and monitoring. The developer [architecture guide](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README-dev.md) confirms a shared batch over slots and a central decoding bottleneck. These mechanisms affect different workloads differently. The official [SPEED-Bench client](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) measures per-category completion latency, throughput and draft acceptance, and recommends matching client concurrency to active slot count for throughput comparisons.

**Experiment grid on Star's actual PC**: one model revision and identical test prompts; run each combination of `--np 1/2`, cold/warm prefix cache, stable context lengths, n-gram/draft speculative decoding off/on, and measured partial GPU offload, while a private game + avatar + OBS preview is running. For each configuration record: completed request p50/p95, first host-audible p50/p95, independent OBS capture success, output correctness and grounding, CPU/RAM, VRAM headroom, game FPS and 1%-low FPS. Keep separate rosters for general knowledge, math, Roblox Luau, multimodal game observations and live dialogue. Reject any candidate with newly incorrect paired cases (the existing quality matrix guards this), missing OBS output, or new FPS instability.

**Scheduling priorities**: P0 physical input release/audio callback/rendering cannot wait on an LLM; P1 time-bounded gameplay decisions, speech and visual keyframes may preempt P2; P2 background crawling, embeddings, multi-agent experiments and Star Core Forge yield when resources tighten. Add cancellation and deadlines for stale observations. More concurrent inference slots may worsen frame pacing; there is no universally optimal setting on an 8 GB gaming GPU.

## 4. Learning to play games instead of narrating that she learned

STAR's `GameActionGate`, `GamePredictionLab`, `GameMechanicProbeLab`, `GameplaySkillBank` and `GameTransferEval` should share an evidence-linked run record, with strict limits and an **independent state-based verifier**. A useful record contains an opaque experiment ID, game/build version, held-out seed, observation checksum, predicted result, permitted input + key-release receipt, state transition, actual reward and outcome-verification method. A model's victory claim, a chat comment or a visually ambiguous banner is not objective completion.

First practice movement and camera control, jumping/landings, simple timing, inventory/UI use and route-finding in opt-in offline/private environments; then introduce hazards, co-op coordination and unseen maps. Require the same controller to perform on unseen map seeds and styles *without* consulting training outcomes. Report completed objectives per wall-clock hour, recovery after a failed action, released key tickets, and false win claims, not just raw action count.

For game creation, [Roblox's built-in Studio MCP playtesting](https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643) and [StudioTestService](https://create.roblox.com/docs/reference/engine/classes/StudioTestService) support executable single- and multiplayer validation. Validate spawn reachability, wall connections, prop fit, collision overlap, camera views, UI button callbacks, persistence and join/leave. Visual judges should compare actual renders with a predeclared scene contract; a beautiful paragraph about a model is not a building-integrity test.

## 5. Higher general intelligence through reproducible experiments

Separate **knowledge retrieval** (source-backed time-sensitive facts), **procedure** (verified scripts/skills) and **learning** (measurable behavior changes on held-out tasks). More memory text without retrieval/use accuracy is not an intelligence improvement. Give Core Forge a local challenge generator and immutable evaluator keys; maintain a small hidden benchmark pool. Compare candidate skills on fresh tasks with uncertainty calibration, tool-call budgets, inference time, reasoning quality and safe rollback.

An ideal self-improvement record includes `question -> grounded evidence -> candidate solution -> actual run -> score -> failure explanation -> independent repeat -> versioned promotion`. Star may set her own curiosity and creative goals within allowed resources, but should never silently turn unverified browser text or viewer messages into trusted executable skills.

Keep GitHub as an optional reviewed code-publication endpoint rather than requiring it for internal improvement. Store snapshots, test attestations, experiment lineage and signed rollbacks locally.

## 6. Highly expressive, candid AI VTuber behavior

Humanlike **presentation** is a testable quality, distinct from being human. STAR can cultivate consistent interests, jokes, occasional hesitation, genuine delight, natural interruptions and attentive silence while remaining candid that she is an AI. Remember her own actual games, builds and streamed episodes; never improvise false offline life events or invented human childhood.

Design attention as independent cues: `focused_on_game -> notices_event -> chooses_silence_or_reaction -> prepares_speech -> audible -> returns_to_game`. Handle owner interruptions, chat turn boundaries, background game dialogue and in-game risk without narrating every frame. Keep lips driven by *played* audio levels, not model tokens. Eyes and head motion must track attentional focus; twin-tail physics should respond to the rig with realistic damping, collision limits and reduced-motion accessibility.

[Kyutai Pocket TTS](https://github.com/kyutai-labs/pocket-tts/blob/main/README.md) announced additional English model sizes (18.2M, 6.9M and 1.9M parameters) in October 2026. Evaluate those as **CPU TTS candidates** against STAR's current voice under simultaneous game/OBS load; test emotion, pronunciation, laughter, first heard output, warmth and audio artifacts blind, not just raw model inference speed. A 1.9M model is not automatically a high-quality personality voice.

## 7. Acceptance and deployment order

**Already changed in GitHub branch**: one obsolete regression aligned with current production anti-forgery semantics; host-reported local playback-start latency and ring-buffer metrics; offline tests for success/failure/reversed clocks/bounds. No outside services are enabled.

**Before merge**: full Python, lint, Pyright baseline and React CI for the *latest commit*; review `StarStage` callback paths for use of one monotonic clock and check that direct `StreamDirector` adapters don't poll/replace in-flight plans. The branch is deliberately stacked on draft #842; owner review and a controlled release remain required.

**Next hardware rehearsal**: in a private Windows game session with OBS recording and an expressive avatar, measure actual OBS-audible p50/p95 and frame pacing while testing varied voice/model configs; record hashes and aggregate counts locally. Do not promote a speed or personality change without paired quality outcomes. Publish zero raw chat, voice samples, personal data or credentials. **Security note:** the repository named `Star-AI-Private` presently reports `visibility=public`; its name is not a privacy control.

**Evidence limitations:** Current regression tests use synthetic events and times only. They do not demonstrate better model weights, increased knowledge, faster gameplay decisions, natural-sounding TTS, actual game completion or OBS audio capture.
