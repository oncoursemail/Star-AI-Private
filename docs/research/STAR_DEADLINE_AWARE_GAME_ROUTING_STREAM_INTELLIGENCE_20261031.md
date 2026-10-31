# STAR AI — deadline-aware game reasoning and real-time VTuber performance

**Research date: October 31, 2026.** **Implemented scope:** An opt-in, offline-only scheduler advisory and synthetic tests. No actual Windows gameplay, OBS session, model training, production integration, or measured speed improvement. The repository named Star-AI-Private was publicly visible: never commit keys, private chat, audio, host identifiers or recordings.

## Problem: inference can be correct but too late

RealtimeBench (Ningxin Pan et al., **October 14, 2026**) evaluates 180 continually running game tasks. Its two-timescale approach uses a fast student during live gameplay and a deeper teacher between attempts. Two self-improvement rounds raised the *paper's own benchmark* average from 13.51 to 24.19: https://arxiv.org/abs/2610.20665 . **Not a STAR result.**

Realtime-Bench (Jingyu Tang et al., submitted **October 15, 2026**) compares Wall Clock, Paused Clock and Token Clock conditions. It shows why decision-making latency changes success independent of offline correctness: https://arxiv.org/abs/2610.22155 .

STAR already has game_action_gate.py (host action claim and freshness), game_action_freshness.py (capture-to-assessment metrics), stream_brain_governor.py (hardware reservations), game_practice_curriculum.py (progression), gameplay_skill_bank.py (signed outcomes). A missing pre-inference decision was whether a measured quick model could finish before a game's observed scene became too old. The new game_deadline_router.py fills this narrow gap with no OS access.

## Implemented controller

GameDeadlineRouter is disabled until a trusted host explicitly enables one game/version session. It records a bounded 64-sample window (minimum eight by default) of host-measured reactive inference duration and rejects replayed timing sample IDs. A timed-out attempt enters the latency window at 5,000ms; dropping failures would give an incorrectly optimistic p95.

For an active game, remaining decision time equals **maximum observation age minus observed scene age minus a 40ms dispatch reserve**. A nearest-rank p95 of measured reactive inference must be **strictly below** this slack. For example: an observation already 120ms old, a 350ms scene maximum and 40ms handoff reserve leave 190ms; an 70ms p95 quick model qualifies for *routing advice* while a 320ms p95 model is skipped. Stale/unknown/unverified data, pressure, replay and mismatched game scope reject the route.

A separate offline teacher study may be suggested only while the game is inactive, independently approved and not under hardware pressure. A GPU-based quick path is skipped under GPU pressure; a CPU quick path may proceed only with CPU headroom.

No return value authorizes game input, a model launch, model promotion or broadcast. This is an estimation control plane, NOT a verified skill improvement. Only signed, independent practice/held-out outcomes can prove learning.

## Required host integration (not installed)

1. Collect host-attested inference timing samples (including timeouts) on the exact machine, model, quantization, context and game workload being tested. Keep game/version/model/hardware profiles separate. Warm up the quick model offline first.
2. At live capture, compute monotonic observation age; request deadline advice before allocating an inference job.
3. Even when the route says reactive, separately obtain a real lease from StreamBrainGovernor / AdaptiveQoS. Never pass model text or chat into host-attestation parameters.
4. Before any game input, existing GameActionGate must reverify action allowlist, focus, permissions, frame binding, freshness, input-release watchdog and streaming restrictions. Route advice alone never presses a key.
5. Between attempts, let the teacher inspect failed signed training trials, propose alternative strategies and difficult exercises; verify each skill on untouched held-out maps before promotion. Reset the timing profile after a version or device change.

## Supporting opportunities researched

**Faster inference:** The official llama.cpp releases feed includes Windows CUDA and CPU build artifacts as of **October 29, 2026** (https://github.com/ggml-org/llama.cpp/releases). Test STAR's pinned build against one reviewed newer version with frozen model and prompts. Compare first-token latency, p95 end-to-end completion, prompt reuse, speculative decoding only for supported models, GPU layer offload, and simultaneous gaming + OBS frame pacing. Upstream hardware-specific gains are not proof of improvement on STAR's 8GB GPU. Preserve a rollback path.

**Better gaming skills:** Combine fast reaction and offline teacher reflection (RealtimeBench) with game_practice_curriculum.py. Evaluate unknown levels, UI changes, input styles and multiplayer sessions. Measure objective success *and* capture-to-input timing; a model that is smarter when the game is paused may be worse in a continuous game.

**More natural VTuber speech and animation:** The official LiveKit documentation describes local CPU v1-mini audio turn detection (https://docs.livekit.io/agents/logic/turns/turn-detector/). Evaluate it against STAR's existing stream_turntaking.py, not as an automatic replacement. Make Star's voice and facial rig respond to actual audible PCM, real reactions and genuine viewer pauses. Coordinate expressive eyes, blinking, lips, hair, ear/tail physics and physical audio stop. Intentional silence during tense gameplay should be a feature. Maintain Star's original AI identity and truthfully grounded gameplay memories rather than fabricated human biography. Measure completed-audible-turn p95 and interruptions with stream_latency.py and StarStage.

**Higher-quality game creation:** Roblox StudioTestService (https://create.roblox.com/docs/reference/engine/classes/StudioTestService) supports scripted multiplayer play tests. Roblox's 2026 developer announcement includes virtual input and device simulation (https://devforum.roblox.com/t/new-studio-testing-apis-and-assistant-improvements/4657854). Combine executable Lua tests with screenshot/lighting audits, collision/geometry checks, viewport and animation checks, complete player journey tests and UI tests across devices. A code-only pass does not establish game quality.

**Broad general knowledge:** Use reviewed retrieval for verifiable facts. Keep fictional Star lore separate from factual claims. Evaluate updates with frozen model/backends on general_knowledge_benchmark.py, but reserve entirely unseen domains as a gate: ten visible development tasks cannot establish broad intelligence. Run heavier research between broadcasts, not on the voice/game critical path.

## Reproducible acceptance

- Run: python -m pytest -q tests/test_game_deadline_router.py; then run the repository's full offline suite. Unit cases cover outlier p95, timeout accounting, stale scenes, deadline equality, hardware pressure, guest teacher exclusions, replay protection and session resets.
- Windows rehearsal (still required): profile 30+ warmup inferences per hardware configuration, then 20+ matched baseline/candidate game attempts across three authorized games. Record game objectives, capture-to-host-claim p50/p95, deadline misses, OBS dropped-frame ratios, 1%-low FPS, GPU VRAM, CPU stalls and first audible response p95.
- Promotion: no independent skill/quality regression, fewer actual deadline misses, stable game/OBS frame pacing, no new voice interruptions or unsupported claims; require human review and owner-controlled rollback.
- Sensitive media, telemetry and credentials must remain off the publicly visible repository.

**Delivered:** A tested local advisory implementation and a research/acceptance plan. **Not delivered:** actual model acceleration, Windows gaming experiments, autonomous streaming, human voice production, or deployed control of Star's PC.
