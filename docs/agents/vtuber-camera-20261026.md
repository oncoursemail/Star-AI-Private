# STAR Camera (item "STAR Camera", branch star/vtuber-camera-20261026, Claude, 2026-10-26)

Owner request: STAR turns her camera on in a Discord video call (or any app) and it shows her VTuber avatar; she can
share her screen. Research and picks: `docs/research/vtuber-camera-20261026.md`. Package: `star/vtuber/`.

## What is built (all tested with fakes; nothing has run on her PC)
| file | what |
|---|---|
| `lipsync.py` | her voice -> 20 ms mouth frames (opening + aa/ih/ou/ee/oh) on an audible-time `Timeline`; `LipSyncSpeaker` wraps her Speaker; UDP feed to the camera process (127.0.0.1:39541) |
| `rig.py` | `LiveRig`: mouth + mood + events -> `Pose` per frame; blinks, saccades, breathing, sway, cues; `REACTIONS` (same vocabulary as `star.stream_stage` plus video/game/call events) |
| `model.py` | layered 2D avatar from `avatar.json` + PNGs; bindings from pose parameters to move/rotate/scale/opacity; `"starface"` = the mascot expression set as it is; Pillow, CPU only |
| `placeholder.py` | generated test character (not Star's art) used by tests and the sample |
| `sinks.py` | `PyVirtualCamSink` ("STAR Camera", Unity Capture backend; OBS fallback), `MemorySink`, `PngSink` |
| `vmc.py` | the pose as VMC/OSC for a VRM avatar in VSeeFace/Warudo (`vmc_port` in config) |
| `camera.py` | the frame loop: fixed clock, late frames dropped, quality then fps degrade, stats |
| `control.py`, `__main__.py` | config, hidden below-normal camera process, heartbeat, `python -m star.vtuber on|off|status|preview` |
| `discord_ui.py`, `activities.py` | "camera on", "camera off", "share screen", "stop sharing" through the real Discord app (screenshot -> her image model -> click via star-home executor -> confirm on two screenshots) |
| `__init__.py` | `register_home_activities`, `attach_speaker(speaker)`, `emit_event(kind, strength)` |
| `installer/star-camera/install-camera.cmd/.ps1` | driver install for the setup flow (below) |

## Owner steps (once, on her PC)
1. Run `installer\star-camera\install-camera.cmd` (administrator prompt). It downloads the two Unity Capture DLLs from one
   pinned commit of schellingb/UnityCapture, refuses them unless the git blob SHA-1 matches (`da0b4101...` 32-bit,
   `cd6d7de9...` 64-bit), registers them as "STAR Camera" (regsvr32, both bitnesses), pip-installs pyvirtualcam + numpy
   into `C:\STAR\home\venv`, writes `%ProgramData%\STAR\vtuber\config.json`, and starts and stops the camera once as a
   self-test. Not run (needs admin and a download). Parse-checked only. Needs STAR Home installed first.
2. Avatar: the default model is `starface` (the approved mascot expression images, used unchanged). When the owner
   approves a layered model, put it in a folder with `avatar.json` and set `"model": "C:/path/to/folder"` in
   `%ProgramData%\STAR\vtuber\config.json` (format: docstring of `star/vtuber/model.py`). The StarFace faces have their
   mouth painted in, so with `starface` the mouth cannot open: she squashes slightly with her voice. Real lip-sync needs
   layers with mouth shapes (aa ih ou ee oh + closed + small).
3. In Discord once: Settings > Voice & Video > Camera: choose "STAR Camera" (the activity also tries to pick it).

## Wiring other agents / the lead must do (not in my files)
- `star/home/activities.py`: `PLUGIN_MODULES += ("star.vtuber",)` so the four activities register. They use interest
  `video_call`, which is not in her interests list, so the scheduler never picks them by itself; the Discord call-answer
  code runs them by name: `registry.items["camera on"].run(ctx)` (returns ok / verified / summary / evidence).
- Voice call (`star/voice/call.py` or wherever her Speaker is built): `speaker = star.vtuber.attach_speaker(speaker)`.
  It must be applied to the speaker whose `pending_seconds()` is the real device queue (the PlaybackBuffer speaker), so
  the mouth is timed to what is audible. Returns the plain speaker if anything is wrong.
- Game / watch / call code: `star.vtuber.emit_event("game_win" | "game_danger" | "video_funny" | "friend_joined" | ...)`.
- Emotion: the camera process reads `emotion.current()["avatar"]` itself once a second when `emotion_enabled` is true
  in her settings; nothing else to wire.

## Measured (this dev PC, other agents running, CPU 56-68 % busy; 1280x720)
- Render: StarFace pack 24 ms/frame at quality "high", 15 ms at "fast"; placeholder 28 / 14 ms. The loop held 30.0
  fps for 6 s with 0 dropped frames and no degrade (StarFace and placeholder, MemorySink).
- Lip-sync analysis: 0.109 ms per 20 ms hop.
- Not measured: the real virtual camera, Discord, her PC, a real voice stream, VRAM (renderer uses none).
- Tests: `tests/test_vtuber_camera.py`, 62 passed (APPDATA/STAR_VTUBER_DIR in temp); ruff clean on `star/vtuber` and the
  test; `tests/test_stream_motion.py`, `test_stream_stage.py`, `test_star_home.py` still pass (68).
- Lip-sync shape accuracy: calibrated and tested on synthetic source-filter vowels only. aa/ou/ee separate; oh vs aa and
  ih vs ee overlap. Not heard or seen on recorded speech with a judge.

## Live acceptance on her PC (not done)
1. Does Discord list "STAR Camera"? (Not verified: no source confirms Unity Capture in Discord.) If not: config
   `"backend": "obs"` with OBS running its virtual camera, or feed VSeeFace's camera over VMC, or write the Media
   Foundation source (research doc section 3).
2. `python -m star.vtuber on` then `status`: frames > 0; `off` releases the device.
3. Speak a sentence through the call: mouth follows her audio without lead or lag (audible-time stamps).
4. "camera on" / "share screen" with a real Discord call: the image model must find the buttons (prompts are in
   `discord_ui.py`); screenshot coordinates assume Discord is on the primary display.
5. Game running: confirm the loop's degrade lines in `status` and that the game's frame rate does not suffer.

## Limits and decisions
- Camera shows only what the model folder contains; no art was drawn or changed. The placeholder is a plain geometric
  test character and is never selected unless `"model": "placeholder"` is set.
- Discord automation is click-by-vision and unverified on a real client; a read that is not "done" twice in a row is
  never reported as verified. Screen share can be switched off with `"allow_share_screen": false`.
- Automating a user account can break Discord's terms; the owner accepted that risk (STATE.md 2026-10-26).
