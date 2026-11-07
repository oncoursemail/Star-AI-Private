# STAR: Windows evidence, real-time gaming intelligence, and credible AI VTubing
Research/implementation note — 2026-11-07 (America/Chicago)

## Decision: prove the first Windows component before adding more audio abstractions

PR #1047 introduced an opt-in NAudio 3.3 process-isolated WASAPI diagnostic, compiled and self-tested on Linux, but *not run on Windows*. A practical deployment blocker was incorrectly treated as a reason to change frameworks: the connected owner PC has an older .NET runtime, whereas **NAudio.Wasapi 3.3 requires .NET 9**. Downgrading the project's target to net8.0 is NOT a valid solution. NuGet explicitly lists net9.0 as the minimum package target [1]. Windows process-loopback needs Windows build 20348+ and must target a dedicated voice-process tree [2].

This change adds a GitHub-hosted Windows workflow, not a background executable or a new conversation policy:
- Restore and compile the exact existing .NET 9 project on an ephemeral Windows runner.
- Publish a **self-contained, single-file win-x64 diagnostic**, so no .NET 9 runtime installation on the owner's computer is required.
- Exercise `--self-test` and two invalid invocation paths; **never** call a valid `--observe` in CI.
- Upload a 1-day artifact with executable, owner runbook and source-tree/exe SHA-256 manifest; provenance fields explicitly say **live capture untested**, **quiet unverified**, **stream unauthorized**.
- Permissions limited to `contents:read`; never expose an owner's Windows PC or personal voice/chat processes to untrusted pull-request code.
- A green hosted smoke test proves Windows build + executable startup + argument guard, **not** actual loopback packet capture, hardware sound stopping or audience-ready behavior.

Acceptance after this patch: owner-approved, local, nonbroadcast dummy voice-process trial **on real Windows hardware**, with separate native audio abort confirmation, checked process start identity, measured capture-health polling, and proof of drained native packets. An absent NAudio callback is *not* silence. Only then may the existing `IsolatedLoopbackQuietWitness` receive a trusted native witness, and only through an independently audited host adapter.

## Highest-return intelligence design (research recommendations, not deployed by this patch)

### 1. Separate *reaction*, *planning*, and *learning* clocks

The October 27, 2026 Gym-Anything-RT research evaluates agents while the environment keeps moving. Paused-environment success severely overestimates real-time game skill [3]. STAR already has `game_realtime_loop.py`, `game_deadline_router.py`, `game_paired_study.py`, and `game_holdout_seal.py`; new systems should *reuse* them, not create parallel unconnected scheduling abstractions.

- **Immediate control**: small local state estimator + bounded, deadline-stamped action policy. Reject stale screen observations and out-of-window actions. An AI generation must never block the game's render loop.
- **Tactical thinking**: background planner works on lower-frequency snapshots with an explicit time budget. Its result is advisory and tagged with the observation generation; invalid when the map, health, target or objective changes.
- **Training loop**: record action, perceived state, outcome, latency, and ground-truth evidence. Compare candidate skills against the previously frozen baseline on equal, withheld game seeds with randomized A/B order. Promote only if improvement survives variance and survives unfamiliar maps/mechanics.
- **No benchmark gaming**: segregate training from held-out episodes and avoid reading the scoring implementation in the agent's policy context. Require improvement with real game time advancing, not only pause-mode scores.

For every independent game lane report: objective win/completion rate, deaths/failures, action deadline misses, p50/p95 capture-to-actuation, p95 tool timeout and uncertainty by task family. Do not conflate aim accuracy with successful level completion.

### 2. Hardware-aware inference for 8 GB GPUs: optimize the whole experience

Earlier read-only snapshots of an RTX 3060 Ti 8 GB on Star's Windows PC ranged from very little to several gigabytes of free VRAM. A snapshot is NOT a benchmark. The live target shares VRAM with the game, UI/avatar and potentially OBS; model routing must respond to *measured free headroom and latency*.

Design experiments using fixed prompt and game sequences, stable KV cache, candidate quantizations and streaming token timings:
- Preflight local GPU before model loading. Admit a GPU model only if a configured game/OBS/avatar reserve remains. Make both the reserve and maximum stall explicit and user-configurable.
- A quick policy handles short game reactions and social acknowledgement; expensive reasoning runs asynchronously on another machine or a CPU/split offload only if measured latency is acceptable.
- Compare cold start, warm-cache response, first speakable audio, total task latency and game frame-time 1% low **together**. More tokens/second can be a worse stream if audio start or frame-time jitter increases.
- Treat speculative decoding and prompt caching as A/B experiments with identical questions and correctness checks, not automatic speed boosts.
- STAR's existing `voice/pocket_benchmark.py` can evaluate Kyutai Pocket TTS. Its tiny 2026 English CPU options are legitimate options but published numbers on other CPUs are not STAR benchmarks [4]. Include pronunciation, expressivity and hardware contention in acceptance.
- Protect ongoing games from a large model's memory spike with explicit lease admission/revocation and a graceful CPU fallback. Avoid sustained paging across PCIe.

Proposed *initial* gates for a **private experiment**, not claimed achieved targets: zero crashes in 30 minutes; no sustained FPS collapse; no GPU OOM; zero unauthorized live broadcast starts; all speech interruptions cancel stale model, TTS, queued and native outputs. Gather measurements before setting p95 numeric targets for a specific game/PC.

### 3. Train game skills without losing general reasoning

A reliable skill bank should contain an executable or action-schema skill, supported game/version, preconditions, observations/receipts, counterexamples, and withheld evaluation outcome. Do not promote a natural-language claim of learning.
- **Curriculum**: navigation → timing → dodge → aim → tactical objectives → cooperative play → unknown-game exploration; vary visual theme and controls to measure transfer.
- **Fast failure analysis**: classify failures into perception, planning, deadline, actuator, UI focus, anti-cheat constraint, or unsupported input. Practice the failing subskill rather than repeating the same level.
- **New games**: detect controls and HUD in a sandbox/offline mode, learn simple actions with reversible probes, then gradually escalate. Respect game rules and service terms; never bypass anti-cheat or exploit other players.
- **General knowledge**: curated retrieval with source/date/license metadata, disagreement detection, reproducible code/document tests and uncertainty tagging. Don't train a model on unverified synthetic answers merely to inflate knowledge.

### 4. Produce better games than just plausible-looking code

Roblox added built-in Studio MCP playtesting in March 2026 [5], then expanded external agent Open Cloud access with permission-granted asset and management operations on **November 4, 2026** [6]. This supports a constrained production loop:

Design brief → small testable task → Rojo/Wally/Luau static checks → Studio MCP build → scripted player playtest → visual inspection → independent outcome witness → repair → second run on a different seed → staged publish only with explicit owner approval. Exports to Blender and imported models need asset provenance and moderation gates. No unauthorized purchases, monetization changes, publication or mass server restarts.

Star's tool graph already contains many game evaluation and automation modules. Consolidate verified signals instead of spawning more code paths with no live integration. A high-quality completed vertical slice with objective runtime tests beats hundreds of loosely integrated tool wrappers.

### 5. Human-like *interaction quality*, not false human identity

Research on proactive gaming companionship [7] and full-duplex listening/speaking [8] suggests naturalness comes from selective timing, recognizing interruption versus backchannel, not flooding a stream with commentary. STAR already has multiple output epoch/queue/native-abort gates. Integrate and measure them end-to-end before adding another conversational heuristic.

Design the VTuber as a visibly AI character with consistent character lore. Use:
- Event-sourced memories of **verified** game moments, viewers' opted-in preferences and earlier conversations, with deletion and retention controls. Do not invent memories of offline social activities.
- Vocal prosody driven by game events (surprise, relief, concentration, humor), matched to rig expressions and lip sync. Emotions are character-performance states, not proof of subjective experience.
- Speaking policy: consider relevance, game intensity, recency, whether a person is currently speaking, social value and repeat frequency; silence is a valid action.
- Clear interruption policy: on authenticated request, cancel stale reasoning → TTS → queued PCM → native playback → avatar gestures, await independent host confirmation.
- Evolving personality: consistent interests, distinctive preferences and recurring jokes that reflect actual experience. Avoid unsolicited parasocial manipulation or pretending to be a human host.
- Moderation/consent: age-appropriate interactions, privacy-minimized viewer memory, chat-safety and explicit permission for external account actions. Do not silently reveal player/streamer identities or conversations.

Private owner evaluation: 20-minute replay under changing game pressure; annotate mistaken interruptions, awkward silence, ungrounded commentary, stale jokes, turn latency and avatar/audio desync. Use blinded A/B ratings and include objective latency.

## Suggested build sequence and no-go gates

1. **Now (implemented in this PR)**: hosted Windows packaging and safe CLI smoke of the existing process-loopback diagnostic; collect artifact provenance; avoid changing runtime audio.
2. **Next (not implemented)**: on a dedicated owner-controlled dummy voice process, verify real Windows loopback callbacks and audio device-route stability; fail closed when evidence missing.
3. **Next (not implemented)**: wiring into trusted native PCM/epoch fence and repeatable *recording-only* OBS/VTube Studio game session (never public stream by default).
4. **Next (not implemented)**: randomized paired game policies with blind holdout, measured hardware contention and CPU-TTS comparisons.
5. **Later (not implemented)**: autonomous educational practice and cross-game transfer, with owner-approved tools and audited rollback, daily concise capability/evidence reports.

Treat a green compiler job as a small infrastructure success, not "smarter AI." Make the strongest claims only after real gameplay outcome evaluations, consistent performance gains and physical hardware evidence.

## Sources checked 2026-11-07

[1] NuGet NAudio.Wasapi 3.3.0, net9.0 minimum — https://www.nuget.org/packages/NAudio.Wasapi/3.3.0
[2] Microsoft process loopback, Windows build 20348+ — https://learn.microsoft.com/en-us/windows/win32/api/audioclientactivationparams/ns-audioclientactivationparams-audioclient_process_loopback_params
[3] Gym-Anything-RT preprint, October 27, 2026 — https://arxiv.org/abs/2610.37567
[4] Kyutai Pocket TTS (small English models October 2026) — https://github.com/kyutai-labs/pocket-tts
[5] Roblox Studio built-in MCP and playtest automation, March 5, 2026 — https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
[6] Roblox MCP Open Cloud Permissions and asset import, November 4, 2026 — https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849
[7] Proact-VL, March 3, 2026 — https://arxiv.org/abs/2603.03447
[8] Realtime-Venus, September 12, 2026 — https://arxiv.org/abs/2609.13814
