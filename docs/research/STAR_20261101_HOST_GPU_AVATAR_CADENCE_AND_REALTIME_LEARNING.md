# Star AI — Host-verified GPU high-water mark, audible-avatar continuity and faster game intelligence

Date: 2026-11-01. Status: implemented **offline measurement guards** plus research and acceptance plan; no Windows deployment or streaming performance claim.

## 1. Why another infrastructure change mattered

The new StreamRehearsalRecorder in draft PR #867 previously let a caller give any numeric gpu_peak_mib to to_realtime_run(), even though the recorder treated other timing boundaries as host-verified events. That weakened the evidence chain behind a GPU-budget comparison: a missing real measurement could be replaced by a plausible number. Its benchmark bridge also admitted a completed utterance with zero avatar render frames, or with one frame at the beginning followed by a long freeze. The speech and game benchmarks could then look excellent while Star was visibly motionless. These are **measurement-qualification** problems, not proof that Star's current real VTuber renderer has these faults.

This patch closes those gaps at the same trust boundary as the other eleven host events:

* Add a strictly typed, opt-in "gpu_peak_measured" event, available only after game frames and after an utterance is no longer active. Its positive, finite MiB high-water mark is supplied by the authorized Windows host only. It may be recorded once per rehearsal **after one audible utterance has completed**. Further frame events are disallowed after the final peak marker, so the sample cannot silently omit later frames. The bridge no longer accepts a caller-supplied GPU value.
* Require at least 120 **game-presented frames while PCM is actually audible**; idle-only frames measured before/after speech must never make a paired game/voice benchmark qualify. Export only overlapping game frame durations, preventing an artificial speed improvement by sampling gameplay after voice stops.
* Measure **the longest observed interval between audible PCM onset, each avatar-rendered frame, and PCM stop**. This catches no-avatar, late-avatar, and avatar-rendering pauses that a first-frame latency percentile hides. Default comparison qualification threshold is 550 ms, configurable from 50 to 3,000 ms for different avatar stacks. The threshold is a quality heuristic, not an animation research constant.
* Keep an incomplete run visible as incomplete rather than manufacturing evidence. Preserve short opaque correlators only inside the recorder; export numeric aggregate timing, frame and GPU counters. No private text, video, audio, game captures, or viewers' identifiers.
* The recorder is OFF unless owner_approved=True. Event host_verified=True is a host-contract assertion, **not cryptographic attestation**. Never let an LLM or untrusted plugin call the recorder in the trusted host's place.

This extends the existing single-utterance bridge to RealtimeRun. It cannot claim facial motion, viseme correctness, intentional-expression quality, or actual human naturalness merely from frame cadence. A visually static frame refreshed sixty times per second can still pass. That requires future video/animation-quality evaluation with appropriate privacy consent.

## 2. Proposed host adapter and live-mode activation

Use a separate Windows process with a well-defined trust boundary, not the generative model:

1. Keep owner's live/offline-rehearsal toggle OFF by default. The local host runs a nonbroadcast rehearsal, with no OBS stream output enabled. Host approval applies to the full rehearsal interval, not individual AI-supplied event flags.
2. Emit scenes from the authorized game capture/input observer with a single QueryPerformanceCounter-derived monotonic clock. Only count actual OS-confirmed worker lifecycle, permitted input, audio device playback, and animation renderer **present** callbacks. A generated animation command is not a rendered frame.
3. Request the GPU high-water mark from a driver/OS telemetry adapter that tracks the relevant process and the **whole measured rehearsal interval**. If such a peak cannot be established reliably, omit "gpu_peak_measured": the run must remain unqualified. Do not pass a snapshot as a peak. On shared GPUs, document the process-vs-device accounting policy.
4. Deliver all events over a bounded local queue. Suppress screenshots, prompts, game/chat text, voice samples and player names. Treat stale clocks, duplicated events, counter resets and dropped sensor packets as incomplete evidence. Use one sensor version and timestamp normalization per run.
5. Export only completed, monotonic, single-utterance recordings with **120–5,000 real-game frames presented while audio is audible**, verified peak and continuous avatar presentation. Audio-free idle frames never enter paired FPS statistics. Pair baseline and candidate on identical game version, fixed route and comparable resource pressure.
6. Feed the existing compare_realtime evaluator. Never automatically promote candidates into the stream based on a single metric. Human review and rollback remain required for hardware, privacy, expression and game-quality changes.

A host-specific adapter can use the VTube Studio public API or an in-app mascot renderer, depending on whether the current character is Live2D or CSS/3D. Merely sending a VTube Studio hotkey does **not** prove the frame was rendered. Keep sending commands and measuring renderer/device acknowledgement separate. Avoid pretending that any plugin API provides frame-level proof unless it actually does.

## 3. Higher-speed intelligence without ruining the stream

**Fast path, ~real-time decision budget:** Observations -> scene state -> last verified skill policy -> authorized input. Use deterministic control for simple mechanics, a small quick model for ambiguous perception, action expiry and independent host cancellation on scene changes. Do not let slow learner or speech code seize the critical game/OBS thread.

**Tactical path, seconds:** Choose goals and strategies using a compressed game state, not full frames or every transcript. Schedule a single bounded inference worker and enforce GPU/CPU quotas. On 8 GB VRAM, keep peak buffer headroom for the game, OBS encoder and animation. Route CPU speech selectively after actual first-audible and continuity measurements.

**Learning path, after rounds or offline:** RealtimeBench (Pan et al., submitted October 14, 2026) tests 180 tasks over six continuously running game types. Its TORSI approach uses a slower teacher to extract reusable lessons, validated by a fast student in later attempts. For Star: store a skill as task scope + observed outcome + validated instruction + version + generalization score, never as a self-asserted memory. Re-test on held-out worlds, changed camera angles, randomized seeds and unfamiliar opponents. Prevent benchmark leakage by splitting tasks and withholding evaluation cases.

**Model routing and inference:** Compare llama.cpp direct, n-gram and draft-model speculation with SPEED-Bench using the actual hardware and target workload. Record p50/p95 time-to-first-token, output latency, accepted draft tokens per target pass, game-frame hitches, VRAM and TTS interruptions. The upstream docs describe speculative methods, but speedup is workload/model/backend-dependent. For low-capacity VRAM, speculative draft contexts may cost more than they save; reject candidates unless measured whole-pipeline wins and no tail regressions.

**Rust:** Consider moving hot-path ring buffers, timestamp validation, CPU-frame preprocessing and telemetry codec to Rust *after* profiling identifies CPU overhead. Preserve Python orchestration and FFI contracts. A rewrite itself does not make model weights or inference intrinsically smarter, and costly FFI copies may erase wins. Use optional feature flags and identical Python/Rust conformance vectors.

## 4. More humanlike, but truthful, VTuber behavior

Build Star as a believable and distinct AI VTuber, not as a system falsely claiming biological humanity. Her expressive identity should emerge from coherent timing and grounded memories.

* **Listening**: independent VAD and end-of-turn detection; LiveKit's "v1-mini" can run locally on CPU. Compare it with lightweight continuous detector CueLight (Apache-2.0, English-only as of source check). Test interruptions, overlapping speech, silence, mic noise, stream delay, language mismatch and multi-speaker voice chat. Never equate ordinary silence with a failed dialogue turn.
* **Voice**: evaluate Kyutai Pocket TTS's October 2026 18.2M, 6.9M and 1.9M English models alongside the current voice, under identical prompt and sample-rate settings. Developer-reported faster-than-real-time output is not Star-measured. Grade first *audible* PCM, mid-sentence gaps, articulation, prosody, emotional consistency, CPU core pressure and avatar lag.
* **Animation**: use PCM progress to drive viseme/mouth cues, and independent blink, eye saccades, head/body anticipation, hair motion, expressive poses and purposeful listening idles. Measure first-render delay, maximum frame silence, freezes at audio stop, and actual expression quality in consented visual review. Preserve reduced-motion support.
* **Persona**: maintain stable interests, game-specific habits, a distinct sense of humor, a memory of what actually happened in her stream, relationships with mascot companions Astro and Amber, and natural recovery from mistakes. Mark imagined lore as fiction; do not claim to have sensations, human relationships, or off-platform experiences she did not have. Apply moderation and privacy protection to viewer interactions.

## 5. Game making and wider knowledge

For game creation, Roblox's October 2026 OpenGameEval shows benefits associated with inspecting relevant objects before editing, and runnable checks during simulated play. CEGame-Bench (October 19, 2026) broadens evaluation to five engines and long-horizon real-input play. Implementation path for Star:

* Inspect scene graph, terrain, positions, collision groups, anchor points, mesh/material provenance, UI layering, network ownership and existing scripts **before** edits; produce structured dependency and placement plans.
* Generate multiple candidates only where cheap. Validate scripts (Luau AST, analyzer/linter), physics, occlusion, scale, anchors, terrain contact, materials, texture seams, animation paths and actual input sequences. A single pretty screenshot is not gameplay success.
* Use Roblox StudioTestService for multi-client join/leave and gameplay checks, the engine's own virtual input tests, and repair loops. Separate reproducible automated checks from aesthetic human preference ratings. Require playable completion rather than merely error-free startup.
* Store general knowledge as versioned and cited retrieval with local license/attribution metadata, source freshness, domain tags and evidence. Validate public web knowledge against docs and prevent user data/private stream transcripts from leaking into persistent public training artifacts. Keep Star Core Forge's versioning, rollbacks, agent evaluations and private-to-public export policies as the center of self-improvement.

## 6. Evaluation matrix and adoption rules

**Before qualification:** the new unit tests must prove that a missing GPU high-water mark, a zero/invalid GPU value, a duplicate peak, a post-peak game frame, only-idle game frames, a missing avatar, and a single-frame avatar freeze cannot create a qualified RealtimeRun. Valid continuous avatar frames and host peak should still export. Prior queue, input, worker and OBS invariants must remain unchanged.

**On the Windows game host (not yet performed):** perform 20+ randomized matched baseline/candidate rehearsals per game/scene, using live game load + OBS preview + audio device + animation. Collect complete GPU high-water mark, actual frame times and presenter timestamps. Measure GPU headroom and p95 first-audible latency. Add pass/fail for zero unapproved actions, zero stale host decisions, no unauthorized speech/audio capture, no unaccounted sensor gaps, no new game hitches, and no frozen avatar spans over configured tolerance. Do not broadcast any testing session.

**Later game mastery:** evaluate 30+ seeded gameplay runs across at least two game types, hold out some seeds and worlds, compare completion/wins/damage/time and generalization to unseen tasks. New learned memories count only when independent result evidence matches the claimed outcome and the next attempt improves on a robust baseline.

**Live VTuber candidate promotion:** require both numeric guardrails and blind naturalness/animation quality review, prevent exaggerated "human" claims, and preserve automatic rollback on worsening latency or privacy policy failures. This patch alone is not such a promotion.

## 7. Source notes checked November 1, 2026

* Pan et al. (Oct 14 2026), "The World Won't Wait", RealtimeBench/TORSI: https://arxiv.org/abs/2610.20665
* Roblox OpenGameEval, 84 core tasks, executable checks and observation-before-edit result: https://github.com/Roblox/open-game-eval and https://arxiv.org/abs/2610.02563
* CEGame-Bench, long-horizon cross-engine end-to-end game-play benchmark (Oct 19 2026): https://arxiv.org/abs/2610.26098
* Roblox StudioTestService: https://create.roblox.com/docs/reference/engine/classes/StudioTestService
* LiveKit turn detection documentation (including local v1-mini): https://docs.livekit.io/agents/logic/turns/turn-detector/
* Kyutai Pocket TTS, Oct 2026 small English models: https://github.com/kyutai-labs/pocket-tts
* CueLight continuous audio end-of-turn detector (English only): https://github.com/sshah03/CueLight
* VTube Studio API: https://github.com/DenchiSoft/VTubeStudio
* llama.cpp speculative decoding: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
* llama.cpp SPEED-Bench client: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

External benchmark numbers are **not** Star results. All sources should be reevaluated when implementations, licensing or releases change.
