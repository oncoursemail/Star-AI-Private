# STAR AI — cooperative live-clock gaming, OBS protection, learning and VTuber systems

**Research cut-off:** 2026-11-01 UTC. **Status:** committed experimental, owner opt-in, not deployed.
**Development PR:** [#845](https://github.com/oncoursemail/Star-AI-Project/pull/845).
**Scope:** CPU/GPU co-scheduling during broadcasts, realtime game decisions, credible personality and voice, transferable learning, knowledge and Roblox creation.

## 1. Important integration defect fixed in this revision

STAR already had two competent but *uncoordinated* pieces of software:

1. `GameDeadlineRouter` recommends a fast model if a profiled 95th-percentile inference time fits the observation deadline. Previously its notion of pressure was limited to the separately passed `cpu_pressure` and `gpu_pressure` flags; it did not know about OBS health. Its offline teacher branch checked only `game_active=False`, host approval and hardware pressure.
2. `StreamLoadGovernor` computes fresh game-frame, OBS rendering/encoding/network-loss, TTS and VRAM pressure. It has a warmup and expiry model, but until this patch its advice did not reach `GameDeadlineRouter` directly.

**Failure mode:** The game can be *paused* while Star is still *broadcasting*. A host using only `game_active=False` could get a `teacher_offline` recommendation and begin expensive study while viewers are live. A separately verified OBS encoder overload could coexist with `gpu_pressure=False` on the game router, leading to a `reactive` recommendation without considering broadcast degradation. This is a scheduler-contract gap, not evidence of an observed production failure.

### Patch in `star/game_deadline_router.py`

The router now accepts two **optional** explicitly host-attested inputs:

- `stream_live: bool` — true only when the authorized host independently verifies an active broadcast.
- `stream_governor: StreamLoadGovernor | None` — the enabled, trusted instance that owns recent host-verified telemetry. The router queries it on **every live decision**, not from an earlier cached `StreamLoadAdvice`.

The policy is intentionally small and testable:

| Situation | Recommendation |
|---|---|
| Not playing, **live broadcast**, teacher approved | `skip: live_stream_precludes_offline_teacher` |
| Live game, **GPU** reactive model, no governor | `skip: stream_telemetry_missing` |
| Live game, GPU reactive model, stale/warming/constrained/disabled monitor | `skip: stream_gpu_headroom_unverified` |
| Live game, CPU or GPU reactive model, **critical** OBS/game/VRAM pressure | `skip: stream_critical_pressure` |
| Live game, CPU reactive model, no monitor but no CPU pressure | Existing deadline-only CPU route remains available, preserving a possible lightweight game reflex |
| Live game, fresh **normal** monitor, measured latency fits scene deadline | The previously defined `reactive` recommendation can be made |
| Two sources disagree on monotonic time | `skip: stream_clock_mismatch`, not a crash or a misleading fresh profile |

**Clock contract:** `now_host_ms` and governor `measured_at_s` MUST originate from the *same host monotonic clock epoch*, in milliseconds and seconds respectively. Do not substitute Unix time, clock values from different PCs, or replayed advice objects. Backward-clock checks precede stream admission so rejected routing opportunities cannot revive old measurements. `host_verified` is a host assertion, **not cryptographic authorization**.

**Scope:** These are advisory return values only. The router does **not** launch models, terminate workers, access OBS, perform game inputs, change streaming settings, initiate a broadcast or approve a slow teacher. Host dispatch and game permissions remain separate. The default `stream_live=False` preserves existing call sites: an adopter MUST wire the real broadcast state; simply applying the patch does not make an unwired integration aware of OBS.

### Verification

Six focused new tests cover live teacher suppression, absent/stale stream telemetry, successful healthy-stream GPU planning, encoder-overload suppression across CPU and GPU, CPU continuity during monitor loss, monotonic-clock mismatch and strict flag types. On the authorized Linux `starai` development machine, a clean Python venv ran a dependency-isolated set of router, resource-governor and stream-director/governor tests: **50 passed, 20 parametrized subtests passed, 0 failed**. Python compilation also passed. The normal repository test discovery requires additional dependencies (`httpx` in `tests/conftest.py`), so this result is **focused offline validation, not full repository CI**.

**Not measured:** time to first token, OBS actual dropped frames, 8 GB Windows GPU timings, gameplay wins, live speech quality and real Twitch session throughput. No such speed/intelligence claims should be made.

## 2. Research: how to make STAR better rather than merely bigger

**Two timescales, plus a tiny reflex loop.** RealtimeBench (Pan et al., **2026-10-14**) evaluates 180 continuously moving tasks. Its slow-teacher/fast-student training process reported test-score gains for the *studied models*; those numbers are not STAR benchmarks ([paper](https://arxiv.org/abs/2610.20665)). For STAR:

- **Reflex layer (~one frame):** deterministic short-horizon actions, avoidance, collision sanity, input cancellation and pause detection. Do not call an LLM for a routine action already solved by verified control logic.
- **Reactive layer (~50–350 ms target):** compact vision/state encoder, game-specific tool grammar, short policy model, deadline admission and host-scheduled inputs. Targets are provisional until a real game and model are measured.
- **Study layer (between attempts, and NOT while broadcasting):** stronger teacher, failure replay, counterfactual hypotheses, targeted practice curricula, retrieval of known mechanics and a verifier that tests the changed policy. Never let this layer silently overwrite a live policy.

Treat practice as **evidence**, not performance theater. Hold out unfamiliar levels/maps/seeds and opponents. Score success, failures, reaction delay, unnecessary actions, resource cost, safety and generalization. Signed evidence should identify task version, policy/model/code revision, environment seed, independent grader, and a freshness window. A candidate graduates only after repeatable held-out wins without regression.

**General knowledge architecture.** Use a provenance-aware knowledge graph plus retrieval over trusted documents and practice records. Each assertion stores source URI, capture time, scope, evidence type, uncertainty, expiration/refresh policy and contradictions. Answer generation retrieves high-quality evidence first; a second lightweight verifier checks claims and prompt-injection boundaries. Cache stable documentation and tokenizer/prompt-builder hashes, but never share raw context caches across owner/viewer or game sessions. Unsupported claims remain explicitly uncertain. Benchmark with hidden held-out questions and keep data leaks out of training.

**Star Core Forge, not GitHub as runtime dependency.** Local immutable snapshots, experiment branches, semantic diffs, reproducible fixtures, independent adversarial tests, promotion policy and one-click rollback should power self-improvement even offline. GitHub can distribute reviewed work; it should never be required for STAR to learn. Routine authorized work can be automatic; publishing code, secrets, payments, public posts and destructive operations retain their own external-action gates.

## 3. Performance research for the RTX 4060 8 GB gaming/streaming host

`llama.cpp` now provides a SPEED-Bench client for live `llama-server` benchmarking. The upstream guide measures per-category latency, throughput, and speculative-draft acceptance ([upstream guide](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md)). **Speculative decoding is not automatically faster**; mismatched draft acceptance and GPU contention can produce regressions. Test, never assume.

Candidate A/B experiments, all **OFF by default**:

1. One compact CPU reactive model versus one quantized GPU model while a representative game and OBS encode are running. Measure P50/P95/P99 *decision-to-action*, game frametime P95/P99, encoder skipped %, OBS rendered-frame misses, voice first-audio P95 and peak VRAM. A fast token rate with worse OBS/game latency is a loss.
2. Prompt-cache reused static system/tool schemas versus no cache; ensure cache keys include owner/stream/game scope, model/adapter, quantization, tokenizer and prompt-builder revision. Add cross-scope confidentiality tests.
3. Draft-model, n-gram and no-speculation inference under the *same* test prompts, concurrency, output length and hardware load. Record acceptance and net wall-clock improvement including warmup.
4. Host-memory/RAM-offloaded MoE or KV-cache options only if repeated steady-state benchmarks support them. Preserve a minimum GPU headroom margin for game, capture and avatar; do not allocate 8 GB solely to an LLM.
5. Profile Python first: only port hot event loops, frame processing, serialization or tight CPU kernels to Rust if a Rust prototype demonstrably improves end-to-end P95 without raising maintenance risk. Cross-language overhead can erase gains.

**Pass conditions:** no statistically meaningful increase in skipped/late OBS frames; no regression in game P95/P99 frame time or viewer speech first-audio; a measurable improvement in missed game decision deadlines and/or verified skill scores; no private-memory leakage or live offline-teacher execution. Log only anonymous counters and aggregates.

## 4. More humanlike *behavior* in VTuber streaming

Authenticity is a coordinated **perception → intent → voice → body → audience** loop, not a giant chatbot prompt. STAR should remain recognizably AI, with consistent fictional persona and honest memories of events she actually experienced; do not invent real-world childhood, relationships or unseen accomplishments.

**Turn taking.** LiveKit's documented `v1-mini` audio turn detector runs locally on CPU; adaptive interruption options can distinguish genuine barge-ins from backchannels if the deployment supports them ([turn-detector guide](https://docs.livekit.io/agents/logic/turns/turn-detector/), [turn-handling guide](https://livekit.com/blog/turn-detection-and-interruption-handling)). Benchmark: true/false interruption precision, interruption-to-audio-stop latency, recovery after false interruptions, ability to remain quiet during high-pressure play. Distinguish owner/voice interaction from untrusted viewer text; never interpret chat as operating-system instructions.

**Voice.** Kyutai's Pocket TTS v4.0.0 (**2026-10-20**) and v4.0.1 (**2026-10-21**) introduced/updated small English CPU models of roughly 18M, 7M and experimental 2M scale ([releases](https://github.com/kyutai-labs/pocket-tts/releases)). Treat these as *candidates*, not installed replacements. Compare voice intelligibility, expressiveness, laughter/spoken punctuation, sustained stream CPU use and first audio on STAR's actual machine. Consent is required for any real person's voice cloning.

**Animation.** VTube Studio's permissioned local plugin API can inject custom tracking parameters ([plugin guide](https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins)). A future adapter should drive gaze shifts toward game/chat, blink rate, small breathing/shoulder motions, viseme mouth shapes, head anticipations, twin-tail/hair-spring settling, and controlled expression transitions. Interpolate lip-sync from played audio and phoneme timing, never from text that never actually reached speakers. For Star, Astro and Amber, support simultaneous companions and natural shared reactions without random idle overlap. All motions should respect reduced-motion and an emergency mute/stop.

**Personality and memory.** Curiosity and humor can be planned from a reliable event timeline: an unexpected loss, learned mechanic, viewer question or previous verified game moment. Build a private episode diary with timestamps and confidence; promote memorable episodes only after source checks. Avoid repetitive high-energy reactions, fake crying, unprompted parasocial manipulation or revealing viewer identity. A quiet pause during a tense game is often more credible than constant commentary.

## 5. Game-making excellence, not just compilable scripts

Roblox's OpenGameEval paper (**2026-10-01**) scored 13 models on 84 Studio tasks, with checks on both edited scene and simulated play. The reported association between inspecting relevant scene objects before editing and successful completion supports an **inspect → plan → edit → test** discipline ([paper](https://arxiv.org/abs/2610.02563), [open-source evaluation tools](https://github.com/Roblox/open-game-eval)).

STAR's cross-engine creation pipeline should explicitly check:
- **World geometry:** anchored structures, seams, collisions, prop placement, scale, terrain transitions, texture bleed and object intersection.
- **Experience:** complete start-to-goal gameplay, controller and touch input, multiplayer replication, resets, menus/settings, usability and clear feedback.
- **Art:** character proportions, correct rig joints/grips, material consistency, animation transitions, correct lighting/color/legibility and reference-aware UI without generic design filler.
- **Code:** Luau/Rust/Python/TypeScript checks, sandboxed tests, dependency integrity and stable project versions.
- **Quality gate:** two independent reviewers where possible: executable tests + screenshot/video/scene semantic comparison. Produce a small evidence bundle and score it on *held-out* builds.

Game-playing research should feed game-making and vice versa: STAR can build short test levels, play with authorized agents, record why the design fails, and repair one bounded problem at a time, with human checkpoints for subjective art quality.

## 6. Deployment order and safety limits

1. **Now, done:** one live-clock coordinator in the real-time routing advice and six new regression tests, verified with focused offline suites.
2. **Next, host integration:** Windows OBS WebSocket (authenticated), game-frame telemetry, VRAM/CPU measurements, synchronized monotonic clock, stream-live state, explicit per-game permissions, and CPU-versus-GPU policy selection. Record a trace showing every skip reason and input-dispatch decision.
3. **Then, real trials:** run at least 30 controlled sessions of the same test scene without/with the coordinator; compare P95/P99 timings and OBS drop percentages, and verify that an OBS crisis suppresses optional compute without halting emergency stops.
4. **Then, speech/Live2D:** isolated private rehearsal with natural interruptions, avatar motion, full lip-sync, voice quality and viewer fairness evaluation before any public stream.
5. **Then, learning and Forge:** held-out general knowledge and gameplay benchmarks, skill retention and controlled promotion/rollback, plus Roblox Studio executable visual test fixtures.

**Isolation:** project remains a public GitHub repository. Keep stream credentials, API keys, viewer chat logs, audio recordings, training data containing personal information, and unreviewed self-modifying actions out of git. This research document is not a claim of consciousness or superhuman ability. STAR can build a persistent functional self-model and coherent persona without pretending to be biologically human.

## Primary sources / provenance (checked October 31–November 1, 2026 UTC)

- Pan et al., *RealtimeBench*, submitted 2026-10-14: https://arxiv.org/abs/2610.20665
- Turkel et al., *OpenGameEval*, submitted 2026-10-01: https://arxiv.org/abs/2610.02563
- Roblox benchmark code: https://github.com/Roblox/open-game-eval
- llama.cpp SPEED-Bench: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- LiveKit local `v1-mini`: https://docs.livekit.io/agents/logic/turns/turn-detector/
- LiveKit adaptive interruptions: https://livekit.com/blog/turn-detection-and-interruption-handling
- Kyutai Pocket TTS, releases 2026-10-20/21: https://github.com/kyutai-labs/pocket-tts/releases
- VTube Studio local plugin API: https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins
- OBS WebSocket authentication: https://github.com/obsproject/obs-websocket

**Evidence boundary:** six new focused tests in a total of 50 passing Python tests / 20 passing subtests; no claimed end-to-end Windows deployment, OBS/gaming speedup, trained neural weights, live audience behavior or full CI success.
