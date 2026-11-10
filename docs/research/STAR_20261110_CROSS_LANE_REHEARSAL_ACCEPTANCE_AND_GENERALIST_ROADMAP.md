# STAR — Cross-Lane Rehearsal Acceptance and Integration Research

**Research date:** 2026-11-10  
**Branch:** star/next  
**Scope:** offline aggregation of trusted, content-free evidence from a private mixed-workload rehearsal  
**Status:** opt-in evaluator only; no runtime, device, game, OBS, audio, model or publication side effects

## Executive finding

STAR has accumulated separate evaluation work for inference speed/quality, real-time game mastery, game creation, voice delivery, turn-taking, multi-party conversation, memory transfer, OBS health and avatar synchronization. The remaining gap is a single session-level acceptance contract that proves these lanes were measured in the same pinned environment and source revision.

This increment adds that contract. It does not replace the specialist evaluators and does not invent a composite “human-likeness” score. Each specialist evaluator remains responsible for deciding whether its own lane passed. The new gate checks that every required lane supplied valid, signed, sufficiently sampled evidence from the same rehearsal session.

A passing result means eligible for owner review only. It does not enable streaming, promote a model, change routing, authorize game input or publish a game.

## 1. Research findings applied

### 1.1 Game mastery must be tested on a live clock and scored from outcomes

GameWorld covers 34 browser games and 170 tasks across runner, arcade, platformer, puzzle and simulation genres. It compares computer-use and semantic-control interfaces and uses serialized game state for verifiable success/progress rather than relying only on screenshots or an LLM judge. This supports a distinct gameplay lane with objective success, action-ack latency, scenario diversity and stale-action rate.

Source: https://gameworld-bench.github.io/

### 1.2 Game creation needs a plan/build/test loop, not one-shot code generation

Roblox's April 15, 2026 Studio announcement describes planning mode, structured task manifests, parallel execution against the plan, and a playtesting agent that inspects code/data, reads logs and uses a player character to test behavior. STAR should keep creator evaluation separate from game mastery: build success, playtest coverage, visual checks and regression count are not the same as win rate.

Source: https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic

### 1.3 Natural voice is a multi-objective problem

LiveKit's current turn-taking documentation separates end-of-turn detection, endpointing, interruption handling, false-interruption recovery and preemptive generation. Adaptive interruption detection can distinguish barge-ins from backchannels; preemptive TTS may reduce response latency but can waste compute when the transcript changes. STAR should measure first-audible latency, false interruptions, missed turns, grounding and actual output-device underruns independently.

Sources:
- https://docs.livekit.io/agents/logic/turns/tuning/
- https://docs.livekit.io/agents/logic/turns/

### 1.4 Speculative decoding is a measured experiment, not a universal speed switch

The upstream llama.cpp SPEED-Bench client benchmarks an already-running server and reports latency, throughput and draft acceptance by workload category. Its instructions recommend matching benchmark concurrency to the server's slot count for throughput runs. This is important because a single-request latency trial and a multi-slot throughput trial answer different questions.

A recent upstream llama.cpp issue (opened August 28, 2026) reports order-dependent ngram-cache behavior across different requests on a long-lived server. It is an issue report, not a universal claim about every build, but it is a concrete reason to pin the exact commit, record cold/warm state, randomize A/B order, and avoid treating repeated identical prompts as independent evidence.

Sources:
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- https://github.com/ggml-org/llama.cpp/issues/27852

### 1.5 Large-scale disaggregated serving is not the first optimization for an 8 GB single-GPU host

TensorRT-LLM describes separating prefill and decode into distinct GPU pools to reduce interference and independently tune time-to-first-token and per-token latency. It also requires KV-cache transfer infrastructure and adds transfer/coordination overhead. That is a useful Brain 1/Brain 2 or multi-accelerator research direction, but it is not a sensible first deployment on a single RTX 4060 8 GB machine. First measure CPU TTS, prompt caching, context size, quantization, model routing, KV-cache budget and game/OBS contention.

Source: https://nvidia.github.io/TensorRT-LLM/1.4.0rc2/features/disagg-serving.html

## 2. New implementation: star/stream_rehearsal_gate.py

The evaluator aggregates eight independent lanes:

| Lane | Required aggregate evidence |
|---|---|
| Inference | TTFT p50/p95, TPOT p50, completion p95, quality pass rate |
| Speech | First-audible p50/p95, underruns, false-interruption rate, grounding |
| Turn-taking | Addressee accuracy, silence precision, false interruptions, missed turns, multi-party comprehension |
| Gameplay | FPS p10, action-ack p95, objective success, scenario diversity, stale actions |
| OBS | Dropped frames, render/encode lag, reconnect count |
| Avatar | Lip-sync error, avatar frame drops, tracking loss |
| Memory | Transfer gain, interference, retention, retrieval latency |
| Creator | Build/playtest/visual pass rates and regression count |

### Integrity contract

- A host-created manifest pins campaign ID, a cryptographically random 256-bit campaign nonce, environment SHA-256, source revision, required lanes, duration range, minimum samples and allowed edge-coverage gap.
- Canonical JSON serialization covers every manifest policy field; its SHA-256 digest is the policy identity.
- A host-signed session receipt pins the actual monotonic session start/end and the exact manifest digest.
- Every lane receipt is HMAC-SHA256 signed by the trusted host and binds the exact campaign, session, environment, source revision and manifest digest.
- Each lane uses an exact allowlist of aggregate metric names and bounded numeric types. Boolean values are not accepted as numbers.
- Duplicate lanes, missing lanes, invalid signatures, mismatched environment/revision/policy digest, insufficient samples and incomplete time windows cannot become a pass. A new nonce or changed policy invalidates old signed receipts.
- Raw prompts, transcripts, screenshots, audio, viewer identities, chat text and file contents are not part of the receipt schema.
- HMAC keys are supplied only by the trusted local host; never expose them to models, skills, chat or viewers.

### Result states

- eligible_for_owner_review: every preregistered lane passed with valid matching evidence.
- inconclusive: evidence is missing, under-sampled, too short or has insufficient time coverage.
- blocked: a lane failed, evidence was replayed/duplicated, signatures failed, or bindings do not match.

The gate intentionally does not calculate per-lane quality thresholds. Existing specialist evaluators own those thresholds; this module verifies that their signed outcomes belong to the same rehearsal. It also does not prove the host is honest or that a key was stored securely; that remains a trusted-host responsibility.

## 3. Recommended private rehearsal protocol

1. Pin the STAR commit, model and quantization digest, inference backend, TTS route, game build, OBS version, avatar rig, drivers and workload configuration.
2. Create the manifest before starting. Keep the required lanes and minimum 30-minute duration fixed for the campaign.
3. Run privately, not publicly. Start a representative game, OBS recording, avatar, microphone/TTS and the intended model route.
4. Exercise several distinct game scenarios, including unfamiliar maps; do not replay one initial state under new IDs.
5. Include solo speech, multi-party speech, backchannels, interruptions, silence, game-critical events and viewer questions from a consented test corpus.
6. Run background research and a bounded creator task while the interactive workload is active.
7. Collect only host-observed aggregate counters and signed lane receipts. Keep raw media local and outside the evaluator.
8. Run each specialist evaluator first; then submit its signed lane receipt to the cross-lane gate.
9. Review any blocked/inconclusive lane. Never silently drop a bad lane or shorten the campaign after seeing results.
10. A complete pass only authorizes human review. Model routing, stream enablement, publishing and external actions remain separately approved.

## 4. What this means for STAR's intelligence roadmap

- Faster: optimize the actual first-audible path, not just tokens/second. Benchmark TTFT, TPOT, completion, CPU TTS, memory pressure and OBS/game frame-time together.
- Smarter: compare model/memory changes on held-out tasks and retain only improvements that preserve per-domain quality and transfer to unseen problems.
- Better gamer: separate fast perception/action from slower strategic reasoning; expire stale observations and score outcomes across diverse live-clock scenarios.
- Better creator: plan against a pinned design brief, build in an isolated test place/project, inspect visual output, playtest and rerun regression checks.
- More natural streamer: evaluate addressee detection, turn-taking, silence, backchannels, interruption recovery, voice delivery, grounding and avatar synchronization separately. Do not collapse these into one “human-like” score.
- More reliable: keep a 30–60 minute session as the system-level acceptance unit; per-module unit tests are necessary but do not demonstrate simultaneous operation.

## 5. Existing STAR work this gate is intended to connect

This is an integration layer, not a replacement for specialist branches. The relevant open work at research time includes:
- PR #1101/#1102: llama.cpp metrics and model quality/speed evidence.
- PR #1091/#1092: replay-safe, consistent paired inference evidence.
- PR #1093: scenario-balanced real-time game mastery.
- PR #1094/#1095: audible-response pacing bound to the exact voice route.
- PR #1097/#1099/#1100: proactive response timing, full-duplex turn-taking and delivery/grounding evaluation.
- PR #1103/#1105/#1107: cross-modal event context, semantic endpointing and multi-party floor control.
- PR #1108: cross-engine game creator evaluation.
- PR #1109: continual-learning transfer/interference/retention evaluation.
- PR #1110: deadline-aware work dispatch.

These are draft development branches, not features in the published v1.0 installer. Their intended integration order and CI state must be checked before merging.

## 6. Verification and limits

- The original 16 focused standard-library unittest cases passed before the manifest-binding extension. Six additional regression cases are authored for policy-digest changes, exact session/lane binding, nonce-based replay rejection, nonce validation and nonce uniqueness (22 total); current-head GitHub CI is the acceptance run for these additions.
- Tests cover full pass, missing/failed/inconclusive lanes, short session, invalid session/lane signatures, environment mismatch, duplicate lane, insufficient samples, incomplete lane window, wrong key, forbidden raw-media fields, boolean-as-number rejection and manifest policy substitution/replay.
- GitHub Actions must independently rerun Python compile/lint/Pyright and the repository offline test suite.
- No actual OBS, game, microphone, avatar, model server, GPU, Windows host or broadcast was started.
- No real performance improvement, model intelligence gain, game win-rate gain or human-equivalent behavior is claimed.

## Related follow-on research

See [Adaptive Memory, Natural Turn-Taking and Local Inference Research](STAR_20261110_ADAPTIVE_MEMORY_TURN_TAKING_AND_LOCAL_INFERENCE.md) for AMA-Bench/AEL memory-policy experiments, LiveKit EOT-Bench evaluation, GameWorld/Roblox creator workflows and llama.cpp MoE-cache experiments.

## Next engineering milestone

Build a trusted Windows rehearsal adapter that obtains OS/device loopback timing, OBS output counters, game-present timing, GPU/VRAM telemetry, avatar frame timing and process identities. It should sign receipts only after independently observing the measurements. Then run a private 30–60 minute rehearsal on the actual host and use the resulting cross-lane report to decide which bottleneck to optimize next.
