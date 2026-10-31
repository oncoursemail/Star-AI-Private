# home-installer-20261026: one script that installs everything her abilities need (Claude, Sonnet sub-agent)

Branch `star/home-installer-20261026` (worktree `worktrees/home-installer`, from origin/star/next 0b171017), board item #266, PR into `star/next`.
Owner request 2026-10-26: she installs STAR on her own Windows PC (RTX 4060 8 GB, second drive) by running ONE script, then tests her live.
Everything lands under one folder (`STAR_ROOT`, default `D:\STAR`). **Nothing was installed or downloaded on the dev PC; setup.cmd was never run for real.**

## Owner steps (exact)
1. Update the NVIDIA GeForce driver to 576 or newer (setup warns if older; the pinned CUDA 12.9 libraries need it).
2. In a browser signed in to GitHub, download the ZIP of branch `star/next` (before this PR lands: `star/home-installer-20261026`) of
   oncoursemail/Star-AI-Private and extract it anywhere.
3. Double-click `installer\star-home\setup.cmd`, answer Yes to the administrator prompt. Optional first: `setup.cmd -DryRun` (no admin needed, changes nothing).
4. Answer the questions it asks FIRST (then it runs unattended): optional screen-reading model (UI-TARS 2B, 2.3 GB; default No when the install
   drive has less than 40 GB free), brain address (Enter = the lead sets it), dry-run mode for her loop (default Yes), the lead's PUBLIC ssh key line
   (Enter = skip), automatic sign-in after restarts (Yes = the Autologon window opens at the END), no lock screen / no admin prompts (default Yes).
5. Walk away. Windows may ask once to allow the VB-Audio driver (click Install). At the end the Autologon window opens (if you said yes): type her password there.
6. If the summary says RESTART WINDOWS (cable driver): restart, double-click setup.cmd again. Finished steps are skipped.
7. By hand afterwards: start Discord from the desktop shortcut "Discord (STAR)" and sign in; sign in to Roblox and Minecraft; Sound settings > Recording >
   STAR Microphone > Properties > Advanced > 2 channel, 24 bit, 48000 Hz; BIOS: Restore on AC power loss = On; allow notification access if Windows asks
   (Settings > Privacy > Notifications) so she can see Discord toasts.
8. Send the lead the `ssh <user>@<address>` line it prints near the end, then run the full check it prints last:
   `cd /d D:\STAR\app`, then `D:\STAR\venv\Scripts\python.exe -m star.home acceptance` (add `--scenario dm-call` with the owner for the first live test).

Re-run options: `setup.cmd -Skip cable,camera` / `-Only models,acceptance` / `-Yes` (defaults, no questions; autologon and the ssh key are skipped) /
`-Root E:\STAR` / `-Grounder ui-tars-1.5-7b|ui-tars-2b|none` / `-DryRun` / `-Uninstall`. Log of a real run: `<root>\logs\setup-<time>.log`.

## Download size and disk (decimal MB/GB from the publishers' sizes; the install-size figures are estimates, not measured)
| part | download |
|---|---|
| Python packages, 73 pinned wheels (CUDA 12 libraries are 1.6 GB of it: cuDNN 743, cuBLAS 553, cuFFT 200, ORT-GPU 226 MB) | 2.07 GB |
| PyTorch 2.9.1+cu128 (official index) | 2.86 GB |
| Voice files (Kokoro 326 + voices 28 + VAD 2 + end-of-turn 9 MB) | 0.36 GB |
| Speech models small.en 484 + distil-small.en 332 MB | 0.82 GB |
| llama.cpp CUDA server 273 + cudart 391 MB | 0.66 GB |
| Qwen3.5-4B Q4 2741 MB + Qwen3.5-2B Q4 1281 MB (fast voice brain, game mode) | 4.02 GB |
| Discord 146, Java 21 179, Minecraft Launcher 2 MB (only what is missing) | 0.33 GB |
| Node.js LTS 33 MB, mineflayer npm tree (not measured, tens of MB), Python 3.12 26 MB if missing, cable 1.3 MB, camera 0.3 MB | about 0.15 GB |
| optional UI-TARS 2B (1117 + 1332 MB) / 1.5-7B (4683 + 856 MB) | 2.45 / 5.54 GB |
| **Total** | **about 11.3 GB without the screen model, 13.7 GB with 2B, 16.8 GB with 7B** |

Disk needed on the install drive: about 19-21 GB (installed venv about 9-10 GB, models 5.9 GB, screen model 2.4 GB, pip unpack temp up to 3 GB; `--no-cache-dir`
and TEMP on the root keep the system drive out of it). Setup asks before going on with less than "downloads + 8 GB" free. Recommended free space: 30 GB.

## What the script does (21 steps, each OK / SKIPPED / FAILED + fix; a failed step never stops the others)
`preflight` (Windows x64, disk, internet, NVIDIA driver; starts the log) | `python` (3.12 via winget, machine-wide) | `files` (folders, the 4 machine variables
STAR_ROOT / STAR_VOICE_MODELS / HF_HOME / PIP_CACHE_DIR, copy `star\`; robocopy keeps `node_modules`) | `venv` | `pip`
(`requirements-home.txt`: 73 exact versions with the SHA-256 of every installable file, `pip install --no-deps --require-hashes`; if pip refuses the hash file it says so
and installs the same versions unhashed; then imports every module to prove it) | `torch` (`requirements-home-torch.txt`, CUDA 12.8 wheel from download.pytorch.org,
checks `torch.cuda.is_available()`) | `node` (winget OpenJS.NodeJS.LTS if older than 22, then `npm install --no-save mineflayer@4.39.0 mineflayer-pathfinder@2.4.5` in
`star\games\mineflayer` and a `require` test) | `apps` (winget: Discord, Minecraft Launcher, Java 21, only if missing; Roblox installs itself on her first join) |
`models` (`python -m star.senses.setup`, new: Kokoro + VAD + end-of-turn files, speech models at a pinned HF commit with model.bin SHA-256, llama.cpp + Qwen 4B and 2B,
all size + SHA-256 checked; `--list` shows what is missing) | `cable` (VB-CABLE pack 45 from vb-audio.com, Authenticode check of `VBCABLE_Setup_x64.exe`
(valid and signer matches `VB-Audio|Burel`), `-i -h`, then `python -m star.senses.routes script` runs the rename to "STAR Microphone" + default recording and
communications device, then `routes verify`) | `camera` (`install-camera.ps1 -Root`, Unity Capture at a pinned commit with git blob SHA-1 checks) | `grounder` (optional UI-TARS,
files at a pinned HF commit with size + SHA-256, `tools\start-grounder.cmd`, `home\computer.vlm.json`; NOT switched on) | `discord` (shortcuts "Discord (STAR)" on the desktop and
in Startup: `Update.exe --processStart Discord.exe --process-start-args "--force-renderer-accessibility"`; warns if Discord already runs without the flag) | `config` | `task` |
`controls` (STAR STOP / RESUME) | `ssh` | `autologon` | `nolock` | `check` (`star.home check`) | `acceptance` (`star.home acceptance --quick`); then the summary, her loop is started,
and it prints the ssh line and the full acceptance command.

## Files
`installer/star-home/setup.ps1` (rewritten around the step runner; the earlier steps are kept), `setup.cmd` (`-DryRun` skips the admin prompt), `pins.json` (non-pip pins),
`pin_requirements.py` (regenerates the lock from PyPI metadata: `python installer/star-home/pin_requirements.py [--check]`), `requirements-home.in|.txt` and
`requirements-home-torch.txt` (repo root), `installer/star-camera/install-camera.ps1` (`-Root`, `-DryRun`, no hard-coded `C:\STAR\home`), `star/senses/setup.py` (the
`python -m star.senses.setup` that setup.ps1 and the home-wiring notes already referred to but did not exist), `tests/test_home_installer.py` (8), `tests/test_senses_setup.py` (6),
one assertion in `tests/test_home_acceptance.py` (the acceptance command is printed "at the end", no longer "the last line").

## Verified (commands run on this dev PC; nothing installed)
- PowerShell parser: 0 errors for `setup.ps1` and `install-camera.ps1` (Windows PowerShell 5.1 `Parser::ParseFile`).
- `-DryRun` on this PC (below), exit 0; afterwards no `C:\STAR` / `D:\STAR`, no machine `STAR_ROOT`, no desktop files, no scheduled task. Also run through `setup.cmd -DryRun` (no UAC prompt).
  Refusals checked: `-Skip bogus`, `-Root D:STAR`.
- Helper functions run in isolation against local `file://` URLs and a fake pip: `Get-Verified` copies, skips a correct file, rejects a wrong hash and a wrong size (partial deleted), replaces a corrupt file;
  `Install-Pinned` falls back to unhashed pins when pip refuses and strips every hash (73 pins left). Both lock files parse with pip's own requirements parser: 73 + 1 requirements, all `==` and all hashed.
- pytest (`APPDATA=<temp> worktrees/pr39/.venv-audit/Scripts/python.exe -m pytest -q -p no:cacheprovider`): test_home_installer + test_senses_setup + test_home_acceptance + test_windows_package_data +
  test_no_undefined_globals + test_pyinstaller_data_files + test_version_sync = 111 passed; test_repo_intelligence + test_github_write_scope + test_pyright_findings = 169 passed. ruff clean on the new Python files.
- The third-party imports of `star.home, senses, social, games, play, computer, watch, vtuber, voice, inner` are all covered by the lock (test): PIL, numpy, comtypes, pyautogui, dxcam, mss, soundcard, sounddevice,
  faster_whisper, httpx, kokoro_onnx, onnxruntime (GPU build), pyvirtualcam, winsdk, torch; plus defusedxml (imported by `star.rbx_xml`), yt-dlp (`star.watch`), opencv-python-headless (dxcam asks for RGB), nvidia-cublas-cu12 (CTranslate2).
- Winget ids checked with read-only `winget show` on this PC: Python.Python.3.12, OpenJS.NodeJS.LTS (24.22.1), Discord.Discord, Mojang.MinecraftLauncher, Microsoft.OpenJDK.21. Sizes read with HTTP HEAD, hashes from the Hugging Face, PyPI and PyTorch indexes.

## NOT verified / risks (read before the live test)
- `setup.cmd` was never run for real, so no step that installs, downloads, registers a driver or changes Windows settings has been seen to work. The `pip install --require-hashes` of the lock and the torch wheel never ran (the fallback exists for a hash-file problem).
- Mixed CUDA libraries: ORT-GPU and faster-whisper use the nvidia-* wheels (cuBLAS 12.9, cuDNN 9.27) while PyTorch cu128 brings its own cuBLAS 12.8 DLLs; a process that loads both takes whichever `cublas64_12.dll` loads first. Not tested on a card.
- VB-CABLE: no published hash exists; the check is the Authenticode signature, and the signer pattern `VB-Audio|Burel` is from VB-Audio's public information, NOT read from the file. If the status is Valid and the pattern is wrong, setup refuses and prints the signer; edit `signer_pattern`
  in `pins.json`. `-i -h` (silent install) and the one Windows driver prompt are from VB-Audio's documented usage, not run. The rename script (`star.senses.routes`) was written by the senses agent and has never run either.
- Discord: `--process-start-args` through Squirrel's `Update.exe` is the documented pattern but unverified; acceptance's `discord_signed_in` and the dm-call scenario need the UI Automation tree (>= 10 elements). Fallback: a shortcut to the newest `app-*\Discord.exe` with `--force-renderer-accessibility`.
- UI-TARS: the pinned files exist at the pinned commits (bartowski 2B, mradermacher 1.5-7B incl. mmproj), but `llama-server` b11870 with `--mmproj` was never started with them; `tools\start-grounder.cmd` is untested and the grounder is deliberately not switched on (needs `calibrate`; the GPU cannot hold it next to the 4B voice model).
- mineflayer 4.39.0 (the newest in the repo's `^4.23.0` range) with `bot.js`: only the fake-bot test exists; Node 24 LTS assumed.
- `huggingface-hub` is capped below 2 (faster-whisper 1.2.1 predates hub 2.x). yt-dlp 2026.10.21 is a 4-day-old exact pin because YouTube changes weekly (`pin_requirements.py` regenerates); yt-dlp may also need a JavaScript runtime
  for YouTube (`--js-runtimes node`); not tested.
- The speech-model prefetch is pinned to a Hugging Face commit and verified, but at run time faster-whisper resolves `main` online: if upstream moves it fetches the new revision (a few hundred MB) outside the pins.
- Windows may show consent prompts the script cannot answer: the VB-Audio driver prompt, notification access for toasts. Roblox Player is not installed by the script.
- The pins are from PyPI as of 2026-10-25; `pin_requirements.py --check` tells when the lock drifted from `requirements-home.in`.

## Dry run on this PC (2026-10-26, `setup.ps1 -DryRun -Yes -Root D:/STAR -Grounder ui-tars-2b`; the dev PC has an RTX 3060 Ti, Node 26, Discord and Java already, so some lines differ from her PC)
```
DRY RUN: nothing on this PC will be changed, downloaded or installed.
STAR install root: D:\STAR
  [dry-run] would: ask: Brain address, e.g. http://<server-1-address>:8080 (Enter = the lead sets it later) (default empty)
  [dry-run] would: ask: Start in dry-run mode (actions logged, not run) until the log looks right? [Y/n] (default yes)

The lead's PUBLIC key: ONE line starting with ssh-ed25519 (from the lead's PC: type %USERPROFILE%\.ssh\id_ed25519.pub). Never paste a private key.
  [dry-run] would: ask: Public key (Enter = skip) (default empty)
  [dry-run] would: ask: No lock screen on wake/idle and no admin Yes/No prompts for her account? [Y/n] (default yes)

== [preflight] Checks: Windows, disk space, internet, graphics card
  Windows: Microsoft Windows 11 Pro build 26200, 64-bit: True
  Download size of the selected steps: 13.2 GB (pip packages 2.0, PyTorch 2.8, voice and speech models 5.7, screen model 2.3, apps 0.3).  Disk needed on D:: about 21 GB.
  Free on D:: unknown (the drive does not exist yet)
  Graphics card: NVIDIA GeForce RTX 3060 Ti, driver 610.88
  [dry-run] would: check that pypi.org, github.com and huggingface.co answer
  DRY-RUN: plan printed

== [python] Python 3.12
  [dry-run] would: winget install Python.Python.3.12 (machine-wide, silent)
  DRY-RUN: would install Python 3.12

== [files] STAR source and folders under D:\STAR
  [dry-run] would: create D:\STAR\app, models\voice, models\hf, tools, logs, cache\pip under D:\STAR
  [dry-run] would: set the machine variables STAR_ROOT, STAR_VOICE_MODELS, HF_HOME, PIP_CACHE_DIR
  [dry-run] would: copy C:\Users\<user>\Documents\starai\worktrees\home-installer\star to D:\STAR\app\star (robocopy /MIR, keeps node_modules)
  DRY-RUN: would copy the source

== [venv] Python virtual environment
  [dry-run] would: python 3.12 -m venv D:\STAR\venv
  DRY-RUN: would create the venv

== [pip] Python packages (requirements-home.txt: exact versions, hashes checked)
  [dry-run] would: pip install --no-deps --require-hashes -r requirements-home.txt (73 pinned packages, about 2 GB, incl. CUDA 12 libraries for onnxruntime-gpu and faster-whisper)
  DRY-RUN: would install 73 packages

== [torch] PyTorch for the RTX 4060 (CUDA build from the official index)
  [dry-run] would: pip install --no-deps --require-hashes -r requirements-home-torch.txt (about 2.8 GB from download.pytorch.org)
  DRY-RUN: would install CUDA PyTorch

== [node] Node.js LTS and the Minecraft bot (mineflayer, npm install)
  Node.js v26.11.1 already installed
  [dry-run] would: in star\games\mineflayer: npm install --no-save mineflayer@4.39.0 mineflayer-pathfinder@2.4.5
  DRY-RUN: would install Node and the Minecraft bot packages

== [apps] Discord, Minecraft Launcher and Java (the apps she signs in to; Roblox installs itself when she first joins a game)
  Discord: already installed
  Java 21 (Microsoft OpenJDK), which Minecraft needs: already installed
  [dry-run] would: winget install Mojang.MinecraftLauncher (Minecraft Launcher, about 2 MB)
  DRY-RUN: would install 1 app(s)

== [models] Voice, speech and fast-path models (pinned, SHA-256 checked, star.senses.setup)
  [dry-run] would: python -m star.senses.setup: Kokoro voice + voice-activity + end-of-turn files (365 MB), speech models small.en + distil-small.en (816 MB), llama.cpp CUDA server (664 MB), Qwen3.5-4B Q4 (2741 MB) and 2B Q4 (1281 MB) into <root>\models
  DRY-RUN: would download about 5.9 GB

== [cable] VB-CABLE virtual audio cable and the "STAR Microphone" device
  [dry-run] would: download VBCABLE_Driver_Pack45.zip (1 MB) from https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip, check the Authenticode signature of VBCABLE_Setup_x64.exe (signer must match 'VB-Audio|Burel'), run it with -i -h
  [dry-run] would: python -m star.senses.routes script > tools\setup-star-mic.ps1, run it (renames the cable output to "STAR Microphone", makes it the default recording and communications device), then routes verify
  DRY-RUN: would install the cable and create STAR Microphone

== [camera] STAR Camera virtual webcam (Unity Capture, pinned hashes)
    [dry-run] UnityCaptureFilter32.dll: would download 168448 bytes from the pinned commit into D:\STAR\camera\unitycapture and check its hash
    [dry-run] UnityCaptureFilter64.dll: would download 157696 bytes from the pinned commit into D:\STAR\camera\unitycapture and check its hash
    [dry-run] would register both DLLs with regsvr32 as 'STAR Camera', pip install pyvirtualcam numpy pillow into D:\STAR\venv only if they are missing, write the default camera config, run the self-test
  DRY-RUN: camera installer dry run printed above

== [grounder] Optional screen-reading model for star.computer (UI-TARS, pinned)
  [dry-run] would: download 2 files (2.3 GB) of bartowski/UI-TARS-2B-SFT-GGUF@5a0ef829 into D:\STAR\models\grounding\ui-tars-2b (SHA-256 checked), unpack the llama.cpp server if needed, write tools\start-grounder.cmd and home\computer.vlm.json (not switched on)
  DRY-RUN: would download 2.3 GB

== [discord] Discord shortcut with accessibility on (--force-renderer-accessibility)
  [dry-run] would: create 'C:\Users\<user>\OneDrive\Desktop\Discord (STAR).lnk' and 'C:\Users\<user>\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\Discord (STAR).lnk' (--processStart Discord.exe --process-start-args "--force-renderer-accessibility")
  DRY-RUN: would create the shortcuts

== [config] Her settings -> D:\STAR\home\config.json
  [dry-run] would: write D:\STAR\home\config.json (brain_url '', dry_run True)
  DRY-RUN: would write the config

== [task] Scheduled task 'STAR Home' (at logon of <PC>\<user>, highest privileges)
  [dry-run] would: register the task: D:\STAR\venv\Scripts\pythonw.exe -m star.home run (start in D:\STAR\app), at logon, restart every minute on failure
  DRY-RUN: would register the task

== [controls] Owner controls on the desktop (STAR STOP / STAR RESUME)
  [dry-run] would: write 'C:\Users\<user>\OneDrive\Desktop\STAR STOP.cmd' and 'C:\Users\<user>\OneDrive\Desktop\STAR RESUME.cmd'
  DRY-RUN: would write the two files

== [ssh] OpenSSH server (for the lead to deploy updates; local network only, key login only)
  [dry-run] would: install the OpenSSH.Server Windows capability, start sshd, firewall rule for the local subnet only
  [dry-run] would: ask for the lead's public key (skipped when empty)
  DRY-RUN: would set up sshd

== [autologon] Sign in as <user> automatically after a restart (Microsoft Autologon)
  [dry-run] would: download Sysinternals AutoLogon.zip, check that Autologon64.exe is signed by Microsoft, open it for you to type her password, stop sleep on AC power
  DRY-RUN: would open Autologon

== [nolock] Never ask her for the password (her own PC): no lock, no admin prompts
  [dry-run] would: powercfg: console lock off; screen saver not secure; ConsentPromptBehaviorAdmin 0 and PromptOnSecureDesktop 0
  DRY-RUN: would change lock and UAC prompt settings

== [check] Self-test (dry run: nothing is executed)
  [dry-run] would: python -m star.home check (her loop is started after the summary)
  DRY-RUN: would run the self-test

== [acceptance] Acceptance, quick (no audio, no model loads, no desktop input)
  [dry-run] would: python -m star.home acceptance --quick (report in D:\STAR\home\acceptance)
  DRY-RUN: would run the quick acceptance

== Summary
  DRY-RUN  preflight   plan printed
  DRY-RUN  python      would install Python 3.12
  DRY-RUN  files       would copy the source
  DRY-RUN  venv        would create the venv
  DRY-RUN  pip         would install 73 packages
  DRY-RUN  torch       would install CUDA PyTorch
  DRY-RUN  node        would install Node and the Minecraft bot packages
  DRY-RUN  apps        would install 1 app(s)
  DRY-RUN  models      would download about 5.9 GB
  DRY-RUN  cable       would install the cable and create STAR Microphone
  DRY-RUN  camera      camera installer dry run printed above
  DRY-RUN  grounder    would download 2.3 GB
  DRY-RUN  discord     would create the shortcuts
  DRY-RUN  config      would write the config
  DRY-RUN  task        would register the task
  DRY-RUN  controls    would write the two files
  DRY-RUN  ssh         would set up sshd
  DRY-RUN  autologon   would open Autologon
  DRY-RUN  nolock      would change lock and UAC prompt settings
  DRY-RUN  check       would run the self-test
  DRY-RUN  acceptance  would run the quick acceptance

== This PC
Computer: <PC>   User: <user>
Address(es): <redacted>   (local network: <redacted>)
Tell the lead: ssh <user>@<address>
Dry run: nothing was changed, downloaded or installed. Run setup.cmd without -DryRun to install.
Dry run finished with 0 failed step(s). Full check of every ability on this PC (plays sound, moves the mouse; --quick = no audio/GPU loads; report in D:\STAR\home\acceptance):
  cd /d D:\STAR\app ; D:\STAR\venv\Scripts\python.exe -m star.home acceptance
```
