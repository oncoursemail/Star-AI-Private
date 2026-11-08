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

## Owner-device silent native activation check (new, optional)

A first test on the owner's Windows 11 build 26200 **successfully activated real process-specific native loopback capture** against a separately compiled, **silent** `StarVoiceProbe.exe` fixture. It does not play sound, capture a microphone, open OBS, listen to another app or claim verified physical silence. The fixture is not the production STAR voice process. An on-device, owner-invoked 900ms run produced 19 diagnostic records, 91 PCM callbacks, 43,680 sample frames and a maximum normalized peak of **zero**. This demonstrates that this Windows setup can produce zero-amplitude PCM callback frames even with no fixture audio playback; these are never proof of physical silence.

From the repository root in PowerShell, with a locally installed .NET 9 SDK:

```powershell
.\\tools\\star-process-loopback\\private-silent-probe.ps1 -OwnerApproved -DurationMs 900
```

The probe is **disabled by default** and refuses to launch without explicit `-OwnerApproved`. It builds in an isolated temporary directory, pins the target to its own child process, validates diagnostic count invariants and refuses any asserted streaming/physical-silence authority. It outputs one bounded **aggregate JSON** summary; no PCM or private content is retained. The script may restore the pinned NAudio dependency. Do **not** run it on a browser, game or general audio process; it does not accept an arbitrary PID. GitHub Actions tests only syntax and the default-deny path, and never performs a valid native capture.

See [the measured owner-device result and intelligence roadmap](../../docs/research/STAR_20261107_OWNER_WINDOWS_NATIVE_LOOPBACK_AND_REALTIME_INTELLIGENCE.md). A real dedicated STAR speech playback + device-stop + OBS recording-only trial remains the next unverified milestone.

## Low-amplitude positive-control fixture (optional; **audible**)

The previous silent fixture only showed native *activation* and often delivered
zero-amplitude PCM. This additional **separately guarded** experiment produces
a short, deliberately quiet 440 Hz tone in a new, dedicated `StarToneProbe.exe`
child process, then validates that its process-tree loopback observation contains
actual nonzero PCM. It never targets an existing process and never uses a
microphone, game, OBS, browser, viewer chat, or production Star speech.
**It can be audible on the default Windows speaker/headset**, so it is OFF by
default, **never run by CI**, and requires both opt-in switches:

```powershell
.\\tools\\star-process-loopback\\private-tone-probe.ps1 -OwnerApproved -AllowAudibleTone -DurationMs 1800
```

The probe builds two pinned .NET 9 projects in a disposable temp folder.
NAudio.WinMM 3.3.0 renders generated 16-bit stereo PCM at **3% of full-scale
peak**, with a 10ms fade and a hard 2-second waveform bound. The tone child
begins after a short lead-in so the process observer can subscribe first, and
exits after bounded playback. The host refuses captures with invalid counters,
missing positive windows, unexpected PCM levels, or authority claims. Only
aggregate diagnostic JSON goes to the local terminal. The diagnostic source
does not save any PCM, and the script clears its temporary build and kills its
dedicated child in `finally`.

`dotnet ...StarToneProbe.dll --self-test` checks its deterministic waveform
without initializing an audio endpoint. GitHub Actions **only** builds and
self-tests this fixture and rejects scripts lacking BOTH switches. The first
source release has **not** established a passing actual Windows positive-tone
run. A passing positive tone would establish only PCM activity from a
controlled process, **not** physical speaker audibility, correct Star TTS
output, speech recognition, cancellation, native packet queue drain, OBS
recording, gaming proficiency, or broadcast permission.

Use the silent negative control separately; neither control is a substitute
for a signed production Star speech process or a complete nonbroadcast
interruption-and-OBS rehearsal.

## Owner-supervised local voice test (explicit, bounded)

```powershell
dotnet tools/star-process-loopback/bin/Release/net9.0/Star.ProcessLoopback.dll --observe --pid <StarVoicePID> --expect-exe StarVoice.exe --duration-ms 1200
```

This observes only the target voice **process tree** for 300–5000 ms and emits sanitized newline-delimited JSON. The `max_peak_milli` is a diagnostic peak (0–1000), not loudness in dB, recognition quality, audible output identity, speech presence, or calibrated threshold. It never drives input or starts OBS/voice. No PCM is written. A native callback may **stop firing when the process is silent**; no callback does *not* prove quietness.

Each emitted JSON record now also reports a **local per-interval activity window**: `activity_window_ms`, `activity_callbacks`, `activity_sample_frames`, `activity_peak_milli` and `activity_rms_milli`. Peak and RMS are amplitude indicators scaled from clamped floating-point PCM (0–1000), not calibrated sound-pressure levels. They reset between reports instead of retaining the peak of the entire recording. **If no PCM samples arrive, peak and RMS are null, not zero**—missing callbacks are not evidence of digital silence. A callback may cover a different period than the JSON polling interval, so these windows are arrival-time buckets, not sample-accurate synchronization, speech recognition or guaranteed end-to-end latency. The dedicated host still needs native packet-state, voice PID lifecycle, audio abort, OBS and avatar evidence. `verified_silence` remains false.

Even though the CLI emits no audio bytes, its coarse activity timing can expose when the voice process was speaking. Keep the output local, ephemeral and private; do not forward the JSON to public chat, Discord, telemetry, a model prompt, or broadcast overlays. The new fields offer a **diagnostic before/after activity trace for owner-supervised rehearsal**, never playback-control authority.

 Process exit, PID/creation-time mismatch, malformed PCM, unsupported Windows or audio activation failure produces nonzero exit or `capture_invalid`. Do not reuse a stale successful run after an audio route/worker restart.

## Real acceptance needed before integration

1. Pin the dedicated voice **OS process handle** inside a trusted Windows supervisor (not user-supplied PID or model text), and attest stable process tree and routing. Establish a known-audible, independent pre-interruption reference.
2. Abort real TTS output; separately verify NAudio capture is healthy, native pending-packet queue is empty, and callback-generation counters do not change for the quiet interval. A missing callback alone is insufficient.
3. Require post-stop observations against the same trusted capture/route generation, independent audio queue drained and avatar neutral, then review an OBS **recording-only**, nonbroadcast rehearsal.
4. Confirm normal gameplay/OBS FPS, endpoint latency, GPU VRAM headroom and speech quality. Never turn this test's diagnostic output into authority to stream.

No live process capture or Windows-native smoke test has yet been performed by this commit.

Sources: [Microsoft process loopback](https://learn.microsoft.com/en-us/windows/win32/api/audioclientactivationparams/ns-audioclientactivationparams-audioclient_process_loopback_params), [NAudio 3 WasapiRecorder](https://naudio.github.io/NAudio/docs/WasapiRecorder.html), [NuGet NAudio.Wasapi 3.3.0](https://www.nuget.org/packages/NAudio.Wasapi/3.3.0).

## Optional GitHub-hosted Windows packaging check

The separate [Windows process-loopback smoke workflow](../../.github/workflows/star-process-loopback-windows.yml) uses an **ephemeral GitHub-hosted Windows runner**, never the owner's Windows PC. For a pull request touching this diagnostic it restores NAudio 3.3.0, builds a **self-contained Windows x64 single-file executable**, executes only `--self-test` and rejected argument paths (no valid `--observe` invocation), and uploads a **one-day retention** diagnostic artifact.

The artifact includes `Star.ProcessLoopback.exe`, this README, and `manifest.json` containing the checked-out Git commit/tree, executable SHA-256, and explicit negative attestation fields for live capture, quiet-state verification, and permission to stream. Self-contained publishing eliminates the need to install .NET 9 on the target Windows machine; it does **not** eliminate Windows/NAudio requirements or attest native capture reliability.

To inspect the artifact **without capturing anything**, extract into a fresh local directory, verify the executable's SHA-256 against `manifest.json`, and run:

```powershell
Get-FileHash .\Star.ProcessLoopback.exe -Algorithm SHA256
.\Star.ProcessLoopback.exe --self-test
```

Do not run the `--observe` command on a general-use process. A real capture rehearsal requires an independently verified dedicated voice subprocess and owner-approved isolation; the artifact is a **diagnostic**, not a streaming executable or proof of silence. If the Windows workflow is queued, failing, or has never run, there is **no verified Windows executable** to claim yet.


## Read-only Python JSONL integrity boundary (new)

For a **private, owner-started diagnostic**, the local trusted host may instantiate
the Python `star.process_loopback_activity.ProcessLoopbackActivityVerifier` with
`owner_approved=True` and feed each complete UTF-8 JSON line from this
native process's **authenticated, PID/start-time pinned stdout stream** to its
`feed_line()` method. The parser validates monotonic cumulative callback
and frame counts against each **atomic activity interval** and fails closed for
malformed/reordered/duplicated/invalid messages. It rejects claims of silence,
game authority, and broadcast permission. Missing PCM yields an *unknown*
amplitude hint; it never manufactures a quiet period.

Read `summary()` only after a normal native process exit and the
`capture_complete_no_silence_claim` terminal event. The summary remains
an advisory PRIVATE diagnostic, **not** an audio-quietness witness. The host
must separately attest that capture remained process-isolated, native stop
succeeded, the avatar returned neutral, OBS never broadcast, and the correct
Windows speaker/monitor was independently observed. A model, chat message or
webhook cannot supply native JSONL or assert these conditions.

The `--self-test` now exercises atomic cross-thread activity-window
accounting with synthetic float packets. It starts **no** Windows capture.
See `docs/research/STAR_20261107_PROCESS_VOICE_ACTIVITY_INTEGRITY_AND_REALTIME_GENERALIST.md`.


## Independent portable-artifact admission gate (manifest v2)

A GitHub-hosted workflow passing its synthetic checks is not proof that the
downloaded EXE is still the one that CI built. The v2 manifest includes a
SHA-256 for the README in addition to the EXE, and the job summary prints the
SHA-256 of the **manifest itself**. Before downloading/extracting, separately
pin the job summary's manifest digest, EXE digest, checkout commit and checkout
tree from a trusted CI interface. Hashes copied from the downloaded manifest
are not independent and cannot establish provenance.

From the Star repo with Python 3.12+, in a private local terminal (no executable
will be run or audio captured):

```powershell
python -m star.process_loopback_artifact_audit `
  --artifact-dir C:\Star\voice-artifact `
  --approved-root C:\Star `
  --expected-manifest-sha256 <independent-manifest-sha256> `
  --expected-executable-sha256 <independent-executable-sha256> `
  --expected-checkout-commit <independent-git-commit> `
  --expected-checkout-tree <independent-git-tree> `
  --owner-approved
```

The gate checks the exact three-file layout, independent manifest and EXE
digests, README digest from the pinned manifest, source commit/tree and
negative nonbroadcast/noncapture attestations. It rejects links, hardlinks,
unknown files, malformed JSON, and changed bytes. It returns only a sanitized
boolean summary. Even success does **not** authorize executable launching,
real recording, game control or broadcasting; those require distinct
owner-approved Windows host checks. Old v1 artifacts are intentionally denied.

See [research and acceptance plan](../../docs/research/STAR_20261107_WINDOWS_ARTIFACT_ADMISSION_AND_REALTIME_LEARNING.md).
