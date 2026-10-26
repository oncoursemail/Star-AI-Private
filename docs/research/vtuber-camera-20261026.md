# STAR Camera research (2026-10-26)

Goal: STAR turns her camera on in a Discord video call (or any app) and it shows her VTuber avatar, lip-synced to her
voice, with expressions from the emotion engine; she can also share her screen. Windows, her own PC, RTX 4060 8 GB.

"Verified" below means I read the source or the official page in this session. "Not verified" means no source found
and no run on a real PC; those items are the live acceptance list in `docs/agents/vtuber-camera-20261026.md`.

## 1. Avatar stacks (free / local, Windows)

| Stack | What it is | Fit for STAR |
|---|---|---|
| VTube Studio API | WebSocket API on `ws://localhost:8001`; plugin asks for a token, the user clicks Allow in a popup; `InjectParameterDataRequest` drives parameters and must be resent at least once a second. API repo is MIT. [DenchiSoft/VTubeStudio](https://github.com/DenchiSoft/VTubeStudio) | Needs the VTube Studio app and a Live2D model (art not approved). The Allow popup is a manual step. Kept as a later option, not built. |
| VSeeFace + VMC | Free; VRM0 models only (not VRM 1.0); sends and receives VMC; has its own virtual camera driver, 1280x720, selectable in Discord per its site. [vseeface.icu](https://www.vseeface.icu/) | Good route if the owner picks a 3D VRM model. STAR sends the pose over VMC (built: `star/vtuber/vmc.py`). |
| VMC protocol | OSC over UDP; blendshapes `/VMC/Ext/Blend/Val name value` then `/VMC/Ext/Blend/Apply`; bones `/VMC/Ext/Bone/Pos`; VRM0 names (A I U E O, Blink_L/R); receiver port 39539. [protocol.vmc.info](https://protocol.vmc.info/english) | Used as the model-driver interface (pose sink). |
| Warudo | Free for non-streaming use; free for streaming only if you own your VTuber IP and have no contract; blueprints. [docs.warudo.app](https://docs.warudo.app/docs/) | Licence wording makes it a poor default for an unattended avatar; not built. |
| Live2D Cubism SDK | Individuals and small-scale businesses are exempt from the release licence; a Publication Licence is required when content made with the SDK is released; assets come from Cubism Editor. [live2d.com licence](https://www.live2d.com/en/sdk/license/) | Heavy dependency plus a licence step; needs the owner's model. Not built. |
| three-vrm | MIT; VRM in three.js (WebGL, WebGPU from v3). [pixiv/three-vrm](https://github.com/pixiv/three-vrm) | Would need a browser/Electron render process plus a capture path to the camera. More moving parts than a CPU renderer. Not built. |
| Direct 2D layered renderer (built) | Pillow compositing of layered PNGs from `avatar.json`, CPU only, no GPU, no external app, no licence. | **Pick.** The approved mascot art (StarFace expression set) works today; a painted layered model with mouth shapes drops in later as a setting. |

Pick: direct renderer as the default (art-agnostic, one process, GPU free for her game and voice models) plus a VMC pose
output so a VRM model in VSeeFace works without code changes.

## 2. Lip-sync from her TTS audio

- Rhubarb Lip Sync: offline CLI, WAV/Ogg input, 6 basic + 3 extended mouth shapes (A-H, X); PocketSphinx recogniser is English only; the page does not claim real-time use. [DanielSWolf/rhubarb-lip-sync](https://github.com/DanielSWolf/rhubarb-lip-sync). Needs a finished file, so it would add the whole sentence length to the delay. Rejected for live use.
- Oculus/OVR Lipsync: 15 visemes (sil PP FF TH DD kk CH SS nn RR aa E ih oh ou) from audio; now end-of-life, Meta points to the Movement SDK. [Meta viseme reference](https://developers.meta.com/horizon/documentation/unity/audio-ovrlipsync-viseme-reference/). Native plugin for Unity/Unreal; not usable from a Python camera process.
- Chosen: amplitude + formant-band heuristic in numpy (`star/vtuber/lipsync.py`), 20 ms hops. Opening from RMS; vowel from the first-formant height (E 500-900 / E 200-900 Hz) and second-formant energy (E 1500-2800 Hz); sibilants get a small teeth shape. It outputs the VRM five (aa ih ou ee oh). Calibrated on source-filter synthetic vowels, not recorded speech: aa, ou, ee separate reliably there; oh/aa and ih/ee overlap.
- Timing matters more than shape: frames carry the moment they will be audible (the speaker's pending-seconds at write time), so the mouth moves with what she is actually saying, and a stalled audio path closes the mouth (110 ms rule, same as `star.stream_motion`).

Idle life: blinks every 2.4-4.4 s (sometimes a double), micro-saccades, breathing, slow head sway, hair/ear/tail follow-through, louder speech adds head movement; expression from `emotion.current()["avatar"]` (face held, a cue fires once per change); event reactions (game danger/win, funny video, friend joined) through the same cue vocabulary as `star.stream_stage`.

## 3. Windows virtual camera options

- **pyvirtualcam** (letmaik): Windows backends `obs` and `unitycapture`; `Camera(width, height, fps, fmt=, device=, backend=)`; Windows device names are `OBS Virtual Camera` / `Unity Video Capture` "or the name you gave the device". [README](https://github.com/letmaik/pyvirtualcam), [camera.py](https://raw.githubusercontent.com/letmaik/pyvirtualcam/main/pyvirtualcam/camera.py). Verified by reading both. The native Unity Capture side looks the device up by its registered name (`get_name` in [virtual_output.h](https://raw.githubusercontent.com/letmaik/pyvirtualcam/main/pyvirtualcam/native_windows_unity_capture/virtual_output.h)).
- **Unity Capture** (schellingb): DirectShow filter, filter part MIT. Install.bat registers one device. The filter accepts `/i:UnityCaptureName=NAME` (verified in [UnityCaptureFilter.cpp](https://raw.githubusercontent.com/schellingb/UnityCapture/master/Source/UnityCaptureFilter.cpp) and the repo's own `InstallCustomName.bat`), so the device can be named exactly **STAR Camera**. Two DLLs (32- and 64-bit). [repo](https://github.com/schellingb/UnityCapture). One open issue: with several devices all mirrored the first ([#41](https://github.com/schellingb/UnityCapture/issues/41)); we register one.
- **OBS Virtual Camera**: needs OBS installed and started; one instance only; fixed name "OBS Virtual Camera". Fallback backend (`backend: "obs"`), not the default.
- **Windows 11 Media Foundation virtual camera** (`MFCreateVirtualCamera`): minimum Windows build 22000; needs a custom media source COM DLL (runs as Local Service in session 0, no desktop access); the pipeline appends "Windows Virtual Camera" to the friendly name; AllUsers needs admin. [MFCreateVirtualCamera](https://learn.microsoft.com/en-us/windows/win32/api/mfvirtualcamera/nf-mfvirtualcamera-mfcreatevirtualcamera), [custom media source](https://learn.microsoft.com/en-us/windows-hardware/drivers/stream/frame-server-custom-media-source). It is the modern route (Chromium also enumerates Media Foundation devices) but needs a C++ source filter and the name could not be exactly "STAR Camera". Future option if Discord ignores the DirectShow filter.

**Which one Discord detects: not verified.** Evidence is indirect: Chromium (Discord's engine) can enumerate both DirectShow and Media Foundation capture devices ([Chromium change](https://chromium.googlesource.com/chromium/src/+/a4b9b88c1e96490c88fc801eedaf7eef513366d9), 2014, old); VSeeFace's DirectShow virtual camera is documented as selectable in Discord; OBS Virtual Camera is widely used in Discord with occasional Windows reports of a black picture after an OBS update ([OBS forum](https://obsproject.com/forum/threads/a-strange-issue-when-using-virtual-camera-to-share-obs-in-discord.194921/)). I found no source that names Unity Capture and Discord together. First live check on her PC: install, open Discord Settings > Voice & Video, look for "STAR Camera". Fallbacks in order: backend `obs`, then VSeeFace's camera fed by VMC, then the Media Foundation route.

## 4. Discord screen share (Go Live) automation

Discord offers no public call-control API for a person's own client. A "Toggle Screen share" keybind exists but a user report says it only works for games ([Discord community post](https://support.discord.com/hc/de/community/posts/22626893228183-Keybind-for-toggle-screenshare), undated); I found no camera-toggle keybind ([Discord keybinds blog](https://discord.com/blog/how-to-use-keyboard-shortcuts-on-discord-create-custom-keybinds) lists mute, deafen, VAD, streamer mode). So the activities do what a person does: screenshot, her image model finds the button, one click through star-home's executor, screenshot again, confirm twice. Built and tested only with fakes (`star/vtuber/discord_ui.py`). Automating a user account can break Discord's terms; the owner accepted that risk on 2026-10-26 (STATE.md).

## 5. Decisions

1. Renderer: own layered 2D renderer on the CPU, model = a folder setting; StarFace expression set works now; VMC out for a future VRM.
2. Camera: pyvirtualcam over Unity Capture registered as "STAR Camera", pinned and hash-checked installer; OBS backend as fallback.
3. Lip-sync: live numpy heuristic with audible-time stamps; no model, no GPU.
4. Camera as its own hidden below-normal process, fed over local UDP (mouth frames, events); it degrades quality, then fps, when frames take too long.
5. Discord: vision-guided click loop with double confirmation; explicit-call activities (interest `video_call`, never scheduled on their own).
