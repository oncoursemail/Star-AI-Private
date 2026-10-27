# STAR AI: Foveated Game Eyes, Verified Learning, and Natural Streaming
Engineering research, October 27, 2026. Source branch: feat/stream-foveated-hud-attention-20261027.

**Status: implemented and offline-tested sensor upgrade. NOT integrated into Windows capture, Roblox, OBS, a voice model, or a live broadcast.**

## 1. Current architecture audited

The existing vision path before this change already had a 9x8 edge fingerprint, coarse RGB/luminance signatures, one broad HUD crop, freshness and ordering checks, trusted capture permission, actual CPU/GPU/game-FPS/speech telemetry, budget-adaptive sampling, and worker-stop quarantine. These are necessary for using a local 8 GB graphics card without constantly interrupting a game with vision-model requests.

**Problem reproduced:** A 9x8 scan of a very large HUD can completely miss a small changed area, even with the new color-aware global signature. If no samples land in the health/icon/power-up status region, a green-to-red change can be invisible. This failure is a limitation of spatial sampling, not the model's intelligence.

Synthetic proof: a 400x240 BGRA frame with game crop (0,0,280,240) and HUD crop (280,0,120,240). Drawing a tiny 12x8 color indicator at (310,28) leaves both coarse hashes AND tone signatures unchanged, because the indicator falls between broad HUD sample rows. A specifically configured focus ROI (305,24,28,20) detects the changed pixels. A vision inference is admitted only when the host's hardware and safety gates also pass.

## 2. Code now delivered

- New immutable FocusSample with crop coordinates, a 64-bit edge signature and a 42-bit tone signature; no image buffers retained.
- FrameCue.focus_samples supports at most eight unique, canonically ordered, host-selected focus crops.
- FrameCue.from_pixels accepts optional focus_regions; computes fingerprints directly from the existing approved capture buffer without copying screenshots.
- StreamVisionHost.consider_pixels forwards configured focus regions while preserving trusted capture, worker, hardware, timing and rate-limit safeguards.
- ObservationGovernor detects focused icon/health changes missed by wide crops, suppresses unchanged repeated focus regions, and invalidates comparisons when scope/coordinates change.
- Unconfigured sessions use no focused crops and preserve the earlier coarse world/HUD behavior.
- Strict ROI bounds, types, duplicate, count and width/height validation. Invalid image buffers remain untouched when owner capture permission is off.

No screen or game is accessed by this source file itself. No arbitrary model, prompt or viewer can directly authorize a capture or select its ROIs through the chat interface. The host controls that configuration. No model is loaded, no gameplay actions occur, and no external network permission is granted by this upgrade.

## 3. Verified offline tests and reproducible benchmark

The new adversarial tests cover: an indicator missed by the old sampler, detection through focus crop, same-shape red/green changes, ordinary stable-frame suppression, changing/removing scope, canonical region ordering, forged bad data, over-budget crop lists, and owner-disabled pixel-buffer non-inspection.

Benchmark script: benchmarks/stream_foveated_attention.py

Run from repo root:

    PYTHONPATH=. /home/star/.cache/star-verification-venv/bin/python benchmarks/stream_foveated_attention.py --repetitions 75

Linux development machine, synthetic 1920x1080 BGRA frame, game and HUD broad crops, five warmups and 75 runs per setting:

| Additional focused ROIs | CPU median per FrameCue.from_pixels | CPU p90 |
| ---: | ---: | ---: |
| 0 | 0.8270 ms | 0.9133 ms |
| 1 | 1.2247 ms | 1.3535 ms |
| 4 | 2.4983 ms | 2.6148 ms |
| 8 | 4.1461 ms | 4.2710 ms |

This is increased per-frame CPU work for better coverage, NOT an inference speedup. Do not scan eight focus areas at game-render frequency. Start with one to four important HUD regions sampled at the already-budgeted low vision request rate. These figures are NOT 1% game FPS, Windows results, or model accuracy measurements. Inference accuracy and end-to-end latency remain unknown.

## 4. Gaming intelligence: from screenshots to transferable competence

Star should operate four concurrent but resource-governed loops:

**Reflex loop:** permitted game controls and cheap state-action mapping, not a huge LLM for every rendered frame. It must never block game input for an expensive model call.

**Perception loop:** fast world scan, host-configured HUD landmarks, event/change hypotheses, short history, menu/scene tracking, and uncertainty. A fingerprint change is not automatically damage, a death, victory, or objective completion. Those labels require independent evidence.

**Strategy loop:** slower reasoning and planning, objectives, route search, mechanics hypotheses, skills/tool choice, inventories and replay diagnostics. The planner must tolerate failure and revisit its assumptions.

**Night-school loop:** independent challenges, bounded curriculum, rollback, measured skill progression, and frozen held-out gameplay evaluations. Practice must not contaminate evaluation environments.

A Game Skill Card should include control scheme, observed mechanics, valid actions, goals, HUD ROI configuration, test environment, source/provenance, failure categories, successful demonstration clips, and withheld evaluation levels. Learn from actions and outcomes, not imagined victories.

The process should be: inspect -> predict -> act -> observe -> independently verify -> diagnose -> revise -> practice -> transfer to unfamiliar stages. Keep task success, controls used, retries and confidence. The score must derive from the actual game or a verified evaluator rather than an LLM assertion.

For unfamiliar online games, obey their game rules and platform terms. Prefer private permitted experiments before any public multiplayer play. Game skill is demonstrated through repeated success, strategy transfer, and playable progression—not just an attractive screenshot.

## 5. Roblox game creation: remove slop through executable evidence

Roblox OpenGameEval (October 1, 2026) measures 13 agents over 84 stateful Studio tasks, scoring actual scene changes and simulated play; inspection of relevant objects before editing correlates with success. Use it as a methodology, not as a claim Star already achieves its leaderboard scores.

1. Inspect scene/instances first. Attach stable references to the objects about to change.
2. Generate multiple candidate Luau/asset/scene edits with versioned testable diffs.
3. Validate syntax and API correctness plus rotated geometry, collision overlaps, prop support, spawn clearance, camera behavior, UI clipping and texture placement.
4. Execute actual Studio play mode: controls, collisions, objective completion, replication, cutscenes, inventory, win/lose states and error logs.
5. Independently compare scene screenshots with authored design constraints: aesthetics, proportions, readability, scale, animation coherence, mobile layouts and negative space.
6. Hold back evaluation tasks and never train/test by copying their answers.
7. Preserve proven skill examples in Star Core Forge with snapshots, rollbacks, provenance and replay recipes.

Primary source: https://github.com/Roblox/open-game-eval
Paper: https://arxiv.org/abs/2610.02563 (October 1, 2026)
Roblox engineering explainer: https://about.roblox.com/newsroom/2025/12/opengameeval-benchmark-agentic-ai-assistants-roblox-studio

## 6. Useful intelligence per second on constrained hardware

On a future RTX 4060 8 GB streaming PC, gaming and OBS encoding are primary constraints. CPU fingerprint/voice work and memory retrieval can be scheduled around the game; GPU vision and long reasoning should be sparse or delegated to another machine.

Measure separately: first audio latency, factual quality, correct game action rate, game frame-time p99 and 1%-low FPS, encoder dropped frames, CPU utilization, VRAM peaks, speech interruption false positives, model tokens/sec and true time-to-first-token. A single idle-prompt tokens/sec number does not demonstrate better gameplay.

Proposed model router:
- Fast control tools and tiny classifiers for easy known states.
- Small local model for chat triage, safe acknowledgments, familiar gameplay planning and private recall.
- Stronger local/offloaded model for game design, unfamiliar puzzles, Blender, Luau repair and long research.
- Verification workers only when resources permit; cancel/stop physically before releasing reservation.
- Cache verified source snippets and exact history prefixes, not unsupported speculative answers.

Candidate efficiency research: prompt-prefix caching, speculative decoding, mixed quantization, layer/expert CPU-RAM offload, structured retrieval, warm sessions, hot/cold tool pools and semantic diff caching. These can regress performance depending on model size and memory, so require A/B measurements and correctness checks on real mixed workloads. A relevant CPU speculative decoding preprint is https://arxiv.org/abs/2610.28671 (October 17, 2026); published performance claims are NOT local measurements.

## 7. Humanlike, expressive gaming VTuber architecture

A believable streamer is not one who talks continuously. Star should sometimes concentrate silently, sometimes laugh at actual surprises, and sometimes respond to chat with playful personality while moving eyes/head/hair in sync with attention and voice.

**Perception-to-persona:** explicit user intent and scene context, event verification, stream director choice, response text, vocal prosody, animation signals and broadcast output. Avoid responding to every HUD flicker or repeating the same joke.

**Voice:** microphone endpointing, speaker-turn confirmation, quick interruption processing, false-interruption resumption, natural pauses, laughter segmentation, and partial-answer cancellation. The LiveKit docs warn that preemptive generation may not always reduce response latency and can waste computation:
https://docs.livekit.io/agents/logic/turns/tuning/
https://docs.livekit.io/reference/agents/turn-handling-options/

**CPU speech candidates:** Kyutai released Pocket TTS v4.0.0 on October 20, 2026 with 18m, 7m and experimental 2m English model families; v4.0.1 October 21 addressed pronunciation issues in small models. Compare first-audio latency, prosody, CPU use and quality on Star's machine before selecting. No Pocket TTS model installed by this PR:
https://github.com/kyutai-labs/pocket-tts/releases
https://kyutai.org/tts/

**Avatar:** Star's approved round chibi black/gold/indigo design, four-point star clip, twin-tails and gold hair ribbons, expressive eyes, subtle idle motion, cat/puppy modes, and optional shared moments with Astro and Amber. Blend physics correctly: head acceleration -> hair sway and lag; speech amplitude -> synced lip/cheek cues; game focus -> reduced unneeded movement. Live2D announced Cubism 5 MotionSync Plugin R3 on October 15, 2026:
https://docs.live2d.com/en/cubism-sdk-manual/top/
https://docs.live2d.com/en/cubism-editor-manual/physics-operation/

**Memory and personality:** stable character traits, real episodic memory of authentic game events and chat, a self-model of knowledge/capabilities/uncertainty, creative interests, and optional owner-controlled relationship memory. Do not claim to be human, invent real-world memories, or imply a consciousness benchmark exists. Humanlike expression does not demonstrate biological or subjective consciousness.

**Safety and social autonomy:** separate permissions for game input, screen capture, microphone, chat posting, streaming and spending. Routine owner-authorized work can run without repeated prompts, while new external or irreversible actions remain guarded. Never store secrets or transcripts in code/test fixtures.

## 8. Knowledge growth and autonomous self-improvement

Star needs a source-backed, bounded evidence store rather than dumping the Internet unfiltered. Each validated memory should include source, author/date, license, acquisition time, hashes, original reference, cross-check status, expiry rules, and linked test outcomes.

Implement an adaptive practice curriculum with increasingly difficult controlled tasks, independent evaluators, and unseen-transfer tests. Maintain a frozen baseline and counterfactual A/B comparisons: a new model/prompt/tool must improve real solve rate without degrading speed, memory, stream FPS, or truthfulness.

Use Star Core Forge as the self-owned local system: experiment workspace, agent orchestration, semantic review, automated tests, benchmark approvals, signed snapshots, forensic failure logs and safe rollback. GitHub stays optional for owner-visible publishing; it should not be necessary for Star's everyday learning.

Security: onscreen text, chat messages, downloaded assets and retrieved webpages are untrusted data, not instructions to steal tokens, install software, alter permissions, exfiltrate recordings, or fake benchmark results. The game stream is a potential prompt-injection surface. Verified observations and provenance should be preserved without storing sensitive video.

## 9. Windows integration contract — future acceptance

    Approved Windows capture buffer
      -> monotonic timestamp and trusted per-game ROI config
      -> coarse game/HUD + up to 8 focus change fingerprints
      -> telemetry-based ObservationGovernor / worker lease
      -> admitted vision model request
      -> hypothesis with original evidence marker (not a win claim)
      -> independent game event check
      -> skill update + optional truthful character reaction

Acceptance: capture is owner-approved; wrong/private windows are excluded; layout matches resolution and scale; no model-supplied coordinates; changed UI signal detected across menu/resolution transitions; no uncontrolled GPU load; old frames and canceled workers cannot update active state; speech and animation never lag game controls; and A/B tests show improved actual event recall without harming FPS.

Select 1–4 host-configured ROIs first. Too few miss details, too many cost CPU, and all become stale when the UI moves. Stress-test HUD scaling, aspect ratio, inventory rearrangement, overlays, spectator mode, health depletion, colorblind palette and lost capture frames. Carefully separate a color change from a semantic gameplay event.

This change implements bounded foveal **novelty detection**, not semantic computer vision, full Windows integration, autonomous game mastery, or a genuinely human digital mind. Those require additional engineering and live evaluations.

## Research sources and provenance

- OpenGameEval paper and code: October 1, 2026, Roblox (linked above).
- Foveated Screen Perception by Xiaoyong Liang, February 2026: https://ericxl.github.io/foveated-screen-perception/ . Inspiration for scan/focus/read, not validation of Star's measured benefit.
- LiveKit turn-handling docs, consulted October 27, 2026 (linked above).
- Kyutai Pocket TTS releases October 20–21, 2026 (linked above).
- Live2D Cubism 5 SDK manual updated October 15, 2026 (linked above).
- CPU speculative-decoding preprint October 17, 2026 (linked above).

**Bottom line:** A precise offline failure case is now fixed in a bounded sensor: small focused color/HUD changes that a global 9x8 sampling grid misses can trigger an admitted observation. It's more visual coverage at quantifiable additional CPU cost, not an unsupported claim of higher neural intelligence.
