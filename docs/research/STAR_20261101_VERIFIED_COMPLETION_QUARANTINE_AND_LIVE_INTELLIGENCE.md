# STAR: verified inference completion, game learning, and believable VTuber execution

**Research and patch date:** 2026-11-01. **Scope:** opt-in offline engineering, not a live streamer, sentient AI, Roblox publisher, or new inference model. This repository is public; keep screenshots, transcripts, credentials, viewer identities, model weights and other private data out of commits.

## 1. Concrete weakness fixed in this patch

In `star/game_realtime_loop.py`, a valid live inference lease could be consumed by `finish(..., host_verified=False)` or a finish call carrying a reversed host monotonic clock. The call returned a rejection but erased the lease without retaining evidence that the inference process might still exist. The next verified frame could consequently be offered another inference slot while an unconfirmed prior worker remained in flight. This violated the previously added superseded-worker quarantine.

**Invariant:** an issued lease can cease to occupy the worker slot only after independently verified completion or independently verified process termination. Rejecting model output, discarding a lease, an exception, or receiving an untrusted timestamp is not evidence the worker exited.

**Patch:** when the *matching* lease's purported completion lacks host verification or its host timestamp regresses, preserve `worker_stop_pending` until the host provides an explicit termination attestation. Keep valid but quality-rejected completions eligible to free the slot, since their host completion was independently verified. Do not alter input permissions or launch workers here.

**Red/green reproduction:** new tests first reproduced two failures in the original source, then passed with the fix. The third new test protects against excessive quarantine when a trusted completed worker is rejected for CPU pressure. Host process-handle management and true cancellation are still outside this advisory module.

## 2. The next integration should be an end-to-end measurable Windows rehearsal

STAR already has modules for game-frame provenance, deadline-aware inference advice, input permits, speech-continuity evaluation, OBS health, and avatar playout. A large pile of separate passing tests cannot show that they cooperate in a real broadcast. Build a local, opt-in **flight-recorder harness** with no content capture by default.

Proposed event schema (all one host-monotonic clock, same episode ID): `scene_observed`, `fast_worker_started`, `fast_worker_exited`, `lease_invalidated`, `action_claimed`, `action_released`, `speech_queued`, `pcm_first_audible`, `pcm_stopped`, `avatar_frame_rendered`, `obs_stats_sampled`. Keep bounded durations, anonymous counters, hashes, and validated Boolean attestations only. Do not persist player text, voice, frames, or Twitch messages. Wall-clock timestamps are for human reports, never action deadlines.

Required invariants: every worker has a unique host-owned ID and terminal exit observation; an old worker's stop acknowledgment cannot release a newer worker; an input permit is valid only for the same verified frame and focus session; speech/avatar timestamps derive from audio **actually played**, not from TTS generation completion; OBS and game performance remain within measured local baselines. When streams reconnect, reset freshness epochs conservatively.

**Acceptance:** record paired, reproducible dry-run sessions on the authorized Windows PC with same game/OBS scene and model settings. Include P50/P95/P99 scene-to-action, speech cue-to-first PCM, audible barge-in stop, OBS dropped/skipped-frame fraction, render hitches, CPU/GPU occupancy and VRAM high-water mark. Compare both distributions **and** individual regressions. A simulation passing is not proof of playable real-time gaming.

## 3. Game intelligence: fast action, slow teacher, verified practice

The October 14 preprint **RealtimeBench/TORSI** evaluates 180 continuously running tasks across six game types; teacher-generated instructions improved a fast student's average progress in that study, from 13.51 to 24.19. These are **research results, not STAR results** ([primary paper](https://arxiv.org/abs/2610.20665)).

Use a fast, deadline-limited game student **only** during live gameplay. It should have compact state (objective, visible hazards, cooldowns, recently verified skill instructions), a limited set of game-authorized actions, a safe no-action fallback, and measurable uncertainty. A slow teacher operates **between** runs on saved, consented, privacy-safe practice events and proposes small revisions to strategy cards. STAR Core Forge uses holdout maps/seeds, signed outcomes, retention probes, and automatic rollback to reject instructions that overfit one map or silently worsen timing. No expensive teacher call on the gameplay critical path.

Priority curriculum: (1) camera and navigation; (2) platformer jumps with moving obstacles; (3) timing and dodging; (4) team communication; (5) strategic planning with resource conservation; (6) generalization to unfamiliar maps. Record progress with first-attempt success, time-to-completion, intervention count, repeated failures, and performance under active real-time clocks. Do **not** reward self-reported model confidence as evidence of winning.

## 4. Speed: optimize the complete stream, not a tokens-per-second screenshot

The official [llama.cpp SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) measures server latency, throughput and speculative-draft acceptance. It is useful for replaying the *same* workload with speculation on/off, but does not measure game rendering, OBS, lip-sync or speech contention. A May 14, 2026 [llama.cpp report](https://github.com/ggml-org/llama.cpp/issues/23052) illustrates that speculative decoding can help predictable code but **regress** creative, high-entropy content; a per-request runtime toggle was not generally available in that report. Do not assume speculative decoding is universally faster.

For the current 8 GB VRAM class of GPU, pin the fast game model and its context only when VRAM headroom actually permits it. Prefer bounded prompts, explicit max output, prompt prefix reuse when privacy boundaries permit, low concurrency during games, cancellation and one active work lease per game session. Evaluate draft-model allocation against its extra VRAM, context and initial setup cost. Test CPU-only TTS alongside LLM inference, then choose by *measured* total scene-to-action plus audible latency. Rust is a candidate for independently benchmarked hot paths (frame ring buffer, audio timestamping, event serialization and scheduler), **not** a reason to rewrite tested high-level orchestration blindly.

Gate any speed optimization on P95/P99 response latency **and** the absence of new single-session OBS frame hitches, dropped speech, missed game commands or memory growth. New features default off, with explicit rollback and reproducible baseline artifacts.

## 5. Natural VTuber: a coherent character, not excessive talking

A plausible streaming character needs a **single unified timebase** and a state machine coordinating: watching game / listening / planning / talking / reacting / interrupting / focusing. Star may act playful, curious or frustrated as expressive character *performance* grounded in her actual observed events; do not falsely assert human experiences or consciousness.

- **Turn-taking:** LiveKit's [audio turn detector](https://docs.livekit.io/agents/logic/turns/turn-detector/) documents `v1-mini` local CPU execution, whereas full `v1` uses cloud inference. Benchmark actual interruptions, noise, long pauses, overlapping viewers, and CPU contention before adoption. VAD alone is not a complete intention detector.
- **Speech:** Kyutai's [Pocket TTS](https://github.com/kyutai-labs/pocket-tts) offers CPU-oriented streaming speech and October 2026 English models around 18.2M, 6.9M and 1.9M parameters. Compare clarity, names/pronunciation, laughter, first audible PCM, internal unplanned silence, and playback-stop time. The smallest model is not necessarily the most believable. Use licensed voices and no unauthorized voice clones.
- **Avatar:** The [VTube Studio public API](https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md) supports authenticated custom parameters and parameter injection. Build a bounded opt-in adapter for gaze, blinks, brows, head tilt, mouth motion and recovery to a neutral pose when PCM/host heartbeat becomes stale. Astro and Amber can animate through a separate scheduler without stealing Star's live input focus. Respect reduced motion.
- **Personality and memory:** keep per-game play diaries of *verified* wins and fails, small character-level interests/hobbies, audience-safe preferences, consistent recurring jokes, and contextual recollections with source provenance. Keep private viewer data ephemeral or consented; memory does not grant permissions. Alternate natural silence with timely brief commentary instead of constant talking.

Use independent listener ratings on paired, blinded 5-10 minute rehearsals (coherence, timing, naturalness, emotional fit, interruption handling), plus objective PCM timing and missing-commentary detection. An evaluation score cannot establish whether Star is literally human.

## 6. Robust game creation and general knowledge

[Roblox's Studio testing modes](https://create.roblox.com/docs/studio/testing-modes) document StudioTestService simulation of up to eight clients, VirtualInput, and scriptable device profiles. STAR's game builder should inspect a scene, generate a small change, check geometry and asset licences, run executable multiplayer joins/leaves and UI journeys, inspect visual output, then repair. Avoid editing live published user places without owner authorization.

General knowledge should be a versioned retrieval-and-verification layer: source authority, freshness date, license, scope and provenance are stored separately from chat memory. Avoid training on arbitrary webpages as if they were trusted ground truth. Run fixed holdout evaluations over coding, math, explanations, up-to-date documentation and game-design decisions. Independent grading and strict app/model version pinning are required before promoting improvements.

## 7. Owner-facing next gates (ranked)

1. **Now implemented in this patch:** make worker completion trustworthy and prevent stale inference concurrency; keep owner authorization and independent worker termination proof mandatory.
2. **Next high-value build:** local Windows rehearsal adapter, bounded anonymous metrics, and event correlation. Begin with prerecorded synthetic inputs **without game-key control**; no automatic stream launch.
3. **Then:** one actual owner-approved game session with OBS, audio playout, avatar and one fast model, measuring all major P95/P99 latencies and GPU/CPU pressure.
4. **After baseline:** conduct paired A/B model, Pocket TTS, turn detector, caching and speculative-decoding trials. Keep only improvements that meet quality and safety gates.
5. **Next learning cycle:** independent teacher/study tasks between games; challenge generation, practice retention and holdout-map checks in local Star Core Forge. GitHub is an optional review/publish channel, not the authoritative learning database.

**Evidence status:** this commit's test results must be separately reported after execution; nothing in this document demonstrates a streamed game, trained model, improved voice realism, Windows deployment or actual hardware acceleration.