# STAR AI — OS-witnessed GPU leases, real-time skill learning, and natural VTuber architecture
**Research / implementation date:** November 6, 2026 (America/Chicago). **Target:** Star's Windows gaming/streaming host plus separate Linux development system. **Stage:** tested, OFF-by-default infrastructure; not deployed to a real streaming session.

## Executive finding: eliminate the weakest integration boundary first

The previous draft PR #1028 introduced `RealtimeGPUWorkLeases`, an opt-in accounting ledger for optional research, vision, training and rendering workers. It correctly refuses to recycle their reserved VRAM on a mere stop request. But it still expects a *caller-supplied boolean* (`host_confirms_worker_stopped=True`) as the assertion that a process actually stopped. That flag must never become part of an LLM-visible tool API.

This branch adds `star/stream_gpu_lease_host_bridge.py`, a **host-only process-witness integration** plus deterministic fake-process regressions. It connects reservations to independently observed OS worker identity:

- The trusted host binds an **already host-launched** optional worker, pinned by its exact OS PID and creation timestamp. It checks the pinned process handle twice before acknowledging a start. An untrusted, equal-looking ticket is rejected by the underlying ledger.
- A bounded `reconcile()` tick observes actual process state, keeps healthy leases alive, and emits typed stop intents when streaming performance triggers a revocation. Stop intents are NOT termination authority; dispatch belongs to an independent, authorized Windows worker supervisor and must not block frame, audio or health monitoring.
- Sending a stop intent does not free VRAM. **Only an original pinned handle positively reporting not-running** can cause host-confirmed release. Exceptions, stale readings, changed PID/birth or a failed liveness check stay charged. Missing process evidence disables optional-work admission and requests shutdown of all bound optional workers.
- Opt-in and host-only; no NVIDIA driver changes, no public broadcasts, microphone capture, game input, process signaling, model inference, external network calls or new downloaded models. Metrics omit PID and creation timestamp.
- Existing important limitation: a caller must still **wire the bridge into the separate Windows process manager** and ensure that manager owns the launched process handles. This change does not implement an out-of-process watchdog or a genuine OBS+game rehearsal.

**Design security caveat:** the host owns `owner_approved`, `process_factory`, worker PID mapping and `host_confirms_*` calls; none should be delegated to an AI model. A process observation can race a subsequent exit. The host must re-check PID+birth before issuing any OS-level stop signal, and keep the established stop path on an independent watchdog. A failed-to-bind worker remains charged and requires local host investigation/stop proof; it must not be silently dropped.

## Priority 1 — Actually finish the on-machine streaming path

**Windows implementation sequence:**

1. Wire trusted NVIDIA/OBS telemetry into `StreamHealthSample`, with measured monotonic timestamps from the **same host clock**. Record process IDs privately inside the supervisor, not in model prompts or exported diagnostics.
2. Make the optional-worker launcher atomically reserve a GPU lease, start the specific process, then call `HostGPUWorkerLeaseBridge.bind_started` using a host-controlled process handle. Any unbound launch must go to a quarantine/stop path, not proceed as an unsupervised job.
3. Run nonblocking `reconcile()` on a separate control timer. The permitted host stop manager must verify pinned PID+creation time **at dispatch** and request graceful shutdown. An OS watchdog independently follows up, verifies cessation, and fences late output. Do not kill arbitrary Windows/game/OBS processes.
4. Run private rehearsals with game frames, host-verified input releases, TTS PCM actually played to an output device, synchronized mascot motion and local OBS recordings. Do not use public chat, public streaming or an unrestricted game host until the rehearsal gates pass.
5. Reconcile free VRAM cautiously. Current claims are double-counted conservatively even if already present in sampled used VRAM. Calibrate resident/pending GPU allocations with host measurement before seeking higher utilization.

**Acceptance criteria:** 100% of bound optional-worker exits observed and claims released; 0 releases on transient OS errors; 0 cases where a model can forge process identity; late stop confirmations do not allow extra allocations before witness verification; p95 control-loop tick < prescribed watchdog period. This release's tests are **synthetic only**, not a Windows latency benchmark.

## Priority 2 — Increase useful intelligence, not just raw tokens

Star should run a three-tier gaming architecture using *existing modules* rather than build an overlapping new brain.

| Lane | Typical budget / responsibility | Evidence of genuine gain |
| --- | --- | --- |
| Reflex | Current frame age, hazard tracking, bounded action/no-action, immediate cancellation | Real game input latency and successful outcomes under a continuously running clock |
| Tactical | Between-frame planning, opponent pattern modeling, strategy switch, exploration of mechanics | Counterbalanced wins vs baseline on unseen maps, opponents, and game versions |
| Learning | Self-generated curriculum, saved attempts, retrieval, domain-transfer rehearsal, best-of-N verified Luau builds | Held-out skill gains that survive a game/seed split; fewer regressions per verified task |

A useful next **skill pipeline** is `observe → hypothesize → select safe test → act → independently check world state → attach evidence → summarize reusable skill → evaluate on holdout`. Distinguish the model's prediction from measured success. Preserve observations of bad moves and deliberate no-actions; never train exclusively on success-filtered examples. Retain consent and origin metadata for knowledge.

For Roblox building, take advantage of [OpenGameEval](https://github.com/Roblox/open-game-eval) (stateful executable scene and play-session checks) and Roblox's [Studio MCP Open Cloud permission model](https://create.roblox.com/docs/studio/mcp-open-cloud). Implement in a private test universe with minimum scopes and explicitly gated production publishing, monetization, bans and data-store writes. The November 4, 2026 Open Cloud rollout expanded what Studio-connected agents can do; it did **not** make permission checks optional.

For general intelligence, add evidence-aware retrieval from checked primary sources, source timestamps, confidence/uncertainty calibration, multi-document synthesis, a personal episode memory with deletion/retention and access controls, and a policy to challenge previous guesses with a concrete observation. Give factual retrieval, debugging and research tasks separate holdouts. More stored text does not guarantee a smarter model.

Sources: [Roblox OpenGameEval](https://github.com/Roblox/open-game-eval); [Roblox Studio MCP guide](https://create.roblox.com/docs/studio/mcp-open-cloud); [Roblox Open Cloud announcement, November 4, 2026](https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849).

## Priority 3 — Meaningfully faster local AI under 8 GB VRAM

Benchmark a reproducible matrix, not a single synthetic tokens/second claim:

- **Models:** one small fast reflex/chat model, one stronger planner or multimodal observer, one optional CPU-oriented voice model. Select by observed skill, not vendor marketing or parameter count. Quantization and KV-cache occupancy must be recorded per workload.
- **Methods:** shared-prefix prompt caching, small retrieved evidence instead of bloated contexts, short response envelopes for gameplay, GPU admission control, parallel *offline* candidate verification, and optional llama.cpp speculative decoding. Compare draftless n-gram to draft-model approaches; a new draft model can consume scarce VRAM.
- **Voice:** evaluate [Kyutai Pocket TTS](https://github.com/kyutai-labs/pocket-tts) on CPU for a consented Star voice. Its October 2026 1.9M / 6.9M / 18.2M English models may reduce GPU pressure, but quality, pronunciation, emotion and actual Windows CPU contention require blind testing. Published demo speeds are not Star's measurements.
- **Measurements:** cold/warm p50/p95 first token, verified decoded tokens/second, generated-vs-accepted draft tokens, end-to-end `frame captured → action dispatched → host confirms result`, audible first PCM, input/audio interruptions, GPU peak resident memory, *minimum* free VRAM, OBS rendered/encoded drop percentages, stream/game FPS and CPU load.

**Promotion rule:** no regression to meaningful held-out task accuracy, no missed game-input release, no degradation to OBS/audio stability; any claimed speedup must compare matched warm-up, identical prompts, hardware, quantization, context size, and simultaneous game/TTS/OBS load. Different samples of the GPU can show radically different free-VRAM readings and should not be treated as steady-state performance.

Source: [llama.cpp speculative decoding and SPEED-Bench documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md); [Kyutai Pocket TTS](https://github.com/kyutai-labs/pocket-tts).

## Priority 4 — Convincingly natural AI VTuber (without pretending to be a biological person)

High-quality naturalness comes from **timing, grounded reaction and continuity**, not merely a larger LLM.

- A real-time **conversation director** should know when NOT to speak: tense fights, a player talking, unverified visuals, respawn/cutscenes, or a full audio queue. Proactive speech should be rare and contextual; short reactions to actual gameplay evidence, longer reflections between rounds.
- Support full duplex turn-taking only when the microphone capture, echo clearing, verified speaker/permission identity, TTS cancel, output buffer flush and avatar animation are synchronized. If the owner interrupts, clear physically buffered PCM and stale mouth-animation cues rather than just resetting a text token.
- Give Star a *consistent fictional adult personality*: recognizable humor, preferences, aspirations, friendships, signature reactions and hobbies; express disappointment and celebration naturally without claiming fabricated human experiences. Always disclose she is an AI VTuber.
- Avatar: eye attention, gaze, blink timing, head micro-motions, twin-tail and ribbon physics, reaction layering, laughter, idle breathing, mouth shapes tied to actual PCM timestamps; allow reduced motion and an offline-safe mode.
- Evaluate unscripted 10–30 minute *private* conversations and gameplay in blinded review. Score speaking overlap, false interruption rate, grounded factual claims, syllable/mouth alignment, awkward silence and repeated catchphrases. Keep abusive viewer input from acquiring tool permissions.

The ideas above align with [Microsoft Research Proact-VL, May 2026](https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/) (when to respond) and [NVIDIA DyaPlex, June 2026](https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/) (full-duplex speech+motion). These are research directions; no claim that either production model is integrated with Star.

## Priority 5 — Broader creation and long-term independence

Beyond gaming: build a bounded autonomous **design / creation / playtest / reflection** loop. Expand Blender animation and rigging, Luau and Rust development, sound effects and music generation under licensed/consented assets, gameplay tutorials, website and UI design, game-server operations, digital art and general web research. Reuse a permissioned tool registry and skill bank; measure task outcomes against objective checks and held-out user-review samples. Keep offline-first artifacts locally versioned and rollbackable; GitHub remains an optional publishing layer.

For learning to *play* unfamiliar games, initially use private supported games and simulation environments; do not bypass game protections or automate public competitive play against service terms. A useful curriculum progresses from walking and camera control, through navigation and timing, to multi-step goals, cooperation, and unseen game variants. Record game-state hashes, timestamps and outcome receipts rather than storing unbounded screenshots.

### Milestones and honest boundaries

**Implemented in this branch:** a testable host-only OS process binding/stop-witness bridge and its deterministic regression tests. It is designed to avoid false GPU lease release and to expose stop work without blocking AI/gameplay health ticks.

**Not implemented or independently demonstrated:** automatic Windows process stop with verified PID identity, actual GPU allocator control, measured inference improvements, autonomous game winning on held-out games, an integrated all-lanes OBS rehearsal, live AI VTuber naturalness, or a new foundation model. Those must be measured, not inferred from passing offline unit tests.

**Repository acceptance sequence:** run the new tests plus existing admission/lease and rehearsal tests; run Ruff, Pyright, compile checks; publish a **draft PR stacked on #1028**, leave main untouched, review GitHub CI before merging. No large model downloads while the Linux root volume remains near 95% full.
