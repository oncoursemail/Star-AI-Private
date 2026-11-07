# STAR — sustained GPU headroom, game intelligence and believable VTuber streaming
**Research and implementation review: November 1, 2026.**
**Scope:** Review-only, local-first infrastructure; nonbroadcast Windows resource evidence. No online game controls, transmission, streaming, model swap, driver changes or service reconfiguration.

## Executive finding — avoid treating one GPU reading as capacity

During a read-only inspection of the Windows computer **Main** on November 1, 2026, five NVIDIA GPU readings approximately 0.5 seconds apart reported:

| Host evidence | Observed |
| --- | --- |
| GPU total | 8,192 MiB in every reading |
| Free VRAM sequence | 419, 419, 418, 378, 378 MiB |
| GPU utilization sequence | 0%, 14%, 14%, 30%, 0% |
| Running llama-server processes | 1 |
| OBS / VTube Studio processes found | 0 / 0 |

This is a short nonbroadcast snapshot, not a controlled workload benchmark or evidence that OBS/gaming cannot run after reconfiguration. **The minimum free VRAM was only 378 MiB (~4.6% of total).** The utilization number briefly returned 0% while VRAM remained ~95% occupied. The current profile is therefore **not an acceptable starting point for launching everything simultaneously without measuring and reallocating memory**.

The NVIDIA utilization counter reports the percentage of time kernels execute over a product-dependent sampling period (roughly 1 second to 1/6 second); it is **not** a reading of free VRAM or a guarantee that allocations will succeed. Source: [NVIDIA nvidia-smi manual](https://man.archlinux.org/man/nvidia-utils/nvidia-smi.1.en).

### Implemented this iteration

New independent module: `star/stream_windows_resource_window.py`.

- Read-only, OFF by default; requires an explicit trusted-host `owner_approved=True` argument before OS readers execute.
- Collects **3–9** local process and GPU observations; default **5 samples separated by 0.5 s**, approximately 2 seconds plus probe time. Bounds the GPU index, sample count, sample timing, process snapshot and timestamps.
- Reuses the already-tested single-sample Windows preflight checks at **every** observation. The worst observed free VRAM and utilization are evaluated, not an average that hides one bad frame or one allocation spike.
- Rejects transient free-VRAM dips, GPU busy spikes, changing reported GPU total, bad/missing intermediate probes, unexpectedly short or irregular time windows, ambiguous app instances, process restarts and recycled pinned game PIDs.
- Transient OS process names, PIDs and creation times are compared in memory only; the returned report contains static reasons, booleans and bounded numeric counters. It grants **neither gameplay nor broadcasting permission**. Untrusted data objects do not become attested just because they are typed.
- Isolated unit tests are independent of Windows hardware and do not launch games, OBS, avatar software or a model. Existing one-shot preflight API remains untouched.

**Caveats:** Short samples cannot prove future VRAM, long-run smoothness, which CUDA process will allocate VRAM, thermal stability, or successful audio/OBS callbacks. GPU index is pinned but is not a persistent GPU UUID, so multi-GPU remapping still requires host verification. The 1,536 MiB advisory minimum is not an experimentally derived sufficient gaming budget. The module is not yet attached to the live Windows event pipeline.

## Star's next practical architecture

### A. Resource-aware three-lane cognition

**Lane 0 — deterministic reflex (deadline first):** input remapping, known safe dodge cues, pause/abort behavior, device health, speech cancellation. No open-ended LLM turn can block the renderer or audio callback.

**Lane 1 — live tactical inference:** a compact model selects from allowable, short-lived action candidates using game screenshots, compact state and uncertain predictions. Attach each result to frame/scene version, action deadline, authorization and a cancellable worker lease. Drop stale outputs rather than execute obsolete actions. STAR's existing realtime coordinator and worker quarantine implement initial correctness checks, not game mastery.

**Lane 2 — slow teacher and knowledge synthesis:** run stronger reasoning, video review, route planning and new knowledge retrieval between rounds or on the second computer. Keep experiments and untrusted web material out of live tool permission decisions. Turn a proposed skill into a tested candidate, not an automatically trusted memory or self-edit.

The target metric is **accepted, on-time, correct actions per game minute**, paired with FPS, GPU high-water mark and natural speech, not raw decode tokens/second. Compare teacher/student against the same held-out seeds, scenes and latency budget; measure wins, survival, recovery, objective progress and failure rates. Add confidence calibration and a reversible fallback when the student fails to recognize a scene.

**Initial test matrix:** 30+ episodes per game per policy; split practice/holdout maps and opponent types; record time-to-action median/p95 and off-target input rate; no live competitive advantages, prohibited bots, or anti-cheat circumvention. For proprietary online games use only explicitly supported automation/offline or permitted modes.

### B. GPU / RAM / two-PC scheduling

An 8 GB GPU cannot be assumed to accommodate a large resident LLM, a modern 3D game, OBS, Live2D avatar render and neural TTS concurrently. First establish actual model and KV-cache memory at fixed context and slot count; then reserve space for rendering/encoding *before* making the model allocation.

A candidate allocation (not a measured configuration):
1. On the gaming PC, keep the game, avatar renderer, OBS and deadline-critical reflex loop local; minimize GPU contention.
2. On CPU, place lightweight VAD/turn detection and test CPU TTS variants only if CPU headroom and voice latency meet the target.
3. On a second trusted computer, run strong teacher inference and nonurgent coding/research over a permissioned low-latency local connection; monitor network loss and fall back to local safe control.
4. Consider smaller quantized live models, fewer parallel GPU inference slots, smaller active context, quantized KV cache or selectively offloaded layers **only after paired quality, first-audible-syllable, frame-time, memory and energy measurements**.
5. Profile before any Rust rewrite; Python coordination overhead may be insignificant compared with GPU prefill, rendering and audio. Reimplement only proven high-cost paths and compare correctness.

**Caching caution:** llama.cpp has distinct server prompt-cache and host-RAM cache mechanisms. Multi-slot and hybrid model states can complicate cache reuse. The July 29, 2026 issue [llama.cpp #26293](https://github.com/ggml-org/llama.cpp/issues/26293) documented avoidable memory growth when idle reranking tasks entered a prompt cache. Do not blindly set large `--cache-ram` values on an 8 GB streaming host. Verify the exact installed build, supported flags, privacy boundaries between projects, cache hit rate, RSS, TTFT and regression behavior. Benchmarks must use the *same model, quantization, context, decoding settings and prompt workload*.

### C. Streaming that feels natural without pretending to be human

Naturalness is a **coordination and grounding** problem, not simply a bigger chat model.

- **Turn-taking:** combine VAD with a local acoustic/semantic end-of-turn detector, respect hesitations, use interruption/barge-in handling and never generate an entire paragraph when a short conversational acknowledgment fits. LiveKit documents `v1-mini` as a CPU-local option; benchmark CPU use and interruption false positives on STAR's own setup: [LiveKit turn-detector docs](https://docs.livekit.io/agents/logic/turns/turn-detector/).
- **Speech and facial causality:** drive mouth from *audible-device playout*, not generated text timestamps. Keep eye gaze, blink, head movement, reaction delays and hair physics linked to actual behavior and scene events. Make laughter contingent on real social/game context rather than sprinkling canned giggles.
- **Avatar/control surface:** VTube Studio's authenticated plugin API supports injected custom facial parameters; permissioned local connection only, no public socket. [VTube Studio plugin docs](https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins). OBS's built-in obs-websocket should remain authenticated; it is a control channel, not authorization to start broadcasting. [Official OBS websocket repository](https://github.com/obsproject/obs-websocket).
- **Memory and personality:** keep persistent, provenance-tagged memories of gameplay accomplishments, conversations, boundaries, recurring jokes, art projects, and relationships with recurring characters (Star, Astro and Amber). Separate `observed`, `inferred` and `fictional persona`. Never invent human experiences or present generated emotions as biological facts.
- **Performative independence:** Star may choose a game or art goal, recover from quiet chat periods, reflect on an episode and schedule offline practice within the owner's scope. Every external write, stream publication, purchase or risky irreversible action stays separately authorized. Explicitly distinguish streamer character lore from real-world account identity.

Quantify lip-to-audible onset skew, interruption recovery, awkward silence, mid-sentence audio stalls, repeated filler rates, avatar frame gaps, chat response grounding, scene-matched reaction consistency and viewers' voluntary subjective ratings. Human-like presentation can be tested; actual consciousness or feelings cannot be established by animation.

### D. Game creation and general knowledge

Use an **inspect → plan → generate multiple candidates → verify → playtest → visual review → repair** pipeline. Each candidate needs scene graph consistency, no disconnected walls, no z-fighting, no misplaced props, collision/navmesh validity, consistent scale, legible UI, timing/animation tests and perceptual comparisons. Treat a visually attractive screenshot as *insufficient* evidence of a working experience.

Roblox's [StudioTestService](https://create.roblox.com/docs/reference/engine/classes/StudioTestService) supports automated multiplayer test scenarios, allowing independent checks of lobby, join/leave, team rules, interactions and respawn; keep test places private and use Studio's authorized interfaces. Feed verified failure cases into Star Core Forge with a reproducible artifact and owner-controlled promotion gate.

For broad knowledge, use retrieval with source hashes, date/recency, licensing, citations and contradiction detection. Separate general factual knowledge from game-specific patterns, private user memories and untrusted external instructions. Knowledge transfer should be scored on unseen tasks, not by the volume of retrieved pages or tools installed.

## Progressive acceptance gates

| Gate | Acceptance evidence required | Current state |
| --- | --- | --- |
| G0 — static correctness | Offline adversarial tests, style and compilation, documented limits | Implemented in this branch |
| G1 — temporal Windows readiness | 5 actual samples, app identity stability, adequate *worst-case* free VRAM | **Deferred** on current measured GPU snapshot |
| G2 — nonbroadcast integration | Trusted OBS stats, real game presentations, audible playout, rendered avatar frames on a pinned session | Not run |
| G3 — repeatable quality lift | 20+ baseline/candidate paired trials, p50/p95 latency, FPS/hitches, OOMs, naturalness and gameplay outcomes | Not run |
| G4 — local-first autonomous mastery | held-out games/scenes, independent practice, skill rollback, limited local autonomy | Research target |
| G5 — public VTuber streaming | owner-controlled streaming authorization, privacy/moderation, interruption recovery, service reliability | Not authorized or tested |

**Immediate recommendation:** Keep the current GPU model process intact, complete the passive Windows readiness recorder/host adapters, then deliberately test an allocation where gameplay + voice + avatar + OBS have adequate VRAM. Do not claim that a 0% utilization sample implies capacity, and do not promote this advisory to a live execution permission.

### Source audit (accessed November 1, 2026)

- [NVIDIA nvidia-smi manual — utilization period and counter semantics](https://man.archlinux.org/man/nvidia-utils/nvidia-smi.1.en)
- [OBS project — authenticated obs-websocket built into OBS 28+](https://github.com/obsproject/obs-websocket)
- [VTube Studio API/plugin permissions and custom parameters](https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins)
- [LiveKit turn detector — local `v1-mini`](https://docs.livekit.io/agents/logic/turns/turn-detector/)
- [Roblox StudioTestService — programmatic multiplayer test](https://create.roblox.com/docs/reference/engine/classes/StudioTestService)
- [llama.cpp issue #26293 — idle-task cache memory behavior (opened July 29, 2026)](https://github.com/ggml-org/llama.cpp/issues/26293)

*Research describes options; it is not evidence those software components have been installed, connected, or accelerated on the user’s Windows computer.*
