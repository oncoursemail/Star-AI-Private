# Star AI: PCM-gated live captions, game mastery, general intelligence, and believable VTuber behavior
**Research and proposed integration — October 29, 2026**

## What actually shipped in this increment
- `star/stream_audible_captions.py` adds **AudibleCaptionLane**: optional captions aligned to the *same* host-verified PCM playout frames that already drive Star's Live2D timing. Requires the existing StarStage, StarPlayoutClock and DeviceAudibleSampleHost. Off by default; owner approval **and** independent on-air approval of the TTS text are required.
- `tests/test_stream_audible_captions.py` exercises the **real Python Stage/Clock/Device objects** with a fake monotonic clock. This is an offline regression suite, **not** a real WASAPI/OBS broadcast test.
- A short, approved phrase appears only after a trusted output backend advances the **consumed** sample cursor into the phrase's independently aligned PCM interval. Merely generating or queuing TTS does not show captions. Pauses, stale playback frames, interrupts, completed playback, invalid stages and stopped epochs cause silence (the overlay must actively blank). A second render-time `current()` check blocks old frames.
- A host can use one PlayoutRigFrame for both Star's VTube Studio animation lane and captions, avoiding an extra inference pass, duplicate playout sampling or an independently drifting subtitle clock.
- No OBS browser overlay, forced alignment model, physical audio-device observer, microphone capture, web transport, gaming input, user data export or neural retraining is included. Caption chunks and timings are supplied by the trusted host; **this component cannot prove word-level acoustic accuracy**.

## Exact host integration protocol
1. Start a trusted, authorized StarStage speaking turn and arm its StarPlayoutClock with the TTS audio track. Ensure the output backend actually consumes PCM and reports played frames to DeviceAudibleSampleHost.
2. The TTS/voice host must produce **approved, short, ordered PCM sample intervals** for the audio it is going to play. **Do not** align captions to generated text tokens, estimated TTS generation time, a chat message, or a previous voice turn. For a chunk with unknown alignment, omit its caption rather than guess.
3. Opt in via `lane.enable(owner_approved=True)`, then `lane.bind(plan, epoch, chunks, text_approved_for_broadcast=True)`. Owner/moderation approval must originate from the authorized host, not a viewer or model.
4. When `device.report_played(...)` succeeds, call `rig = device.sample(epoch)` **once** and fan out that exact frame to both avatar and caption consumers. Call `proposal = lane.sample(epoch, rig)`. Just before publishing text to a rendered overlay, require `lane.current(epoch, proposal)` and revalidate any separate broadcast permission.
5. Treat `None` or false `current()` as an explicit **clear caption** action. A *browser/OBS renderer* must set `textContent` or use an escaped text API, never interpolate the caption into raw HTML. Never persist raw captions, transcript text, viewer identifiers, moderation inputs, audio or account credentials in telemetry.
6. On pause, device reset, interruption or shut down, first stop/flush physical PCM as appropriate, immediately blank the actual overlay, then revoke/disable the lane. A Python `disable()` alone **cannot erase a previously displayed OBS source**.

### Known failure boundaries
- A `CaptionRender` is a short-lived suggestion, **not** an OBS write authorization. `DevicePlayoutEpoch` identity is process-local, not a cryptographic credential. Host discipline and local device authority remain critical.
- The caption text denotes the **currently playing** short TTS phrase, not a guarantee that all its words have already been heard. Do not use it as courtroom-quality closed captions or a verified verbatim transcript.
- Lost OBS connection, untrusted host callbacks or loss of played-sample evidence must blank the overlay. Future Windows fault-injection work should verify this externally, not just in unit tests.
- Speech chunks must be moderately short, for example 2–7 words or under 1 second, with a bounded display window; use line wrapping at the UI layer, not untrusted raw HTML.

## Research and prioritized high-value work

### 1. Real game mastery: learning from consequence, not descriptions
**GameWorld** (April 8, 2026, https://arxiv.org/abs/2604.07429) studies 34 games/170 outcome-verifiable tasks and identifies execution latency, sparse feedback, and long-horizon control as major challenges. STAR's existing signed gameplay bank, GameLearningLadder, paired practice, prediction lab, and holdout transfer evaluator already provide pieces of the right answer.

**Next integration:** build a thin *authorized game host* that (a) samples real frames, (b) invokes Star's scoped action gate, (c) persists host-verified before/after evidence, (d) gives the practice planner only permitted training evidence, and (e) tests true skill transfer against separately sealed, unfamiliar game seeds. Run this on a **private owner-controlled test environment** first. Avoid unpermitted competitive-game input bots.

Acceptance: preregister at least 40 unseen tasks over multiple game types; compare baseline and learning-enabled agents on the **same** cases; report failure modes, input latency, task completion, unseen-game generalization and confidence intervals. Never train on held-out validation receipts.

### 2. Creating good games means shipping playable worlds
**OpenGameEval** (October 1, 2026, https://github.com/Roblox/open-game-eval and https://arxiv.org/abs/2610.02563) tests 84 curated Roblox Studio tasks in stateful environments using executable checks. The benchmark reports that inspecting relevant objects before edits correlates with success. **CEGame-Bench** (October 19, 2026, https://arxiv.org/abs/2610.26098) tests whether games made across five engines are actually playable, not merely compilable.

**Next integration:** connect Star's scene-integrity compiler, pathfinder checks, visual inspection, real client action runner, and playtest-learning worker into one transaction. Require scene snapshot -> contract -> implementation -> executable Studio checks -> playthrough -> targeted repair -> recheck. Use paired build evaluations with held-out references. Score design taste independently of functional correctness; neither a pretty screenshot nor valid Luau alone proves a good game.

### 3. Higher intelligence through better experiments and feedback
**VISTA** (October 26, 2026, https://arxiv.org/abs/2610.35051) describes active exploratory harness improvement, retaining hypotheses and failed trials in a lineage graph rather than repeatedly reflecting on static logs. Its robotics results cannot be assumed to transfer to STAR, but the experimental discipline fits Star Core Forge.

**Next integration:** log hypotheses, reproducible benchmark inputs, code diff, measured latency/accuracy, resource cost, independent test verdict and rollback pointer in Core Forge. Enforce a host-owned approval boundary for irreversible actions. A candidate should only be promoted after it passes frozen unseen tests and stability checks, not because another model said it improved.

For general knowledge, retain separate reviewed source statements, source dates, contradiction statuses, retrieval traces, and independently graded recall attempts. A larger vector index is **not** itself increased intelligence: prioritize correct answers, calibration, citation quality and retrieval time over memory volume.

### 4. Higher speeds on limited VRAM without stream degradation
Use **llama.cpp SPEED-Bench** (https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench) to compare ordinary decoding vs draft-model, n-gram and MTP speculative strategies on the **actual** game/voice/research prompt mix. Do not assume speculative decoding is faster for every model or content type. Measure warm and cold p50/p95 first-token times, prompt-reuse effects, speculative acceptance, correct task completion, CPU and RAM usage, and total tokens per watt. Preserve an unchanged baseline.

Use the already implemented OBS frame/network QoS gate and event-continuity witness to veto seemingly faster configurations that stutter Roblox, increase skipped output frames, reconnect, or impair audible first response. On an 8 GB RTX 4060 or 3060 Ti, reserve VRAM for game/rendering first; run speech candidates on CPU if actual listening tests and latency justify it, but do not equate fewer parameters with better personality.

**Kyutai Pocket TTS** (https://kyutai-labs.github.io/pocket-tts/) offers October 2026 18.2M, 6.9M and experimental 1.9M English models; run blinded voice samples and full-stream stress tests against STAR's existing voice before any change.

### 5. A lively, expressive, responsible gaming VTuber
Humanlike *performance* is observable: good timing, nuanced nonverbal expressions, sustained attention, turn-taking, genuine callbacks to prior events, and honest uncertainty. It is **not** proof of human consciousness, and Star should not claim human childhood, firsthand memories or feelings she cannot verify.

**LiveKit turn detector** (https://docs.livekit.io/agents/logic/turns/turn-detector/) documents a lightweight local CPU audio-based `v1-mini` path which improves end-of-turn recognition beyond silence-only VAD. Test it against Star's existing gate for real backchannels, coughs, interruptions and game noise before integrating. Do not allow game audio to impersonate an authenticated owner's voice.

**GameCommBench** (October 8, 2026, https://arxiv.org/abs/2610.11129) finds live observation and strategic analysis are bottlenecks in generated game commentary. Prefer specific, verified reactions to random noises. Distinguish verified victories, tentative visual clues, chat questions and personal memories. For avatar polish, keep neutral/idling states, adjustable hair physics, authentic playful modes, reduced-motion controls and a listener-testable voice. The content scheduler should intentionally choose **silence** during demanding gameplay.

## Experiment matrix (must be run on Windows/real hardware)
| Question | Primary measurement | Failure/rollback condition |
|---|---|---|
| Are captions synchronized with heard TTS? | recorded loopback + consumed frame cursor + overlay timestamps; alignment error p50/p95 | displayed text from an unplayed/stopped epoch, overlays not blanked |
| Does STT/turn detection sound more natural? | blinded interjection tests, true-interruption latency, false barge-ins, laugh quality | more accidental interrupts or worse audio quality |
| Can STAR win unfamiliar games? | held-out completion, first-action latency, transfers between games | learned policy only memorizes seen seeds |
| Can STAR build playable Roblox games? | real-input ending reached, multi-client tests, no missing assets | code-only tests pass but actual game fails |
| Is decoding actually faster? | warm/cold TTFA, tokens/s, correctness, OBS rendered/delivered frames, game 1%-low FPS | either streams stutter or task accuracy drops |
| Can self-improvement be trusted? | frozen evaluations and rollback reproducibility | model grades its own changes or alters evaluation fixtures |

## What is NOT claimed
No live Windows WASAPI callback, OBS caption source, Roblox Studio playthrough, real TTS alignment, end-to-end streaming test, improved model weights, verified inference speedup or acquired game mastery was delivered in this increment. This is a **tested offline caption-planning component**, plus a referenced integration and research plan. GitHub updates should remain draft/unmerged until independently accepted. The repository named `Star-AI-Private` has previously been reported publicly visible; do not store credentials, viewer logs or recordings there.
