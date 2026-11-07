# STAR: physical-input Studio smoke tests, game mastery, speed and VTuber research
**29 October 2026 — implementation and research.** The repo is named "Private" but is currently **public** on GitHub. Do not put identities, stream keys, chat transcripts, credentials, personal memories, or private gameplay recordings here.

## What is new in this change

\`star/studio_virtual_input_smoke.py\` compiles a **reviewable client LocalScript** for an explicitly owner-approved, private Roblox Studio session. It uses the documented 2026 \`UserInputService:CreateVirtualInput()\` interface and \`VirtualInput:SendKey()\` to press and release preapproved gameplay keys. It watches \`InputBegan\` and \`InputEnded\`, optionally measures *horizontal* change in \`HumanoidRootPart.Position\`, makes a bounded release attempt if an injected key stays held, and emits one small JSON console line containing a plan SHA-256 and the observed step outcomes.

Only W/A/S/D/Q/E/F/R/Space may be scheduled. Plans are immutable and limited to 1–8 steps, 30–180 ms per key pulse, and a 100–2500 ms warmup. No arbitrary script snippets, chat commands, CoreGui interaction, data persistence, automatic Studio connection, publishing, external URLs, or training is generated. The game is not run by the Python compiler. The feature is OFF unless the trusted host requests compilation with explicit owner approval.

\`parse_virtual_input_log()\` accepts only bounded and structurally consistent console records for the exact immutable plan. Its output is **untrusted candidate evidence** even when \`candidate_passed=True\`: a client log does not prove objective completion or independently verified input. In particular, it must **never** advance \`StudioPlaythroughGate\` by itself. Only authenticated host evidence derived independently from actual Roblox state and input delivery can sign playthrough phases.

### How to inspect and try it on a private Studio test

1. Define a trusted plan in Python, for example \`VirtualInputSmokePlan("obby-smoke-01", (VirtualInputStep("W", 140, 0.15), VirtualInputStep("SPACE", 100)))\`. The second action checks a key-down/up event but not horizontal displacement.
2. Generate the Luau text with \`compile_virtual_input_local_script(plan, owner_approved=True)\`. Review the generated script before use. No Roblox input occurs at this step.
3. In a disposable **private** Studio project, manually install the LocalScript in \`StarterPlayer > StarterPlayerScripts\`; launch Play or Server & Clients with Studio's test controls. The script immediately returns outside Studio and will not type into a focused TextBox. It operates only on its own client.
4. Collect the single \`STAR_STUDIO_INPUT_SMOKE\` console record and run the strict Python parser. The result can point to a broken key-binding or character-movement regression.
5. To establish a verified game-playthrough receipt, have a **separate trusted Windows/Studio observer** capture actual runtime state, validate a predeclared test objective, and sign it outside the game and model's control. Do not sign merely because the console line said "passed."

Limitations: client \`InputBegan\`/ \`InputEnded\` callbacks or simple displacement are helpful smoke tests, **not evidence of the intended game mechanic**. Alternative movement systems, physics, lag, focus, or CoreGui can lead to false negatives. Unexpected character movement/teleports can lead to false positives for motion. The release watchdog is best-effort; a host must retain an independent session-stop/key-release watchdog. No live Roblox Studio test was executed for this change, and no gameplay mastery was demonstrated.

The 2026 official APIs are documented at:
- Roblox, [VirtualInput](https://create.roblox.com/docs/reference/engine/classes/VirtualInput/SendKey)
- Roblox, [UserInputService:CreateVirtualInput](https://create.roblox.com/docs/reference/engine/classes/UserInputService)
- Roblox, [StudioTestService](https://create.roblox.com/docs/reference/engine/classes/StudioTestService/AddPlayers)
- Roblox, [Studio testing modes](https://create.roblox.com/docs/studio/testing-modes)

Roblox notes that \`VirtualInput\` cannot inject keys into built-in CoreGui, that \`CreateVirtualInput()\` can return nil, that \`StudioTestService\` supports up to 8 simulated clients, and that \`GetTestArgs()\` currently has client-LocalScript limitations. This generator consequently does **not** rely on client \`GetTestArgs()\` or pretend to drive all clients at once.

## Intelligence: replace synthetic success with a measurable proof ladder

1. **Inspect:** For Roblox, collect allowed, fresh screenshots, object hierarchy, map collision/navigability, and the actual input mapping. Keep source provenance and uncertainty in the task record.
2. **Predict:** State a falsifiable belief such as "W reaches platform B" or "interacting with switch opens door." Predict a measurable before/after state. Do not judge success from LLM text.
3. **Act:** Use the trusted action gate and private Studio input adapter for a bounded action. The new VirtualInput LocalScript can provide another real-input smoke path.
4. **Observe independently:** Compare actual character state, UI state, objective predicates, and reproducible input trace. Host-authenticate game results; never give a model its own signing key.
5. **Learn:** Store compact outcome, mechanics hypothesis, state/action/feedback, source freshness, confidence, and why the attempt failed. Retrain/rewrite only after holdout benchmarks improve.
6. **Generalize:** Reserve different maps and entirely new games as holdouts. Success on a previously practiced level alone does not establish transferable game skill.

**Suggested initial measured targets (not claims of current performance):** record baseline completion rate over at least 30 seeded private Studio game episodes; track end-to-end episode wall time, expected vs observed action effects, game FPS, human intervention count, objective completion, and held-out completion. Compare same-seed A/B trials with a fixed time and token budget. Require a genuine quality win before enabling a change.

## Hardware speed: optimize useful outcomes per second

- Treat the future Windows/4060 gaming host as a latency-sensitive lane: game, OBS, voice, Live2D/VTube Studio, and minimal visual attention are high-priority. Move CPU-heavy indexing, self-play training, experiment search, and batch inference to Brain 1/other authorized machines when available. Admission control should prevent gameplay/OBS stalls.
- Benchmark \`llama.cpp\` speculative decoding configurations **on the actual model and hardware**, not based on published speedups from different GPUs. Compare TTFT, p50/p95 audible answer time, completion accuracy, draft acceptance, peak RSS/VRAM, game FPS, and OBS skipped/network frames. The upstream SPEED-Bench client includes category-based measures for server inference: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- Cache stable system/tool documentation and reusable task prefixes; invalidate caches with source/model changes. Make semantic retrieval provenance-aware and deduplicate near-identical memories to reduce context costs. Avoid feeding a huge undifferentiated "brain" into every prompt.
- Reserve fast, short, low-cost paths for game reactions and interrupt acknowledgments, with deliberate slower reasoning for novel mechanics or research. More raw tokens are not automatically more intelligence.
- Compare CPU speech models against a known baseline using listening tests, barge-in recovery, and actual latency; never trade away intelligibility merely to lower model cost.

## More believable VTuber personality without fake human history

STAR should be expressive and responsive *as an openly virtual character*. Use a persistent, **evidence-grounded** episodic memory of games, viewer-friendly callbacks, real experiments, and genuine achievements. Never fabricate human childhood experiences, relationships, or private viewer information. A personality can have interests, humor, running jokes, preferences and a fictional character biography while accurately identifying which events actually occurred.

A promising streaming plan is: an **attention arbiter** decides whether she is concentrating on difficult gameplay, answering a question, celebrating, or pausing; a **turn-taking director** handles interruptions and short acknowledgments; a **performance director** maps verified events to eye/blink/mouth/head/ear/twin-tail physics and emotion cues; and an **audio-led timeline** aligns subtitles and mouth motion with playback, not text generation. Add voice variation, believable laughter/breath timing, silence when appropriate, and nonrepeating expressions. Evaluate viewer latency, overlapping speech, false-memory rate, audible-caption sync, OBS health, and perceived naturalness in blind human tests.

The VTube Studio WebSocket API documents authenticated plugin access, hotkeys, and custom parameter injection. Its hotkey queue is bounded and should not be flooded:
https://github.com/DenchiSoft/VTubeStudio

For OBS, preserve password-protected localhost WebSocket access and explicit event continuity. OBS WebSocket ships with OBS Studio 28+:
https://github.com/obsproject/obs-websocket

## Next implementation priorities

**P0 — Windows Studio reality check:** run the generated LocalScript in an authorized private Studio test and inspect failure cases. Then connect the independent observer and prior seven-stage playthrough gate to a genuine Studio episode; reject unsigned or client-only logs.

**P1 — Game mastery evaluation:** add a task suite with seeded obby, combat/dodge, platformer, and UI puzzle episodes, hidden goals and fresh maps. Measure zero-shot, after-practice, and transfer scores. Add a visual before/after world-state verifier and persistence check on real rejoin.

**P1 — live multi-resource A/B:** run Roblox/OBS/Star voice/avatar together and compare the same workload against candidate inference configurations; automatically reject regressions in OBS continuity, FPS, p95 response, and held-out quality.

**P2 — character performance:** run a 20-minute private stream rehearsal with natural interruptions, gameplay attention changes, idle gestures and realistic twin-tail physics, collecting listener ratings and AV synchronization error. Only promote configurations that outperform baseline.

**P2 — knowledge and creative breadth:** build a rights-aware index of official Roblox/Luau documentation, Blender, animation, math, networking, audio production, and general STEM, with license/source/version and contradictory-evidence handling. Practice new knowledge on private reproducible exercises, then verify transfer.

**P3 — Star Core Forge:** use the owner-controlled, offline-first internal experiment repository as the canonical self-improvement record; GitHub remains optional publishing of reviewed results. Keep local semantic diffs, verified benchmarks, rollback snapshots, and approval gates for irreversible/public actions.

**Deployment state:** only offline compilation and Python unit tests are available here. No live Studio, OBS, audio, VTube Studio, source-model retraining, or proven acceleration occurred in this change. All performance improvements described above are hypotheses requiring measured verification.
