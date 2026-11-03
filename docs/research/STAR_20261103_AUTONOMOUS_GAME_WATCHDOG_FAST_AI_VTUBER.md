# STAR AI — autonomous gaming receiver, fast cognition, game creation and humanlike VTuber
**Engineering date:** November 3, 2026. **Implementation:** offline host-side telemetry ticker with deterministic and timer-driven regression tests. **Not:** live gameplay, new intelligence weights, speed benchmark, Windows emergency-stop proof or public broadcast.

## What changed this iteration

Star's previous chain is *engine-owned sample -> signed source -> authenticated receiver -> corroborated game transition -> private stream journal*. The receiver liveness guard (#943) could revoke stale observations, but **only if its external host continued calling `check()` even when the transport was silent**. A normal IPC receive loop blocked on a missing frame would not call it.

This change adds **`GameTelemetryTickSupervisor`**, a local, owner-armed daemon thread that calls the existing guard at a configured interval even when NO packets arrive. It provides a single host ingestion wrapper (`accept()`) and a best-effort trusted `on_lost` notification, immediately revoking the signed bridge and private episode history when silence, a clock error, invalid packet or watchdog-worker exit is detected. The default sample interval is 100 ms; configuration refuses intervals greater than one third of the underlying silence limit. It adds no network port or physical action interface and is **off until explicitly started**.

**Operating contract:**
1. Owner enables the already-independent game engine reader, verified observer, journal and authenticated bridge; constructs `GameTelemetryLivenessGuard` and arms it with owner approval.
2. Receiver host constructs `GameTelemetryTickSupervisor(guard, interval_s=0.1, on_lost=trusted_stop_callback)` and starts it with separate approval; drive all packets through the supervisor's `accept()`.
3. `on_lost` must signal a *trusted host-level emergency-stop coordinator* that separately cancels game inference, neutralizes Windows keys, mutes audio and avatar output, and blocks stream/broadcast transitions. It is not a model tool or network-facing callback.
4. Even after a successful local thread test, deploy an **independent process/OS watchdog**. Python's daemon thread can be stalled by host process death, OS scheduler starvation or a whole-process deadlock. A callback can itself fail; this module reports failure but cannot guarantee physical shutdown.
5. Do not treat signed *client* state as engine authority. Real deployment requires a trusted engine-side plug-in in an owner-controlled game, peer-bound local IPC, safe credential provisioning, host-independent focus/key-release safeguards, and a full nonbroadcast Windows rehearsal.

## Why this improves the path to autonomous game playing

The new thread lets Star's receiver fail shut on missing game evidence **without waiting for a next packet**, which matters when a model would otherwise talk over a frozen game or learn an old checkpoint as a fresh experience. This is infrastructure correctness, not an improvement in frame rate, TTS prosody, winning rate, model size or consciousness. No gameplay result can be labeled a verified win solely because this thread is running.

### Real acceptance criteria (still pending)
- Offline Windows game, NO public stream and NO untrusted multiplayer. Capture real source timestamps, frame continuity, input key-up acknowledgments and screenshot-to-action latencies (p50/p95/p99) with the environment *continuously advancing*.
- Inject engine process failure, game exit, transport silence, unexpected invalid bytes, clock error, model timeout, OBS state transition and emergency-stop failures. Test each in isolation and in combinations.
- Verify that game input stops and held keys release independently of Star's model; OBS output stays offline; output audio and avatar are muted/cancelled within owner-chosen deadlines; no invalid memory enters a later episode.
- Confirm zero hidden telemetry bypass paths. Bind each session to actual game scope, permitted window/process, game version, source peer identity, and monotonic signing sequence. Run host physical emergency stop outside the Python process.

## 1. Faster cognition must be evaluated at the correct boundary

**Reactive (~time-critical):** a bounded local model sees current observations and produces *symbolic hints*, not unrestricted OS commands; the existing `RealtimeGameLoop`, `GameDeadlineRouter`, input gate and independent action port decide whether any action is allowed. **Tactical (~seconds):** a planner tracks objectives, map and route, reconciles recent verified observations and adapts strategy without flooding the fast path. **Teacher (~minutes/offline):** a stronger model studies misses, proposes new skill scripts, repairs Roblox code, and chooses future practice challenges. It must not monopolize a GPU during a game or OBS encode.

This is a three-speed **systems design**, not three new models installed by this PR. An 8 GB RTX 4060 must share VRAM with the game/VTuber/encoder; model weights, KV cache and graphics allocation all count. Don't assume any exact tokens/sec or viable context length without local measurements.

**Performance experiment:** identical game scene and seeds, warm-up, game/OBS/TTS load and prompts. Compare a smaller reactive model against larger context and prompt-cache variants. Record p95 end-to-end input latency and missed decisions first; separately TTFT, decode t/s, CPU p95, RAM, VRAM high watermark, 1% low game FPS and dropped OBS frames. Preempt teacher and batch image tasks on load, without assuming the GPU can be overcommitted harmlessly.

**Important finding as of Oct 22, 2026:** llama.cpp issue #30961 documents a reproduced cached-prompt restore failure with **unified KV cache + RAM prompt cache + multiple slots**, which can cause full prompt reprocessing. Treat this combination as a benchmark hypothesis, not a free guaranteed speedup; pin a build, try A/B toggles, measure cache hit rate and watch logs. Issue: https://github.com/ggml-org/llama.cpp/issues/30961 (reported Oct 22, 2026). Upstream speed benchmark: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench . Upstream RAM cache PR: https://github.com/ggml-org/llama.cpp/pull/16391 .

## 2. How Star should actually learn games

Create an offline **Game Gym** for owner-controlled levels, with engine-state verifiable progress and a training/test split by *level family*, not just different RNG seeds. Each attempt records: scope/version/seed, observation freshness, action hints, actual executed action, outcome witnessed independently, step-level progress and end-to-end latency. Don't show validation or holdout answers to Star's teacher model. Preserve old baselines, avoid selecting only successful clips, and require repeated improvement on unseen conditions before accepting a skill as learned.

Build a **failure-driven curriculum** from *verified* misses: camera occlusion, moving targets, different jump timing, increased opponent variety, routing, puzzle state, interrupted co-op and changing lighting. The offline teacher proposes exercises; external game telemetry grades them. The fast reactive policy can be distilled or prompted from lessons only after independent validation. Avoid autonomous self-modification of real game clients or online anti-cheat bypasses.

**GameWorld (2026)** emphasizes scoring from serialized game state (success + normalized progress) rather than a vision-only judge, and separates paused from real-time evaluation where the world keeps moving. Star's existing capture-to-action benchmark and signed witness should become the local regression gate for that distinction. Primary source: https://gameworld-project.github.io/ (2026).

## 3. Game creation with real visual feedback, not code-only success

**GameDevBench's 2026 camera-ready 333-task Godot benchmark** shows why Star needs screenshot/video inspection: assets, 2D animation, UI and shader work remain harder than gameplay logic for agents. The project describes visual-feedback improvements on matched workloads but these are NOT Star's scores. Source: https://github.com/waynchi/gamedevbench (ICML 2026, current repo README).

**Roblox built-in Studio MCP**, announced March 5, 2026, supports project inspection and automatic playtest iterations; the April 9 Studio playtest-agent beta adds a separate character QA worker. Prefer those native, owner-approved tools over a screenshot-only ad hoc interface. Sources: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 (Mar 5, 2026) and https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767 (Apr 9, 2026).

**Quality gate for Star builds:** read the game tree -> propose two or more candidate Luau changes -> static analysis (Luau/StyLua/Selene as appropriate) -> controlled Studio launch -> `StudioTestService` single-/multi-client scripted assertions -> independent screenshot/video review -> replay on fresh seeds -> versioned rollback checkpoint. Assert replication, mobile input, camera motion, visual hierarchies, performance and actual game completion. Provenance of media and host logs matters; no visual screenshots means no claim of visual quality.

## 4. A much more natural Star VTuber: timing, not pretending to be human

Star can be **humanlike in expressive behavior**, not literally human. Her persona should be consistent, playful and genuinely grounded in what she has actually observed. Don't invent private memories, real-world experiences or emotional needs. Make it clear she is an AI VTuber.

Natural timing requires a joint policy for **when to speak**, **when silence is appropriate**, **how to yield**, and **how to recover from a false interruption**:
- Use `StreamDirector` to prefer a genuine, moderated viewer question over a repetitive game cheer, but defer both under critical gameplay or QoS pressure.
- Use `TurnTakingGate` / TTS-stop acknowledgments to yield to a genuine authenticated owner utterance, while not interpreting incidental audio as a barge-in. No VAD-only identity guesses grant owner authority.
- Use `StreamFocusInbox` for a brief, bounded deferred question after an intense encounter; release it naturally as an earlier question, not as a live command.
- Only have Star celebrate a witnessed event and describe uncertainty when evidence is old; voice should show timing, audible micro-pauses, repair of mistakes, and conversational variety—not a forced reaction on every frame.
- Coordinate TTS chunks, visemes/lip sync, gaze and avatar expression with actual playback position; cancel stale animations and audio when the utterance is aborted.

Research support: Microsoft's **Proact-VL**, ICML May 2026, explicitly evaluates response timing and controllable volume of proactive gaming commentary. Source: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/ . Kyutai **Pocket TTS** is a candidate streaming CPU speaker that can preserve GPU resources, but its public MacBook benchmark is not evidence of speed or naturalness on Star's hardware. Source: https://kyutai-labs.github.io/pocket-tts/ (2026). LiveKit documents interruption/turn-handling mechanisms worth testing, not necessarily adopting wholesale: https://docs.livekit.io/agents/logic/turns/ .

**Measure real speech:** first audible PCM (not first model token), interruption-to-playback-stop, false interruption rate, overlap with guests, unplanned stutter gaps, repeated commentary frequency, groundedness and blind independent listener judgments of naturalness. Compare A/B with identical gameplay and speakers. Preserve AI disclosure.

## 5. General knowledge and stronger independent work

Keep distinct local stores for (a) curated/documented API facts, (b) reproducible programming and game skills, (c) authenticated gameplay episodes, and (d) Star's stable fiction/persona preferences. Attach provenance, observation time, version scope, contradicted/retracted flags and confidence; don't mix hallucinated thoughts with witnessed facts. Refresh high-volatility facts like Roblox APIs and model runtime options rather than assuming the knowledge base never expires.

The longer-term personal-life sandbox can include supported games, drawing, Blender, code experiments, conversation practice, reading, creative projects, scheduled rest and repeated independent evaluation. Star may choose routine *approved* local exercises but money movement, public broadcasting, contacting strangers, unknown executables, deleting data and security changes require separately defined permissions and auditable actions.

## Bounded next-step queue

1. **Owner-controlled live engine -> local authenticated IPC** on Windows with a separate OS-level watchdog for whole-process failure and physical key/speaker stop. Rehearse offline; record complete capture-to-action evidence.
2. **Performance sweep** on the actual game+OBS hardware: CPU-only/local speaker vs GPU speaker, cached vs uncached prompt, 1 vs 2 slots, reactive models at bounded contexts; isolate whether KV-cache restore problems occur.
3. **Game Gym evaluation** on small platforming and driving challenges with matched seeds, withheld levels and autonomous curriculum; graph independently graded success/progress vs active practice time.
4. **Humanlike VTuber quality session**: 20+ matched conversational scenarios, authenticated source evidence, audio/avatar playback captures, neutral listener scoring and explicit AI identity. No public broadcast until gates pass.
5. **Game builder acceptance** on one user-owned Roblox project with native MCP and Studio tests, verified visual frames and rollback.

**Evidence from this PR:** a local watchdog API and offline regression tests. **Not demonstrated:** model intelligence increases, FPS/tokens/s speedups, game wins, expressive voice quality, Roblox production builds, real-world emotion or actual live streaming.
