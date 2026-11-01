# STAR: capture-order correctness, real-time latency and skill transfer
**Research and engineering date:** 2026-10-31  
**Status:** production-library safeguards and unit tests committed to draft PR #845; Windows gaming, streaming, OBS, inference-speed and voice-quality measurements **not performed**. This file is an engineering plan, not evidence of improved model intelligence.

## 1. Repository audit: one real defect, one missing measurement

The existing `star/game_action_gate.py` already has a two-phase host-mediated symbolic action interface: opt-in allowlist, scope/version/episode checks, bounded key-hold proposal, single outstanding ticket, expiry, owner-verified host claim, explicit physical key-up acknowledgement, per-minute budget, CPU/game/voice pressure rejection and a monotonic clock. **Do not replace it with an unbounded action agent.** No action is executed here; the trusted game host is a separate boundary.

The gate previously checked that `frame.sequence` increased, but did not check that the **actual capture timestamp** increased. Consider an asynchronous capture/vision queue:

1. An approved action is proposed from frame 81, captured at 1000 ms.
2. The host completes and releases that action.
3. A delayed vision worker delivers frame 82, labeled with a higher sequence but captured at 990 ms. If the host processes it while its age and spacing budgets still pass, the old scene could lead to a new action.

**Implemented:** remember the timestamp of the last *offered* frame and deny any higher-numbered frame whose capture time is not strictly greater. Rejected attempts do not advance accepted-frame history; a new approved episode resets it. This is a scene-order check, not cryptographic authenticity. The host still owns frame timestamp, focus, observation verification, process/game allowlists, and game/input permission.

The second gap was **lack of per-session observation-to-action diagnostics in the existing gate**. The new bounded anonymous telemetry measures:
- `observation_to_offer_p50_ms` / `p95_ms`: capture -> advisory permit creation;
- `observation_to_host_claim_p50_ms` / `p95_ms`: capture -> trusted host claim acceptance.

Each uses nearest-rank percentiles across the most recent 64 eligible samples. Rejected events do not add samples; failed claims and expired permits do not pretend to be dispatched inputs. Samples reset at the beginning of an approved episode. No screenshots, prompts, action identifiers, player identifiers, personal details or raw game content are retained. Claim time is **not** a physical keypress or verified gameplay success.

The new `tests/test_game_action_gate_latency.py` covers delayed/reordered captures, equal-timestamp duplicates, successful recovery on a truly new frame, rejected/expired claims, matching issued-permit identity, latency p50/p95, unverified input, identity-free metrics and episode reset.

**Existing complementary module:** `star/game_action_freshness.py` tracks observation age in seconds for a possible downstream adapter. It is advisory and independent. **Do not concatenate two gates casually:** their time units, lifetime, sequence semantics and input policies differ. Choose one responsible input boundary or integrate through a single trusted host clock with explicit conversion tests. Neither module authorizes sending game input.

## 2. Research finding: slow thinking can lose to fast action

The October 14, 2026 RealtimeBench paper, *The World Won't Wait*, evaluates 180 tasks across six game types while environments continue moving. Its TORSI method separates slower offline teacher reasoning from low-latency student execution, and only adopts revised instructions after validation. The paper reports improvements on its evaluation suite; these results are **not** Star results.

**Star Core Forge adaptation** (proposed, not implemented in this patch):
- **Fast student:** brief, cached instructions + a small model or deterministic approved policy selects short symbolic actions from trusted game observations. Aim to finish *before* the action's capture-age deadline; never solve a long problem in the input loop.
- **Slow teacher:** after a run, review only owner-approved observation traces and independently signed successes/failures. Generate hypotheses, concise skill cards and tests.
- **Independent verifier:** preregister maps/seeds; compare baseline and candidate on 20+ paired holdout trials in realtime mode (not paused mode). Require stable success, normalized progress, response latency and no newly failed tasks. Use `star/game_skill_gate.py` as advisory and `star/gameplay_skill_bank.py` / `game_transfer_eval.py` for cryptographically signed evidence where applicable. Do not let the teacher grade itself.
- **Memory promotion:** retain a skill only after reproducible evidence, with explicit game/version applicability, expiry, provenance, limitations and rollback handle. Store failed attempts too. Avoid poisoning future policies with a viewer's unverified claimed wins.
- **Latency discipline:** track observation-to-offer and observation-to-claim p50/p95 alongside final input delivery; reject all out-of-order captures before any action suggestion reaches the host. Recheck focus and emergency-stop controls at the actual OS dispatch boundary.

**Key falsification test:** a faster model may execute more actions but win fewer games; require unseen objective success and frame-time stability, not higher action count.

Primary source: https://arxiv.org/abs/2610.20665 (2026-10-14).

## 3. Making Star faster on an 8 GB gaming GPU

The best optimization is often **avoiding unnecessary inference** before upgrading the engine or rewriting orchestration in Rust. A pre-stream / in-stream admission controller can reserve hard realtime resources:

| Priority | Work | Behavior under gaming or voice pressure |
| --- | --- | --- |
| P0 | Game controls, audio playback, rig key-up and stop | Never wait for background inference; drop overdue actions |
| P1 | Brief voice and avatar reactions to verified events | Cancel/rewrite obsolete utterances; silence is a valid output |
| P2 | Small vision decisions and already-cached skill retrieval | Frame-deduplicate, use bounded latest-only work queues |
| P3 | General questions, speculative reasoning and long web research | Defer or send to CPU/other machine when permitted |
| P4 | Model training, game generation, bulk embeddings, self-play curriculum | Pause during live broadcast; use night-school window |

Benchmark **on the actual RTX 4060 8 GB / 32 GB RAM target**, not by transferring others' RTX 5090 token benchmarks. Compare one baseline against one change at a time: quantization, context size, GPU layers, prompt-prefix caching, continuous batching, draft/speculative decoding, number of server slots and optional alternate inference server. Record version, hash, loaded model, hardware, exact prompt mix, TTFT, tokens/sec, p95 action time, 1% low game FPS, TTS start latency, VRAM peak and CPU contention. Prefer end-to-end quality-adjusted performance; reject changes that lose whole-task success even when tokens/sec rises.

Official llama.cpp SPEED-Bench measures server throughput, latency and speculative acceptance for an already running server: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md. It is **not** evidence of an automatic speedup for Star.

**Rust decision:** profile first. Rust is valuable for measured high-frequency capture/transport, low-overhead audio buffers and well-defined service boundaries. It will not accelerate LLM matrix multiplication or repair wrong game plans by itself. Avoid duplicating Star's Python orchestration until profiling shows a concrete hotspot. Keep optional native extensions independently benchmarked and recoverable.

## 4. Natural VTuber presence without fabricated experiences

Star's social believability depends on timing, memory continuity, embodied behavior and genuine skill growth more than nonstop talking. Recommended controlled experiments:

- **A/B conversation pacing:** sample real local host conversation (opt-in), compare short and long pauses, interruptions, purposeful silence, acknowledgement timing, question relevance, filler rate, repetitive jokes and over-talking. Prefer low misfire rate over constant vocal activity.
- **VAD/turn taking:** retain `star/stream_turntaking.py` as a local deterministic host gate; benchmark LiveKit's local CPU `v1-mini` **only as a speech-turn detector**. A turn detector is not a speaker-authentication mechanism, and cloud-only functionality should never silently become a dependency for offline Star. Official docs: https://docs.livekit.io/agents/logic/turns/turn-detector/.
- **Speech comparison:** Kyutai's October 2026 Pocket TTS small-English configurations (18M, 7M, experimental 2M) are candidates for CPU TTS when the GPU is gaming. Compare listener-rated expressiveness, pronunciation, time to first audible sample, tail latency, CPU saturation and model license. The repo's performance claims are not Star measurements: https://github.com/kyutai-labs/pocket-tts and release notes https://github.com/kyutai-labs/pocket-tts/releases.
- **Expression coupling:** a verified narrow win should trigger a small delighted cue; a high-stakes moment may require silence or a focused expression. Animation and mouth movement must follow *host-confirmed playback*, not merely generated text or a TTS queue event. Retain existing speech epoch and motion cancellation constraints.
- **Persona continuity:** stable preferred topics, games and aesthetic style, expressive indigo-black/gold twin tails and voice/laughter, permitted cat/puppy modes, truthful session recollections. Distinguish persona fiction from actual experienced events; disclose AI identity, do not invent real relationships or life events. A strong consistent fictional character does not demonstrate consciousness.

**Rehearsal acceptance:** owner-authorized 30-minute local recording, no public broadcast; randomized repeated gameplay segments, opt-in safe chat prompts, loopback measurement of actual audible output, lipsync/hair/gaze review, 1% low FPS, p95 timing, audio drift and memory-claim audit. Compare to prior revision on the same hardware and identical segments. Do not publish unredacted recordings or chat.

## 5. Game creation, physics, visuals and general knowledge

Star should test the whole game rather than accept plausible Luau and a beautiful screenshot as success.

**Roblox Studio gauntlet:** inspect scene graph before editing; validate bounding boxes and collision groups; anchor/weld integrity, object pivot placement, texture UVs and missing props, mobile legibility, input focus, animation clipping and camera collision. Run scripted **StudioTestService** multiplayer tests, player join/leave, orientation/device emulation and a fixed client/server gameplay holdout. The official StudioTestService provides programmatic server and simulated client test tools: https://create.roblox.com/docs/reference/engine/classes/StudioTestService.

**Creativity quality:** use multiple candidate game designs with independent critic rubrics for gameplay novelty, clarity, accessibility, performance, aesthetics and mechanical integrity. Blind human ratings are still needed to detect sterile or repetitive visuals. A generated variation is not necessarily new. Prefer one finished high-quality game to ten broken prototypes.

**General-knowledge growth:** create evidence stores with epistemic classes:
1. verified test-run receipts,
2. inspected local code or documents,
3. dated external references with licensing and source URI,
4. unverified hypotheses,
5. persona preferences and fictional lore.

Build multi-domain self-generated curricula (math, physics, writing, audio, Blender, visual design, world knowledge, debugging, security hygiene, engineering, conversational behavior). Use *independent unseen holdout questions and tasks* for recall accuracy and transfer. Never treat a longer vector store or more autonomous loops as intrinsic intelligence; measure correction rate, factual uncertainty calibration and unseen-case improvement. Respect source licenses and disable web/network access by default.

## 6. Measurable next steps and rollback

**Next integration gate:** when an authorized Windows host adapter is available, instrument one end-to-end path:
`captured_frame -> verified_host_observation -> model_hint -> GameActionGate.request -> exact_permit_claim -> host_permission/focus_recheck -> physical_dispatch -> confirmed_key_release -> verified_game_outcome`.

The first new measurements should be:
- p50/p95 observation-to-offer; p50/p95 observation-to-host-claim; **separately** p50/p95 observation-to-physical-input via the host;
- expired/reordered-frame denial rates; gameplay objectives achieved on novel maps; failure rate and game FPS;
- voice first-audible p95, cancellation/false interruption, mouth/audio sync and perceived naturalness.

Compare before/after on the same replay seeds and device. If a candidate increases game/input errors, owner-permission failures, 1% low FPS regressions or ungrounded claims, roll back through local Star Core Forge and retain signed negative evidence.

**Verification for this commit:** `pytest -q tests/test_game_action_gate.py tests/test_game_action_gate_latency.py`, Ruff and Pyright, then whole offline CI. Passing offline tests means only those synthetic checks succeeded. No benchmark, model retraining, Win11 integration, OBS recording, livestream, speech/audio engine change or physical gaming occurred in this patch.

**Publishing:** keep #845 draft until CI passes and hardware/device checks exist; internal Star Core Forge remains the source of autonomous trials, with GitHub an optional review/export mirror. The repository named `Star-AI-Private` currently reports **public** visibility in GitHub metadata. Never commit credentials, private chats, recordings or raw viewer identities.
