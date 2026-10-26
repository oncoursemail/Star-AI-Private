# Star's own PC: first start

This is a source installation preview for her dedicated Windows PC with an RTX 4060. It includes the Home runtime, installer, proposed character art, emotes, editable painting tool and OBS scene setup. It is not a finished Live2D model or a tested live broadcast. Keep this folder together; the installer needs the `star` folder beside `installer`.

## Install on her computer

1. Copy and extract the newest numbered `Star-Own-PC-Preview` ZIP onto **her computer**. Sign in as her Windows user. Leave at least 40 GB free for the selected downloads and models; the optional art model is not included.
2. Double-click **Preview Star Setup.cmd** to preview. To install, double-click **Set Up Star.cmd**. Choose the install folder, such as `D:\STAR`. The installer asks its questions before downloading; answers that need your account are not invented by `-Yes`.
3. Enter the address of the existing Star brain server when asked. An empty address leaves her without a working brain. Keep the initial action dry run on while checking her logs. Sign in to the apps you own once and keep their sessions signed in. No account passwords belong in a chat, prompt or this repository.
4. Let setup finish, restart if a driver needs it, then run setup again. Check each failed or skipped step and its printed fix. Preview mode does not install, remove shortcuts, start the loop or apply PC cleanup. Package verification failure stops that install step.
5. On the target PC, from `D:\STAR\app`, run the quick check first:

```bat
D:\STAR\venv\Scripts\python.exe -m star.home acceptance --quick
```

Then run the full check while you are present. It can play sound, load models and move the mouse:

```bat
D:\STAR\venv\Scripts\python.exe -m star.home acceptance
```

Read `D:\STAR\home\acceptance\latest.md`. Missing native devices, inaccessible apps, a disconnected brain or failed checks are setup problems to resolve, not successful installation. The desktop **STAR STOP.cmd** and **Ctrl+Alt+Shift+F12** stop her actions. Only the owner resumes her.

Autologon, remote support and lock settings are separate installer choices; review the questions on her PC. The cleanup tool described below does not change Windows security.

If you use Modrinth, run `Set Up Star.cmd -MinecraftLauncher modrinth`. Setup remembers that choice in `D:\STAR\setup-preferences.json` and skips the official Minecraft Launcher on later runs; Java and the separate game client remain available. The Discord desktop shortcut opens the existing app with accessibility enabled. Setup consolidates its own older duplicate shortcut while preserving custom shortcuts.

Keep **STAR Microphone** as the Windows recording and communications input. Keep Windows playback on the intended speakers or headphones; the voice bridge hears that playback and sends Star's voice into the virtual microphone. Camera configuration, status and logs now use `D:\STAR\home\vtuber`, or the explicit `STAR_VTUBER_DIR` override. Camera registration waits for the actual registration result, and installation preserves existing camera configuration.

Installed speech recognition uses the verified snapshot downloaded by setup, including offline startup. Missing or changed weights require repairing the models step; the runtime does not substitute an unverified revision for those installed models.

Follow **STAR-LIVE-TEST.md** for the first supervised session, game authorization and STOP rehearsal. The latest source adds separate voice/game cleanup, delayed-speech cancellation and recovery after failed activities. Those checks used synthetic devices and temporary state. They do not establish live reliability on her computer. Preview now also suppresses native game startup, Home voice and camera activation.

The memory follow-up rejects unsupported generated biographies, reconciles deleted source facts and labels activity reports by their verification status. It also rechecks age status and forgetting before using stored context. See the [memory validation notes](docs/agents/codex-memory-validation-20261026.md) for tests and limits. This does not enable the experimental recall hook or establish improved conversation quality without its measured gate.

The latest [release-preparation fixes](docs/agents/codex-release-prep-validation-20261026.md) start the owned speech output correctly, prevent duplicate Home starts for the same data folder and validate completion reports. They were checked offline; actual sound and calls remain unverified. When using SSH for setup, keep her Windows account logged on at the desktop and start the installed interactive **STAR Home** task rather than a second Home loop in the SSH session.

## What she can see and do

Home already contains screenshot, Windows accessibility, mouse/keyboard and application adapters. A screenshot observes the current visible desktop; it does not reveal covered windows, off-screen tabs or private server state. Some games and custom interfaces need the optional calibrated vision grounder. Downloading it alone does not enable or validate it. The installer prints its separate start and calibration instructions. Use the smaller option as a candidate for an 8 GB card and measure it alongside the game and voice.

The Home brain's `vision` setting must only be enabled with an endpoint that actually accepts images. Its default is off. Test a known screen and verify her observations before relying on autonomous computer actions. Existing memory, interests and emotion state shape her responses; these do not establish consciousness or human feelings. The handoff's emotion/inner-recall evaluation gates remain in place. The [emotion evidence review](docs/research/star-emotion-evidence-20261026.md) compares primary research with Star's measured results; the experimental emotion and inner-chat additions remain off because their quality gates have not passed.

The repository contains personal Discord desktop and game adapters, but native acceptance has not been performed here. Discord's [official rules prohibit automated normal user accounts](https://support.discord.com/hc/en-us/articles/115002192352-Automated-User-Accounts-Self-Bots); desktop automation does not establish an exception. No one was messaged or befriended by this work. There is no claim that unattended social use is permitted by a service or tested end to end.

## Character and modes

Review these files before commissioning or enabling replacement model art:

- `assets\vtuber\star-streamer-design-sheet-v3.png`: front, back and expression studies.
- `assets\vtuber\modes\cat-concept.png`: pointed ears and a fluffy tail.
- `assets\vtuber\modes\puppy-concept.png`: floppy ears and a puppy tail.
- `assets\vtuber\emotes\upload`: laugh, love, hype and think PNGs at 28, 56 and 112 pixels.

These are flat concept illustrations. They are not separated facial/hair/ear layers, a layered PSD, Cubism meshes or a `.moc3` export. The approved painted mascot remains the runtime default. A production Live2D model still needs layered artwork, hidden surface painting, rigging and visual approval. Live2D's [material separation guide](https://docs.live2d.com/en/cubism-editor-manual/divide-the-material/) explains why a flat portrait is insufficient.

The runtime can switch normal, cat and puppy motion without restarting the camera:

```bat
D:\STAR\venv\Scripts\python.exe -m star.vtuber mode cat
D:\STAR\venv\Scripts\python.exe -m star.vtuber mode dog
D:\STAR\venv\Scripts\python.exe -m star.vtuber mode normal
```

`dog` selects `puppy`. These commands do not start the camera or replace its art. Ears and tail only appear when the selected avatar has corresponding painted layers and bindings; status reports those bindings separately from the requested motion mode. The new concepts are not silently substituted as a rig.

Short facial cues also work through the local camera event path:

```bat
D:\STAR\venv\Scripts\python.exe -m star.vtuber expression smile --seconds 2
D:\STAR\venv\Scripts\python.exe -m star.vtuber expression reading_chat --seconds 2.4
D:\STAR\venv\Scripts\python.exe -m star.vtuber expression neutral
```

Available expressions include smile, laugh, surprise, thinking, reading chat, concern and pride. They have bounded duration, fades and repetition limits. Blinks stay closed when appropriate, and expression cues do not overwrite speech mouth shapes. Game, video and selected chat events can drive the same path. Speech interruption clears the cosmetic cue. These are expression controls; their visible detail depends on the selected artwork's layers. The command reports a request, not verified delivery or proof of feelings.

## Editable art

[Krita supports OpenRaster](https://docs.krita.org/en/general_concepts/file_formats/file_ora.html), the layered format used by the new art studio. The installer includes Krita. A painting session saves `painting.ora`, `preview.png`, `strokes.json`, preserved original/reference files and a checksummed receipt under `D:\STAR\workspace\gallery\art`.

To enable brush painting, first configure a working image-capable Home brain, then add this to the local `D:\STAR\home\config.json`, preserving its other settings:

```json
"vision": true,
"art_studio": {
  "enabled": true,
  "mode": "paint",
  "allow_generation": false,
  "reference": ""
}
```

Home can then choose the **art studio** drawing activity. It makes four brush passes with image feedback and saves independently replayable raster strokes. To paint over an approved reference instead, place the image under `workspace\art-input`, select `"mode": "reference"`, and set a relative path such as `"reference": "art-input/my-reference.png"`. The original remains preserved.

Optional generation requires an already configured local ComfyUI workflow and separately enabled generation. Nothing in this pack downloads or benchmarks that model. The publisher's [Klein 4B model card](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B) lists about 13 GB VRAM; an RTX 4060's 8 GB does not establish a native fit. Painting/editing works independently of that generator. Export and pixel consistency are verified; finished anime quality and a real Krita editing round trip still need review.

## Streaming

OBS installs through the official Windows package entry. From `D:\STAR\app`, prepare the five local overlays and a portable source-selection plan:

```bat
D:\STAR\venv\Scripts\python.exe -m star.stream_setup prepare --root D:\STAR
```

In OBS, enable its built-in WebSocket server with authentication. Use its local password at the prompt, not a Twitch stream key. With OBS idle on the target PC:

```bat
D:\STAR\venv\Scripts\python.exe -m star.stream_setup status --root D:\STAR
D:\STAR\venv\Scripts\python.exe -m star.stream_setup apply --root D:\STAR --confirm-this-pc
D:\STAR\venv\Scripts\python.exe -m star.stream_setup selections --root D:\STAR
```

The first apply creates the separate **STAR AI** collection with capture disabled. In local `home\stream\setup.json`, choose the exact virtual camera, virtual microphone and game identifiers returned by OBS; enable the intended sources and apply again. Default/physical room microphones and whole-desktop capture are not selected. Starting, BRB and Ending remain silent; her voice and avatar are used in Chatting and Gameplay only when selected. Game/application audio routing still requires local setup.

Check every scene locally, including source selection, sound meters, feedback and dropped frames. Connect your Twitch account in OBS yourself, follow the service's [broadcast setup](https://dev.twitch.tv/docs/video-broadcast/) and do a private/local rehearsal before a public stream. This adapter never starts streaming or recording and does not handle a stream key. Measure the combined game, speech and camera load; no sustained RTX 4060 streaming benchmark has been run here.

## Reading Twitch chat

The read-only Twitch adapter uses the official [EventSub chat API](https://dev.twitch.tv/docs/chat/authenticating/). It supports the authorized broadcaster's own channel and requests only `user:read:chat`; it has no chat-send, channel-creation or stream-key functions. Twitch app registration and the owner's authorization are still required. Obtain the read-only user token through Twitch's official authorization tools, then enter it only at this local hidden prompt:

```bat
D:\STAR\venv\Scripts\python.exe -m star.twitch_chat save-token --client-id YOUR_APP_ID --broadcaster-id YOUR_NUMERIC_USER_ID
D:\STAR\venv\Scripts\python.exe -m star.twitch_chat status --client-id YOUR_APP_ID --broadcaster-id YOUR_NUMERIC_USER_ID
```

The token is validated against the app, account and read-only scope before native OS storage. A revoked or expired token stops the session; this preview has no automatic token-refresh flow. The listener handles deletion, user/channel clear, duplicate events, reconnect and keepalive. Chat remains in a bounded memory queue, and selected messages expire or become invalid if removed. Its CLI prints counts and state rather than viewer names or text.

For Home reading, add the following local settings, preserving the rest of `home\config.json`, then restart Home:

```json
"stream_chat": {
  "enabled": true,
  "client_id": "YOUR_APP_ID",
  "broadcaster_id": "YOUR_NUMERIC_USER_ID",
  "respond": false
}
```

Home can choose **read stream chat** at quiet moments. It uses a separate model context with no desktop tools, passwords or private-call history, and drives the short reading expression. Reading pauses during private calls or demanding game moments. The feature is off by default and no Twitch account was connected here.

Automatic spoken replies are **not connected for native use yet**. They require trusted input/output moderation and a dedicated cancellable public speech route that keeps checking deletion, STOP and private-call state during playback. Setting `respond` alone does not enable speech. Ordinary shared voice playback is deliberately refused because it could continue into a newly started private call. Offline callback tests do not establish a working public audio route or completed Twitch rehearsal.

## PC cleanup

Preview the optional-app and startup audit:

```bat
powershell -NoProfile -File D:\STAR\app\installer\star-home\optimize-star-pc.ps1 -Root D:\STAR
```

Preview a specific startup change, then apply only your selected IDs:

```bat
powershell -NoProfile -File D:\STAR\app\installer\star-home\optimize-star-pc.ps1 -Root D:\STAR -DisableStartupId spotify,steam
powershell -NoProfile -File D:\STAR\app\installer\star-home\optimize-star-pc.ps1 -Root D:\STAR -DisableStartupId spotify,steam -Apply
```

It stores an encrypted restore manifest for the same Windows user before removing selected startup entries. Restore with `-RestoreManifest <the-printed-file> -Apply`. It does not uninstall apps, erase their data, stop services, disable Windows protection or apply registry speed tricks. Review unwanted apps in Windows Settings separately: ordinary app uninstall can remove app data, so blanket deletion is not treated as reversible optimization.

## Passwords and allowance

Credential and allowance foundations are included for review. Host credential storage returns opaque handles rather than exposing passwords to a language model. The wallet starts disabled with zero funds; it has no connected card or payment execution adapter. No money moved and no bank account was opened. Choose the provider, funded allowance and limits before connecting it. Streaming earnings remain the owner's account income; an allowance ledger does not create a legal person or bank account for Star.
