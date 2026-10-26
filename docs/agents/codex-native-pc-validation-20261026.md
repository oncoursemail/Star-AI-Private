# Dedicated Windows PC: measured setup progress

The fresh Windows installation exposed failures that offline fixtures had not exercised. Camera registration inspected an unset native exit code, speech recognition looked for an unpinned Hub alias instead of its installed snapshot, and the audio reader opened WASAPI from a thread without COM initialization. These paths are corrected, with independent review and focused regression checks. The installer also remembers the owner's Modrinth choice and consolidates its generated Discord desktop shortcut.

## Native observations

The dedicated machine reported an RTX 4060 with 8188 MB video memory and 32 GB system memory. Installation uses `D:\STAR`. Native logs and account details remain local; no credentials or private screen captures belong in this repository.

| Check | Observed result | Limit |
|---|---|---|
| Installed packages | Hash-checked packages/models installed; PyTorch reported CUDA and RTX 4060 | Not a combined game/stream benchmark |
| Desktop input | A fixed Notepad test moved along 67 points and saved the expected text in 5.8 seconds; a separate real Executor test refused movement under STOP and restored the cursor afterward | This preceded the new native receipt patch; no claim of perfect control |
| Microphone | Virtual cable route verification passed; native Windows default input reports STAR Microphone | Discord's selected input and an actual conversation still require checking |
| Speech output | Verified local models; CUDA session; warm process loaded TTS in 1.5 s, synthesized a 2.603 s clip in 0.750 s and drained it to the physical output | First cold process loaded for 82.2 s and hit its 90 s watchdog during first inference; the owner was not listening to the successful playback |
| Camera | Awaited registration succeeded; local self-test sent 18 frames with zero sink errors | Initial self-test reported 42 dropped frames; sustained frame rate, Discord camera selection and the production rig remain unverified |
| Conversation engine | After the speech-cache and COM fixes, the loopback-to-virtual-microphone bridge stayed alive for its five-minute limit and cleaned up | Zero conversation turns completed; this is not proof of an answered Discord call |

The official Minecraft Launcher package was uninstalled through its exact package ID. Its absence was checked afterward, while Modrinth remained present. The desktop Discord link now opens the existing app with accessibility enabled; the signed-in session was not restarted. Automatic user-account calling was not enabled.

## Continuous capture and pacing

Computer activities now own a continuous, memory-only latest-frame worker. It overwrites a single slot, rejects stale frames, preserves capture timestamps, and closes with STOP, attention interruption or activity cleanup. Preview neither starts capture nor sends vision requests. Pending cleanup retains per-home ownership, and a live session switched to preview remains cancelled until rebuilt. Sampling rate and maximum frame age are local settings; defaults remain 30 Hz and 0.5 seconds.

Two six-second tests used the same 640x360 moving synthetic window on the target PC, with a 60 Hz requested sampling rate. Known test colors were checked in the captured region; no pixels were saved or sent to a model.

| Version | Sample updates/second | Consumer frame age p95 | Capture-call time p95 | Cleanup |
|---|---:|---:|---:|---|
| Event-wait pacing | 28.95 | 30.85 ms | 2.08 ms | Complete |
| Short-sleep pacing | 53.53 | 17.87 ms | 2.05 ms | Complete |

A separate timing probe found `Event.wait(1/60)` at 32.48 ms median and `time.sleep(1/60)` at 17.35 ms on this machine. The revised pacer uses positive sleeps of at most 5 ms between cancellation checks and does not change global Windows timer settings.

These are sampled desktop-state measurements, including confirmed unchanged states. They do not measure distinct rendered pixel changes, semantic model perception or reasoning speed. Continuous capture is connected during Computer activities; always-on idle capture and continuous semantic perception are not connected. The visual grounding endpoint remains unconfigured until native model calibration establishes a usable model and coordinate convention.

## Checks and remaining setup

The new standalone checks total 186 cases: camera paths/registration 11, setup preferences/shortcuts 10, pinned speech cache 9, audio COM/failure visibility 6, live capture/lifecycle 120 and native input receipts 30. Independent agents reviewed the implementation and reran the relevant checks. Existing affected suites passed in overlapping groups, including 151 consolidated tests and 127 Home/voice tests. The 151-test run retains one warning from an existing fake TTS object in a background acknowledgement thread; harness tests were not edited. Compilation and focused Ruff/Pyright checks passed. This does not claim the whole repository's pre-existing typing errors are resolved.

The native input receipt changes validate OS insertion counts, retain uncertain worker ownership and report failed cleanup as unverified; they still require the updated native app-level input probe. See [input receipt notes](codex-native-input-receipts-20261026.md).

Full unattended desktop acceptance, delivered conversation, permitted game sessions with other people, combined streaming load, vision grounding, production avatar rigging and subjective voice review remain open. The source preview's overall target-acceptance and production-rig flags remain false. Emotion/recall candidates remain disabled, no accounts or bank services were connected, no stream was started, and the sealed evaluation was not changed.

Primary implementation references: [Microsoft COM thread initialization](https://learn.microsoft.com/en-us/windows/win32/api/combaseapi/nf-combaseapi-coinitializeex), [PowerShell awaited processes and quoting](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/start-process?view=powershell-5.1), and [pinned DXcam capture/release behavior](https://github.com/ra1nty/DXcam/blob/v0.3.0/README.md).
