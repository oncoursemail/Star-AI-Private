# Star AI — Isolated Voice Quiet Evidence, Natural VTuber & Faster Gaming Roadmap
**November 7, 2026 — Opt-in engineering experiment, not a live-stream deployment**

## Tested change in this branch
The earlier draft #1044 can ask PortAudio to abort output promptly, but an abort-return flag and an empty application buffer are **not independent evidence of silence**. This branch adds `IsolatedLoopbackQuietWitness` and deterministic tests. The witness processes short signed PCM16 little-endian mono samples from a separately owned *isolated voice-output capture*. It retains no audio, speech text, viewer data, or device identifiers. It requires:

1. Owner opt-in; fixed capture sample rate; one fresh, never-reused speech epoch.
2. A real, nonzero reference block observed just before interruption, confirming that the capture path was receiving actual audio. No valid pre-stop signal = hold.
3. An authenticated epoch revoke and a native-abort request done **outside** this module by the trusted host. Call `begin_stop` with its time.
4. Continuously timestamped, genuinely captured *post-stop* blocks totaling a configurable quiet interval (180 ms by default). A loud block, missing block, stale frame, route change, replay or failure invalidates or restarts evidence as appropriate.
5. Freshness check plus **separate** trusted confirmations that isolated capture is healthy, the native abort completed and the avatar is neutral. Only then may the host use `ready()` as one input to `LocalEpochPCMSink.observe_quiet(... native_output_flushed=True)` and `NativeAbortPCMSpeaker.resume_after_flush(... independently_quiet=True)` on a *new* epoch.

**Scope limitation:** The new class accepts trusted digital PCM16 capture; it does not open WASAPI devices or attest physical headphones, speakers, virtual mics, OBS monitoring, or listeners. A malicious or defective capture backend that fabricates healthy zero-filled buffers could still mislead it. The owner-controlled native host must validate routing and actual capture health before setting its flags. No model or viewer may supply them.

## The important Windows discovery: endpoint loopback is the WRONG capture for a gaming VTuber
Microsoft's regular WASAPI loopback captures the whole output-endpoint mix. If a game is still making sounds after Star interrupts her own TTS, whole-endpoint loopback stays nonquiet and cannot distinguish Star speech from game audio. **Do not mute the game to pass the speech quiet gate.** Instead, isolate Star's voice with a dedicated output path or Windows *application/process loopback* (include only the trusted speech process tree).

Microsoft documents process loopback as available beginning in Windows 10 build 20348; the owner computer's read-only OS inspection during this run reported Windows 11 Pro build 26200, so it is an eligible **research candidate**, but the feature, permissions, process tree and routing are not yet exercised. A dedicated voice process must not share its PID tree with game/OBS sound. Validate process descendants and session changes. An application loopback that captures no active streams returns silence, hence the required pre-stop nonzero reference and health checks.

References:
- Microsoft, [Application loopback audio capture sample](https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/).
- Microsoft, [WASAPI endpoint loopback](https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording).
- Microsoft, [AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK](https://learn.microsoft.com/en-us/windows/win32/api/audioclientactivationparams/ne-audioclientactivationparams-audioclient_activation_type).
- [PortAudio abort semantics](https://files.portaudio.com/docs/v19-doxydocs/portaudio_8h.html).
- [VTube Studio local WebSocket API](https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md).

## Operator integration sequence (nonbroadcast; owner-controlled)
- OFF by default. Do not connect to installed microphone, OBS broadcasting, live audio service or a game process in unattended tests. Use separate synthetic audio and isolated trusted capture in a local *recording-only* rehearsal.
- Confirm speech process identity and parent/child tracking with Windows Job Objects; route ONLY speech to process loopback. Verify signal present while short test TTS is audible on that route; verify quiet capture does not merely mean capture process disconnected.
- Revoke the output epoch before stopping producers and audio queue. Trigger strict PortAudio abort, then start witness post-stop block collection. Include application-loopback buffering in latency estimates.
- Sample avatar neutrality directly from the trusted rig bridge; do not infer it from finished network writes. Require all gates with a common monotonic clock and fresh route-generation ID; reject captured blocks after device/route/process change.
- Count actual last speech sample after stop to compute p50, p95 and worst-case *isolated-voice* interruption latency. Compare independent OBS recording to the capture timing without claiming listeners heard exactly that waveform.
- Never send `StartStream` as part of private tests. Require a human-controlled approval gate before any broadcast.

## Intelligence, game mastery and high throughput: specific next engineering steps
1. **Task-level adaptive compute.** Keep the fast reaction loop deterministic and latency-bounded. Run strategic planning on snapshots with frame timestamps and deadlines; discard plans that have become obsolete. Escalate only genuinely hard situations to a stronger model. Benchmark success on *held-out*, real-time game episodes, not self-ratings.
2. **Verified skill memory.** Store compact observation/action/result receipts keyed by game version, scene hash and known mechanics, with short skill expiry under changed mechanics. Compare strategies in matched episodes before promoting them; keep experiment rollbacks and provenance offline. Research basis: Roblox [OpenGameEval](https://arxiv.org/abs/2610.02563), which uses executable game tests, and [Gym-Anything-RT](https://arxiv.org/abs/2610.37567), which studies live reaction deadlines.
3. **RTX 8GB resource arbitration.** Read-only snapshot on the connected Windows PC during this run: RTX 3060 Ti, **422 MiB free out of 8192 MiB**. This is an instantaneous observation, not a sustained benchmark. Avoid simultaneous aggressive LLM VRAM allocations and live gaming; reserve a measured GPU budget for renderer, avatar and OBS. Use CPU TTS when it *passes quality and latency tests*; route large analysis jobs to the second computer/offline windows.
4. **End-to-end latency experiments.** Bench first-audible-speech ms, p95 interruptions, game frame-time spikes, OBS drops, caption staleness and game success. Compare candidate model quantizations, KV reuse, speculative decoding and CPU-vs-GPU speech generation with matched prompts and scenes. Improve performance only with independently reproducible measured gains; not assumed tokens/second.
5. **A believable but transparent VTuber.** Pair persistent *verified* episode memories with contextual reactions, natural pauses, speech-to-gesture alignment, viewer-addressed turn selection, interruption handling, tone variation, jokes and self-initiated creative projects. Do not impersonate a human or manufacture experiences: Star is an AI performer with a consistent character.
6. **Autonomous Roblox creation.** Roblox's [November 4, 2026 Studio MCP update](https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849), if permissions are enabled, can support Open Cloud actions and Blender asset imports. Keep permission scopes narrow; use Luau lints, test places, asset audits, independent playtests and reversible commits. Treat OpenGameEval as an evaluation model, not as evidence Star already builds complete games unattended.

## Acceptance and outstanding gaps
- **Delivered:** Python witness, simulated tests including the existing `LocalEpochPCMSink` handoff, deterministic invalid-route/stale-frame/replay cases; no external audio input required.
- **Not delivered:** real Windows process-specific WASAPI capture backend, actual sounddevice + portaudio playback verification, VTube Studio websocket motion feedback, OBS recording, network gameplay, validated FPS/tokens-per-second improvement, or human-level cognition. Those are distinct integrations requiring observation and evaluation.
- **Safety:** Never treat empty buffers, untrusted zero samples, stopped flags, fake tests, or an agent's own report as independently verified silence. Retain draft status until CI and separate owner-reviewed Windows rehearsal pass.