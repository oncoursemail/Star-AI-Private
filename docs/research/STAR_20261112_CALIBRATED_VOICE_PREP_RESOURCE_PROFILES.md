# STAR research: calibrated resource envelopes for live voice preparation

**Date:** 2026-11-12  
**Status:** research + offline profile/bridge implementation  
**Branch:** `feat/voice-prep-calibrated-resource-profile-20261112-run11`  
**Parent:** draft PR #1161

## Executive finding

PR #1161 adds a `VOICE_PREP` admission lane and connects stable-prefix thinking to STAR's existing multi-resource scheduler. Its remaining operational weakness is that the bridge accepts a caller-supplied static `ResourceVector`. That vector is only an allocation estimate; it is not tied to the exact model/backend configuration, it has no expiry, and the code cannot distinguish a measured budget from an old hand-written guess.

This change adds a configuration-bound `ThinkResourceProfile`. The bridge can now be configured to require a fresh profile and will fail closed when the profile is stale or belongs to a different inference configuration. Existing static-resource construction remains available for compatibility and offline tests.

## Implemented

### `star/voice/think_resource_profile.py`

- Builds a profile from 8–4096 bounded, host-calibrated `ResourceVector` allocation samples.
- Requires an explicit `trusted_host=True` assertion from the host adapter.
- Computes the per-dimension maximum across samples, then adds a configurable integer safety margin (default 25%) using ceiling arithmetic.
- Stores only the resulting envelope, sample count, configuration fingerprint, calibration monotonic time, margin, and expiry. It does not retain raw samples, model paths, host IDs, transcripts, or credentials.
- Binds the envelope to a lowercase SHA-256 configuration fingerprint.
- Defaults to a 24-hour maximum age; supports a bounded expiry of 1 second through 7 days.
- Rejects future-dated, stale, mismatched, malformed, undersampled, or overflowing profiles.

The maximum observed sample plus margin is deliberately conservative. Eight samples are an engineering minimum for rejecting one-off guesses, **not** a statistical p95/p99 guarantee. A production host should collect more repetitions and use representative warm-up, steady-state, and peak-context runs.

### `star/voice/incremental_think_admission.py`

- The bridge accepts exactly one resource source: the existing static `ResourceVector` or a `ThinkResourceProfile`.
- A profile-backed bridge requires an expected configuration fingerprint.
- Every new START resolves the profile at the current monotonic time. A stale or mismatched profile rejects the request; there is no static fallback.
- The binding stores the exact resource envelope used for enqueue, so the scheduler lease must match that vector.
- Before a lease is offered to the host worker, the bridge rechecks profile freshness/configuration. If it expired while queued, the lease is released before any worker is started.
- Adds one aggregate `profile_unusable` counter without exposing fingerprints, request IDs, model names, or measurements.

The `trusted_host` boolean is a contract assertion, **not** a security boundary. The Windows host still must isolate the collector, validate its source, protect process control, and produce real process-start/stop receipts. A scheduler lease remains resource accounting, not tool authorization.

## Calibration contract for the future Windows host

The host should collect incremental resource deltas for one thinker worker while the normal stream workload is already running. Measure the worker's added resource use, not total system use, otherwise the profile will double-count OBS, the game, audio, and avatar processes. `ResourceVector` fields are scheduler allocation units, not a promise that raw OS counters can be copied directly into the vector. The Windows collector must calibrate a stable mapping from physical CPU/RAM/VRAM deltas into the same units used by `ResourceBudget`.

The configuration fingerprint should be a SHA-256 of a canonical, sorted, non-secret manifest containing at least:

- model artifact digest (not a user-specific file path);
- quantization and KV-cache type;
- inference backend and exact build/version;
- context-length bucket and batch/parallel-slot settings;
- GPU offload/layer split and device identity class;
- draft/speculative method and draft-model digest, if enabled;
- multimodal projector/encoder digest, if the thinker uses one.

Do not include API keys, access tokens, raw filesystem paths, user prompts, transcripts, or viewer information. Any material configuration change must create a different fingerprint and force recalibration.

Recommended sampling procedure:

1. Start the private OBS + VTube Studio + game rehearsal in its normal configuration.
2. Record a stable baseline with no speculative thinker.
3. Run the exact thinker configuration through warm-up and steady-state requests.
4. Collect at least 8 independent per-worker peak-delta samples; prefer 30–50 repetitions across short and long prefixes.
5. Capture CPU utilization, incremental resident RAM, and incremental VRAM with the same monotonic sampling window, then convert those measurements through the host's calibrated mapping into `ResourceVector` allocation units.
6. Build the profile from the maximum observed value in each dimension plus a safety margin.
7. Recalibrate after model, quantization, backend, context, offload, batch, driver, or major host changes.
8. Expire the profile rather than silently carrying it forward.

The profile is a scheduling envelope, not a hard guarantee against sudden external load. Fresh host health telemetry and the scheduler's real-time reserve remain independently required.

## Research implications

### Local inference optimization

Upstream `llama.cpp` now documents several speculative-decoding families: standalone draft models, EAGLE-3, DFlash, DSpark, MTP heads, n-gram cache, and n-gram map variants (including `ngram-mod`). The server can combine some draftless methods. These approaches trade proposal cost, acceptance rate, memory, and target-model verification work; none is a universal speed switch.

For STAR, create a matched experiment matrix rather than copying a command line from another GPU:
- baseline with speculation disabled;
- low-overhead n-gram method for repetitive code/reasoning patterns;
- small draft model only when its VRAM/RAM cost fits the calibrated profile;
- EAGLE-3/MTP/DFlash/DSpark only when compatible weights/builds exist and the target backend supports them;
- measure accepted draft tokens, proposal/verification overhead, TTFT, time-per-output-token, first-audible latency, quality, and concurrent game/stream health.

Keep model/backend/configuration fingerprints separate: enabling a draft model, changing the speculative method, or changing KV-cache/context settings invalidates the old resource profile. Do not enable a method globally based on isolated tokens/second.

Source: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

### Performance telemetry

Use standard dimensions where available: operation duration, server request duration, time-to-first-token, time-per-output-token, token usage, agent inference calls, tool-call counts, and workflow duration. Keep labels low-cardinality and exclude prompts, transcripts, user IDs, tool arguments, secrets, and raw model paths.

Source: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md

### Natural streaming is a separate evaluation target

MP-Bench evaluates group conversation comprehension, turn-taking, appropriateness, and latency. Its benchmark page reports that the evaluated real-time agents were at or below 22% on multiparty comprehension and near chance on multiparty turn-taking. This motivates a STAR-specific test set for viewer-to-viewer conversation, direct address, backchannels, yielding, and intentional silence; the benchmark result is not a STAR measurement.

Source: https://www.fullduplex.ai/benchmarks/mp-bench

Full-Duplex-Bench v3 evaluates spoken requests with disfluencies and chained tool use, scoring task accuracy, latency, and turn-taking. STAR should separately score semantic correctness and conversational timing rather than collapsing both into one quality number.

Source: https://www.full-duplex.ai/benchmarks/fdb-v3

### Gaming and creation

OpenGameEval runs agents in reproducible Roblox Studio sessions and checks both edited scenes and simulated play. STAR Creator should inspect relevant objects before editing and verify the result in an actual play session.

Source: https://github.com/Roblox/open-game-eval

GameDevBench evaluates multimodal Godot game-development tasks spanning gameplay logic, UI, 2D/3D graphics, and animation. It supports using screenshots/runtime video as feedback alongside executable tests.

Source: https://github.com/waynchi/gamedevbench

Voyager's Minecraft agent illustrates the value of an executable skill library, automatic curriculum, environment feedback, and self-verification. STAR Gamer should store versioned, testable skills and validate transfer on held-out maps/games rather than treating a successful demonstration as mastery.

Source: https://arxiv.org/abs/2305.16291

### Avatar integration

VTube Studio supports custom parameters and plugin-fed parameter values. STAR should keep its avatar transport isolated from the audio callback, use playback-clock evidence for lip sync, and never let an animation backlog delay voice or gameplay.

Source: https://github.com/DenchiSoft/VTubeStudio

## Required acceptance tests

### Offline

- Reject malformed fingerprints and invalid clocks.
- Require at least eight bounded samples.
- Reject non-ResourceVector samples and untrusted construction.
- Use per-dimension maxima plus exact ceiling margin.
- Reject arithmetic overflow rather than clipping a resource request.
- Reject stale, future-dated, or mismatched profiles.
- Never fall back to a static vector when a configured profile is unusable.
- Preserve the exact resource vector from enqueue through scheduler lease.
- Recheck profile validity before host launch; release an unstarted lease if the profile expired while queued.
- Keep profile diagnostics aggregate-only.

### Windows private rehearsal (not performed)

Run matched trials with thinker disabled/enabled and with OBS, VTube Studio, audio, and a game active. Measure:

- first-audible-response p50/p95;
- model TTFT and time-per-output-token;
- CPU/RAM/VRAM incremental peaks;
- game frame-time p95 and FPS p10;
- OBS render/output skipped-frame deltas;
- audio underruns and playback backlog;
- thinker cancellation-to-stop latency;
- stale/mismatched profile rejection count;
- task correctness and conversational interruption quality.

A configuration is acceptable only if it improves the user-visible response or task outcome without regressing real-time audio, game smoothness, avatar timing, OBS output, or answer quality.

## Limitations

- This PR adds a pure calibration/profile policy and bridge integration only.
- It does not collect Windows hardware telemetry, start a model process, connect to llama.cpp, OBS, VTube Studio, TTS, a microphone, or a game.
- No resource profile has been measured on the owner's machine.
- No measured speedup, intelligence gain, human-equivalent behavior, game mastery, or production readiness is claimed.
- Existing static `ResourceVector` construction remains for compatibility; production host integration should opt into the profile path after a trusted collector exists.
- Production `main`, model weights, inference defaults, permissions, broadcast settings, and release artifacts are unchanged.

## Unified capability roadmap: streaming, gaming, creation, and knowledge

The resource profile is only one reliability layer. STAR should use the same central scheduler to protect a foreground loop while separate, cancellable subsystems handle strategic and long-running work.

### Social/VTuber brain

Use a multiparty conversation state rather than a single-speaker chat loop. Track only transient turn context needed to decide whether STAR is being addressed, whether viewers are speaking to each other, whether a backchannel should be ignored, and whether she should yield or remain silent. MP-Bench is a useful external reference because it evaluates multiparty comprehension and turn-taking separately; STAR needs a private, consented rehearsal set with direct-address, viewer-to-viewer, overlapping speech, backchannels, jokes, topic changes, and intentional-silence cases.

A natural avatar should combine:
- speech playback position, not text-generation completion, for mouth motion;
- listening state and gaze/pose transitions while viewers speak;
- a small set of consistent persona expressions with bounded transitions;
- interruption barriers that cancel stale motion and reconcile the portion of speech actually played;
- deliberate silence and a cooldown against repeated reactions to the same event.

Human-like timing and expressive continuity are engineering goals, not evidence of human consciousness. STAR should not invent memories, emotions, or viewer relationships that are not supported by actual interaction state.

### Gamer brain

Follow the separation demonstrated by SIMA 2 and Voyager:
- **reactive controller:** low-latency movement, camera, aiming, and immediate actions;
- **strategic planner:** objectives, maps, inventory, opponent hypotheses, and route planning;
- **learning loop:** practice curriculum, error classification, skill library, replay, and held-out transfer tests.

SIMA 2 shows language-guided, goal-directed action in diverse 3D environments, and its authors describe self-improvement through self-directed play. The authors also identify limitations in long-horizon tasks, short interaction memory, precise low-level control, and visual understanding. STAR should therefore preserve task checkpoints and test skills on unseen maps/games instead of treating one successful run as mastery.

Sources:
- https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- https://arxiv.org/abs/2305.16291

### Creator brain

The creator loop should inspect before editing, execute inside the actual engine, capture visual evidence, run gameplay checks, repair, and repeat. OpenGameEval is a Roblox-native reference for reproducible stateful Studio tasks and executable checks. GameDevBench provides multimodal Godot tasks across gameplay, UI, 2D/3D graphics, and animation. Keep separate scorecards for script correctness, scene correctness, playability, progression, save/load, multiplayer behavior, performance, and visual quality.

Sources:
- https://github.com/Roblox/open-game-eval
- https://github.com/waynchi/gamedevbench

### Knowledge and memory brain

Separate:
- **working memory:** the active conversation, current game objective, and immediate plan;
- **episodic memory:** what actually happened in a session, with time and source;
- **semantic memory:** verified facts and concepts with provenance and freshness;
- **procedural memory:** tested skills and repeatable workflows.

Mem2ActBench is important because it tests whether an agent applies long-term memory to future tool choices and parameters, not merely whether it can answer a direct recall question. Its paper describes 2,029 synthesized sessions and 400 tool-use tasks; the authors' human evaluation found 91.3% of tasks strongly memory-dependent. STAR should measure memory-to-action success, stale-memory mistakes, contradiction handling, and whether retrieved information actually improves the task.

Knowledge writes should preserve source, timestamp, confidence, scope, and expiry/refresh policy. For current facts, retrieve fresh sources; for durable facts, use reviewed reference material. Never silently convert a guess about a viewer into a stored fact. Keep public-stream context ephemeral unless retention is necessary and explicitly permitted.

Source: https://arxiv.org/abs/2601.19935

### Self-improvement gate

Use an offline-first experiment loop:
1. propose one measurable change;
2. freeze a baseline and a held-out evaluation set;
3. run the candidate in an isolated workspace;
4. compare correctness, latency, resource use, and safety regressions;
5. retain the experiment record and artifacts;
6. promote only after tests and owner-controlled policy gates pass;
7. keep a one-step rollback path.

Do not let a benchmark score, model self-report, or synthetic result alone promote a new model, skill, memory, or production behavior.
