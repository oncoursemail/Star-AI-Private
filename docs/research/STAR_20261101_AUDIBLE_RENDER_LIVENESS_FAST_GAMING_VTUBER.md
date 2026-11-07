# STAR AI: audible-first avatar timing and verified intelligence roadmap
**Research and implementation:** 2026-11-01 (UTC)
**Status:** one render-boundary bug fix + local automated tests; the remaining proposals below are not deployed.

## 1. What actually changed

STAR already routes gameplay, natural-language responses, OBS quality observations, audible output and avatar motion through separate systems. Their boundaries matter: generated text is **not** heard speech; an animation frame issued earlier is **not** permission to render it later. The host must check the physical output-device cursor at the final frame-write boundary.

In `star/stream_playout_clock.py`, `sample()` rejected a stale or stalled audio cursor, but `current()` only rechecked age of the recently issued animation frame. A host could receive a frame just before the audio freshness deadline, delay the actual rig write, then have `current()` approve mouth motion after the audio device had ceased to provide fresh evidence.

Reproduction using a fake monotonic host clock:
- At 100.00 s, the trusted output device provides a playout cursor.
- At 100.14 s, `sample()` issues a frame; the 0.16 s cursor-age limit has not expired.
- At 100.17 s, `current()` previously returned true: the frame is only 30 ms old, **but the physical audio cursor is 170 ms old**. Expected: false.
- With a fresh but non-advancing cursor re-sampled at 100.18 s, `sample()` can legitimately issue a frame at 100.19 s. At 100.22 s, the frame is young, but actual audio progress stopped 220 ms earlier, exceeding the 0.20 s stall threshold. Previously accepted; expected rejection.

The fix shares a pure lock-protected `_cursor_live(now)` policy between `sample()` and `current()`. Late dispatch revokes the outstanding frame and records a stale event. This is **an authorization/reliability fix**, not a new speech engine or a measured increase in render FPS. The physically authorized host must still neutralize the rig when no current frame is returned. A loss of audio progress is deliberately not papered over by an artificial blink or predicted phoneme.

Three new offline tests cover a cursor expiring after sampling, a cursor that is fresh but whose position is stalled, and normal progressive speech that should remain authorized. The first two tests failed against the original implementation and passed after the fix.

## 2. Why this matters for lifelike streaming

A streamer avatar feels most artificial when the eyes and mouth communicate a different state than the voice. STAR's animation should derive speaking movement from **heard** TTS, not from finished LLM tokens, queued TTS samples or unverified third-party audio. Idle listening and game-focused motion should be visibly distinct from speaking. Intentional silence during hard gameplay is often more natural than narrating every event.

Proposed host pipeline:

```text
authorized game frames + game outcome receipts + moderated chat
           |                     |
     low-cost salience       signed practice facts
           |                     |
  gameplay / viewer dialogue director -> text-to-speech / interruption host
           |                                   |
      speech intent                   actual PCM output device
           |                                   |
      stage speech plan <---- measured playhead position + monotonic timestamp
           |                                   |
      avatar frame sample -> final render-boundary current() -> VTube rig
                             else neutral pose + stop stale lip motion
```

Do **not** let untrusted chat messages set `playing`, `sampled_at` or `position_s`; those are trusted audio-host assertions. An overlay/game event can suggest a reason for a reaction but never certify audible speech. Speech interruption must also mute the output device and revoke queued frames; Python planning alone cannot enforce physical silence.

VTube Studio's documented local plugin API can inject custom Live2D tracking values after explicit authorization, but the application must rate-limit writes and treat a disconnected avatar client as a fail-to-neutral path. See https://github.com/DenchiSoft/VTubeStudio . No VTube Studio integration was installed by this change.

## 3. High-value next intelligence improvements, sorted by evidence required

### A. Full real-time host integration (highest immediate value)
- Build one **Windows host-owned monotonic timeline** with independent observations from the game, OBS, speaker output device, and avatar renderer. Do not compare Linux GPU telemetry to Windows wall-time timestamps as though they shared a clock.
- Attach stage sequence/epoch identifiers to every PCM lease and rig write; a restarted TTS stream or model cannot reuse a prior render lease.
- Treat any missing/malformed cursor as no permission to move the speaking rig. Trigger a neutral pose on the host after a short, bounded grace interval, without substituting unverified "mouth probably moving" prediction.
- Profile p50/p95/p99 end-to-end reaction delay **including** capture, event routing, first audible PCM, actual first speaker sample, first synchronized rig frame, and OBS-visible output. High token/sec alone will not measure this.
- Preserve FPS, 1% lows, dropped/late OBS frames and VRAM headroom during the benchmark. Never launch a heavy inference microbenchmark on an active stream by default.
- Record only aggregate performance and synthetic test identifiers in public CI; no private gameplay, speech, viewer IDs or credentials.

**Acceptance:** a deliberately stalled output device cannot authorize any new mouth motion past the configured stall deadline, even if a previously issued frame is <150 ms old; normal progressive speech still produces valid frames; interruption physically stops sound and makes subsequent stale frames invalid.

### B. Three-timescale gaming brain with independent skill verification
1. **Fast safety loop:** host-proven game state, deadline-aware keyboard/gamepad action gating; no big-model call in a 16.7 ms render budget. Explicit neutral input when perception is stale or control is revoked.
2. **Tactical loop:** small/local model or deterministic game-specific policy (e.g., aiming, platform jump timing, team coordination); adapt based on observed mechanics, not external hallucinations.
3. **Offline teacher:** analyze recorded, consented replay features and signed outcome receipts after a match; propose hypotheses and training drills. Keep outcome validation and hidden maps held out from the teacher.

A skill is not acquired merely because STAR can explain the rules of a game. Track held-out win rate, deaths per run, reaction latency, objective completion, resource usage and performance across fresh seeds/opponents. Use paired baselines and reserve novel challenge types to detect memorization. STAR may invent harder practice tasks, but the evaluator must be independent of the generator and must guard against success-metric gaming. Maintain a bounded replay/history store so abandoned sessions cannot exhaust pending-task capacity.

### C. Fast local reasoning that does not steal the GPU from OBS
- **Admission policy:** game rendering, OBS encoding and physical speech playout are protected. Background long-context RAG, model distillation, nightly self-play and teacher inference are preemptible and OFF during constrained live sessions.
- **Latency routing:** deterministic function / cached fact / compact local model / larger teacher, selected by deadline and uncertainty; never route all replies to the biggest model.
- **Inference experiments:** compare llama.cpp cached prompts, batching, quantified speculative acceptance, quantization and CPU/GPU expert placement. Benchmark with `SPEED-Bench` while reproducing real FPS and audio workloads. `--np`, server batching or speculative decoding may worsen tail latency under VRAM pressure; choose only a candidate that wins on measured end-to-end performance.
- **Rust selectively:** move profiled bottlenecks such as audio/capture buffer copies, hot-loop telemetry aggregation or packet decoding only if a Rust prototype beats the existing Python host without adding scheduling jitter or fragile FFI. A whole-backend rewrite is not evidence of increased intelligence.
- **8 GB VRAM constraint:** maintain configurable model residency and CPU-only speech fallback. Model selection must fail closed if estimated memory pressure threatens OBS or Windows stability.

Primary source: llama.cpp SPEED-Bench official benchmark instructions, https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md . These evaluate throughput, latency and draft acceptance; they cannot by themselves establish real stream quality.

### D. Humanlike presence grounded in reality, not pretending to be human
- **Listening:** distinguish acknowledged owner interruptions, conversational end-of-turn, background noise and streamer backchannels. Do not cut off speech for every noise; do not ignore a valid interruption. Evaluate late stops separately from late starts.
- **Speech:** stream text chunks into local TTS, attach expression intent only to actually played audio, preserve a silent state, and revoke on barge-in. VoiceChat-TTS (August 13, 2026) explores streamable speech and mid-utterance interruption without clearing the KV cache: https://arxiv.org/abs/2608.13831 . Study its architecture/availability rather than assume it runs optimally on an 8 GB consumer GPU.
- **Avatar:** subtle eye shifts while listening, blinks, quiet breath-like body motion, accurate lips when speaking, deliberate focus on gameplay during action, small emotion cues after verified wins or failures. Respect reduced-motion settings.
- **Memory:** persist useful self-authored goals, creative preferences, genuine game experiences and consented audience interaction summaries; never fabricate a personal past, viewer relationship or unobserved game accomplishment. Retain source/provenance and uncertainty. Provide a local "why STAR said that" trace for owner review.
- **Persona:** Star, Astro and Amber can participate as distinct named characters with separate speech/rig leases; a companion's voice must not animate Star's mouth. Neither companion should gain independent access to chat, control or memory by sharing a scene.
- **Evaluation:** the September 9, 2026 Realtime-Venus report explores full-duplex continuation and interruption, but its published benchmark results are model-specific and are not measured results for STAR: https://realtime-venus.github.io/ . Construct opt-in recorded test conversations with interrupt, overlap, background voices, quiet gameplay and viewer question fairness.

### E. General knowledge, creative game-building and self-improvement
- Make retrieval **source-verifiable**: documentation/API version, licensing, code signatures, runnable example and a separate independent check. Keep unfamiliar software facts behind a request-time web toggle, OFF by default.
- Build a "read -> plan -> construct -> inspect -> playtest -> revise -> compare" loop for Roblox, Blender and web UI. Verify object transforms, mesh/wall joins, collision, texture stretch, animation blending, accessibility and multiplayer correctness. Prefer real viewport/frame evidence over model confidence.
- Roblox's StudioTestService supports programmatic multiplayer tests (up to eight simulated clients per session, per documented constraints). Source: https://robloxapi.github.io/ref/class/StudioTestService.html . Isolate Studio test instances; never run an unbounded simulation against a user's live place.
- Let Star Core Forge perform local speculative branches, fast tests, image/video validation, paired quality gates and rollback. GitHub remains an optional outward publishing/review destination, not a prerequisite for local self-improvement.
- Maintain a compact, searchable general-knowledge graph with evidence timestamps and conflict detection. Distinguish **knowing**, **having tried**, and **having proved** a technique; self-assessed confidence must not grant new capabilities or access.

## 4. Experiment matrix: demonstrate changes, do not announce hypothetical speedups

| Lane | Baseline | Candidate | Independent success criterion |
| --- | --- | --- | --- |
| Avatar output liveness | prior `current()` behavior | shared cursor checks | no stale render lease at physical cursor/stall deadline; existing progressive audio accepted |
| End-to-end speech | current model + TTS + OBS | cached prompt, CPU TTS, or speculative decode | improved paired p95/p99 audible time with no worse OBS drop / frame-time spikes |
| Gameplay learning | fixed policy, fixed seed | gated self-play + offline teacher | improved held-out performance with new seeds/maps, verified outcomes and no human oracle leakage |
| Game creation | current Star pipeline | viewport inspect + executable multiplayer tests + visual critic | higher independently reviewed pass rate, no collision/geometry regressions |
| Natural conversation | current turn-handling | stateful interruption + grounded expressive TTS | fewer false cutoffs, missed owner interrupts, hallucinated claims; no meaningful latency regression |
| General knowledge | current retrieval | provenance/contradiction/expiration gate | more correct held-out answers, demonstrably lower unsupported factual claims |

Treat each experiment as a reversible opt-in through Star Core Forge. Reject a candidate when one critical tail-latency lane deteriorates, even if its average gets better. Preserve golden evaluations that the improving agent has not seen.

## 5. Scope, hazards, and operator requirements

This change does not install models, capture a Windows speaker, control an avatar, launch OBS, play a game, train STAR, or prove a human-level persona. It fixes one concrete audio-to-avatar trust-boundary bug and provides an evidence-focused development direction. The host's real audio device remains the authority over whether speech was heard.

Only record/analyze games in which the account is authorized to use automation; no competitive cheating, anti-cheat evasion, account-sharing, or unauthorized third-party game control. Chat retention, viewer data, and recordings require consent and bounded storage. All expensive experiments are safely stoppable and subject to low-resource fallbacks.

**Next implementation checkpoint:** Windows audio callback/consumed-frame cursor -> `StarPlayoutClock.observe_playhead()` -> `sample()` -> `current()` immediately before per-rig parameter write; neutralize on false. Run the paired jitter/dropout harness, measure the actual speaker-to-avatar timing, then choose a hardware-specific TTS/inference configuration. Do not claim FPS or token/s gains before this check.
