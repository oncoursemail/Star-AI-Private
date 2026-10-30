# STAR AI — type-gate recovery, verified game intelligence and natural VTuber roadmap
_Date: 2026-10-30. Status: review-only, not deployed. Owner-approved capabilities remain OFF by default._

## Proven problem and scope

GitHub Actions for stacked draft PR #828 failed on 2026-10-30: 14,285 Python tests passed, one synthetic reasoning-handoff test failed due to missing real STAR Server credentials, and the pyright gate reported **108 additional error diagnostics across 46 Python files**. The React UI gate passed. Draft PR #829 isolates the synthetic credential lookup and addresses some voice types, but did not establish a green CI pipeline at inspection time.

This change addresses real type-contract defects across game input, Roblox Studio practice, voice timing, Linux memory pressure, OBS/Twitch integration, and visual learning. It deliberately does **not** expand the pyright baseline, weaken production authentication, enable streaming, execute game inputs, or change inference backends. Changes include checked numeric narrowing, explicit optional-value guards and preserving tuple geometry types, plus runtime fail-closed handling where a missing ticket, sample, socket method, or clock would otherwise be ambiguous.

These fixes are only a candidate until fresh **full GitHub Actions** passes. Desktop Commander reported no remote calls available for local verification. A 2026-10-30 GitHub Actions result must be inspected after publishing this draft. Do not merge/deploy or infer benchmark gains from type cleanup.

## System-level intelligence priorities (ordered)

1. **Evidence-first learning:** every autonomous practice task stores a scoped build hash, scenario seed, policy/model hash, observation digest, bounded action, engine witness, score and replay pointer. Separate training attempts from an unseen holdout suite. Report both first-attempt success and learning efficiency, not self-scored claims. For Roblox Studio, start inside authorized private Studio playtests with owner-curated symbolic input and a real key-release watchdog.
2. **Three-timescale game intelligence:** keep reflex-level deterministic controls independent of LLM generation; use a short-interval visual/tactical model for perception and a slower planning model for strategy. New model requests should respect audio-output deadlines, OBS dropped frames and game FPS. A completed action requires an independently signed engine outcome.
3. **Knowledge quality, not volume:** maintain document-level source URL, version/retrieval date, confidence, expiry, citation and verified-vs-hypothesized tags. Build compact validated skill cards from successful episodes; never treat a generated tutorial as tested game competence. Retrieval should be bounded by evidence and latency budgets.
4. **CPU-first performance:** compare llama.cpp settings using paired matched prompts and identical hardware/model hashes. Record first visible text, first phrase ready for synthesis, output callback and OBS loopback independently. Examine prompt prefix stability, cache invalidation, speculative decoding acceptance, memory-stall pressure, memory bandwidth, scheduling overhead and GPU sharing. Promote only if quality doesn't regress and completed-task latency improves.
5. **Star Core Forge locally:** use isolated experiment worktrees, reproducible tool versions, skill-regression tests, evidence receipts, canary deployment and automatic rollback. GitHub is an export/review surface, not a required runtime dependency.

## Game creation must satisfy a complete journey

Building a game is not success until the engine can launch it, accept actions, reach objectives, save state, reopen, recover state and finish. Check missing walls, unsupported props, incorrect anchors, overlapping meshes, broken lighting, animation clipping, invalid collision geometry, unplayable UI scales and unreliable camera control before review. Compare visual quality with independent renders; verify actual Roblox engine behavior through private playtesting. Reserve holdout scenes to measure generalization instead of memorizing one game.

## Natural, AI-transparent VTuber architecture

Natural presence combines expression, restraint and memory. Track genuinely observed game events, focus state and speech audibility separately. During hard gameplay Star should **prioritize controls and sometimes be quiet**; defer selected moderated questions briefly and answer at a genuine conversational boundary, including a clear 'asked earlier' cue. Facial expression, eye-gaze, eyelids, mouth visemes, asymmetric twin-tail/hair physics and small body movement should follow real emotional cues and sound timings, not arbitrary RNG. Build optional cat/puppy persona styles on the same game-grounded state machine, without fabricated human memories.

Keep distinct clocks for LLM first phrase, TTS generation, PortAudio callback, OBS audio loopback and rendered video output. A PortAudio callback only confirms delivery to the device callback, **not** audibility or captured OBS sound. Use non-speech sync markers and local recordings in owner-authorized rehearsals, measuring p50/p95 game-event-to-audio latency, A/V skew, interruptions, dropped frames and gameplay 1%-low FPS. Retain only aggregate metrics; never store voice recordings, viewer IDs or private gameplay by default.

Investigate LiveKit CPU turn detection as an opt-in A/B candidate against Star's existing turn-taking; it requires VAD and a minimum silence duration of 0.25 seconds in the cited documentation. Check licensing, latency and energy usage before adoption. Keep a physical microphone/output mute and stream kill switch independent of any model.

## Hard acceptance criteria

- **CI:** new draft passes complete offline Python tests, pyright baseline gate and frontend checks. No ignored diagnostics, baseline inflation or hidden production keys. New warnings/errors require remediation.
- **Gaming:** record at least 30 seeded *training* trials and 30 unseen *holdout* trials per skill, with actual Studio outcomes and failure analysis; no self-reported success.
- **Speed:** pre-register a matched baseline/candidate trial design; evaluate p50/p95 first-speakable and OBS-audible latency, hallucination/canary failures, GPU/CPU pressure and game 1%-low FPS. Report confidence intervals; do not describe parser speed as intelligence improvement.
- **VTuber:** complete an owner-approved local OBS rehearsal with source audio + loopback corroboration, synchronized animation, failed-device handling, quiet-mode behavior and immediate shutdown. No unsolicited public broadcast.
- **Forge:** reproduce a failing test, apply an isolated candidate, collect signed evidence, reject regressions and roll back without relying on GitHub.

These numbers are **proposed acceptance thresholds** only, not achieved results.

## Primary technical references (checked during this research)

- Roblox Studio built-in MCP and input-simulated playtesting, 2026-03-05: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- Roblox's agentic Studio announcement, 2026-04-15: https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic
- Roblox dedicated Playtest Agent beta, 2026-04-09: https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767
- Roblox Studio test modes: https://create.roblox.com/docs/studio/testing-modes
- Roblox StudioTestService: https://robloxapi.github.io/ref/class/StudioTestService.html
- LiveKit turn detector / v1-mini: https://docs.livekit.io/agents/logic/turns/turn-detector/
- llama.cpp server KV/prefix cache and timings: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- llama.cpp server speculative-decoding benchmark: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- OBS WebSocket protocol: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md

## Privacy and deployability

The GitHub repository named `Star-AI-Private` was **publicly visible** when inspected. This memo contains no credentials, voices, raw observations, private viewer data or unpublished owner details. All changes stay in a draft branch; experiments are opt-in and must earn promotion through real machine and engine verification.
