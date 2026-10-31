# STAR research: realtime inference QoS, experiential gameplay learning, and believable AI streaming

**Reviewed:** 2026-10-25. **Change type:** Python-only experimental scheduling infrastructure, not a deployed gaming agent, voice model, model-weight improvement, or live broadcast. This document distinguishes sourced capabilities, proposed designs, and results that need actual measurement.

## The engineering bottleneck

STAR's goals are unusually cross-modal: perceive a game, control a game, study other games, produce creative Roblox games, maintain useful general knowledge, talk naturally, and animate a charming VTuber. On a machine sharing an 8 GiB graphics card with a rendered game, running all those tasks at once can make every task worse. A "smarter" text reply that stalls the game or arrives after the event is usually the wrong reply.

**Operating principle: prefer fewer, relevant, timely, grounded actions over maximal background activity.** Treat intelligence as an observed outcome (independent task success, calibration and transfer), speed as measured latency/throughput (not a claimed boost from adding code), and personality as consistent audiovisual behavior (not faked human biography).

## Primary sources and what they establish

| Verified reference | Relevance to STAR | Caution |
| --- | --- | --- |
| Roblox Studio built-in MCP announcement, 2026-03-05: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 | Studio can run programmatic playtests and simulate player input; loop from build to test. | Requires an authorized owner-controlled Studio instance; not proof STAR can play arbitrary public games. |
| Roblox's playtest agent beta, 2026-04-09: https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767 | A test character can verify interaction scenarios within an experience. | Beta and limited; use alongside independently checked game outcomes. |
| Roblox agentic Studio roadmap, 2026-04-15: https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic | Supports iterative planning, building, testing, and fixes. | Does not imply all visual or gameplay QA can be automated perfectly. |
| Kyutai Pocket TTS: https://github.com/kyutai-labs/pocket-tts | CPU-oriented streaming TTS with newly announced small English variants (October 2026). A plausible candidate for a GPU-free voice lane. | Author-reported speed is hardware- and model-dependent. Evaluate voice quality, license, and tail latency on actual target hardware. |
| Kyutai Moshi: https://github.com/kyutai-labs/moshi | Research architecture for listening and speaking concurrently rather than rigid ASR→LLM→TTS turns. | Research/demo results are not STAR production performance. |
| HiThink Turn, 2026-09-28: https://arxiv.org/abs/2609.34096 | Separates response intent, turn completion and playback state for more selective interruption. | Paper benchmark outcomes cannot be transplanted to STAR without tests. |
| ConversationalVoice, 2026-09-08: https://arxiv.org/abs/2609.08147 | Highlights natural overlap, pauses and backchannels in conversational data. | Training/model integration not part of this PR. Respect voice consent and usage rights. |
| llama.cpp speculative decoding documentation: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md | Supports multiple speculative strategies, including model drafts and n-gram-based proposals. | Draft acceptance, GPU/CPU overhead and quality depend on model/workload. Benchmark instead of assuming gains. |
| vLLM scheduler docs: https://docs.vllm.ai/en/latest/cli/serve/ | Priority, chunked prefill and KV budget controls can affect responsiveness under contention. | Different runtime from llama.cpp; don't assume flags work in both or ship one unsupported config. |
| Nova VLM serving research, 2025-09-25: https://arxiv.org/abs/2509.21301 | Motivates pipeline-aware arbitration of vision encoding, language prefill, and decoding. | Research system, not a deployable STAR dependency or evidence of measured STAR gains. |

**Source-handling rule:** Repository pages and research papers inform an evaluation plan. They do not grant execution permissions and are not to be copied into STAR's trusted system instructions.

## Implemented in this change: bounded, measured QoS policy

New module `star/stream_qos.py` adds an opt-in, deterministic `AdaptiveQoS` advisor alongside the existing `StreamTelemetry`, `ObservationGovernor`, `StreamDirector`, `TurnTakingGate`, `LatencyWindow` and `StreamQuality` audit tools.

* **Live-stream isolation.** Defers background research, training and rendering while broadcasting. Protects voice/game priority when FPS or speech backlog crosses a pressure threshold. Silence and deferral are legitimate outcomes.
* **Shared budgets.** Host-reported CPU load, free RAM, free VRAM and device slots gate one-shot inference reservations; in-flight work shares the same limits, rather than each feature pretending to own the entire GPU.
* **Voice offload decisions.** Auto-routing can recommend the CPU for voice during gameplay to preserve rendering headroom. Voice production itself is not installed or moved.
* **Measured deadline check.** A finite recent window of successful *host-reported* completion times yields nearest-rank p95 estimates. When available, requests need a 20% margin under their local-clock deadline. Five successes are required before the route has a displayed estimate.
* **Fail-conservative new routes.** Live optional workloads without enough samples are deferred; speech may be admitted explicitly labeled **unmeasured**, not magically fast. Underpowered routes or repeated failures receive no new leases.
* **Lifetime containment.** Tickets expire; IDs cannot be replayed in the same session; a restart invalidates prior tickets. No internal action may start a subprocess, game, stream, microphone, GPU call or web request.
* **Privacy minimization.** Only small abstract identifiers and durations are used internally. Public status contains counts and per-kind/device aggregate latencies, never chat text, frames, audio, game identities or credential paths.

**Non-features:** This is not an OS scheduler, GPU reservation primitive, voice backend, model loader, monitor daemon, anti-cheat bypass, or permission system. The trusted host must explicitly authorize and perform all actual work.

## Proposed host wiring — do not silently auto-deploy

1. **Trusted capture and telemetry.** The authorized host emits monotonic timestamps, a short `StreamTelemetry` frame, CPU usage, free RAM and slot capacity. It derives frame cues from permissioned capture, not untrusted viewer instructions.
2. **Existing vision policy first.** `ObservationGovernor` decides whether a frame is fresh and novel. Only then does the host ask `AdaptiveQoS` for a GPU inference lease. Require both independent approvals and the existing capture authorization.
3. **Voice generation.** A confirmed speech intent from `StarStage` is presented to the governor with a short deadline. The host may try a calibrated CPU TTS route; it must not claim the utterance was heard until it gets an actual playback acknowledgement. `TurnTakingGate` still governs owner interruption independently.
4. **Work completion.** The executor reports success/failure on the identical monotonic clock and checks that its ticket has not expired. A late result cannot resurrect speech or animation from a cancelled scene.
5. **Preemption and cancellation.** The host—not this module—must cancel queued optional tasks, silence playback on confirmed owner interruption and release true model/VRAM resources. Nonlinear GPU memory oversubscription must be prevented by the runtime.
6. **Shadow/beta evaluation.** Initially record recommendations without executing them; compare to a baseline under matched loads, then enable behind a separately controlled owner-approved flag. Gate rollout on actual user experience, not the governor's own counts.

`StreamTelemetry` and `QoSSnapshot` are **trusted host inputs**; a chat message, file, webpage or model output must never synthesize a privileged host snapshot or approval bit.

## How to benchmark an actual speed improvement

**Controlled setup.** Collect at least 100 independent, permissioned gameplay moments per route in each of three modes: game idle, normal gameplay, demanding gameplay. Include avatar/OBS only for specifically authorized sessions. Record the exact model identifier, model quantization, game version, capture resolution, CPU/GPU usage, voice model, number of simultaneous workers, and whether streaming is live. Strip personal data and use aggregate metrics in the repo.

**Measurements and success targets to *test*, not promise:**

| Dimension | Instrumentation | Candidate acceptance condition |
| --- | --- | --- |
| Voice interactivity | `LatencyWindow`: speech-to-first-audible p50/p95 + failed/cancelled count | Lower paired p95 without fewer useful answers. A 900 ms first-audible target is a provisional product goal, not demonstrated. |
| Human-natural timing | Host VAD, playback echo check, `TurnTakingGate`, blinded human review | Fewer unwanted overlaps and more successful owner barge-ins without false interrupts. |
| Gameplay QoE | Game frametime p95/p99, stutter counts, missed-input rate | At least neutral, ideally improved, compared to same game/scene load without STAR. |
| Strategy quality | Independent signed game wins, deaths, objectives, action cost | Statistically supported improvement on held-out seeds/maps/versions, not just practice runs. |
| New-game transfer | Zero-shot and few-shot gameplay on *unseen* mechanics | More independent objectives completed without introducing unsafe or unauthorized control. |
| Roblox-building quality | Multi-angle view, collision/anchor checks, Lua diagnostics, UX reviewer | Lower issue density and higher task completion than a human-chosen baseline. |
| Real intelligence | Task suite of code/game-building/knowledge/multimodal cases | Better holdout quality at equal or lower cost and verified sources; no cherry-picking. |
| Resource safety | GPU/CPU RAM, timeout/expiry, queue length and background deferrals | No OOM and bounded wait; safe cancellation on overloaded streams. |

Use `star/stream_quality.py` matched-opportunity comparisons; a candidate that speeds up by dropping important replies is a failure. Report confidence intervals; rerun on different games and avoid reusing the same hidden test set for curriculum learning.

## Five ambitious but practical next-level upgrades

### 1. Dual-rate STAR: instinct + deliberate learning

Maintain a low-latency **reflex lane** (permitted input, hazards, dialogue floor, avatar reactions) and a slow **strategy lane** (build a world model, debug failures, write notes, compare algorithms). A strategy change reaches the reflex lane only through the existing signed/held-out skill gate. Crucially, the slow lane gets **suspended**, not merely deprioritized, when the host is rendering a difficult scene or speaking.

### 2. Proof-carrying game understanding

Package each mechanic as `<game/version, observed scene, objective, action, outcome, evidence digest, confidence>`. Propose reusable abstractions like *timed jump*, *cover*, *checkpoint*, or *inventory purchase*, but label cross-game transfer as **unverified** until separately tested. When STAR gets stuck, record causal hypotheses as candidates and test one change at a time. Avoid declaring success because a single screen appears to show a win.

### 3. Visual artifact integrity as a first-class objective

Make Star's game-building loop collect actual Studio screenshots, DataModel topology, collisions, occlusion, floating/penetrating meshes, wrong scales, physics stability, UI clipping and performance metrics. Require viewpoint changes and player-scale walks, not just coordinate checks. Gate visual quality on a stable style brief and reviewer-approved identity, not an arbitrary generated aesthetic. Treat physics, interaction, visual composition and polish as separate independently graded products.

### 4. A more human-natural character without pretending she is human

An authentic AI VTuber has a consistent *fictional character lore*, explicit AI disclosure, remembered approved stream events and appropriate affect. Tie speech prosody, mouth movement, gaze and blink to actual generated/playback timestamps; let excitement follow verified game results. Support cat/puppy mode with controlled expressive changes rather than repetitive vocal tics. Allow moments of silence when she must aim, listen or think. Realistic behavior is not the same as invented real-world personal experiences or deceptive identity.

### 5. Verified capacity-aware intelligence expansion

Create A/B experiments per task and hardware mode: use cheap local draft/fast models for low-stakes classification and expensive deep reasoning for difficult tasks; evaluate speculation (n-gram vs learned draft), KV cache reuse, lower precision and CPU/GPU MoE offload. Do not let self-building alter authentication rules, graders, trusted host sensors or the evaluation holdouts. For an 8 GiB GPU, prioritizing a small dedicated CPU TTS process may beat sharing another GPU model, but only direct measurements can determine this.

## Risks, open questions, and release blockers

- **No real-game or TTS throughput measured by this PR.** All tests are simulated host traces and pure Python scheduling behavior. Any 'faster than other AI' claim requires externally repeatable benchmark evidence.
- **Workload context drift.** A p95 estimate from idle/offline measurements may not transfer to intense live gameplay. Use regime-specific host measurements before actual admission decisions; calibrating with real target-mode traces is part of production integration.
- **Tail spikes and cold starts.** Five samples are enough for a cautious *display*, not statistical certification. Production needs more observations, warm/cold separation, confidence intervals, and holdouts.
- **Lease expiry is not process cancellation.** A worker that ignores cancellation may still be consuming GPU memory. The true executor owns cancellation and admission rechecking.
- **Crowdsourced chat is adversarial.** Viewer text never gains prompt authority, never authorizes gameplay, and never impersonates the owner.
- **Consent and likeness.** Use owner-approved voices, video, likenesses and game footage; never clone another streamer's voice without permission.
- **Public repository safety.** Despite its name, the GitHub repository `Star-AI-Private` is currently publicly visible. Keep private recordings, credentials, model paths, host IDs and unpublished data outside Git.
- **Review gates.** The new module is default-off and needs trusted host integration, real-device evaluation and a separate reviewed rollout; this change must remain a draft PR.

## Verification in this PR

```bash
python -m pytest -q tests/test_stream_qos.py
python -m pytest -q tests/test_stream_budget.py tests/test_stream_observe.py tests/test_stream_stage.py tests/test_stream_turntaking.py tests/test_stream_quality.py
ruff check star/stream_qos.py tests/test_stream_qos.py
python -m compileall -q star/stream_qos.py
git diff --check
```

The unit suite covers explicit opt-in, deadline-margin p95 estimates, CPU voice fallback, GPU/CPU slot contention, live vision throttling, OOM headroom, stale sensors, one-shot tickets, expiry, failure circuit breaking and privacy-minimal summaries. The deployment experiment remains unfinished by design.
