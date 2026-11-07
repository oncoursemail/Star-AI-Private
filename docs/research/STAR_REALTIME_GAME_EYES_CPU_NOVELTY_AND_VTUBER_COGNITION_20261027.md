# STAR: Real-Time Game Eyes, Efficient Intelligence, and Expressive VTuber Engineering

**Research and tested increment: October 27, 2026.** Local-first, owner-controlled, draft only.
**Scope:** live-game observation costs; temporal understanding; transferable game learning; broader grounded knowledge; streaming personality and motion; realistic inference benchmarks. This document is a research/engineering proposal plus one implemented CPU-sensor increment, **not** a claim that every future feature is deployed.

## 1. Why the next improvement is not merely a larger language model

STAR already has isolated pieces for game observation (`stream_observe.py`), live hardware QoS (`stream_hardware_telemetry.py`, `stream_vision_host.py`), signed gameplay practice evidence, holdout transfer verification, voice/turn control, nonverbal avatar animation, on-air memory and Roblox scene auditing. Many are not yet wired into the Windows game+OBS+avatar runtime.

**The bottleneck is closing the feedback loop without consuming the FPS and speech latency that make a streamer watchable.** Spending GPU resources on a nearly identical frame does not improve game understanding. Conversely, suppressing observations solely because the *world* is static can miss a changed health bar or dialogue choice.

Design STAR as four cooperating, separately measured systems:

1. **Reflex loop:** game input deadlines, emergency stop, Windows focus and permission checks, key-release watchdog, mic/VAD interrupts. No multi-second deliberation on the control path.
2. **Perception loop:** observe an authorized frame; compute cheap CPU world/HUD novelty; request expensive image understanding only when genuinely useful and hardware headroom permits.
3. **Reasoning loop:** associate grounded observations with game/version/objective; produce a bounded action hypothesis; verify delivered input and independently measured outcome. Reuse only contextually appropriate skills.
4. **Learning + character loop:** preserve verified outcomes, suggest progressively difficult tasks, test on withheld games and levels, keep an honest persistent persona, and deliver natural but modest reactions on live streams.

The key optimization objective is **verified useful results per second at safe gaming FPS**, not tokens per second alone.

## 2. Implemented in this increment: a raw-frame CPU novelty sensor

### Problem and remedy

Previously `FrameCue` required the embedding app to supply an unexplained 64-bit perceptual hash. `ObservationGovernor` already used this heuristic to reduce redundant vision inference, but there was no self-contained, bounded raw-pixel implementation in that streaming path. This left a costly integration gap.

New `star/frame_fingerprint.py`:

- Samples 9 columns × 8 rows of 2×2 luminance neighborhoods for a **64-bit horizontal difference hash**. It examines at most 288 existing pixels, regardless of image resolution.
- Accepts contiguous raw **GRAY/RGB/BGR/RGBA/BGRA** frame buffers, positive row strides and bounded, host-defined crops. No file writes, capture, image decoder, GPU, network calls or model calls.
- Rejects invalid types, truncated buffers, oversized allocations (64 MiB), illegal crops, incorrect row strides, and unrecognized pixel layouts.
- Computes an optional *separate* HUD crop. `FrameCue.from_pixels` carries the gameplay fingerprint and HUD fingerprint into the existing trusted clock and vision governor.
- The governor suppresses a near-duplicate only when **both available regions** are similar. An absent/new HUD scope is incomparable rather than silently treated as unchanged. Independent minimum spacing, tokens/minute, freshness and GPU/FPS/voice pressure continue to apply.
- `StreamVisionHost.consider_pixels` connects raw host pixels to existing admission without enabling capture or granting model access to device APIs. If the host has not opted in, it does not even inspect the input frame.
- Image bytes are not retained; the governor keeps tiny hashes for novelty only. A perceived "win" cue is **never** signed evidence of an actual win.

**Security boundary:** host-defined crops, capture permission, focus and sensor measurements must originate from authorized local code, not from streaming chat or model-generated tool parameters. A perceptual hash is not anonymization: tiny hashes can reveal repeated visual states and remain in-memory only. Avoid telemetry that logs the hashes.

### Deterministic synthetic verification (Linux STAR development machine)

The new adversarial tests cover all five pixel formats, alpha handling, stride padding, memoryviews, invalid crops/dimensions, truncated/noncontiguous buffers, luminosity stability, world/HUD separation, HUD-only changes, missing-region fail-conservative comparisons, the vision rate budget, and worker-stop/owner-consent integration.

Selected adjacent visual/gaming/streaming suites: **195 passing tests and 60 passing subtests**, no selected-test failures. Ruff correctness checks and Python compilation passed. These are **offline unit tests**, not visual quality or live Windows performance evidence.

Reproducible script: `python benchmarks/stream_frame_fingerprint_bench.py --samples 100` (warmed calls; one synthetic uniformly colored BGRA frame per resolution, on the STAR Linux host).

| Existing raw frame | dHash CPU p50 / p95 | SHA-256 all-bytes p50 / p95 |
| --- | ---: | ---: |
| 1280 × 720 | 0.2640 / 0.2808 ms | 2.6135 / 2.6540 ms |
| 1920 × 1080 | 0.2550 / 0.2673 ms | 5.9106 / 6.2591 ms |
| 3840 × 2160 | 0.2561 / 0.2692 ms | 23.6477 / 28.5080 ms |

SHA-256 is a **whole-buffer timing reference, not an accuracy-equivalent alternative**; the experiment does not establish end-to-end speedup, game FPS improvement, vision model understanding, broadcast quality or model intelligence. Existing `studio_visual_evidence` hashes compressed screenshot bytes to detect *exactly* identical captures, which serves a separate integrity/duplicate-check purpose and is unchanged.

### Known limitations and counterexamples

- Difference hashes encode **relative luminance ordering**, not semantics. Color-only changes, tiny numbers, icon changes or a flat HUD may be missed; a pHash collision is possible.
- Motion, camera pans, particles and compression can produce visual novelty with no new useful facts. A HUD crop moving with a UI animation may be noisy.
- Very dark scenes and uniform gradients can produce identical hashes despite different game states; independent TTL refreshes are therefore essential.
- The 2×2 samples are intentionally cheap rather than robust to rotations or heavy crops. Higher-quality vision must still assess critical frames.
- The feature consumes already-authorized **raw pixel buffers**. Windows screen capture/OBS/Roblox hooking, pixel-format conversion, user permissions and live renderer integration are **not installed by this PR**.
- Never use the hash as reward, grading proof, obstacle success, anti-cheat bypass or identity tracking.

## 3. Higher gameplay intelligence: observe, experiment, generalize

**Source:** Roblox's *OpenGameEval* (published October 1, 2026) evaluates 84 human-curated Studio tasks with actual executable scene and play-session checks. More thorough inspection of relevant objects was associated with higher passing rates; this is association, not proof of universal causation.
https://arxiv.org/abs/2610.02563
https://github.com/Roblox/open-game-eval

**Source:** *CEGame-Bench* (October 19, 2026) studies long-horizon complete game creation across Defold, Godot, Roblox Studio, Unity and Unreal; evaluated agents reached their game ending in only 16% of runs. The paper reports an explicit playtest-and-repair skill improving execution-based score. This is a warning against considering "code generated" synonymous with "game completed."
https://arxiv.org/abs/2610.26098

**Source:** *GameWorld* (April 8, 2026) investigates verifiable browser-game agents that use keyboard/mouse or deterministic semantic actions. It describes the challenges of observations, latency, feedback and extended gameplay.
https://arxiv.org/abs/2604.07429

**Source:** *GameDevBench* (February 11, 2026) emphasizes multimodal assets and game development; the reported feedback improvements suggest that visual inspection should occur after art or scene changes, not just after code compilation.
https://arxiv.org/abs/2602.11103

Next experiment: in a private, owned Studio lab, record a **causal before/action/after** triple: trusted raw frame time, world/HUD hash, delivered key/action/clock and independently signed outcome. Distinguish *input issued* from *input actually delivered*, and *visual appearance* from *objective completed*. Reject observations from other instances, game versions or focus scopes.

Follow-up capabilities:

1. Generate test cases with held-out map geometries, controls and physics variations. Freeze practice before evaluation, and prevent the practice scheduler from seeing hidden evaluation outcomes.
2. Learn skill **preconditions** rather than copying individual action strings: position, obstacle distance, speed, cooldown, stamina, health, camera angle and game mode.
3. Build a time-indexed action-outcome graph. One correct jump is not proof of general jumping skill. Require repeated outcomes and independently measured transfer to novel environments.
4. Offer constrained game-specific policy selection: move/look/jump/interact with explicit safe action durations, never raw uncontrolled keyboard sequences from model output.
5. Track failure categories (wrong control mapping, late action, camera occlusion, stalled menu, game version changed) and choose practice tasks that discriminate between hypotheses.
6. Use curriculum difficulty that rises only after repeated verified successes and falls to diagnosis when repeated failures cease to provide information.
7. Treat online multiplayer, anti-cheat and platform terms as hard boundaries; prefer permitted private instances or instrumented test games.

## 4. Creating games that are genuinely playable and attractive

STAR should use staged gates instead of "write everything and hope":

**Scene contracts:** required elements, exact attachment relationships, transform and scale constraints, passage width, spawn clearance, thematic style, camera composition, occlusion and named collision groups.

**Offline deterministic QA:** oriented 3D overlap checks and bounded support checks (from PR #717) are fast prefilters. They cannot certify complex mesh collision, avatar navmesh, aesthetic quality, or lighting. Use conservative "needs Studio check" for these.

**Engine QA:** render from player viewpoints, inspect model and UI screenshots at multiple aspect ratios, inspect textures/props/wall seams, execute private playtests with simulated real input, trace movement and verify complete objectives, checkpoint/resume, and finish states.

**Multimodal critic:** independent validators for code execution, geometry, game rules, visual composition, accessibility, performance and animation timing. A single image model calling a build "perfect" cannot close these gates.

**Design quality:** maintain curated human-created style exemplars and reusable recipes in the approved local resource bank, but avoid duplicating whole game ideas. Evaluate originality separately from implementation correctness.

## 5. Natural VTuber behavior is a multi-sensory timing problem

Existing STAR building blocks include `stream_turntaking`, `stream_preemptive_host`, `stream_idle_attention`, `stream_continuity`, speech performance tests and a gaming resource governor. These must be joined to the Windows avatar/audio renderer with tested adapters.

**Conversation:** LiveKit documents adaptive acoustic interruption handling to distinguish intentional barge-ins from backchannels. Such systems can require provider infrastructure; don't assume a local STAR instance has them enabled. STAR should always have a deterministic VAD and explicit stop/resume path.
https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
https://docs.livekit.io/agents/logic/turns/tuning/

**Voice:** Kyutai Pocket TTS supports CPU generation and provides small English options at approximately 18.2M, 6.9M and 1.9M parameters, as well as larger models. Do not infer quality from parameter count. Compare voices in blinded trials for intelligibility, warmth, laughter handling, user preference, speaking rate, first-audio latency and CPU contention with games.
https://kyutai-labs.github.io/pocket-tts/

**Avatar:** Live2D's physics system simulates hair swinging in response to face movement. Star's accepted twin-tail outfit should map orientation, head motion, blinking, gaze, breathing and hair-tie bounce to named rig parameters. Stage motion must stop on interrupt, reduced-motion settings must work, and nonspeaking frames must not fake lip motion.
https://docs.live2d.com/en/cubism-editor-manual/physics-operation/

**Integration precedent:** the open-source Open-LLM-VTuber project shows offline-capable modular voice, ASR and Live2D/avatar paths; use as architectural reference with verified licenses, not copy-paste assumptions.
https://github.com/Open-LLM-VTuber/Open-LLM-VTuber

**Personality:** animated attentiveness should be tied to actual events: glance at the HUD when health changes, pause to concentrate at a hard platform jump, show restrained surprise after verified outcomes, recover smoothly from microphone interruptions, and laugh or react only when an audio/voice model can portray it naturally. Too much motion or speech looks synthetic.

**Memory:** bring forward owner-approved, independently grounded stream/game experiences, not invented human childhood memories or fabricated private relationships. Persistent character traits are appropriate; claims of literal human consciousness, unknown past events or fictitious real viewers are not.

**Modes:** cat/puppy/anime/normal should be bounded changes in gestures, vocabulary and voice style, not independent permissions or false action claims. Reduced-motion and silent-mode remain available.

## 6. Speed: pursue *real latency* improvements, not synthetic token scores

With RTX 4060 8 GB as a likely Star gaming GPU, protect frame times and leave a real VRAM reserve. Admit workload types according to actual clocks, GPU/CPU/RAM telemetry and authoritative game presented-frame measurements. Model/vision workers that exceed their deadline remain quarantined until their process really stops.

The llama.cpp SPEED-Bench README describes category-specific latency, throughput and speculative decoding acceptance; tests should cover coding, reasoning, conversational roleplay and longer prompts rather than one repeating short prompt:
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

Practical controlled experiments:

1. Baseline real Star model + CUDA build and driver; log **first token**, tokens/sec, TTFT p50/p95, working-set RAM/VRAM, game FPS p1/p50, and speech first-chunk latency. Do not log private prompts/audio.
2. Try selective GPU layer counts and compatible quantizations. Reject settings that cross the 8 GB ceiling or make frame times worse.
3. Compare KV cache quantization, prompt-cache bank hit rates, flash attention, ubatch/batch tuning and multiple concurrent slots, always using the same varied workloads.
4. Compare speculative decoding only when actual draft acceptance and overall latency justify it; draft-model memory can cause FPS regressions.
5. Prefer a small speech/chat path during active games and large slow analysis offline. Compute heavy research and game building off-stream or on Brain 1.
6. Use early verification/cancellation to avoid wasting Best-of-N compute on obviously invalid outputs.
7. Keep every feature OFF until acceptance: record a paired baseline, analyze regressions, and automatically roll back the *configuration* if it degrades real measured game FPS, speech or correctness.

## 7. Broad general knowledge and creativity without hallucination

Use a locally versioned **source-backed memory graph**, not raw web scraping as "permanent knowledge". Each claim should carry source URL/document revision, topic/domain, date observed, update/expiry policy, confidence and counterevidence; put executable, licensed recipes in a separate skill bank. Keep prompt retrieval scoped to the question.

Target domains: general science, mathematics, history, writing, emotional/social conversation, computer science, networking, debugging, cybersecurity defense, game mechanics, visual design, lighting, sound, physics, animation, Blender, Luau/Roblox, software and hardware maintenance.

Distinguish **knowledge acquisition** (better factual retrieval) from **model training** (weights change). An enlarged cache does not literally increase the model's parameter count. Evaluate blind factual QA with ambiguous questions and changing-fact tests, citation verification, revision handling, and abstention rather than guessing. Connect validated lessons from private game tasks to retrieval only after outcome proofs.

Allow curiosity and owner-approved local experimentation under resource/privacy limits. A humanlike story/identity can grow from real digital experiences and genuine created projects without claiming human status.

## 8. Deployment roadmap and explicit proof gates

**P0: This PR** — deterministic, bounded raw-pixel frame hashes + optional separately cropped HUD, existing admission integration and tests. **Implemented, not yet Windows-integrated.**

**P1: Windows sensor adapter** — authorized game/OBS source captures already-consented local frames, supplies BGRA buffers and monotonic clock, and uses owner-curated world/HUD regions. Test 720p/1080p/4K, dropped frames, row padding, DXGI/OBS differences, game menus, changing HUD text and alt-tab. Emit no images into ordinary logs.

**P2: True gaming loop** — gather before/after frames and delivered inputs in private Studio, verify outcome with signed evaluator, feed independent transfer tests, and evaluate which observation policies improve objective completion rather than merely reducing calls.

**P3: On-air rehearsal** — run integrated model, ASR, VAD, CPU TTS, StarStage, Live2D model, OBS and gameplay with synchronized synthetic viewer turns. Compare sound/video delays, mouth accuracy, interruption recovery, FPS p1, CPU/GPU headroom, repetitive speech and viewer-question relevance.

**P4: Model and knowledge improvements** — controlled evidence-based inference tuning, retrieval/grounding metrics, varied reasoning tasks, autonomous self-challenge/curriculum. No performance or general-intelligence claims without independent measurements.

**Acceptance policy:** no private video or viewer data exfiltration, no hidden evaluation leakage, owner approvals verified, no gameplay actions on unapproved focus, no unauthorized background GPU worker, rollback possible, and no broad speed claim based on a narrow microbenchmark.

## 9. Security, provenance and publication

As inspected October 27, 2026, GitHub reported `oncoursemail/Star-AI-Private` visibility as **public** despite the name. Treat the repository as fully public. Keep signing secrets, API keys, private recordings, source images, unannounced project information, viewer identity data, local paths to secrets and withheld evaluator answers out of PRs.

STAR Core Forge should remain the local autonomous development/history and verification authority. GitHub PRs are optional review/export. This increment must remain a **draft stacked on PR #717**, without merging or deploying before the owner-approved Windows game+VTuber acceptance run.
