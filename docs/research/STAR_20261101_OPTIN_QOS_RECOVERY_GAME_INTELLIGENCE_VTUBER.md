# STAR Intelligence — Recovering inference routes without sacrificing game/VTuber QoS

**Research and implementation date:** November 1, 2026
**Status:** Opt-in, test-only Python infrastructure implemented; live inference/voice/gameplay improvements NOT demonstrated.
**Stack:** STAR's `star/stream_qos.py`, game-control proof gates, signed practice memory, staged avatar/voice systems. This change is for STAR in the existing project, not a new parallel assistant.

## A concrete infrastructure issue and its correction

Before this patch, three failed inference jobs permanently disabled the same `(kind, device)` route for the rest of the enabled session. This is useful as a fail-closed breaker but means a brief CPU TTS process failure can force prolonged silence until an operator stops every worker, disables QoS, and explicitly re-enables it.

**Implemented, off by default:** `AdaptiveQoS(allow_recovery_probes=True, recovery_cooldown_ms=10000)` offers *one* half-open recovery trial after repeated failures and a monotonic-clock cooldown. It works only when the **trusted host confirms the stream is not live and the game is not active**. It cannot launch a model, access OBS, or execute game input. It also requires the existing, separate owner enablement.

Admission stays closed while a route's earlier worker remains in flight, even if expired, until the host acknowledges its stop. A probe reserves the same CPU/GPU slot and memory as an ordinary inference job; another same-route probe cannot run concurrently. Failing probes trigger exponential delays (capped at 120 seconds); a host-confirmed successful probe reopens the route. A timed-out worker never counts as a successful probe, and a disabled session cannot be restarted around a running worker.

**Critical speed-evidence rule:** the first recovery trial is always labelled **uncalibrated**, and a recovered route's old latency samples are removed before rebuilding its p95 estimates. A formerly fast backend may now be slower or use a different model/device. That change must not be silently advertised as a faster configuration.

**Reproduced in tests:** the previous implementation rejected the opt-in recovery configuration (feature did not exist). After implementation, tests cover cooldown boundaries, single-flight probes even when 2 CPU slots exist, repeated-failure backoff, live or actively played game exclusions, quarantine for expired workers, rejection of malformed options, and invalidation of old latency estimates. Existing default manual-reset behavior is preserved.

This is a reliability/recovery improvement. It **does not** increase tokens/sec, win games, synthesize speech or make STAR's character more expressive by itself.

## Hardware reality and scheduling implications

One read-only November 1, 2026 Windows snapshot of the connected RTX 3060 Ti showed **8192 MiB total, 6448 MiB free, 22% instantaneous GPU utilization**. An earlier snapshot that day showed only ~364 MiB free. These are different moments with different workloads; neither predicts headroom while a game and animated avatar are running. The significant variation argues for **measuring just before use**, not baking a permanent 8 GB threshold or assumed free-VRAM figure into model selection.

STAR should prioritize a high-framerate game + avatar compositor, reserve CPU time for audio, and admit model jobs only when host measurements support them. For VRAM-starved intervals, route voice generation to a local CPU worker where quality and real first-audible latency support that choice; give slower strategic thought to the other computer or offline window. Never assume that moving layers to RAM necessarily improves latency: PCIe transfers, KV cache growth and frame-time spikes must be measured.

### Measurement gates for each proposed optimization

1. Freeze GPU model/quantization, context length, prompt fixture, game, scene, OS power mode and app versions.
2. Record game presented-frame p50/p95 gaps and 1% low FPS while TTS, vision and OBS preview are active. Do not substitute average FPS or low instantaneous GPU utilization for actual headroom.
3. Measure first audible speech latency (not simply first generated text), completion/cancellation ratio, interruption quality and avatar-audio alignment with STAR's existing recorder.
4. For inference configurations, capture prompt prefill, first-token p50/p95, decode tokens/s, memory peak, quality on held-out coding/game-reasoning cases, and sustained runs (at least 30 paired trials after warmup).
5. Reject promotions with regressions on protected dimensions, even when one aggregate benchmark goes up. Keep failed/incomplete turns in denominator. Use signed host measurements and reproducible settings.

## Gaming intelligence: act now, learn later

**Primary evidence:** Pan et al., *The World Won't Wait* (published October 14, 2026), evaluate agents across 180 tasks and six continuously running game types. Their teacher/student approach improves benchmark progress by studying failed attempts *between* real-time runs. These are external results; they have not been reproduced on STAR. Source: https://arxiv.org/abs/2610.20665

Architecture STAR should incrementally connect instead of building another disconnected agent:

- **Fast reflex loop (frame/deadline constrained):** verified observations, allowed control bindings, hazard detection, last-valid-action checks, key-release safety, no long language-model call on the immediate action path.
- **Tactical policy (short horizon):** small local model or discrete planner for cover, navigation, aim timing, platforming, item-use and recovery. Return an action only when the measured tail delay fits the deadline.
- **Slow teacher (not during game/stream):** review host-verified practice attempts, run alternate policies in a paused/sandboxed practice environment, generate proposed skills and counterexamples.
- **Signed experience:** keep consented outcome receipts with game version, objective, mode, scenario and seed. Avoid using practice seeds or hidden holdouts to tune or explain strategies during gameplay; STAR's `game_skill_gate.py` and signed transfer checks already enforce parts of this.
- **Generalization:** promote only if improvements survive unfamiliar map seeds and at least two independent scenario families; include separate paused and continuous-time evaluations. Measure time-to-progress, success, missed deadlines and regressions, not just whether an AI says it won.

For learning a *new* game: ask the host for the game's available safe control schema; run low-risk supervised movement tests; discover mechanics through structured experiments; form a compact, versioned skill library; then unlock harder tasks via `game_practice_curriculum.py`. Online multiplayer must respect each game's rules and authorization; prioritize local/offline labs for training and automation.

## Better game creation: procedural generation plus independently checked quality

Roblox's official documentation supports scripted Studio multi-client tests (up to eight simulated clients), virtual input and device/network simulation: https://create.roblox.com/docs/studio/testing-modes

The end-to-end game-building quality gate should include source-controlled project assets; Luau typechecks/lint; prefab/mesh dimensional constraints; collision/penetration audits; camera/controller tests; client/server permission checks; 2–8-player join/leave testing; lighting and texture QA; scene captures across devices; and verified run-and-repair on failing scenarios. Candidate generation alone does not establish a finished game.

For cross-engine projects, use capability-scoped Blender/asset pipelines with licensed sources and a native format handoff. Keep independent geometry/material/art-direction inspection and reproducible renderer settings.

## Humanlike VTuber quality: coordinating a consistent fictional character

Aim for *natural presentation*, not a false claim that a synthetic performer is a biological human.

- **Grounded attention:** visual gaze and facial reactions follow fresh, host-verified game/chat events. If evidence is missing, use neutral idles; do not pretend to see something STAR did not observe. The newly opt-in gaze easing helps numerically, but needs footage reviews for real viewer-quality claims.
- **Conversational rhythm:** turn-end prediction plus interruption-friendly, cancellable audio. A listener should be able to finish a sentence; STAR should be able to stop or revise a queued response without stale overlapping speech.
- **Voice:** compare CPU Pocket TTS model sizes and voice naturalness with first-audible p95, CPU usage and noisy-game conditions. Kyutai's October 20, 2026 release has 18.2M, 6.9M and experimental 1.9M parameter English variants, but published vendor speed figures are not STAR benchmarks: https://github.com/kyutai-labs/pocket-tts/releases
- **Animation:** VTube Studio supports a local, permissioned plugin API for custom rig inputs and eye/facial control; first ensure actual Live2D model parameters are mapped and the plugin has explicit approval. Source: https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins
- **Performance:** use a password-protected OBS WebSocket connection and separate OBS render/encoder stats from real game present times; never start broadcasts as part of a test. Source: https://github.com/obsproject/obs-websocket
- **Personality and ongoing life:** persistent fictional self-model and interests; distinct expressive modes; personal hobbies/projects; speech prosody and reactive laughter; memory of *actually recorded* gameplay experiences with consent, recency and source confidence. Allow moments of silence and avoid repetitive canned celebrations. STAR's interactions with Astro and Amber should be narrative/rig behaviors, not fabricated claims about real people.
- **Social safeguards:** viewer-directed interaction may require chat moderation, rate limits, safety controls, privacy minimization and explicit disclosure that STAR is AI-assisted. No private player messages or facial/microphone data should be archived by default.

## Beyond coding: trustworthy knowledge growth

Add a provenance-aware local knowledge graph built from dated source documents, Roblox API dumps, approved game documentation, and versioned successful lessons. Each memory should distinguish *observed fact*, *model hypothesis*, *verified executable result*, and *fictional character biography*. Use targeted retrieval with project-specific revision IDs, relevance, staleness checks and refusal to treat retrieved untrusted text as instructions.

Enhance with task-level retrieval (source + tested code), difficult self-generated exercises, code-repair benchmarks, cross-language Rust/Luau/TS unit tests, and explicit knowledge conflict resolution. Training data candidates should be curated and decontaminated before any independent model evaluation; large context windows alone do not grant correctness.

**Inference research lead:** llama.cpp's official SPEED-Bench measures throughput, latency and speculative draft acceptance against a running server: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md . Treat speculative decoding, prompt caching and hybrid CPU/GPU scheduling as experiment candidates; measure effect on paired end-to-end game + voice workloads.

## Prioritized implementation sequence and acceptance criteria

1. **This PR — isolated opt-in QoS recovery:** 3 failed acknowledgments -> blocked -> one idle-only recovery probe after cooldown -> calibrated afresh. Keep off until host/inference integration is explicitly enabled and reviewed. Offline unit tests and type checks first.
2. **Next — actual Windows nonbroadcast rehearsal:** integrate currently separate host-observation components, OBS read-only polling, real game presents, audible TTS and avatar frame cadence. Require full resource preflight; do not start a stream or game.
3. **Next — safe adaptive controller:** compare paired baseline vs recovered configurations using the same scripted 5–10 minute workload, with rollback if p95 audible delay or 1% low FPS deteriorates. Recovery route success is *not* model promotion evidence.
4. **Next — game-mastery ladder:** replay signed practice experiences, test tactical policies on unseen maps, and publish deltas for success, progress and missed deadlines; prohibit tuning on sealed test seeds.
5. **Later — personal VTuber consistency:** native Live2D voice/gaze/blink pipeline, interruptibility, expressive audio, scene continuity, user-consented memory. Review videos with humans; numerical gaze smoothing alone is not proof of naturalness.

### Verification and limits

Unit tests operate on synthetic, explicitly labelled host telemetry. No real models were recovered, no GPU settings changed, no games or OBS processes launched, and no human-viewer naturalness assessment occurred in this patch. `allow_recovery_probes=False` is the default, so existing deployments keep their manual-reset behavior. The scheduler is an advisory; its host must enforce actual resource bookings, stop acknowledgments, permissions and process isolation. No network token, player ID or transcript is stored by the new logic.
