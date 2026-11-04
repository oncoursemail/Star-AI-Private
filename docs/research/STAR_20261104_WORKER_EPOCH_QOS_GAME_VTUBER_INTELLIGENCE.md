# STAR Intelligence: worker-epoch isolation, game-stream inference and humanlike VTuber research

**Date:** 2026-11-04. **Scope:** incremental improvement for the private nonbroadcast gaming/streaming rehearsal. **Status:** implemented host-side worker epoch routing and offline unit tests; no real game, model, voice or OBS runtime has been exercised by this patch.

## Why this matters

Earlier Star PRs #959–#965 measured GPU memory, separated game-only from game+stream latency, bound QoS estimates to exact model/runtime/voice artifacts, then verified files at a trusted host preflight. The remaining failure mode: **the same model build can restart or move to another PID while its previous warm-worker latency history persists in the running AdaptiveQoS scheduler**. The model digest has not changed, but process memory, KV cache, pending requests, warmup and memory pressure have. Reusing old p95 values on a cold or degraded process can cause a late speech reply, stalled game or inappropriate admission.

This patch adds `star/stream_host_worker_epochs.py`. A trusted host records the independently observed OS PID, creation time, observed process-runtime SHA-256 and monotonic observation time for each route. It makes a new opaque `epoch-*` routing profile for a new process, isolating its QoS training samples. A new process with the *same* PID but a different creation time receives a new epoch; old handles are fenced out. An observation must be fresh (250 ms by default), monotonic, match the known verified-runtime digest and come from owner-opted host code. Bindings inherit the trusted memory reservations and device rather than accepting estimates supplied by an LLM.

### Explicit limits and correct host use

`HostWorkerEpochRegistry` is **not** an OS attestation system. The current module does not inspect process memory, launch programs, authenticate telemetry, verify that the process loaded a specific GGUF, or enforce termination. The owner-controlled launcher must:

1. Load an owner-managed manifest, run `verify_host_artifacts`, and launch the **same checked runtime and weights** with appropriate OS isolation. A digest checked *before* process start is not by itself proof of continuity.
2. Obtain PID + OS creation time from an OS API independent of LLM output or viewer requests. Independently verify the running executable image and worker model/configuration; securely bind those to the route. Avoid trusting a friendly process name, command line alone, user-supplied SHA or model self-report.
3. Call `observe(alias, witness, now_ms, owner_approved=True)` only after a current trusted process observation; immediately before dispatch call `bind(job, epoch=epoch, now_ms=...)`. Never allow the model to call these host methods.
4. Pass the returned `InferenceJob` to existing AdaptiveQoS / StreamBrainGovernor, retaining **all** gaming, OBS, speech and privacy checks. Treat QoS admission as advisory until the host enforces the reservation.
5. On worker death, restart or unexpected process identity change, cancel pending work, call `retire(epoch=old)`, terminate/acknowledge actual worker resources and start a fresh epoch. Keep historical metrics for offline analysis but never borrow the old epoch's realtime p95.
6. For an actual Windows deployment, implement real worker-executable and loaded-model process verification. Windows path equality or SHA read from a mutable disk path is not strong runtime attestation. **Keep this feature opt-in until that bridge exists.**

There is **no** automatic broadcast, game input, unrestricted file access, microphone capture, self-modification or worker launch. Human authorization is still required for high-impact outside-world actions.

## Technical checks performed

- Host-only, immutable worker observation with bounded PID, OS process birth, monotonic time and lowercase SHA-256.
- Nonce-separated per-worker QoS profiles, including processes using the same model, voice and runtime configuration.
- Reject a stale/future process observation, repeated observation, backwards monotonic clock and stale inference binding.
- Bind same host-declared CPU/GPU reservations, ensure model type matches job and prevent request profile injection.
- Replace the epoch if OS PID or process birth changes; stale retirement cannot close its replacement.
- Per-route worker cap and lifecycle retirement; no unbounded queue, network, file or GPU activity.

These protections help prevent **false claims of deadline safety**. They are not faster neural inference or more intelligent neural weights. A real paired host benchmark is needed to measure success.

## Research and next high-impact performance experiments

**1. Quality-adjusted speed, not just tok/s.** The official llama.cpp SPEED-Bench client can compare per-category latency, throughput and speculative draft acceptance against an already-running server. On the RTX 3060 Ti 8 GiB machine, benchmark at 1 live speaking / 1 gaming scene before raising `--np` (parallel slots). Run idle, game-only and private OBS+avatar+TTS regimes separately. Record p50/p95 *completed audible reply* and p95 game frame time; stop if GPU memory headroom falls below the user-configured reserve. Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md . Do not run multiple model variants concurrently on an 8 GiB GPU for a misleading throughput win.

**2. Inference optimizations to A/B, all opt-in:** cache-stable prompts per session, token streaming, early retrieval, n-gram speculative decoding before adding a second GPU-resident draft model, short context for reflex actions and deep planning between matches. Compare exact output quality and task success; speculative decoding can lose speed when draft acceptance is low. Source: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md . Confirm current tool/build flags before use.

**3. Natural AI VTuber conversation:** an interesting streamer does not talk constantly. Use game-event salience, "should I speak?" decisions, viewer turn-taking, interruption handling, appropriate pauses, actual audible PCM for mouth motion, authentic context-grounded laughter, recurring interests and permission-respecting long-term episodic memory. Proact-VL (accepted ICML 2026, code announced 2026-03-16) evaluates when a companion should comment or remain quiet: https://github.com/microsoft/AnthropomorphicIntelligence/blob/main/Proact-VL/README.md and https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/ . Do not invent feelings, fictional gameplay successes or human identity. Present Star as a clearly disclosed AI performer.

**4. Voice placement experiments:** Kyutai Pocket TTS (October 20 v4.0.0 / October 21 v4.0.1, 2026) offers small CPU-oriented English model options (18.2M/6.9M/1.9M). A CPU voice worker may free GPU memory for game+OBS rendering; benchmark pronunciation, intelligibility, prosody, streaming first-audible latency, audio artifacts and CPU contention. v4.0.1 fixes a reported small-model pronunciation issue. Source: https://github.com/kyutai-labs/pocket-tts/releases and https://github.com/kyutai-labs/pocket-tts . Do not install multi-GiB GPU dependencies unnecessarily.

**5. Game mastery with ground truth:** split reflex skill, tactical planning and offline learning; measure independently verified completion, action delay, mistake recovery, transfer to unseen seeds/maps, and robust behavior when the game continues moving. Use Star's existing signed GameplaySkillBank, holdout checks and real-delay game benchmark as evidence, not fabricated victory text. Protect training/validation separation and use increasingly difficult practice levels. Do not use private competitive games in ways that violate rules or unfairly automate online multiplayer.

**6. Star as a game creator:** Roblox Studio's built-in MCP server (announced 2026-03-05) and studio playtest automation can inspect projects, test input and validate fixes; `StudioTestService` can automate server/multiclient tests. Use an isolated place, snapshot backups and independent test scoring before promoting generated Luau. Sources: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 and https://robloxapi.github.io/ref/class/StudioTestService.html . Follow current engine API constraints.

**7. General knowledge & stronger reasoning:** build retrieval with provenance, versioned source URLs, aging/contradiction checks, uncertainty calibration and independently graded QA. For difficult coding/game-building requests, fan out a small number of candidate solutions, use executable Luau tests + visual inspections, select only passing candidates, log causes of failures without leaking private secrets, and retrain/adjust only after holdout evaluation. Track verified solved tasks per watt-hour and per minute, not number of generated tokens.

## Acceptance tests for subsequent private Windows rehearsal

- Verified executable and loaded model/voice worker identity in the host, plus PID/creation-time continuity; all PIDs and process paths remain out of public reports.
- Running real game, local OBS recording **without broadcast**, avatar renderer and CPU/GPU TTS through the same 5–10 minute rehearsal.
- Measure screenshot-to-action latency, true game progress, game p95 frame time, OBS dropped/skipped frames, first audible PCM and actual mic interruption stop latency.
- Restart the speech worker in the middle of that load: the old epoch must be rejected, fresh uncalibrated worker cannot borrow old p95, and Star either speaks within independently measured deadline or deliberately remains silent.
- Test owner speech, other viewers, silence, false VAD and unexpected game hazards. Reviewer must hear recorded results, not just trust traces.
- Roll back any candidate that increases late/unverified statements, lost gameplay, unwanted overlap, broken Roblox projects or sustained GPU pressure.
- Keep all new capabilities disabled by default, honor reduced motion and disclose Star's AI identity when streaming.

**Proof boundary:** only the code+offline test gates above are implemented in this change; all claimed game, voice, intelligence and hardware performance results remain pending actual host experiments.
