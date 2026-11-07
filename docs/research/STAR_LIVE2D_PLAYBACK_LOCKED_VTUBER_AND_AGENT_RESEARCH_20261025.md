# STAR: Playback-Locked Avatar Control, Agent Intelligence and Low-Latency VTuber Research
**Research date:** 2026-10-25 (America/Chicago)
**Status:** one offline-tested Live2D transport adapter added; the rest is a prioritized experimental roadmap, not deployment evidence.
**Scope:** offline-first self-hosted Star; gaming and VTuber work should never force an unapproved broadcast or compromise GPU frame time.

## 1. The highest-value practical gap: real output, not imaginary animation

Star already has offline pieces for stream arbitration, host-provided voice activity, a motion planner, a stage manager that requires actual sound-device playback acknowledgement, and real-time trace capture. What was missing is a correct, bounded translation from **heard audio-aligned motion** to the existing Live2D desktop program's external parameter protocol.

New code: star/vtube_live2d_bridge.py, with offline tests in tests/test_vtube_live2d_bridge.py.

- Uses the documented VTube Studio API 1.0 request schema: ParameterCreationRequest and InjectParameterDataRequest.
- Produces 14 custom rig inputs for speech mouth envelope, eyes, smile, brows, head/shoulder movement, gaze, ears, tail and hair. Values and names are fixed by code; chat and models cannot select arbitrary controls.
- Emits frames only if the exact StarStage turn is **currently audible**, the same opaque playback epoch is active, the host-reported device cursor has actually reached that frame, the frame is within 100 ms of audible playback, time is monotonic, and minimum inter-frame spacing is met.
- Every accepted frame gets a unique request ID; duplicate/out-of-order/future frames are dropped. Late events from an interrupted or completed turn are rejected.
- After host-confirmed device stop, issues **one** full neutral-control reset for the matching epoch only; a stale old-turn reset cannot clobber a newer turn. Rebinding a retired turn is refused.
- Does not set the optional VTube Studio faceFound flag: this adapter does not assert real face tracking; face tracking remains owned by the application.
- All work is local and pure Python, with no devices, API token, audio, PII, network, VTS or OBS side effects. The authorized Windows host must authenticate VTS, create and map controls, send messages, handle responses, and flush outbound buffers on interruption. Before each send it must check stage.current(plan) (excluding the explicitly acknowledged neutral reset).

**Important limitation:** these are **normalized control targets**, not viseme-perfect speech or real Live2D physics. Hair and ear control channels do nothing until an artist maps them in the actual rig. Actual lip timing must be driven by a playback cursor from the sound driver, not by TTS generation time. A local transport must map to the rig and run an on-device rehearsal before any live show.

### Primary protocol source
DenchiSoft's official API documents unique alphanumeric parameter names 4–32 characters long, parameter-creation limits (100 per plugin), InjectParameterDataRequest with mode=set and weight, and the need to refresh active overridden values at least once per second. This bridge stays below those limits and emits on each played motion tick:
https://github.com/DenchiSoft/VTubeStudio

## 2. Human-natural presence: engineer turn-taking, don't fake humanity

The target is Star feeling present: attentive, reacting at the right moment, sometimes quiet, playful in a consistent original voice, and aware of her past verified gameplay. Star should remain clearly identified as an AI; real private experiences and invented personal history must not be passed off as actual human life.

A successful live pipeline has distinct clocks and evidence states:

1. Host-approved game event and moderated chat are observed, with a freshness timestamp and source confidence.
2. StreamDirector decides whether speaking is appropriate; intense gameplay may take priority over speech.
3. The conversation model writes a concise utterance or chooses silence. It can cite retained signed skill-bank evidence, not invented accomplishments.
4. The audio engine emits PCM chunks, records the sound device's actual playable samples, and marks the utterance *audible* only on playback acknowledgment.
5. The motion planner consumes audio energy and optional phoneme timing, never unplayed text.
6. The Live2D adapter converts only the corresponding current-epoch, already-reached motion frame.
7. Interruptions stop audio, flush outbound animation queues, and send a neutral reset. The voice turn is counted as complete only after audible end of the utterance.
8. Audio, input, expression and gameplay frame timing are recorded anonymously to compare candidate configurations. Raw chat/video is not needed for this timing loop.

**Specific improvements to investigate next:** streaming phoneme/vowel timing (rather than envelope-only jaw movement), restrained non-speech laughter breaths, asynchronous ear/tail physics authored in Live2D, anticipation/saccades keyed to actual observed game landmarks, and gaze-away pauses when concentrating. Avoid a fixed universal laugh or mandatory chat reply: authentic-feeling behavior includes silence and variation.

Moshi models parallel listening and speaking audio streams. The research repo advertises roughly 160 ms theoretical and as low as 200 ms practical latency on an L4 GPU; these figures are **not** a benchmark on Star's 8 GB GPUs. Benchmark full duplex only when resources permit, and compare against separate CPU TTS + voice-activity gate while playing a demanding game:
https://github.com/kyutai-labs/moshi

VTube Studio Live2D and VRM are **different runtime/rig standards**. If Star also has a VRM 3D model, VRM 1.0 defines aa/ih/ou/ee/oh procedural mouth expressions, blink/gaze and override semantics to avoid face deformation from conflicting animation layers. Do not send raw VRM morph names to VTube Studio without an actual rig mapping:
https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_vrm-1.0/expressions.md

## 3. Faster natural speech: update the tiny-TTS candidate set

Timeline correction: Kyutai released the original ~100M-parameter Pocket TTS in **January 2026**. On **October 20, 2026**, it introduced substantially smaller English families at ~18.2M, ~6.9M and experimental ~1.9M parameters; some have reward-tuned variants. Smaller does **not** guarantee better expressive quality, lower total device latency, or improved pronunciation. Tune on Star's exact voice and content:
https://kyutai.org/blog/2026-10-20-pocket-tts-small/
https://kyutai.org/tts/

**A/B protocol:** on the dedicated computer, compare 100M vs 18M vs 7M; include the 1.9M candidate only as experimental. Keep reference voice rights and license review separate from code. Use the same 100+ text utterances: game calls, error names, humor, punctuation, quick acknowledgments and unusual Roblox names. Collect p50/p95 time-to-first-audible PCM, real-time factor, peak RAM/VRAM, ASR intelligibility, owner blind A/B naturalness rating, silence handling and real-game 1% low FPS. Reject any candidate that substantially degrades quality or frame stability, even if raw tokens per second improve.

**GPU management:** a fast voice on CPU may beat an aggressive large TTS sharing 8 GB VRAM with a game. Preserve at least measured game headroom; drop optional vision/research jobs first. Different day/night workloads need different policies. Star's existing stream QoS modules already provide advisory resource admission and A/B trace capture; wire these to actual OS metrics, without confusing idle-time measurements with game-loaded measurements.

## 4. Learn actual games; validate capability, not self-assessment

For game playing:
- Establish authorized host capture+input with strict game focus and key release; currently the repo has StudioPlaytestHost and StudioOutcomeBridge abstractions, not a demonstrated live Roblox gameplay win.
- Group observations into semantic moments (health, obstacle, objective, damage, cooldown, reward) and maintain a bounded causal state with timestamps and uncertain fields.
- Separate exploration from exploitation: a model may intentionally practice skills with uncertain outcomes, but it must not rewrite the independent evaluation task or forge a success receipt.
- For **generalization**, split evaluation by game and mechanic: train on 2 obbies and evaluate on a withheld third; compare win rate, damage taken, time-to-goal, retries, and unseen skill adaptation. Require paired seeds and reproducible playtests.
- Start with deterministic Roblox Studio simulations via the first-party built-in MCP server. The March 5, 2026 Studio announcement says Studio can initiate/stop playtests and simulate user inputs:
https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/mcp.md

**Critical benchmark insight:** Roblox's OpenGameEval (October 2026) reports 84 curated core tasks, 13 models, 16 runs per task and executable validations of edited scenes + simulated play. Its paper finds inspecting objects before editing **correlates** with better success; this is a reason to evaluate Star's inspection-first policy, not to assume a guaranteed effect:
https://github.com/Roblox/open-game-eval
https://arxiv.org/abs/2610.02563

REKI (October 2026) demonstrates compact register-token history in a 2.4B vision-language-action robotics model and reports fewer oscillations. **Transfer hypothesis only**: give Star's game-action policy a small cached temporal state of recent verified observations, then A/B it against a stateless policy on a withheld set. Do not claim robot-success numbers apply to video games:
https://kyutai.org/reki/
https://arxiv.org/abs/2610.22178

## 5. Intelligence and generalized creative capability

Star should expand what she knows, but distinguish collection from intelligence:

- *Provenance ledger*: each retrieval stores license, source URL, source version, claim, observation date and counterexamples; hard-fail unsupported facts or expose explicit uncertainty.
- *Curriculum with uncertainty*: prioritize verified unknown mechanics, repeated failures and cross-domain gaps; a skill should graduate only on withheld problems, not training replays.
- *General-knowledge baseline*: use offline, frozen, versioned QA and reasoning sets; report by topic and difficulty, calibrated confidence, contamination controls and blind human comparisons. Never call a cached web page a new foundation-model capability.
- *Multimodal creation*: Roblox scene graphs, collision tests, screenshots, short video inspection, PBR/style reference and playtests all matter. Require unattached-walls, overlapping-props, texture and UI readability checks before presenting an asset as finished.
- *Self-improvement*: Star Core Forge should store internal experiment provenance, test receipts, rollback plan and change diff. Publishing an optional GitHub PR is not the core self-development engine, and nothing merges to main without the full green suite.

## 6. Optimize the user's hardware with measurements

Use a benchmark matrix with fixed model weights, quantization, context and prompt:

| Mode | Measures | Acceptance |
|---|---|---|
| Idle Star chat | time-to-first-token, tokens/s, accuracy, VRAM, RAM | faster with no answer-quality regression |
| Game + Star speaking | p95 first-audible PCM, 1% low FPS, p95 game input latency | no noticeable game/voice stutter |
| Game + Star researching | GPU spikes, background backlog, cancellation effectiveness | foreground game always prioritized |
| New game mechanic | held-out wins, failures, retries, generalization | improvement survives blind test |
| Building/animation | executable task success, layout overlaps, image/video defects | visual + engine correctness, not text claims |

llama.cpp supports multiple speculative-decoding variants and provides a SPEED-Bench client specifically for measuring latency, throughput and draft acceptance. Its maintainers have also documented cases where speculation becomes **slower**. Therefore benchmark a no-speculation baseline alongside draft/n-gram variants, using the exact game-active resource regime:
https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
https://github.com/ggml-org/llama.cpp/issues/10664

Avoid automatically loading large draft models onto the same 8 GB GPU merely because speculative decoding is available; extra VRAM can degrade the game.

## 7. Integration order and verifiable milestones

**M0 (this change; done locally):** offline protocol envelope, 14 custom params, playback-epoch gating, 100 ms freshness budget, frame-rate limit, neutral cancellation, replay/error tests.

**M1 (requires user's Windows VTuber rig, not done):** authenticate VTube Studio local WebSocket with explicit plugin permission; register custom params, map sliders to the **original Star** Live2D artwork, test eye/mouth/ears/tail/hair at 30 Hz. Capture a private, 3-minute audio+motion rehearsal. Fail closed on auth errors or missing mappings. No public broadcast.

**M2:** obtain real sound-card first-audible and end-of-playback callbacks; test 100 interruptions and 1,000 latency samples with simulated and real audio; inspect any lip-sync drift and send no frame when unavailable.

**M3:** run local TTS A/B matrix, measured CPU/GPU stream quality; test independent speech naturalness, laughter without fake events, chat interruptions, and low 1% FPS. Prefer lower latency **and** higher quality, not lower parameter count alone.

**M4:** connect authorized Roblox Studio gameplay loop to independent outcome evaluator; inspect game assets first, practice and compare held-out games. Record only signed, versioned practice results; don't publish user/private footage by default.

**M5:** add held-out general-knowledge/reasoning/visual-design challenges to Star Core Forge, paired quality/performance evaluator, and reversible candidate promotion. Only a reproducible improvement qualifies as "smarter" or "faster."

### Integrity and scope
No actual broadcast, installed TTS, live model, Roblox controller, VTube Studio socket, human voice imitation, or model-weight upgrade is claimed by this PR. All tests here are offline and simulated; publication as a draft PR must not be described as a real-game or voice-performance result.
