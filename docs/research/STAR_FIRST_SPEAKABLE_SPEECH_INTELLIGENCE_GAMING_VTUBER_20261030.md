# STAR: First Speakable Latency and Verified Intelligence Roadmap
**Research and implementation snapshot — October 30, 2026**

## 1. What was implemented in this change
STAR previously measured first **visible** model text and full completion. Neither is a reliable estimate of when the production voice system can start TTS: the model may stream a role-only event, a single letter, hidden reasoning, markdown, or a long punctuation-free sentence. The new streaming benchmark reuses `star.voice.chunker.SentenceChunker`, the exact class already used by `star/voice/call.py`, to add the first **TTS-ready phrase** milestone.

The opt-in benchmark now reports:
- `first_visible_p50_ms` and `first_visible_p95_ms` (existing);
- `first_speakable_p50_ms` and `first_speakable_p95_ms` (new);
- `speakable_ready` and `speakable_missing` (new);
- fully completed request latency and failure counts (existing).

The streaming parser does not save prompts, generated text, model reasoning, stream chat, voice, or personal records. Phrase analysis is in-memory and capped at 4,096 characters per request. Canary comparisons still capture at most 256 characters. An additional bug fix initializes the capture piece even if a server emits more than that bound in earlier chunks; an oversized exact-canary response is marked truncated, not silently accepted.

**Important distinction:** A first phrase ready for synthesis is *not* first PCM generated, first audio submitted, first sample actually played, or first sound heard by viewers. The status remains synthetic/offline until timed against an actual local model and real audio output. This patch does not change the speech model, gameplay controller, OBS, model routing, or any service settings. It remains opt-in.

### Verification
- Compiled the changed Python source and tests on STAR's Linux development computer.
- **42 tests passed** for the new inference streaming benchmark and existing voice-chunker behavior, including new tests for fragmented SSE deltas, a hidden-only reply, no-terminal-punctuation replies, malformed canaries, and invalid clock values.
- All tests used synthetic responses; no model speedup, learning gain, gaming win, or Windows/OBS streaming quality improvement is claimed.
- Review and merge remain owner-controlled. Do not interpret a successfully published draft PR as production deployment.

## 2. Measurable streaming pipeline: optimize *what viewers hear*

A human-feeling gaming VTuber needs a measured pipeline with separate stages:

```
game/viewer event (trusted) → attention selection → response policy
→ LLM first visible text → LLM first speakable phrase
→ first TTS PCM → audio-device playback / independently witnessed audible sample
→ avatar phonemes/motion → OBS local recording → verified spectator experience
```

Each stage needs an opaque per-turn correlation ID and monotonic clock on the **same host**. For cross-machine work, record clock calibration and error bounds rather than subtracting timestamps from unsynchronized clocks. Track median and p95 latency, interrupted-turn waste, game-frame-time p95, speech underruns, and OBS dropped frames together. Save aggregate measurements, not viewer messages, screenshots, microphone audio, or identifiable gameplay footage by default.

**Evaluation**: A paired A/B run should hold the game scene, model hash, microphone/ASR configuration, inference slots, cache policy, streamer workload and output device stable. Include cold/warm and mixed-prompt tests. A faster first letter is not a speech improvement if the first speakable chunk is later; a faster chunk is not better if the audio queue or viewer playback is later. Separate text quality from timing.

Use the existing STAR components rather than creating a second orchestration stack:
`star/voice/call.py`, `star/voice/chunker.py`, `star/voice/metrics.py`,
`star/stream_trace_capture.py`, `star/stream_pcm_envelope.py`,
`star/stream_playout_clock.py`, `star/stream_brain_governor.py`,
`star/stream_realtime_benchmark.py`, and `star/inference_stream_benchmark.py`.

## 3. Faster AI: controlled hardware experiments, not guesses

STAR's Linux machine has multiple running `llama-server` instances. Protect realtime play/voice work from optional experiments using the existing memory-pressure guard and QoS controls. Do not restart model servers, change speculative decoding, or allocate additional VRAM during live sessions without a controlled maintenance window.

**Candidate experiments, in order:**
1. **Baseline actual task latency**: capture cold/warm first-visible, first-speakable, complete-response times, token rates, backend queue depth, PSI stalls, and power/CPU/RAM usage on identical private synthetic inputs.
2. **Cache-stable prompts**: use consistent system/tool prefix, bounded conversation updates and explicit cache diagnostics; report repeated-prompt gains separately from mixed-case gains.
3. **Routing**: deterministic small-model fast path for short commentary; stronger-model deliberation for multi-step Studio edits, source reconciliation and difficult strategy. Only promote routes after matched task-quality and safety checks pass.
4. **Speculative decoding**: run llama.cpp SPEED-Bench on a separate idle baseline and speculative candidate; include draft acceptance, latency, quality, and effective memory cost, not just decode tokens/second.
5. **Workload admission across Brain 1/2**: reserve game FPS/audio deadlines first; schedule embedding, research, long render, and self-training opportunistically. Never let a slow tool or background agent block the gaming input path.

llama.cpp's SPEED-Bench documents latency, prefill/decode throughput and speculative-draft acceptance in controlled comparisons:
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

## 4. Autonomous gaming: evidence-first practice, then transfer

A gaming assistant needs more than a high-level LLM interpreting isolated screenshots. Use two loops:

- **Fast control loop**: bounded local actions (walk, aim, jump, interact) with verified input focus, recent frame/game state, collision and human override. No unsafe or anti-cheat-bypassing automation; practice in owned, private, or explicitly authorized environments.
- **Slow planning loop**: map objectives, infer mechanics, try falsifiable hypotheses, choose new curriculum exercises, record confidence and correct strategies using *independently verified* game outcomes.

Recommended first offline/private curriculum:
- moving platform crossing with checkpoint completion;
- timing a jump at two different frame rates;
- navigation from unseen starting positions;
- aiming with a moving target in an owned test place;
- cooperative puzzle solved with an assisting simulated player.

Hold back new maps and seeds, then measure zero-shot win rate, attempts to win, damage/mistake count, intervention count, calibration error, and out-of-distribution transfer. Include negative controls: changed camera perspective, altered frame rate, fake HUD cues and inaccessible objectives. Do not teach a skill from STAR's unsupported self-declaration.

Roblox announced Studio's built-in MCP server with playtest and simulated input support March 5, 2026:
https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643

OpenGameEval (Oct 1, 2026) reports 84 Roblox Studio tasks with engine-executed validation; inspection of relevant objects predicted better task success:
https://arxiv.org/abs/2610.02563

Use STAR's existing StudioPracticeCycle and game_journey_completion modules to close the loop: build → inspect → play → verify → repair → replay fresh environment → document only verified learning.

## 5. More intelligence through trustworthy knowledge

Replace vague "learn everything" operations with retrieval and verification:
- **Episodic evidence**: task ID, environment version, observation digest, attempted action, independently checked result, mistakes, and confidence change.
- **Skill memory**: scoped reusable procedures for Luau, Studio UI, VFX, rigging, Blockbench, Blender, debug triage and game strategies; each with executable examples and known failure cases.
- **Knowledge memory**: cited primary documentation, provenance, freshness date, legal license and incompatibilities. Expire time-sensitive claims and re-check them with explicit web permission.
- **Self-improvement control**: STAR Core Forge owns experiments, diffs, graded canaries, rollback and immutable evaluation receipts. GitHub is an optional publication/review mirror, not a required brain component.

Prevent evaluation contamination: unseen challenges must not become training examples until the assessment is over. Promote a new skill or model only when it improves outcomes on held-out tasks *without* regressions in live voice, gaming and computer-control safeguards.

## 6. Game creation: optimize completed experiences rather than isolated scripts

An effective Roblox/game platform builder checks physical and visual properties, not only compilability:
- no detached walls, floating fixtures, z-fighting, inappropriate scale, intersecting props or broken interaction reach;
- full keyboard/gamepad/touch navigation, readable HUD at small displays and consistent safe-area margins;
- camera-safe animation and VFX, timed audio, rig joints, collision and spawn/respawn behavior;
- a finishable player journey that survives saving, reloading and a fresh process;
- replayable automated gameplay plus screenshot/video comparison assessed by independent reviewers.

Use best-of-N only with bounded budgets and independently measured success; do not confuse the most elaborate render with the best usable game.

## 7. Natural AI VTuber: personality tied to genuine experience

**Behavior policy**: Let STAR concentrate silently during difficult gameplay; prioritize actual chat questions after attention windows, use voluntary short reactions to verified events, vary sentence cadence, avoid robotic over-narration, and react to losses, surprises and accomplishments without claiming an invented human past. Transparent AI identity does not prevent lovable, funny, consistent characterization.

**Speech**: Compare lightweight local turn detection (LiveKit `v1-mini` runs on CPU) against current VAD, with false interruption, latency, multilingual behavior and chat background-noise tests:
https://docs.livekit.io/agents/logic/turns/turn-detector/

**Voice models**: Kyutai Pocket TTS supports CPU streaming; October 2026 smaller English model variants are potential CPU-light candidates, not proven upgrades for STAR's voice. Check license, expressive quality, first-PCM latency and actual output under OBS + gaming before selecting one:
https://github.com/kyutai-labs/pocket-tts

**Animation**: Drive eyelids, eye gaze, mouth motion, breathing, twin-tail physics and facial intent from the *same* verified audio/game event timeline. Respect motion-reduction settings, use fixed-cost animation, and avoid running full video generation on the gaming GPU during live play.

**Social and privacy**: Separate persona lore from lived events; get permission before remembering identifying viewer data or recording private chats. Rate-limit interaction, retain on-device moderation and account controls, and allow a physical owner kill switch/stream stop. No undisclosed impersonation.

## 8. Highest-ROI next acceptance test (not yet executed)

On an **idle** authorized Windows machine with OBS and a test game:
1. Record 20 repeated but randomized synthetic, *non-personal* voice turns and 20 varied turns across two candidate models/configurations; include concurrent gameplay.
2. Capture first visible, first speakable, first generated PCM, independently observed first audio, animation lipsync offset, game frame-time p95 and OBS output health.
3. Compare matched A/B with confidence intervals; reject changes worsening correctness or interrupt handling even if token rate rises.
4. Run five previously unseen private-game practice tasks with engine-verified objectives; compare performance before and after learning.
5. Roll back automatically if spoken latency or gameplay quality regresses; request owner review for anything irreversible, public or externally visible.

**Known limitation and security note:** This update is an opt-in benchmark only. No live model or Windows OBS measurements are reported. `Star-AI-Private` was observed with **public** GitHub visibility on October 30, 2026; do not add credentials, private voices or viewers' personal data to this repository without correcting access controls.
