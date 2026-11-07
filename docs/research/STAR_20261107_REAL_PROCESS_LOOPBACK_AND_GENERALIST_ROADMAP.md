# Star AI: real voice capture, fast gaming, generalist skill and natural VTubing
**Research checkpoint:** 2026-11-07 (new work in this patch, versus earlier advisory-only voice witnesses).

## Evidence-led change: from theoretical quiet witness to actual native capture

The previous PRs #1044–#1046 implemented abort coordination and logical quiet evidence, but still lacked a source of real, process-isolated captured audio. This change adds a real, **owner-invoked Windows WASAPI process-loopback diagnostic** in `tools/star-process-loopback/`:

- NAudio.Wasapi **3.3.0** (current stable as checked November 7, 2026), .NET **9**, explicit `WithProcessLoopback(...IncludeTargetProcessTree)`, `BuildAsync()`, stereo 48 kHz IEEE float.
- Enumerates local OS process identity using PID + immutable process start time + expected basename; verifies identity across bounded sample ticks.
- Reads *actual* PCM callback samples in memory to aggregate maximum absolute peak, callback generation and frame count; outputs sanitized NDJSON. Does **not** write raw audio, record microphone, inspect viewer chat, save game frames or broadcast.
- Default invocation without `--observe` fails. One bounded private observation: 300–5000 ms. The only always-safe path `--self-test` checks argument rejection and PCM arithmetic with synthetic samples, without audio capture.
- Important: this is **diagnostic telemetry, not an authoritative silence witness**. It does NOT independently verify native pending capture queue, capture-route health, callback generation against the Windows engine, PortAudio abort completion, physical speaker output, OBS monitor output, or audience hearing. Its own output must not grant a streaming or speech authorization.
- This code is newly compiled with the separately provisioned, local .NET 9 SDK on Linux; **not yet proven on Windows**. Target Windows machine's observed .NET runtime was **8.0.31**, with no SDK shown: an approved .NET 9 runtime or self-contained build is still needed before a local Windows test. Do not silently install runtimes, start a game, capture the user's microphone, or go live.

Technical references: [Microsoft AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS](https://learn.microsoft.com/en-us/windows/win32/api/audioclientactivationparams/ns-audioclientactivationparams-audioclient_process_loopback_params) (Windows 10 build 20348+), [NAudio 3 modern recorder](https://naudio.github.io/NAudio/docs/WasapiRecorder.html), [NAudio.Wasapi 3.3.0 NuGet](https://www.nuget.org/packages/NAudio.Wasapi/3.3.0).

### Avoid false claims from silence

NAudio documents that process loopback may emit **no buffers at all when no sound plays**. Do NOT stuff zero audio in a queue, interpret no callback as an endpoint quiet guarantee, or confuse an individual voice process with the full speaker mix. To promote #1046's quiet-witness adapter, a trusted native host must supply independently corroborated capture-health, queue emptiness, stable process handle, callback generation, current route identity and real clock. Only then compare pre-stop captured speech against post-stop quiet, and require stop/queue/avatar independent gates.

## Game intelligence: prioritize actions before the deadline

*Gym-Anything-RT* (Aggarwal/Welleck, **October 27, 2026**) evaluated 100 minigames with moving environments and paused controls. Its observed paused-versus-real-time performance gap is a reason to split reflexes, tactics and postgame learning, **not** evidence that Star already plays well.

Architecture for Star's 8 GB gaming GPU:

1. **Reactive path (deadline-bound)**: frame/time stamped perception, small resident model or verified replay skill, stale-frame rejection, single-actuation permit, focused-input watchdog; performance based on first *useful* action latency, not tokens/second.
2. **Tactical path (between opportunities)**: plan positions/objectives/risk, maintain a compact state summary and a bounded action whitelist; never start a large teacher model in a critical gameplay frame.
3. **Teacher/practice path (off-stream)**: controlled minigame resets, matched A/B skill variants, scene observations, trusted outcome checks, multiple independent seeds, and unseen holdouts. Keep private holdouts out of the training planner.
4. **Transfer metric**: compare success and latency on new seeds, maps, controls and game versions; if data is inconclusive, retain prior policy and request more practice. No self-reported intelligence points.

Sources: [Gym-Anything-RT](https://arxiv.org/abs/2610.37567), [Roblox OpenGameEval](https://github.com/Roblox/open-game-eval) / October 1 paper [arXiv:2610.02563](https://arxiv.org/abs/2610.02563). OpenGameEval's inspected-object advantage suggests Star should examine scene hierarchy and logs before Luau edits, then test the running game.

## Real inference and system speed: measured rather than speculative

In one read-only snapshot from the connected Windows RTX 3060 Ti on 2026-11-07, NVIDIA reported **8,192 MiB total, 407 MiB free, and 89% GPU utilization**. This is *not* an average, an A/B benchmark or proof of memory pressure in a particular process. It does make a VRAM-heavy extra model unsafe to launch without fresh admission.

- Preserve GPU headroom for game rendering + avatar + OBS; GPU worker leases must conservatively account for allocations and confirmed process exit.
- Benchmark identical model/quantization/context/prompt sets under: idle desktop; actual game; game + avatar; game + avatar + OBS recording. Log p50/p95 **speech-ready** latency, first-token, full answer, game frame pacing, audio underruns and free VRAM, not just token throughput.
- Consider smaller local drafts, KV/prompt reuse and speculative decoding only as *A/B candidates*. Consumer-GPU speculative decoding can regress on small models: never assume a speedup from an unrelated benchmark.
- Use CPU-oriented streaming voice as a candidate to keep the GPU free; compare Kyutai Pocket TTS `english_18m_2026-10`, `english_7m_2026-10`, and `english_2m_2026-10` for expressiveness and accurate pronunciation before selecting, not just size.
- Improve on quality with a model router: lightweight quick replies when verified confidence and time budget permit, stronger teacher after game, bounded retries and evidence-based repair for coding. Use audit logs containing only outcome hashes and anonymized statistics, never chats or private screen content.

Sources: [Kyutai Pocket TTS](https://kyutai-labs.github.io/pocket-tts/), [NAudio](https://naudio.github.io/NAudio/docs/WasapiRecorder.html), and [speculative decoding measured on consumer GPUs](https://trust.inventivehq.com/blog/llama-cpp-speculative-decoding-consumer-gpu).

## Natural gaming VTuber: build a consistent expressive character, not an imitation human

Natural-feeling streams require low latency, reliable interruptions, intention-driven silence, and believable feedback loops. Plan:

- **Live understanding:** listen to approved chat/voice inputs, track actual game events and upcoming danger, use voice activity timing to avoid speaking over people. Keep the assistant explicitly identified as AI and do not claim human consciousness.
- **Speech:** stable individual voice, micro-pauses, laugh/sigh and surprise only when context appropriate, stop promptly for interruptions, never speech on invalidated turns; mouth/eyes/emotion motion must follow actual emitted audio rather than model-estimated duration.
- **Visible behavior:** idle eye movement, blinks, gaze toward tracked in-game objective, animated response to verified wins/losses, noninvasive overlay transitions and reduced-motion support.
- **Personal continuity:** owner-approved long-term notes and verified game highlights, versioned persona choices, avoid fabricating memories or private viewer history; a hobby/goal queue can schedule practice off-stream.
- **Autonomy:** private rehearsals first. Gameplay account access, live conversations, posting and purchases use existing owner-defined boundaries. Prevent chat prompt injection, unauthorized game input, risky moderation and inadvertent streaming of secrets.

Sources: [DyaPlex full-duplex speech-motion](https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/) (June 2026), [Roblox Studio MCP Open Cloud update](https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849) (November 4, 2026).

## Autonomous game creation / general knowledge

For Roblox, bridge Studio MCP to source-controlled Rojo/Luau edits, inspect touched objects before editing, run StyLua/Selene/luau-analyze, execute in **owner-approved private test place**, inspect gameplay and repair. Keep Open Cloud permissions scoped per game; do not publish, modify monetization or access player data without fresh owner approval. Evaluate with OpenGameEval-like executed checks, not just generated code style.

For general knowledge, keep multiple verified source views, uncertainty, date/source pins and an independent grader. Use daily challenge generation in sandboxed settings: new coding/debugging/navigation/UI/audio problems, difficulty matched to verified competence. Store successful lessons only after reproducible evidence, not model confidence.

## Prioritized next acceptance milestones

**P0:** On an approved Windows machine with .NET 9, perform a **private, local** diagnostic against a dedicated dummy voice process, with no OBS broadcast and no user microphone input; ensure no other application enters captured output. Confirm process start-time pinning and no-packet behavior. This source must be integrated through a trusted native pending-packet witness; current stdout alone is insufficient.

**P1:** End-to-end local playback abort + independent source PCM verification + neutral avatar + old-generation queue drop. Measure interrupt time from actual DAC/OBS recording rather than Python test timestamps; no broadcast.

**P2:** Rehearse a small safe game with bounded authorized inputs, avatar, OBS **recording only**, voice and model simultaneously; compare success on 20 seeded trials and p95 response time against measured baseline. Hold inference VRAM when no headroom.

**P3:** Expand game skills and natural turn-taking once P0–P2 produce reliable observed results. Research documents or standalone controllers are not proof of improved intelligence, gaming or character naturalness.

No deployment, autoplay, independent learning, stream, additional GPU worker or measured neural speed gain is claimed in this PR.
