# STAR — Verified gameplay forecasts and an integrated real-time VTuber intelligence plan
**Research and implementation date:** 2026-11-01
**Status:** draft, owner-opt-in; no live gameplay, OBS broadcast, model upgrade or measured inference acceleration.

## 1. Concrete source audit and code correction

The local STAR prediction pipeline has two distinct boundaries: `GamePredictionLab.precommit()` records a model's *prospective* success probability, and `GamePredictionLab.resolve()` compares it to a *separately signed* practice outcome stored in `GameplaySkillBank`. Every practice/validation label must retain its original provenance.

**Reproduced defect:** Before this change, `resolve()` looked up a pending run and compared the caller-supplied observation timestamp against the forecast deadline **before** checking whether that `GameTrial` was actually in the signed bank. A fabricated, non-ingested trial with a matching run ID/scope but an earlier or future timestamp would permanently change the pending row to `cancelled`. A real signed outcome could then never be evaluated. That is a denial of learning, not evidence of poor gameplay or an authorization to touch the game.

**Fix:** Verify the exact signed practice trial first, then apply irreversible stale/cancellation logic only to authenticated evidence. Preserve existing fail-closed practice/holdout separation and 180-second deadline semantics. Never use the claimed timestamp as a substitute for a signed receipt. The added adversarial regression attempts both an earlier and a future forged observation, confirms the pending forecast remains present, then confirms the real signed result can resolve.

**Verification procedure:** Run `python3 -m unittest discover -s tests -p test_game_prediction_lab.py -q`. The new test failed on the original code, passed after the fix, and is designed to stay within the existing offline/std-lib test infrastructure. These tests are synthetic, not evidence of better game win rate or faster model inference.

## 2. Source-aware learning: truthful ability, not self-declared progress

Existing STAR components: `game_prediction_lab.py`, `gameplay_skill_bank.py`, `game_practice_curriculum.py`, `game_skill_gate.py`, `game_transfer_eval.py`, `game_deadline_router.py`. These form a useful baseline but are not themselves gameplay policies. The next integration should join them with a host-produced, signed trial lifecycle:
1. Record a pre-action prediction and capture/decision timestamp from the permitted game host.
2. Run the fast player through `game_action_gate.py` and `game_action_freshness.py` before issuing allowed inputs.
3. Collect an independent observed outcome; require its signed receipt, matching game/version/objective/action/run, and elapsed-time envelope.
4. Compute calibration and learning deltas from fresh practice only. Review failures, produce a constrained skill update, and schedule increasingly difficult repetitions.
5. Freeze the update before evaluation; test on fresh, preregistered game scenarios and unseen maps. Never teach from withheld validation labels.
6. Promote a skill only when outcome quality, deadline performance, regression gates and resource-budget thresholds pass *together*. Keep rollback history in local Star Core Forge.

**Novel proposed integration:** Introduce a signed `LearningAttemptEnvelope` tying prediction, action, rendered-observation digest, verified completion outcome, and host-monotonic latency together. The envelope should have a new unpredictable episode ID, exact model/policy digest, adapter version, game ID and a replay-resistant sequence. Do not include private frames/chat in the public report. A policy cannot claim skill progress from its own commentary or a text-only imagined victory.

**Research basis:** RealtimeBench (Pan et al., published October 14, 2026, https://arxiv.org/abs/2610.20665) evaluates 180 real-time tasks across six game types and motivates a slow teacher working *between* attempts, while a fast student acts during live game time. STAR should replicate this structure and validate on its own games; the paper's published scores cannot be treated as STAR results.

## 3. Real-time system architecture: fast enough *and* responsive

There are four separate clocks: screenshot capture, model/action selection, *actual* game input observation, and spoken/audio-visible output. A high tokens-per-second result alone does not measure any of them. STAR already has `stream_load_governor.py`, `stream_health_bridge.py`, `stream_admission.py`, `game_deadline_router.py`, `stream_playout_clock.py`, and several QoE evaluation modules. Integrate those into one read-only, host-measured acceptance recorder before enlarging the architecture.

**Scheduling proposal** (not implemented here):
- **Hard priority:** game input freshness and verified owner interrupt/audio stop. Expired visual context must never produce a keypress.
- **Interactive priority:** bounded CPU turn detector and TTS first chunk, scene reactions, avatar hotkeys. Drop obsolete commentary rather than queue it after the event is over.
- **Opportunistic priority:** retrieval, large teacher inference, Blender rendering, rehearsal, software changes; only off-stream or when signed telemetry explicitly admits them.
- **Prevent starvation:** cap each priority queue, track age/p95/p99, reserve short viewer-answer opportunities, and rate-limit background jobs. The host, not an LLM, must authorize execution.

For the 8 GB GPU, benchmark **three variants**, not an assumed Rust or CUDA miracle: (A) one reactive model; (B) small CPU voice + GPU reactive model; (C) a draft/speculative model only if measured VRAM headroom allows. Pin model and quantization revisions, warm up fairly, record CPU/GPU/RAM/VRAM usage, tokens/s, first audible chunk, game FPS/p99 frametime, OBS skipped/rendered frames, and peak interrupts. Reject an inference optimization if it improves tokens/s but worsens OBS dropped frames or live action deadlines. Rust can optimize hot data paths only after profiling shows Python overhead is material.

**Primary technical references:**
- llama.cpp SPEED-Bench (https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) measures latency, throughput, and speculative draft acceptance for an existing `llama-server` — **not** OBS/game performance.
- OBS WebSocket (https://github.com/obsproject/obs-websocket) is integrated into modern OBS; keep it authenticated and its telemetry read-only. Untrusted output-status claims cannot admit work.
- Roblox's May 28, 2026 Studio announcement (https://devforum.roblox.com/t/new-studio-testing-apis-and-assistant-improvements/4657854) documents scripted multiplayer tests, cross-device simulation and virtual input, which can provide real outcome evidence rather than script-only checks.

## 4. Humanlike, entertaining VTuber behavior grounded in actual events

**Speak less but better.** Naturalness is not maximum verbosity. STAR should acquire selective attention, eye contact, gestures while listening, game-critical silence, immediate reaction to a real surprise, genuine follow-up to a viewer, and bounded callbacks to *verified* prior moments. Keep the Star / Astro / Amber companion cast distinct and permissioned, without inventing human memories, relationships, or feelings as factual evidence.

**Recommended audio-to-avatar pipeline:**
1. Microphone/chat ingress with owner-approved roles and source-specific trust boundaries; ignore unverified chatter as instructions.
2. VAD and endpointing with calibrated pause times; do not let noise/coughs trigger false barge-ins.
3. A planner emits an *intent* (listen, laugh, react, answer, focus) and validated speech text, not untrusted motion commands.
4. TTS yields chunk timestamps plus an audio-playout receipt; visemes and facial/eye gestures follow actual audible samples rather than anticipated text. Cancel motion and captions when speech is interrupted.
5. Animated companion behavior is constrained by explicit consent, per-scene timing and stage rules, and broadcast quality gates.
6. Session memory stores only host-observed, consent-to-broadcast game moments; private viewer identities and chat are never embedded in exportable memory.

LiveKit's current official turn detector supports a CPU-local `v1-mini` (https://docs.livekit.io/agents/logic/turns/turn-detector/); its docs specify minimum VAD silence of 250 ms and different endpointing defaults. Test self-hosted behavior instead of assuming cloud-only adaptive interruption works locally.

Kyutai's Pocket TTS release v4.0.1 on **October 21, 2026** (https://github.com/kyutai-labs/pocket-tts/releases) updated small English voices and fixed sub-20M behavior. Benchmark first audible sample and natural prosody on the actual Windows CPU; tiny models may be faster but less expressive. Store voice assets and licenses explicitly. STAR must never claim live performance or emotional authenticity without actual device/observer evidence.

## 5. Make STAR a better game builder, not merely a code generator

A complete Studio task must have an inspected *scene before edit*, an objective contract, a candidate patch, a render/geometry check and executable client-server playthrough. Use `studio_scene_integrity.py`, `studio_multimodal_quality_gate.py`, `studio_test_farm.py`, `studio_playthrough_contract.py`, and `studio_virtual_input_smoke.py` as existing foundations. Check:
- Geometry: anchored/connected walls, realistic size and orientation, prop collisions, navmesh and door clearances, material/texture continuity.
- Function: startup, win/lose conditions, inventory, respawns, interactions and performance budgets.
- Usability: small-phone portrait vs desktop, camera and input behavior, readable text, functional UX and animation timing.
- Multiplayer: at least two clients; eventually four and eight; test join/leave, disconnects, avatar replication, latency and authoritative server logic.

Independent acceptance should combine game-engine assertions with reviewed screenshots/video and blind user playtests. Favor actual fixes over repeated generated screenshots, which can hide invisible geometry and broken physics. Hold out unseen projects and tasks so STAR does not merely memorize its own test suite.

## 6. General knowledge, curiosity, and continual self-improvement

Use retrieval with source URL, access date, license, publication date and confidence rather than endlessly placing retrieved pages into one giant prompt. Keep user-private/agent-internal memory separate from stream-approved facts. Give STAR a practical self-directed curriculum: language fundamentals (Python/Rust/Luau), graphics/math, computer operation, security, audio/music, game-mechanics analysis, game UX, animation and world-building. Each topic must lead to a task that has an externally checked answer or measured output, followed by a spaced review on an unfamiliar variant.

The existing `general_knowledge_benchmark.py` should compare *fixed model/hardware/prompts* across software changes and also run holdout knowledge tasks. Reward fewer factual errors, calibration and source faithfulness, not merely bigger answers. Keep model swaps isolated from application changes so progress attribution remains meaningful.

**Core Forge role:** local/offline-first experiment registry, proposed semantic diffs, independent static/dynamic checks, resource quotas, reproducible artifact hashes, private backups and one-click rollback; GitHub is an optional export/review channel. No autonomous public posting, financial spending, irreversible host operations or game-server modification without owner-defined boundaries.

## 7. Concrete qualification matrix (no fictional wins)

| Gate | Minimum evidence | Fail if |
| --- | --- | --- |
| Forecast provenance | Forged earlier/future game timestamps never cancel pending signed outcomes | Any unsigned input mutates verified/pending outcome state |
| Real-time game | 100+ same-scenario A/B attempts plus unseen scenarios; signed success and input-age distributions | Candidate loses holdout score, misses deadlines or has stale actions |
| Stream QoE | Actual OBS GetStats/GetStreamStatus + game performance samples, across peak load | > agreed dropped-frame or p99 frametime threshold |
| VTuber humanlike speech | Matched viewer conversations with audio capture and ground-truth event timestamps | Speech overlap, missed owner interrupts, fabricated memory, excessive silence |
| Avatar | Captured audio/viseme/expression timing and observer evaluation | Lip/motion continues after actual audio stops |
| Knowledge | Unseen factual tasks with verifiable citations and hallucination audit | Unsupported claims or validation leakage |
| Game-building | Studio executable tests + visual/geometry review + multi-client playthrough | Broken UI, missing props, collision faults or non-playable end state |

**Current outcome:** only the forecast provenance correction and its deterministic tests are implemented by this change. All integration suggestions above remain engineering proposals until the authorized Windows host, OBS/game adapters and independent evaluations have been run. The repository is publicly visible: no API keys, private media, chat records or personal details belong in Git history.
