# Star AI — trusted clock failure containment and verified generalist VTuber roadmap
**Research / implementation date:** 2026-11-09 (America/Chicago)
**Scope:** Experimental offline host-controller changes, not deployment or a claim of improved model intelligence.

## Concrete engineering result this pass

The optional RTX 4060 workload lease ledger is useful only when the trusted host keeps providing valid, monotonic time and resource measurements. There were two fail-open *error-handling* edges:

1. A malformed host timestamp (NaN, infinity, a boolean, a negative value or invalid type) raised a Python ValueError in `OptionalGpuLeaseGate.review()`. The ledger did not revoke live optional workers. A host that catches/logs that exception without independently stopping the worker might keep previously issued reservations alive until another successful review.
2. A non-ValueError exception from the stream load governor (e.g., an adapter failure) escaped `_refresh()`, likewise bypassing the advisory stop result.

Both now return a bounded, non-sensitive decision and latch revocation of *all* existing reservations. The ledger continues accounting for reserved VRAM until an independently authenticated native worker-exit witness acknowledges each receipt. Malformed request timestamps with an already running worker also latch stop. The clock exception is never interpreted as permission to continue a model step. Synthetic regressions cover six timestamp faults, simultaneous workers, adapter failure, and physical stop acknowledgment.

**Important boundary:** The Python ledger is *advisory*. This patch cannot kill Windows processes, verify user-supplied host attestations, prove that no orphan CUDA worker exists, or supersede a native watchdog. Native host must still time out and terminate optional workers independently. The existing `stream_windows_job_worker.py` / `stream_optional_gpu_launch_supervisor.py` host path uses Windows Job Objects, but this particular new gate is not yet joined to that implementation. We must avoid creating contradictory *parallel* GPU budget authorities.

## Primary technical sources, verified as of Nov 9

- Microsoft, [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects): jobs group processes; `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` can terminate the associated process tree when the last job handle closes. This is containment of owned optional workers, not a complete adversarial sandbox.
- Microsoft, [GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes): process creation timestamps enable stronger PID reuse checks when the host must inspect a specific process. Hold OS process handles to avoid race-prone PID-only stop acknowledgments.
- llama.cpp, [speculative decoding](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md) and [SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md): compare draft model, no-extra-model n-gram, and no-spec baselines; include draft acceptance, first-token and end-to-end latency, *not just* generated tokens/s. Extra draft models can lose when VRAM is tight.
- Kyutai, [Pocket TTS](https://github.com/kyutai-labs/pocket-tts): as of October 2026 also advertises 18.2M, 6.9M, and 1.9M English variants and CPU-only delivery. Useful *experiment* to reserve the GPU for game/vision and LLM; evaluate intelligibility, voice consistency, CPU contention and first-audible latency on the actual Windows CPU rather than importing a vendor's hardware claims.
- Microsoft Research, [Proact-VL (ICML 2026)](https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/): choose *when* to comment on gameplay, and control output length/quantity under continuous video and limited latency.
- Roblox, [Studio MCP and playtest automation (Mar 5, 2026)](https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643), [agentic plan-build-test (Apr 15, 2026)](https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic), and [playtest-agent beta (Apr 9, 2026)](https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767): instrument real Studio sessions and inspect data model, logs, visuals and player-agent actions.
- Gym-Anything-RT [October 2026 research](https://arxiv.org/search/?query=Gym-Anything-RT&searchtype=all): compare real-time gameplay against slowed/paused equivalents on **held-out** tasks, including strict action deadlines.

## A high-impact Star architecture, not another pile of toggles

### 1. One owner-configured native Windows execution authority

Use ONE GPU worker launch path, enforce authenticated host identity, and make every optional worker launch depend on fresh OBS/game metrics and a physically owned process-tree/job handle. Admit leases *before* process launch, start workers suspended under a Job when feasible, verify pinned files again before resume, stop on stale/reversed/malformed host telemetry, and retain VRAM claims until the original OS handle/job proves empty.

The old lease ledger and new optional gate need a typed adapter or convergence; do not combine independently favorable budget decisions. Startup sweep must ensure any previous optional workers are gone before rearming. Intentionally crash the Python controller with a disposable worker alive; a fresh process must not admit a replacement until native containment/reconciliation completes. Never terminate arbitrary system PIDs or use untrusted chat as a process command.

### 2. Smartness comes from verified outcomes rather than self-reported learning

Three timing tiers:
- **Reflex (tens of milliseconds where possible):** a bounded host/game-specific controller executes previously tested short actions; the LLM is not in a per-frame action loop.
- **Tactical (hundreds of milliseconds to seconds):** perception → state/uncertainty → goal selection → bounded action chunk → independently observed result.
- **Deliberative (seconds/minutes offline):** generate multiple candidates, simulate/playtest, compare evidence and costs, diagnose failure, select passing changes. Longer reasoning must never block the reflex lane.

Add an evidence-bearing skill card for each game: engine/build version, state prerequisites, valid action scope, permitted controller interface, expected and actual observations, independent score and replay hash. Deduplicate seeds and initial-state hashes; separate practice from hidden evaluation; require paired improvement on multiple levels and keep an unchanged baseline. Avoid games with anti-cheat prohibitions on bots; train first in user-owned offline/synthetic environments.

### 3. Better Roblox creation

Study the Studio data model *before* editing. Then make small Luau/UI/asset changes in isolated branches, run luau-analyze/StyLua/selene when appropriate, exercise Studio playtest agent via allowed MCP scopes, inspect screenshots, collisions, rig alignment, replication and frame times, repair and rerun. Keep a generated project's source hashes, playtest logs and visual evidence. Do not claim visual polish from an unexecuted code sample. Export verified changes to GitHub only after local Forge tests and owner-review gates.

### 4. Human-like VTuber presence while staying honest about being AI

Maintain a persistent but audited identity/persona: characteristic humor, favorites that come from actual observed game experiences, self-correction and a distinct speaking style. Track on-air memories separately from sensitive private memory. Use a proactive *silence* policy to avoid filler, listen while speaking, yield on interruption, and set a latency bound for each speech cue. Animate eyes, blinking, mouth phonemes, gaze, posture and hair via lightweight deterministic rig controls, not a GPU-heavy per-frame generative video model. Acknowledge uncertainty; never fabricate wins, friendships or personal lived experience. Publicly identify Star as an AI persona.

Live conversation must use stable prompts for caching and isolate untrusted viewer/game text in non-privileged messages. TTS must support physical stop acknowledgment, not only a Python request to cancel. Moderation, child safety, account/spend controls and broadcast permissions remain owner policies.

### 5. Keep Star fast on the actual 8 GB RTX 4060

Benchmark one GPU-resident model against an alternate smaller fast model plus episodic expert calls. Test context windows (4K/8K/16K/32K), KV quantization, explicit prompt caching, batching and speculative decoding. Treat 8 GB as *shared* with games and OBS. VRAM peaks matter more than nominal quantized weight size; game + OBS must have fixed headroom, and pressure should disable optional vision/experiments first.

Use GPU for game/visual LLM only when benchmarks justify it. Try CPU Pocket TTS with a small quality-approved voice; compare against GPU TTS for p50/p95 first audible, syllable artifacts, sustained voice drift, CPU load and 1% FPS lows. Cache STT/TTS speaker states securely; avoid repeated cold starts. Run every configuration in a nonbroadcast rehearsal and save benchmark JSON with model hashes, driver versions, sample counts, measured FPS, OBS dropped frames and p95 spoken latency.

**Suggested acceptance targets (not achieved metrics):** under game+OBS load, no critical OBS render/encoder regressions vs control; p95 time to first audible below 900ms for routine short turns, prompt interruption stops physical audio reliably; optional worker crashes never cause duplicate GPU admission; private 90-minute streams show no unbounded process/memory growth; improvement over fixed-baseline games survives unseen maps/seeds.

## Engineering priority queue

1. **Immediately (this PR):** fail-closed lease decisions for malformed trusted timestamps and exploding resource observers; offline tests, owner OFF by default.
2. **Next:** integrate native Windows Job Object containment and one GPU budget authority with actual host startup sweep; test worker orphan and PID reuse on Brain 2. Wire OBS/disconnection and VRAM telemetry into the same authority.
3. **Then:** run 8 GB gaming+OBS+voice+local LLM ablation, including CPU TTS and n-gram speculative decoding. Publish hardware benchmark evidence before changing defaults.
4. **Then:** enable a private authorized mini-game practice loop with held-out evaluation and replayable failures, while the streamed conversational tier stays responsive.
5. **Finally:** join tested game skills, Roblox Studio agent, persistent persona, live avatar/voice and stream safety into one bounded conductor. No autonomous public stream or external spending without owner's previously set policy.

### Integrity and limits

No live stream, external chat, game automation or model inference is triggered by this document or patch. This work does not claim faster token generation, superior game win rates, an OS-level containment fix, production merge, or human consciousness. Real progress is the measured elimination of two fail-open advisory paths, coupled with a reproducible path to test the larger goals.
