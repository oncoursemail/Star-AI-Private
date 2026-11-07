# Star process-isolated audio diagnostic (opt-in)

This is a **real Windows process-loopback capture implementation** for privately diagnosing Star's voice output. Unlike a placeholder witness, it calls NAudio 3's `WasapiRecorderBuilder.WithProcessLoopback(...).BuildAsync()` and reads actual WASAPI process-tree PCM callbacks. Only bounded counts, peak levels, and heartbeat counters go to standard output: audio samples, filenames, transcripts, and device identifiers are never stored or emitted.

**IMPORTANT:** The CLI is an *untrusted diagnostic*, not proof of audio silence, a live-ready audio device, an authenticated host, stopped audio, or permission to broadcast. It cannot service `IsolatedLoopbackQuietWitness.observe_no_packet_poll` because NAudio's callback count alone is not an independent **native pending-packet query and healthy-poll witness**. It is never automatically launched. Do not pass its stdout to an AI model, chat, remote webhook, or any runtime speech authorization path.

## Requirements

- Windows 10 build **20348 or later**, Windows 11 supported.
- Local .NET **9** SDK for builds, .NET 9 runtime for framework-dependent execution.
- NAudio.Wasapi **3.3.0** (NuGet; MIT). Restore is a developer-controlled network action.
- A **dedicated, owner-authorized Star voice process**; never target explorer, a browser, a general-use terminal, the game, or a process that plays someone else's audio.
- Invoked locally by the trusted owner or trusted host. A `--observe` flag is consent signaling, **not authentication**.

## Offline smoke validation (no audio capture)

```powershell
dotnet build tools/star-process-loopback/Star.ProcessLoopback.csproj -c Release
dotnet tools/star-process-loopback/bin/Release/net9.0/Star.ProcessLoopback.dll --self-test
```

## Owner-supervised local voice test (explicit, bounded)

```powershell
dotnet tools/star-process-loopback/bin/Release/net9.0/Star.ProcessLoopback.dll --observe --pid <StarVoicePID> --expect-exe StarVoice.exe --duration-ms 1200
```

This observes only the target voice **process tree** for 300–5000 ms and emits sanitized newline-delimited JSON. The `max_peak_milli` is a diagnostic peak (0–1000), not loudness in dB, recognition quality, audible output identity, speech presence, or calibrated threshold. It never drives input or starts OBS/voice. No PCM is written. A native callback may **stop firing when the process is silent**; no callback does *not* prove quietness. Process exit, PID/creation-time mismatch, malformed PCM, unsupported Windows or audio activation failure produces nonzero exit or `capture_invalid`. Do not reuse a stale successful run after an audio route/worker restart.

## Real acceptance needed before integration

1. Pin the dedicated voice **OS process handle** inside a trusted Windows supervisor (not user-supplied PID or model text), and attest stable process tree and routing. Establish a known-audible, independent pre-interruption reference.
2. Abort real TTS output; separately verify NAudio capture is healthy, native pending-packet queue is empty, and callback-generation counters do not change for the quiet interval. A missing callback alone is insufficient.
3. Require post-stop observations against the same trusted capture/route generation, independent audio queue drained and avatar neutral, then review an OBS **recording-only**, nonbroadcast rehearsal.
4. Confirm normal gameplay/OBS FPS, endpoint latency, GPU VRAM headroom and speech quality. Never turn this test's diagnostic output into authority to stream.

No live process capture or Windows-native smoke test has yet been performed by this commit.

Sources: [Microsoft process loopback](https://learn.microsoft.com/en-us/windows/win32/api/audioclientactivationparams/ns-audioclientactivationparams-audioclient_process_loopback_params), [NAudio 3 WasapiRecorder](https://naudio.github.io/NAudio/docs/WasapiRecorder.html), [NuGet NAudio.Wasapi 3.3.0](https://www.nuget.org/packages/NAudio.Wasapi/3.3.0).
