# Star AI: verified closed-loop game rehearsal, performance and expressive streaming

Date: 2026-10-25. Status: **research + offline opt-in prototype, not deployed**.

## The actual gap and why this change exists

The current series of drafts has a bounded navigation belief map (#595), session-level game skill evidence and streaming callbacks (#594), playback QoS (#593), and VTuber expression/latency guidance (#581). These are useful pieces but none establishes that a proposed game move *really happened* before recommending another move. That missing feedback loop is more important than adding another personality prompt or claiming higher intelligence without data.

`star/game_closed_loop.py` adds a minimal owner-scoped **host → observe → offer → authorize/dispatch → observe/verify** contract. The host alone owns physical inputs and scene capture. A command is only an ephemeral one-step suggestion. Each subsequent movement must be independently observed; blocked movement, unexplained movement, step deadline expiry, owner stop, and max action budget cause fail-closed behavior. Play mode cannot explore unknown cells; practice exploration requires an explicit isolated sandbox permit. The boolean `trusted_host=True` is NOT cryptographic authentication: the adapter/caller must enforce principal, game ownership, consent, rate limits and scope before invoking the module. No actual input is sent.

This is intentionally **stacked on draft PR #595**. It does not edit another draft branch or merge to `main`/`star/next`. Keep new code OFF in regular gameplay until owner review and a real host adapter exist.

## High-leverage intelligence architecture (prioritized)

1. **Closed-loop embodied learning**: game's own host telemetry → timestamped observations → belief state → one-step proposal → separate actuator permission → observed outcome → independent score → game skill memory. Never trust an AI claim of success, screenshots alone, or a SHA checksum as authentication. Separate stable objective goal states from model speculation.
2. **Curriculum and reusable skills**: organize challenges by game/map/mechanic, require a held-out seed and baseline, record successes and failures independently, promote a skill only after reliable gains across sessions. Voyager demonstrates a reusable skill library and environmental feedback; Dreamer-like world-model methods may later reduce expensive practice, but model learning and generalization must be established through experiments rather than assumed.
3. **Human-quality gameplay**: inputs conditioned on observed state; recover from a failed move instead of repeating guesses; learn event rules, timing, mechanics, puzzles, camera movement, navigation, multiplayer strategy (in permitted private tests), and plan with explicit uncertainty. Do not assume symbolic grids generalize to pixels, physics, arbitrary controls or third-party online games. Future host adapters may translate camera frames into validated objects with confidence, but confidence must be calibrated against manually scored scenes.
4. **Generative game building**: from user requirements → style references and layout graph → geometry/attachment/size/overlap/material invariants → Studio build → multi-angle screenshots and playtest → fix defects → independent approval. A standalone collision heuristic is NOT visual perfection; require art direction and user review for subjective quality. Reference `star/architecture_quality.py`/`star/antislop.py` and the Roblox Studio MCP playtest tools to avoid duplicating pipelines.
5. **General knowledge**: retrieval default-OFF; licensed curated corpora, provenance, freshness, dedupe, conflict tracking, human-reviewed lessons. Use independent held-out knowledge questions, citations, calibration and catastrophic-forgetting regression tests; do not claim the LLM's weight intelligence improved merely because memory expanded.

## Expressive, humanlike-but-honest VTuber architecture

- **Personality continuity**: consistent Star character and modes (normal/cat/puppy), a verified evolving in-game history, grounded callbacks, spontaneous but factual commentary, varied prosody, conversational timing and authentic recovery after failed gameplay. Maintain transparency that Star is AI, and do not invent personal human memories, human identity, or viewer intimacy.
- **Conversation pipeline**: VAD/barge-in → incremental audio understanding → context + priority-aware response planner → low-latency incremental TTS → time-aligned mouth/eyes/head/hair/ears/tail animation → authenticated local OBS and VTube Studio adapters. Every outgoing audio/avatar chunk needs a generation-bound playback gate so interruptions cancel stale speech and motions. PersonaPlex explores full-duplex speech; it is a **research option**, not a deployed Star backend. Avoid voice cloning without rights or consent.
- **Streaming judgment**: owner asks override entertainment; chat answers are optional and paced; silence is an intentional behavior during tough gameplay. Reactions must match observed game events; laughter needs expressive audio and animation rather than a static text command. Distinguish gameplay attention from audience attention; no hidden broadcasts or nonconsensual chat capture.
- **Performance on modest graphics hardware**: protect render FPS and voice tail latency first. Reserve GPU/CPU for game + avatar + audio, throttle background training and video inference; place heavier batch work on a second authorized host. Measure FPS p1/p50, stutter, VRAM headroom, audible response p50/p95, voice interruptions, and win rate together. Separate GPU accelerated model experiments from the game performance budget. Consider model quantization, prefix caching, prompt trimming and speculative decoding only after A/B measurement; memory bandwidth and 8GB VRAM may limit gains, and some choices can make performance worse.
- **OBS security**: OBS Studio 28+ has obs-websocket built in; require loopback, authentication, allowlisted scene changes and hard off-switch. VTube Studio documents a supported plugin API. Do not automatically start a live broadcast or write viewer data to a public repo.

## Deterministic acceptance gates before any real-game or stream pilot

- **Code**: exact module/test blobs pass offline in a clean checkout with `PYTHONPATH=. python -m unittest discover -s tests -p 'test_game_closed_loop.py' -v` and `python -m compileall -q star/game_closed_loop.py tests/test_game_closed_loop.py`; no additional dependencies. The synthetic benchmark `PYTHONPATH=. python -m benchmarks.bench_game_closed_loop --seeds 32` reports seed outcomes; numbers describe toy grids only.
- **Actuator authorization**: user-selected, unpublished test game; independently authenticated owner/host permissions; adapter denies arbitrary game commands and remote processes; explicit maximum actions, timeouts and manual stop. Replays, stale frames, unexpected movement, blocked action, collisions and hazard proposals must fail closed.
- **Evidence**: host-signed authoritative step/result association and independently graded episode outcomes before feeding #594's skill memory or stream moment memory. A checksum detects accidental changes, not hostile forgery. Never promote simulated successes to a real game benchmark.
- **Real vision**: capture game with consent, label geometry and player position, evaluate false-positive and false-negative obstacles, and keep a manual recovery path. A symbolic grid test cannot prove robust visual perception.
- **Release & integration**: review stacked PR dependencies, run full repo CI, and obtain owner go-ahead before enabling any live actuator, TTS, stream software, recording, or game publication. Do not merge into main automatically.

## Primary sources reviewed

- Roblox, **Studio Built-in MCP Server and Playtest Automation** (2026-03-05): https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 . Supports authentic edit/playtest/input loops, not proof of autonomous general-purpose gameplay.
- Roblox Creator Hub, **Studio testing modes**: https://create.roblox.com/docs/studio/testing-modes . Different simulated client/server testing modes matter for verification.
- Voyager, **An Open-Ended Embodied Agent with Large Language Models**: https://github.com/MineDojo/Voyager . Reusable skills and environment feedback; benchmark achievements belong to Voyager, not Star.
- llama.cpp, **Speculative decoding**: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md . Options have model-specific tradeoffs; test actual acceptance rates and latency.
- NVIDIA **PersonaPlex**: https://github.com/NVIDIA/personaplex . Full-duplex conversational speech research, not yet integrated.
- OBS Project, **obs-websocket**: https://github.com/obsproject/obs-websocket . OBS 28+ bundling; password authentication is recommended.
- DenchiSoft, **VTube Studio documentation**: https://denchisoft.com/documentation/ . Plugin/API for animated avatar control.

## Next integration increment

Build a real *owner-controlled* Studio private-place host adapter with authenticated session scope and frame-to-actuator causality, run the same held-out cases in Studio as in this synthetic rehearsal, and report true action success, collisions, wins, FPS and end-to-end speech timing. Integrate game outcomes with #594's verified skill/moment ledgers only after the host observation contract is proven. The present module is not a new LLM and cannot autonomously play arbitrary games without those integrations.
