# STAR — model-profile isolation for real-time gaming and expressive VTuber speech
**Date:** 2026-11-04 · **Status:** implementation + deterministic test evidence, **not** live hardware validation

## Finding: latency measured on one model is not transferable to another

The existing `AdaptiveQoS` controller correctly separated idle, game-only,
stream-only and game+stream observations, but pooled latency observations by
**task kind + CPU/GPU device + workload regime**. That is not enough: a fast
18M-parameter CPU TTS run can be followed by a much slower 100M-parameter
voice run on the same CPU. Similarly, a small VLM's 125 ms evidence must
not certify a larger VLM for a 250 ms deadline. The scheduler also pooled
circuit-breaker failures between those independent models.

This patch keys **p95 measurements, failure counters, recovery cooldowns,
recovery probes and reservations** by the trusted host's opaque
`route_profile` in addition to kind/device/load. The profile must change
whenever the model weights/version, quantization, voice model, context setting,
threads/GPU layers or runtime build materially changes. A profile is an
*identity for calibration*, not permission to use a model or execute a tool.

Default empty profile is retained for legacy clients. The new optional
`require_route_profiles=True` requires a nonempty profile for *protected*
live or private stream-equivalent work. It is **disabled by default**, so it
must be enabled by the trusted host when binding its real model adapters.
Until then, legacy callers can still share measurements; the feature is not
a claim of production enforcement. Route-profile inputs from model output,
viewer chat, webpages or arbitrary tool replies are **not trusted**. Do not
use file paths, names, credentials or other secrets as the profile.
Aggregated diagnostics show a truncated profile hash rather than the raw ID.

### Verification scope

`tests/test_stream_qos_route_profiles.py` checks:
- independently measured CPU speech routes cannot borrow one another's p95;
- an uncalibrated live vision model cannot borrow a calibrated VLM's latency;
- a failure breaker for one model does not disable a different model;
- strict private/live streaming requires a host-bound profile;
- malformed labels are refused; legacy route behavior still works.

Tests use a synthetic monotonic clock and fake telemetry. **No audible
speech, GPU inference, game success, Windows/OBS integration, or streaming
naturalness improvement is demonstrated.** Independent CI is required before
merging. The code retains the underlying rule that unmeasured essential
speech may be explored under a bounded deadline; it must never be
mislabelled as a profiled measured p95.

## Hardware-aware research, 2026-11-04

**CPU speech while the GPU is busy.** Kyutai's Pocket TTS repository
describes CPU-oriented audio streaming and October 2026 small English
models at 18.2M/6.9M/1.9M parameters. They are legitimate A/B candidates,
not a guarantee of equivalent quality or latency on STAR's Windows host.
Measure first-audio chunk p95/p99, xRT, truncation, pronunciations,
human listening scores and CPU contention while OBS renders and a
game is active. A smaller model is only better when it improves the
combined perceived performance without losing voice quality.
Source: https://github.com/kyutai-labs/pocket-tts

**Do not assume prompt-cache correctness or throughput from a feature flag.**
A llama.cpp issue opened on **2026-08-15** reports cross-conversation
restoration in RAM-backed prompt caching under concurrent slots, and an
issue opened **2026-10-22** describes unified KV-cache restore failures.
Treat the exact build/version/configuration as part of the runtime profile;
test replay isolation, per-session privacy, cache correctness and first-token
latency before enabling RAM-backed multi-slot caching on STAR's conversational
runtime. These are reported issues, not independently reproduced STAR bugs.
Sources:
- https://github.com/ggml-org/llama.cpp/issues/27148
- https://github.com/ggml-org/llama.cpp/issues/30961

**OBS/Windows resource contention.** A single `nvidia-smi` free-memory
number or idle inference benchmark cannot certify real simultaneous load.
Collect host-attested, continuous p50/p95/p99 screenshot-to-action,
speech-first-audio and game-frame latency across *game + avatar + OBS +
voice*; attribute GPU residency and WDDM allocation pressure, measure
interruption-to-silence and input-release acknowledgements, then freeze a
model/runtime profile before claiming a gain. Avoid using one GPU sample
or an unloaded score to reopen background jobs.

## Humanlike VTuber behavior is a systems problem, not a bigger prompt

- **Observe:** timestamped game events, player/teammate speech turns,
  approved viewer questions, scene and game phase; keep chat as untrusted
  content, never tool instructions.
- **Decide when to talk:** yield to owner and real interruptions, suppress
  repeat reactions, allow silence during difficult moments, avoid reading
  private details. Prefer grounded, short, specific reactions over
  generic constant narration.
- **Speak and animate:** fast speech scheduling on a calibrated route,
  caption/audio timing acknowledgement, controlled facial expression
  and gesture synchronized to actually audible audio. If a turn is
  interrupted, release audio and avatar motion.
- **Remember honestly:** record verified high-level outcomes and selected
  memories with provenance, context and correction history; never
  hallucinate friendships, achievements or private experiences.
- **Disclose:** STAR is an AI performer. Expressive personality is welcome;
  deliberate impersonation of a real human is not the product goal.

Real success measures: viewer turn response latency, proportion of
grounded remarks, repetition/interrupt error rate, silence quality,
consented listening feedback and audio-avatar synchronization—not just
chat-length or token throughput.

## Gaming practice / Roblox development next gates

1. Record a *private* Windows game+OBS+avatar+voice rehearsal, never a
   public broadcast, using consented, authorized local sources.
2. Link gameplay observations to verified action outcomes and retained
   trajectories; track success and mistakes on genuinely new maps
   or challenge seeds, not training repeats.
3. For learning, compare fixed reactive baselines against a frozen
   upgraded policy on the same held-out episodes; report confidence
   intervals, input latency, FPS, outcome attribution and regressions.
4. For game building, use Roblox Studio's documented MCP tools to
   inspect the project, change one permitted private sandbox place,
   playtest with instrumented clients and check the output visually.
   Multi-Studio `studio_id` selects an instance, not an access-control
   boundary. Preserve explicit authorization and rollback.
   Source: https://create.roblox.com/docs/studio/mcp

**Recommended next engineering integration:** have the *trusted Windows
model/voice host* set `route_profile` from the exact active worker
configuration, enable `require_route_profiles`, and run real A/B trials
under identical stream-equivalent load. This patch provides the measurement
isolation but does not itself configure model binaries, OBS or a voice.
