# home-acceptance-20261026: one command that proves every ability on her PC (+ one install root, + the DM/call scenario)

Branch `star/home-acceptance-20261026`, worktree `worktrees/home-acceptance`, board item #259, PR into `star/next`.
Code: `star/home/acceptance.py`, `star/home/paths.py`; tests `tests/test_home_acceptance.py` (75).
Small edits elsewhere: `star/home/__main__.py` (subcommand), `star/home/control.py` (`home_dir()` follows the root),
`star/voice/engines.py` (`models_dir()` follows the root), `installer/star-home/setup.ps1`.

## Run it (on her PC, in her desktop session, elevated)
```
cd /d <root>\app
<root>\venv\Scripts\python.exe -m star.home acceptance            everything (plays sound, moves the mouse, loads models)
... acceptance --quick                                            no audio, no model loads, no desktop input
... acceptance --dry-run                                          read-only; no brain request; STOP/log checks in a temp folder
... acceptance gpu brain                                          only those checks (plus what they need first)
... acceptance --scenario dm-call [--from NAME] [--her-name Star] [--wait-minutes 30] [--listen-seconds 40]
```
setup.ps1 prints this command as its last line. Reports: `<root>\home\acceptance\acceptance-<utc>.json|.md` and
`latest.json|.md` (scenario: `dm-call-<utc>.jsonl|json|md`, `latest-dm-call.*`). Exit code 1 if any check failed.
Verdict: READY (all pass; the camera check may skip while no camera module exists), INCOMPLETE (skips in --quick/--dry-run),
NOT READY (a failure, each with its exact fix in the report). Secrets: the brain key is read inside `brain.http_chat` for
the request only; the Autologon password is never read (only `AutoAdminLogon=1` and `DefaultUserName`); detail text goes
through `redact_text`.

## The 27 checks
admin (elevated) | install_root (not on the Windows drive, all folders under it) | brain (3 one-word requests, median
latency <= 10 s) | gpu (nvidia-smi: >= 7000 MB total, >= 2500 MB free) | voice_stack (Engines.load with the PC preset: STT,
end-of-turn, voice, on CUDA) | voice_llm (local model server 127.0.0.1:8082 answers) | cable_route (VB-CABLE playback +
recording) | mic_default (WASAPI default input is "STAR Microphone") | voice_speaks (TTS the test sentence, play it into the
cable) | mic_recording (3 s from STAR Microphone transcribes to >= 3 of 5 test words) | hearing_tone (1 kHz tone on the
speakers heard by the WASAPI loopback) | echo_exclusion (the test sentence on the speakers goes through
`EchoCanceller`: >= 10 dB removed or >= 60 % frames flagged as hers) | discord_installed | discord_signed_in (a window
titled "<place> - Discord", not bare "Discord") | notifications (`UserNotificationListener` access = Allowed) | roblox |
minecraft (launcher + a Java version) | node_mineflayer (Node >= 18, `require('mineflayer')` loads) | camera ("STAR Camera"
in PnP camera class or the DirectShow video-input registry; skipped, optional, while neither `star.vtuber` nor `star.camera`
exists) | screenshot (not blank) | uia (UI Automation reads named top-level windows) | human_input (opens Notepad on a temp file,
moves the mouse into it on a `star.play.humanlike.pointer_path`, types "star acceptance test 123" by scan code, Ctrl+S,
reads the file back, closes it) | autologon | lock_screen (CONSOLELOCK AC/DC 0 via powercfg or its policy key, no secure
screen saver, no idle-lock policy) | uac (ConsentPromptBehaviorAdmin 0, PromptOnSecureDesktop 0) | stop (STOP stops the
Executor and `loop.cycle`, resume works; real-home create/remove unless the owner's STOP exists, then left alone; desktop
STOP/RESUME buttons exist) | action_log (a line is appended, a Bearer-shaped value is redacted).
Modes: `heavy` checks (voice_stack, voice_llm, voice_speaks, mic_recording, hearing_tone, echo_exclusion, human_input) run
only in full mode; `brain` not in --dry-run. A check whose prerequisite did not pass is skipped with "needs X".

## One install root (owner request: everything on the second drive)
`star/home/paths.py`: `root()` = env `STAR_ROOT`, else (when the running Python is `<root>\venv\Scripts\python.exe` with
`<root>\app` beside it) that root, else None (dev checkout: old defaults). `home_dir()/workspace_dir()/models_dir()/
tools_dir()/logs_dir()/acceptance_dir()` give the sub folders; other packages (senses, vtuber, computer) should call
`star.home.paths.models_dir()` (or read `STAR_ROOT`) instead of choosing a folder. `control.home_dir()` = `STAR_HOME_DIR`
override, else `<root>\home`, else `C:\ProgramData\STAR\home`. `star.voice.engines.models_dir()` = `STAR_VOICE_MODELS`, else
`<root>\models\voice`, else the old LOCALAPPDATA folder.
`setup.cmd [-Root D:\STAR]`: default root = the machine's `STAR_ROOT` if set, else the first fixed drive that is not
`%SystemDrive%` (`\STAR`), else `C:\STAR`. Layout: `app`, `venv`, `home` (config, STOP, actions.jsonl, curiosity, acceptance),
`workspace`, `models\voice`, `models\hf`, `tools\Autologon`, `logs`, `cache\pip`. It sets machine environment variables
`STAR_ROOT`, `STAR_VOICE_MODELS`, `HF_HOME`, `PIP_CACHE_DIR` (so Hugging Face / faster-whisper and pip also write under the
root). The desktop STOP/RESUME buttons now `cd /d <app>` first (before, `python -m star.home` from the desktop could not
import `star`).
**Must stay where Windows needs it:** the scheduled task "STAR Home" (Task Scheduler store); the Autologon secret (LSA
secret + Winlogon registry values); the power / UAC / lock-screen settings (registry, power plan); VB-CABLE driver files and
the MMDevices rename; OpenSSH server (`C:\ProgramData\ssh\sshd_config`, `administrators_authorized_keys`) and its firewall rule;
Python 3.12 itself (winget installs it machine-wide; only the venv is under the root); Node.js, Discord, Roblox, Minecraft
Launcher and their own data (`%LOCALAPPDATA%`, `%APPDATA%\.minecraft`); Credential Manager entries; the desktop STOP/RESUME
files. Not changed: the desktop app's own app-data (`%APPDATA%\STAR`: settings, emotion.sqlite3) is the owner's and untouched.

## Scenario `dm-call` (the owner's first live test)
The harness never sends, types, clicks or calls: it watches and logs (UTC timestamp per event, JSONL + screen):
1. `dm_received`: a new element appears in Discord's window (UI Automation) that carries `--from NAME`, or (no name) says
   unread / new message / mention. Fails early, with the exact start command, if Discord exposes fewer than 10 elements
   (Electron hides its page from UIA unless started with `--force-renderer-accessibility`; I confirmed on another Electron app
   that without it only the 3 window-chrome buttons are visible).
2. `replied`: a new element carrying her name appears after the DM, or her action log shows `type_text` done + `key enter`.
3. `call_started`: a call element ("Calling..."/"Ringing..." or "Voice Connected"/"Disconnect", anchored so chat text does not
   match) appears after the DM; refuses to start if a call is already on screen.
4. `call_connected`: no ringing element for two polls while the call UI is up; records whether Discord holds the microphone
   (consent store `LastUsedTimeStop == 0`).
5. `audio_out`: >= 1 s of level >= 0.01 on STAR Microphone during the window; 6. `audio_in`: >= 1.5 s on the speaker loopback
   after the first 3 s (join/ring sounds ignored). Both clips are transcribed with the voice stack when it loads (evidence only).
STOP aborts it; `--dry-run` only proves Discord is readable and prints the plan.
Honest limits: step 4 can pass without the owner picking up if Discord shows no "ringing" text (then step 6 fails: nothing
heard); step 6 hears any app playing to the default output (stop other audio); element names are Discord's current UI strings.

## What was run vs only written (2026-10-26, this dev PC, RTX 3060 Ti, Python 3.15 here, repo targets 3.12)
- Run: `tests/test_home_acceptance.py` 75 passed; with `test_star_home`, `test_windows_package_data`, `test_senses_voice`,
  `test_voice_engines*`, `test_pyinstaller_data_files`, `test_version_sync`: 185 passed. ruff clean. setup.ps1 parse-checked.
  `test_no_undefined_globals.py::test_checker_reports_a_missing_import` fails here only because Python 3.15 names a lambda
  `<lambda>` (not caused by this PR).
- Run for real, read-only (`acceptance --dry-run` with a temp STAR_HOME_DIR): the real probes for admin, GPU, Discord files,
  notification access, Roblox, Minecraft, Node/Mineflayer, screenshot, UI Automation, registry settings, STOP/log in the
  sandbox, and the Discord UI Automation script (against another Electron window) all ran and gave sensible answers.
- Never run (needs her PC): audio (cable, tone, echo, speak/record), voice stack load, Notepad mouse/typing test, brain request,
  camera, setup.cmd itself, the scenario against a real Discord. Those probe methods are `pragma: no cover`; their pure
  decision logic (tone/echo/transcript/levels/call state/DM detection) is tested.
- `setup.ps1`: the lock-screen step now uses the CONSOLELOCK GUID (+ unhide) because the alias is not listed on this Windows
  build (`powercfg /aliases`) and the old command would have failed silently; not run (it changes system settings).
  On this PC `powercfg /q ... CONSOLELOCK` prints nothing, so the check says "could not read" there: on her PC check that
  the setting shows after setup, otherwise report it.
- Camera: `star.vtuber` is unmerged; when it lands, replace the generic camera fix text with its exact setup command.
