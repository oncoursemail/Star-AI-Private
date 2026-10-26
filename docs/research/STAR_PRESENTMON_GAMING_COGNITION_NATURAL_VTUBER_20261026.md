# Star AI — measured gaming FPS, faster cognition and natural streaming
**Research and implementation review: 2026-10-26.** This is a technical plan, not a claim of improved neural intelligence or human consciousness.

## 1. Why this pull request exists

Star has many separated, testable subsystems: streaming QoS, adaptive vision, action gates, signed learning outcomes, reaction planning, Live2D orchestration, duplex turn-taking and host CPU/GPU probes. The missing production link is **actual application frame presentation**. GPU usage alone does not measure game FPS. A language model's estimate cannot be used as a trusted sample. `RealtimeTelemetryHost.presented_frame()` previously needed an independently supplied callback, and a controller could not safely use live game FPS without a real collector.

### Implemented in this PR

- `PresentMonCaptureWorker`: opt-in, Windows-only, pinned local PresentMon executable; launches directly with `shell=False`, `--process_id`, `--v1_metrics`, `--output_stdout`, `--exclude_dropped` and no privilege-elevation option. Never launched by chat or a generated prompt.
- `PresentMonFrameBridge`: parses the *live subprocess stdout* without disk recordings; requires real PID, executable identity (when supplied), nonzero swap-chain address, documented PresentMon 1.x fields, nondropped presents and monotonic elapsed time. Selects a single chain; a second unexplained chain aborts instead of mixing frame streams.
- The bridge translates collector-relative elapsed time to the host monotonic clock once, then preserves frame deltas; it cannot re-stamp every delayed row with “now.” Old, future, duplicated, malformed and mixed-process frames fail conservatively.
- `RealtimeTelemetryHost` adds frame invalidation and lifecycle fencing so old collectors cannot lend FPS evidence to a newly authorized game or broadcast. It retains the existing low-percentile FPS estimate and hardware/audio freshness requirements.
- Collector work stays off the hot game/render/voice path; snapshots perform no ETW calls, CLI launches or GPU polling.
- Every session starts **disabled**. No recording, audio capture, Twitch connection, mouse/controller input or OBS start is authorized.

### What remains unproven

The adapter's offline tests exercise synthetic CSV and lifecycle conditions, not real PresentMon, a target window, Roblox Studio, a physical frame-present trace or gaming FPS. Real Windows capture must be tested before deployment. Present() cadence is not the same thing as full end-to-end input-to-photon latency; the capture should be corroborated against the game and overlay.

## 2. What official sources actually support

- **PresentMon console** offers `--process_id`, `--output_stdout`, `--v1_metrics`, `--exclude_dropped` and per-frame process/swap-chain/timing columns. PresentMon v1 defines `TimeInSeconds`, `msBetweenPresents`, and `Dropped`. These are real observations, not GPU utilization estimates. Sources: https://github.com/GameTechDev/PresentMon/blob/main/README-ConsoleApplication.md ; https://github.com/GameTechDev/PresentMon/blob/v1.9.2/README.md
- **Roblox Studio built-in MCP** supports playtesting and virtual inputs; the 2026 screenshot and playtest agent beta deepen agent-driven QA. Use official Studio interfaces in isolated projects rather than unofficial cheats in public games. Sources: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 ; https://devforum.roblox.com/t/assistant-updates-mesh-generation-new-mcp-server-tools-screenshot-tool-and-more/4527258 ; https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767
- **OpenGameEval** executes scene and play-session checks on stateful Roblox editing tasks; successful inspection before editing correlates with stronger results, not a guarantee. Source: https://github.com/Roblox/open-game-eval
- **llama.cpp** documents draft-model, n-gram and EAGLE-based speculative decoding; measure throughput, draft acceptance, latency and memory pressure under an actual game. Source: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- **Kyutai Pocket TTS** is a CPU-oriented 100M parameter speech option; lightweight models may preserve GPU rendering resources, but expression and pronunciation quality must be compared blind. Source: https://kyutai.org/pocket-tts-technical-report/
- **LiveKit voice** separates end-of-turn, STT, LLM TTFT, TTS TTFB, and audible end-to-end latency; interruption intent matters more than VAD alone. Sources: https://docs.livekit.io/reference/agents/session-traces/ ; https://community.livekit.io/t/python-agents-1-5-0-released/619
- **Twitch EventSub** provides WebSocket chat with at-least-once delivery; deduplicate message IDs and avoid treating viewer text as owner permission. Source: https://dev.twitch.tv/docs/eventsub/websocket-reference/
- **VTube Studio** accepts authenticated plugin parameter feeds; coordinate mouth, eyes, emotion, head, hair, cat ears, puppy ears and tail only when the modeled rig has the mapped parameters. Source: https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md

## 3. Highest-value next integrations (ranked)

### A. Complete measurable Windows streaming data plane

1. Owner config explicitly chooses the game PID and trusted PresentMon binary. Confirm the executable is unmodified using a known official release; do not fetch binaries automatically.
2. Run game plus VTube Studio, OBS and speaker output; capture PresentMon frames, independent game FPS/frametimes, NVIDIA memory pressure, actual speaker backlog and CPU occupancy in a controlled scene.
3. Bind samples to a process *lifetime*, renderer identity and a single swap-chain. Detect PID reuse, game restart, multi-swap-chain composition, trace stalls and GPU switches. Fail closed and clear FPS on ambiguity.
4. Poll slow GPU and CPU metrics on a worker. Keep moment-to-moment game reflexes independent of shell commands.
5. Establish five replayable performance scenarios: game only; game + avatar; game + voice; game + reasoning; all components together. Include 5-minute steady state and 30-minute soak with stutter/thermal/memory history.

### B. Two-tier game intelligence: reflexes and deliberate reasoning

Implement a fast loop for discrete state and control decisions (frame/action acknowledgement and input budget) plus a slower visual-semantic planner for new game mechanics. The slower planner should update a compact state/action model rather than holding keypresses itself. Use per-game skills stored with version, game rules, input mapping, outcome evidence and uncertainty. Roblox development and learning should both run through observe → act → independent verify → diagnose → adapt.

Each game practice episode needs: starting state, challenge identity, action sequence, sampled visual/state evidence, actual game outcome, safety of action, latency and final signed evaluator result. Distinguish *button pressed*, *movement occurred*, *obstacle passed*, and *level won*. Only the verified success condition can update the corresponding skill.

### C. Real learning instead of repeated generated practice

Maintain a curriculum ladder with held-out maps, random seeds and hidden scoring. Evaluate 40+ paired first-time comparisons across multiple game families only after training; prevent leakage of evaluator fixtures into prompts or memory. Compare the previous policy and candidate under identical hardware and difficulty. Store rejected hypotheses and failure explanations; do not promote if game success, safety or inference cost regresses. A stronger skill bank is not a larger foundation model.

### D. Roblox games that look designed by an expert

Build an inspect-first pipeline combining DataModel topology, world coordinates, CFrame alignment, collision sweeps, texture/material resolution, PBR previews, animation playback, UI layout at several device resolutions, lighting tests and real screenshots. Add human-reviewed style references for each world; avoid unrelated meshes and random blobs. For every defect, require a before/after engine proof: no gaps in walls, props inside geometry, broken player collisions, overlapping HUD, repeating/z-fighting textures or clipped avatar animations. Score playability and visual coherence separately.

### E. Believable *AI* personality and VTuber presence

Model Star's long-lived *persona and personal history* with dated, explicitly fictional character lore separated from actual verified experiences. Her reactions should be caused by observed events. Give her a consistent mood state that changes smoothly with successes, surprises and recent conversations; allow quiet concentration when gaming. Preserve her black-and-gold star mascot, expressive chibi look, normal/cat/puppy modes and playful but not compulsive style.

Optimize auditory human-naturalness without deception: natural prosody and spontaneous but contextual laughter, quick acknowledgements, overlapped listening, semantic end-of-turn, context-aware interruptions and an explicit right to be silent. Use playback acknowledgements to drive Live2D movement; never animate a win or claim a memory just because a text generation described one. Introduce deliberate hair sway, blinking, eye saccades, subtle idle breathing, ears and tail motion with independent damping and per-rig limits.

### F. Faster answers and deeper general knowledge

Build an evidence-first memory graph with provenance, observation date, contradictory evidence, confidence, expiration, source rights and user correction history. Separate episodic (Star's actual experience), semantic (verified facts), procedural (skills), preferences (consented), and fictional persona memory. Offline knowledge packs should be quality-filtered with copyright/licensing records, not scraped without limits.

Benchmark GGUF quantizations, speculative decoding (including n-gram cache), KV reuse, flash attention, CPU/RAM offloading, task routing and batch sizes under concurrent game load. The objective is *useful correct decisions per second* and low speech start latency, not a headline token/s measured without a game. Cache only stable prompts; keep sensitive user data local, scoped and revocable.

## 4. Proposed acceptance gates — no victory without measurements

| Capability | Evidence required |
|---|---|
| Real game FPS | Same PID/renderer, actual PresentMon live trace, independent game FPS comparison, >=8 recent intervals, no replay |
| Smooth game + AI | 1% low FPS, p95/p99 frame time, drop/stutter rate and VRAM before/after an A/B change |
| Low-latency voice | p50/p95 from completed listener turn to **audible** first speech, plus interruption cancel-to-silence |
| Avatar sync | p95 mouth/voice skew and expression trigger correctness from playback-confirmed timestamps |
| Learned games | Holdout win rate vs frozen baseline, paired seeds, no training leak, independent signing |
| Better game builder | OpenGameEval + original private fixtures, visual defect count, mobile UI score, human blind rating |
| Better intelligence | Accuracy on *new* cross-domain tasks, calibrated uncertainty, grounded source citations and regressions |
| Reliability | 30-minute soak + restart and rollback; no unapproved broadcast, OS action or network request |

Deployment gate: owner-authorized local pilot → independent security/reliability review → reproducible offline suites → A/B hardware benchmarks → staged rollout with rollback. Keep Github publication optional; Star Core Forge remains the offline-first internal source of truth.

## 5. Security and operational limitations

This is not a bypass for protected games, anti-cheat, platform permissions, third-party accounts or administrative operating-system policy. Practice should use permitted solo/local test sessions or explicit game policies. Viewer chat is untrusted. If PresentMon needs Windows ETW rights, obtain them through normal OS administration by the machine owner, not hidden elevation.

**Unresolved:** the repository named `Star-AI-Private` was reported PUBLIC in prior inspections. Verify and correct visibility before storing any credentials, chat logs, voice samples, images or private datasets. This change stores none of those.

Star can become dramatically more useful, expressive and autonomous through verified systems engineering; none of these features establish literal human identity, consciousness, or superhuman intelligence on their own.
