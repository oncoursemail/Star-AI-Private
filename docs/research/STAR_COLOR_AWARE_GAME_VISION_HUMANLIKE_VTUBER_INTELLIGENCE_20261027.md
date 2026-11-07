# STAR: Color-Aware Visual Attention, Real Gaming Intelligence, and Natural VTuber Research
**Research and implementation date:** 2026-10-27
**Status:** Implemented in this branch: CPU color-aware sampling + freshness guard + offline tests. Everything else below is a *proposal*, not a deployed feature.
**Primary constraint:** local-first, offline-capable, RTX 4060 8 GB target; game FPS and spoken conversation take precedence over optional visual analysis.

## 1. A concrete failure uncovered in STAR's visual attention

The previous CPU visual novelty sensor used a 64-bit horizontal luminance difference hash (dHash) to decide whether a scene or HUD region warranted an expensive AI vision pass. It is intentionally insensitive to uniform brightness changes; unfortunately, **a solid red health panel becoming solid green can produce the same 64-bit dHash**, as can a scene that fades evenly from dark to light. A meaningful transition can therefore be discarded as a "duplicate" even when two frames look obviously different to a person.

This branch upgrades the already-authorized raw-frame intake to create two complementary signals in **one bounded sample pass per host-selected region**:
1. **Edge signature:** the existing 64-bit relative-luminance dHash for structural changes.
2. **42-bit tone/color signature:** six-bit bins for the average red, green and blue channel values, plus the average luminance of four spatial quadrants.

Both are intentionally lossy signals, computed from 72 evenly spaced 2×2 pixel blocks (no more than 288 pixels per ROI). This is not OCR, object recognition, automatic privacy protection, game-event verification, or vision-model inference. Tiny interface text or an icon outside the sampled locations can still be missed.

### Integration already added
- A raw host frame becomes a color-aware \`FrameCue\` through \`FrameCue.from_pixels\`; legacy trusted hosts that supply only an edge hash still work.
- Separate game and HUD crops each have both signals.
- The observation governor checks edge changes, tone changes, HUD edge changes and HUD tone changes **before** using its periodic-refresh fallback. One missing/changed crop scope is not quietly treated as comparable.
- Per-channel color changes, uniform fades, and sufficiently large quadrant shifts can request a fresh vision pass even if the relative edge pattern remains unchanged.
- Small color jitters remain subject to a threshold, and repeated frames retain a periodic-refresh floor.
- Out-of-order monotonic capture timestamps are rejected rather than feeding an older image back into a later gaming state.
- Existing consent checks, real hardware telemetry, low-FPS defenses, inference token bucket, single-flight worker leases, and physical-worker-stop quarantine remain in force.
- No new OS permissions, GPU workers, persistent images, network calls or model tools.

**Important truth boundary:** a color-aware frame admission means "this frame may be worth inspecting." It never means "STAR saw a death/win, understood an objective, or truly learned a mechanic." Such claims require subsequent vision/game observations and independently verified results.

### Offline acceptance tests added
- red ↔ green uniform HUD transition invisible to dHash but detected via tone bins;
- uniform gray scene fade caught despite identical dHash;
- two-level ambient gray jitter not treated as novelty;
- separate HUD vs game crop, compatible RGB/BGR/BGRA formats, alpha ignored, padded rows;
- strict unsigned bounds and thresholds, older-than-latest frame rejection;
- color changes cannot bypass inference rate limits or insufficient gaming headroom.

### Important remaining unknowns
- False positive/negative rates on actual gameplay recordings: **not measured**.
- Perceptual changes smaller than a 9×8 sample grid (health digits, icons, crosshairs): **not guaranteed**.
- Windows capture latency, avatar smoothness, Live2D integration, true game FPS, GPU inference speed: **not measured**.
- A trusted host must control the regions. Do not expose ROI selection or raw pixels as untrusted viewer/chat/model tools.

## 2. What external research changes STAR's engineering priorities

### Roblox's OpenGameEval (October 1, 2026)
Roblox researchers evaluated 13 models on 84 curated Studio tasks in reproducible stateful sessions and executable simulated play sessions. Their reported best single-attempt score was 51.7%, and inspecting the objects touched by the reference solution was associated with +13.4 percentage points on scene-only tasks, conditional on task and model. This is *association*, not a guaranteed gain from an inspection tool. The engineering implication for STAR is to inspect the exact scene, scripts, collisions, player spawn and game state **before edits**, and to score complete runtime behaviors after edits.

Sources:
- https://arxiv.org/abs/2610.02563 (published 2026-10-01)
- https://github.com/Roblox/open-game-eval
- https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic (2026-04-15)

### LiveKit's turn-taking tuning (current docs checked October 27, 2026)
LiveKit separates turn detection, endpointing, true interruption vs backchannel recognition, and preemptive LLM/TTS generation. Its current documentation emphasizes that preemptive generation does not always improve measured latency and should cancel speculative content when turns change. For STAR, unverified early hypotheses must **never be spoken as a final answer**, and an interruption should not corrupt the current gameplay or session identity. Natural timing requires measuring interruptions, silence, intelligibility and p95 first-audio latency together—not optimizing for continuous chatter.

Sources:
- https://docs.livekit.io/agents/logic/turns/tuning/
- https://livekit.com/blog/turn-detection-and-interruption-handling

### Pocket TTS v4.0.0 (October 20, 2026)
Kyutai's official v4.0.0 release includes English 18.2M/6.9M/1.9M-parameter voice models (and reflection variants), with CPU-oriented runtime packaging. These are attractive experiments **because they might reduce GPU contention**, not because small parameter count establishes humanlike emotion or voice quality. The official README describes streaming audio, CPU execution and model options. Before any replacement, evaluate voice identity, expressive prosody, safe and lawful cloning consent, first-audio latency, lip-sync timing, and intelligibility with noisy game audio.

Sources:
- https://github.com/kyutai-labs/pocket-tts/releases (v4.0.0, 2026-10-20)
- https://github.com/kyutai-labs/pocket-tts/blob/main/README.md

### llama.cpp SPEED-Bench / speculative decoding caveats
SPEED-Bench scores per-category latency, throughput and accepted speculative drafts; the latter is especially important because a predictor with low acceptance can make difficult or creative questions slower. A May 2026 llama.cpp issue supplied an example in which speculative decoding helped predictable code but regressed creative prose on its tested hardware. It is not STAR's benchmark result. Compare CPU-only, GPU-only and hybrid paths using **the same mixed workload and quality checks**, with VRAM, memory pressure, p50/p95 latency, and live game FPS as hard gates.

Sources:
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- https://github.com/ggml-org/llama.cpp/issues/23052 (opened 2026-05-14)

## 3. Concrete architecture for stronger gaming intelligence

**A. Fast reflex lane (target: milliseconds, not one language-model round trip).** Let the authorized host measure health/respawn, control state, camera pose and fast HUD changes; only already verified deterministic safe controls belong here. Observation admission never grants keyboard or mouse privileges. Budget this lane for game responsiveness, not prose.

**B. Visual understanding lane (event-triggered).** After frame novelty/scene change, run allowed lightweight CV or an actual VLM only if the hardware governor grants a worker lease. Return structured uncertain observations: object categories, UI text (when OCR is available), coordinates, confidence, viewport transform and timestamp. Quarantine outputs when worker/session/frame expires. No success claims from a fingerprint alone.

**C. Strategy lane.** Maintain a bounded local world-state hypothesis: objective, observed rules, known controls, current risk, planned action and confidence. For ambiguous controls, prioritize reversible probes and compare with prior verified mechanics. Use explicit planning budgets and report "unknown" when there is insufficient context.

**D. Verified learning lane.** Connect game actions to independently signed outcome evidence. Practice errors, calibrate predictions, and pre-register unfamiliar-level skill-transfer evaluations (without letting practice agents read holdout answer keys). Learn *skills and conditional strategies*, not just a list of successful button sequences.

**E. Curiosity lane.** Let STAR choose owner-approved private practice problems—movement timing, puzzles, navigation, combat fundamentals—and escalate complexity only after passing held-out tasks. Novel problem generation must not be counted as new intelligence without independent wins on unseen tasks.

Key metrics: success rate on held-out unfamiliar levels; sample efficiency (# attempts to reach a win); objective completion rate; calibrated confidence; damage/death rate; and game FPS. Report per-game and across-game statistics. A faster agent that guesses more is not smarter.

## 4. Make STAR a genuinely better Roblox game creator

Use the same evidence-first cycle for creative work:
**Intent/spec → inspect → scene graph → build → static geometry audit → Studio playtest → visual review → revise → independent acceptance.**

Priorities:
- semantic placement constraints: windows belong in walls, doors connect rooms, floors support objects; asset scale and pivot orientation must agree;
- collision/spawn/navmesh/physics checks, including rotated parts and imported meshes inside *real Studio*;
- compare reference and generated images at multiple camera angles, inspect lighting/PBR/UV/textures/material seams rather than relying only on code validity;
- animation contact sheets plus rigging and motion review: foot slide, interpenetration, blend transitions, props held with proper grip;
- UI legibility across desktop, tablet and mobile; no obstructed controls, clipping, collisions or unintended placeholder shapes;
- accessibility: readable contrast, motion-reduction option, subtitles and input remapping;
- licensed asset provenance and automated provenance checks before distribution;
- continuous multi-user playtest flows with gameplay objectives actually finishable.

STAR's local Core Forge should store the full source, experiment lineage, signed evaluations, rollback points, branch-like isolated changes, and test artifacts **without needing GitHub**. GitHub can remain an optional outbound review/publishing channel.

## 5. Make STAR more naturally humanlike on stream without inventing humanity

STAR can be expressive, engaging, and continuous as an openly AI VTuber, rather than implying she has a literal childhood or biological emotions.

Proposed coherent attention controller:
1. **Focused gaming:** stable gaze toward a game target, subtle blinking, hair inertial motion, short silence while aiming.
2. **Social listening:** naturally shift gaze, retain active speaking turn, use small acknowledgments rarely, respect real interruptions.
3. **Reaction:** tie happy/surprised/relieved responses to authenticated actual game events; react less often when repeated.
4. **Spoken delivery:** fine-grained TTS phoneme/lip-sync timing, speaking-speed and emotion controls with realistic pauses and occasional subtle laughter—not a canned laugh after every success.
5. **Avatar physics:** Live2D parameter layering, twin-tail swing, head tilt, eye vergence, blink timing, mouth open during speech only, framerate-independent damping. Honor reduced-motion toggles.
6. **Memory continuity:** retain owner-approved verified episode facts (game achievements, ongoing challenges, viewer opt-in context). Ask before storing sensitive viewer details. Never manufacture stream experiences.
7. **Playful modes:** chibi Star/Astro/Amber coexistence, cat/puppy modes and playful interactions within the same attention/animation conductor, without sacrificing game FPS.

Suggested evaluation: live human side-by-side blind listening, interruption-resume rate, speech delay, nonverbal expressiveness, viewer fatigue/speech density, lip-sync offsets, GPU FPS interference, and persona consistency. If silent concentration scores better than narration, STAR should be comfortable with silence.

## 6. Speed without sacrificing trust

For the planned 8 GB RTX 4060 PC and 32 GB RAM:
- Reserve GPU for the game first while live; place TTS on CPU when benchmarks justify it and defer optional vision work under low FPS.
- Use small models for simple routing, larger models only for demanding planning/debugging; failed verification routes to a stronger worker.
- Control KV-cache residency by active session and proven scope, not blindly cache every viewer text (privacy and stale-context risk).
- Benchmark prompt caching, mixed-context inference, speculative decoding and grammar-constrained outputs **per task category**.
- Bound each agent: max CPU cores, RAM, GPU VRAM, tool calls, task deadline, retries and safe rollback.
- Give the autonomous system offline practice windows and persistent checkpoints; game/stream processes get priority QoS.
- Distinguish **quality improvement**, **inference acceleration**, and **decreased analysis calls** in reports. They are not interchangeable.

For broad general knowledge, establish a provenance-bearing library of verified facts, API version stamps, contradictions, expiry dates and recall exercises. Knowledge is not assumed true merely because an LLM writes it. Re-reading a document is not independent evidence of retention; held-out answer checks and real project results are stronger.

## 7. Experimental gates, in order

**Gate 1 – CPU sampled vision (this PR):** all offline unit tests; no network/device access, no raw frame retention, no stale or out-of-order promotion, no realtime headroom bypass. Run the synthetic microbenchmark and publish the actual hardware details.

**Gate 2 – Windows replay, opt-in only:** collect owner-approved disposable game clips. Compare old dHash and edge+tone on annotated health-color changes, fades and UI changes. Measure true-positive rate, nuisance-false-positive rate, compute cost and memory allocations. Do not save identities or raw recordings by default. Evaluate missed thin UI changes explicitly.

**Gate 3 – Live capture integration:** use authorized Windows capture buffers already owned by a local host; feed game/HUD ROIs into the existing \`StreamVisionHost.consider_pixels\`. Verify worker stop/quarantine under disable, timeout, low FPS, stream restart, and shutdown.

**Gate 4 – Gameplay competence:** drive private authorized playtests with a pre-registered unseen challenge suite. Objective markers and signed outcomes must come from game telemetry/independent evaluator, never guessed from pixels.

**Gate 5 – Natural broadcaster:** test real microphone + VAD/STT + verified preemptive conversation + CPU voice + Live2D control + OBS. Measure p50/p95 listen-to-speech latency, p95 frame time, user interruption handling, word error rate, lipsync offset and fan/thermals. Gate launch on stability and owner inspection.

**Gate 6 – Learning/general intelligence:** run holdout tests on unfamiliar Roblox tasks plus at least two different game genres and a general-knowledge suite. Compare with prior version under equal compute and human adjudication; refuse "smarter" claims without meaningful improvement.

### Risks kept visible
Uniform color statistics may over-trigger on lighting/pulsing effects; aliasing can miss small sprites/text; low signal-to-noise can exhaust minute budgets; image crops can accidentally contain private UI. Favor specific host-defined crops, balanced thresholds, refresh floors, measured precision/recall and opt-in privacy controls. The current implementation is **an attention heuristic**, not autonomous mastery, learning, human consciousness, live VTuber rendering or guaranteed speed gains.
