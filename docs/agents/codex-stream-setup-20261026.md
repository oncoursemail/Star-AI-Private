# Local OBS stream setup

`star/stream_setup.py` prepares Starting, Chatting, Gameplay, BRB and Ending scenes
in a separate **STAR AI** scene collection. It uses the optional `obsws-python`
client already supported by the desktop distribution. Nothing in this adapter
starts streaming, recording, replay capture or OBS Virtual Camera. It never asks
OBS for stream-service settings or a Twitch stream key.

## Local preparation and target setup

From the installed `app` folder, using the installation's Python:

```bat
cd /d D:\STAR\app
D:\STAR\venv\Scripts\python.exe -m star.stream_setup prepare --root D:\STAR
```

This writes five static HTML overlays and `D:\STAR\home\stream\setup.json`.
All media paths in the plan are relative to the installation root. Moving the
installation and applying again resolves browser sources from the new location.
Preparation refreshes generated overlays but preserves existing device choices.
Optional character art is `app/assets/vtuber/star-streamer-concept-v2.png`;
missing artwork leaves valid text-only layouts. `--art` accepts another local path
relative to the install root; `--art ""` disables character artwork.

The charcoal, cream and gold composition follows the owner's soft-haired streamer
direction. The character occupies the right of the Starting/BRB/Ending screens.
Chatting and Gameplay keep most of the canvas clear and show a small fixed name
label. There are no activity counters, fake live metrics, remote fonts or scripts.
These are static stream graphics, separate from the unfinished production rig.

On **Star's computer**, open OBS, enable its authenticated WebSocket server on
port 4455, and keep streaming, recording, replay buffer and OBS Virtual Camera
stopped throughout setup. The adapter connects only to `127.0.0.1:4455` and prompts
for the WebSocket password without storing it. Do not enter a Twitch stream key.
The SDK's diagnostic namespace is disabled before importing or constructing its
client because its connection log includes the password at INFO level. Existing
child loggers are suppressed too; ordinary application logging stays available.

```bat
D:\STAR\venv\Scripts\python.exe -m star.stream_setup status --root D:\STAR
D:\STAR\venv\Scripts\python.exe -m star.stream_setup apply --root D:\STAR --confirm-this-pc
D:\STAR\venv\Scripts\python.exe -m star.stream_setup selections --root D:\STAR
```

The first apply creates inactive source placeholders. It leaves camera, microphone
and game capture off. The local selections listing supplies OBS's exact selectable
device/window IDs. Edit only the local plan, then apply again when ready:

- `camera_device_id` must identify **STAR Camera / Unity Video Capture**;
  `enable_camera` is an explicit boolean.
- `microphone_device_id` must identify **STAR Microphone / CABLE Output**;
  `enable_microphone` is an explicit boolean. Physical room microphones and the
  default device are refused. Camera-associated audio stays muted.
- `game_window` must be an enabled window from OBS's property list;
  `enable_game` enables it only in Gameplay. The title must be unique. Match mode
  is exact title, with cursor and third-party overlays excluded. This does not
  attach a stable process/window handle; verify the actual selected game locally.

Do not commit the filled local plan or device/window listing to source control.
An existing collection without the adapter's ownership marker is refused. Reruns
reuse scene/source names and reject conflicting input kinds or duplicate scene
items. The setup mutes collection-global desktop/room inputs, hides existing items
before updates, and starts on the static Starting scene. On failure, cleanup first
attempts to mute audio and deactivate the camera, then independently hides capture
items. A stale item does not skip the other actions; a lost connection still
cannot prove cleanup worked.

The voice is on audio track 1 with monitoring off to avoid feedback, with an
optional built-in limiter at minus one decibel. No desktop audio source is added.
Game/application sound routing remains an explicit local OBS acceptance task;
it is not silently replaced with whole-desktop capture. Canvas placement scales
to the current OBS canvas without changing resolution, encoder or Twitch settings.

## Acceptance still required

Check all five scenes locally before broadcasting. Confirm that the virtual camera
is the intended avatar, her cable carries only her voice, Starting/BRB/Ending are
silent, and Gameplay shows only the selected game. Verify camera background/alpha
handling rather than assuming a virtual webcam carries transparency. Verify the
microphone meter, monitor feedback, dropped frames and the chosen game on the RTX
4060. The adapter does not claim a completed rig, working live stream, Twitch
account connection or measured performance.

OBS Virtual Camera is intentionally a separate manual action. Choosing OBS Virtual
Camera as this adapter's camera input is refused to avoid a recursive capture loop.
Twitch account creation, service connection and going live remain outside this
adapter. [Twitch's broadcast documentation](https://dev.twitch.tv/docs/video-broadcast/)
describes the separate encoder/ingest authorization boundary.

## Primary API research

- [OBS remote control guide](https://obsproject.com/kb/remote-control-guide): WebSocket
  is built into OBS Studio 28 and newer; no separate WebSocket plugin installation.
- [OBS WebSocket 5 protocol](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md):
  the adapter uses scene collections, named inputs/items, property-list device
  discovery, transforms, audio monitoring/tracks, source filters and read-only
  output status. A request allowlist excludes broadcast and stream-service APIs.
- [Official obsws-python SDK source](https://github.com/aatikturk/obsws-python/blob/main/obsws_python/reqs.py):
  requests use `send(..., raw=True)` so response fields retain protocol names.
  SDK exceptions are replaced with neutral local errors.
- [SDK connection source](https://github.com/aatikturk/obsws-python/blob/main/obsws_python/baseclient.py):
  constructor diagnostics include connection parameters, which require log
  suppression before the constructor receives a password.
- [OBS browser source](https://github.com/obsproject/obs-browser/blob/master/obs-browser-source.cpp):
  OBS routes local documents through its own `http://absolute/` origin, so the
  image policy permits both same-origin and file images. Browser sources set
  `fps_custom=true` with 30 FPS to avoid inheriting a faster canvas rate.
- [OBS DirectShow input](https://github.com/obsproject/obs-studio/blob/master/plugins/win-dshow/win-dshow.cpp):
  inactive creation and the `activate` properties button control camera activation;
  `video_device_id` and `deactivate_when_not_showing` bind the selected virtual input.
- [OBS WASAPI input](https://github.com/obsproject/obs-studio/blob/master/plugins/win-wasapi/win-wasapi.cpp):
  explicit `device_id` selection avoids the physical default microphone.
- [OBS game capture](https://github.com/obsproject/obs-studio/blob/master/plugins/win-capture/game-capture.c)
  and [window matching](https://github.com/obsproject/obs-studio/blob/master/libobs/util/windows/window-helpers.c):
  the selected-window mode uses title priority 1, not fullscreen or executable fallback.
- [OBS limiter source](https://github.com/obsproject/obs-studio/blob/master/plugins/obs-filters/limiter-filter.c):
  built-in limiter ID and threshold/release settings.

## Verification

Run `python scripts/verify_stream_setup.py`. It uses a stateful fake WebSocket
client and temporary files, not live OBS, devices, accounts or stream credentials.
The verifier checks portable overlays, confirmation/idle guards, silent defaults,
idempotence, virtual-device restrictions, exact game selection, ownership, partial
failure cleanup, denied broadcast requests, relocation and read-only inspection.
All 14 verification cases passed on Python 3.12. The added cases cover an INFO-level
constructor/lifetime logger with a dummy password and a disappearing cleanup item
while the fake connection stays available. Pyright 1.1.414 reported zero
module errors or warnings; Python compilation and whitespace checks passed.
Starting, Gameplay and Ending overlays were also rendered at 1920 by 1080 in a
fresh headless browser profile and visually inspected. The character and text
fit without overlap; the Gameplay render retained transparent pixels outside its
small label. These browser previews do not verify OBS device capture or a stream.
