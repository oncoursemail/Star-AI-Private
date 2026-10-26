"""python -m star.home acceptance: one command on STAR's own PC that proves every ability end to end.

Each check ends as pass, fail (with the exact fix) or skip (with the reason). The run writes a JSON and a Markdown
report to <home>\\acceptance\\ (<install root>\\home\\acceptance, see paths.py) and prints the same on screen.

  python -m star.home acceptance                 everything, on the real devices (plays sound, moves the mouse,
                                                 loads the voice models on the GPU: run it when nobody uses the PC)
  python -m star.home acceptance --quick         no audio, no model loads, no desktop input: settings, installs,
                                                 brain, GPU and the rest that only reads
  python -m star.home acceptance --dry-run       read-only: also no brain request; the STOP and log checks run in a
                                                 throw-away folder, so it is safe on any PC (this is the dev-PC mode)
  python -m star.home acceptance gpu brain       only those checks (and the ones they need first)
  python -m star.home acceptance --scenario dm-call [--from NAME] [--her-name Star] [--wait-minutes 30]
                                                 the owner's first live test (see run_dm_call): waits for a Discord DM
                                                 and watches what she does; with --dry-run it only proves Discord's
                                                 screen is readable and the audio taps open
  --out DIR                                      write the report there instead

Secrets: the brain key is read from its file into memory for the request and never printed or written; the auto
sign-in password is never looked at (only the registry flag that says auto sign-in is on).

`SystemProbes` / `ScenarioProbes` are everything that touches the PC (Windows); tests pass fakes with the same
methods. The checks and the scenario only decide pass/fail and what to tell the owner.
"""
from __future__ import annotations

import argparse
import calendar
from dataclasses import dataclass, field
import getpass
import json
import ntpath
import os
from pathlib import Path
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error

from ..redact import redact_text
from . import control, paths

PASS, FAIL, SKIP = "pass", "fail", "skip"
VENV_PYTHON = sys.executable or "python"      # on her PC this is <root>\venv\Scripts\python.exe
TEST_SENTENCE = "Hello, this is Star. Acceptance test."
SPEECH_WORDS = ("hello", "this", "star", "acceptance", "test")
SPEECH_NEEDED = 3                  # of SPEECH_WORDS that must be in the transcript of the 3 s recording
RECORD_SECONDS = 3.0
TONE_HZ = 1000
INPUT_LINE = "star acceptance test 123"      # letters, digits and spaces only: sent by scan code
FAST_URL = "http://127.0.0.1:8082"           # the local voice model (star/senses/fastpath.py, port 8082)
BRAIN_MAX_SECONDS = 10.0
MIN_GPU_MB, MIN_FREE_MB = 7000, 2500
WINLOGON = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
POLICY_SYSTEM = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
ROOT_DIRS = ("app", "venv", "home", "workspace", "models")
MIN_UI_ELEMENTS = 10         # Discord has dozens of buttons; only window chrome (3 or so) means its page is not exposed
CONSOLELOCK_GUID = "0e796bdb-100d-47d6-a2d5-f7d2daa51f51"      # power setting "require sign-in on wake"


@dataclass
class Outcome:
    status: str
    detail: str = ""
    fix: str = ""
    data: dict = field(default_factory=dict)


def _pass(detail: str, **data) -> Outcome:
    return Outcome(PASS, detail, "", data)


def _fail(detail: str, fix: str, **data) -> Outcome:
    return Outcome(FAIL, detail, fix, data)


def _skip(detail: str, **data) -> Outcome:
    return Outcome(SKIP, detail, "", data)


@dataclass
class Ctx:
    mode: str                       # "full" | "quick" | "dry"
    home: Path                      # her real data folder
    config: dict
    probes: object
    sandbox: Path                   # throw-away folder for the STOP and log checks in dry mode
    shared: dict = field(default_factory=dict)

    @property
    def state_home(self) -> Path:   # where the log check writes: never the real folder in a dry run
        return self.sandbox / "home" if self.mode == "dry" else self.home


@dataclass(frozen=True)
class Spec:
    id: str
    title: str
    run: object
    level: str = "read"             # read: runs in every mode | net: not in --dry-run | heavy: full runs only
    after: tuple = ()
    would: str = ""                 # what a skipped heavy/net check would have done
    optional: bool = False


# ---- pure helpers (unit-tested without a PC) -----------------------------------------------------------------
def speech_hits(transcript: str, words: tuple = SPEECH_WORDS) -> list[str]:
    text = re.sub(r"[^a-z ]+", " ", str(transcript).lower())
    return [w for w in words if w in text]


def tone_report(samples, rate: int, hz: float = TONE_HZ) -> dict:
    """Level, loudest frequency and the share of the energy within 40 Hz of it, for a captured clip."""
    import numpy as np
    x = np.asarray(samples, dtype=np.float64)
    if x.size < rate // 4:
        return {"rms": 0.0, "peak_hz": 0.0, "share": 0.0, "ok": False}
    x = x - x.mean()
    rms = float(np.sqrt(np.mean(x * x)))
    spectrum = np.abs(np.fft.rfft(x * np.hanning(x.size))) ** 2
    freqs = np.fft.rfftfreq(x.size, 1.0 / rate)
    peak = float(freqs[int(np.argmax(spectrum))])
    near = np.abs(freqs - peak) <= 40
    share = float(spectrum[near].sum() / max(spectrum.sum(), 1e-12))
    return {"rms": round(rms, 4), "peak_hz": round(peak, 1), "share": round(share, 3),
            "ok": rms >= 0.002 and abs(peak - hz) <= 40 and share >= 0.5}


def echo_stats(rows) -> dict:
    """rows: (level of what the loopback heard, level after the canceller, flagged as her own voice) per 32 ms frame."""
    import math
    heard = [r for r in rows if r[0] >= 0.003]
    if not heard:
        return {"frames": 0, "reduction_db": 0.0, "own_ratio": 0.0}
    raw = sum(r[0] ** 2 for r in heard)
    left = sum(r[1] ** 2 for r in heard)
    return {"frames": len(heard), "reduction_db": round(10 * math.log10(max(raw, 1e-12) / max(left, 1e-12)), 1),
            "own_ratio": round(sum(1 for r in heard if r[2]) / len(heard), 2)}


def discord_signed_in(titles: list[str]) -> bool:
    """Signed out, Discord's window is titled just "Discord"; signed in it is "<place> - Discord" / "<place> | Discord"."""
    return any(t.strip().lower() != "discord" and t.strip().lower().endswith("discord") for t in titles)


def parse_consolelock(text: str) -> tuple[int, int] | None:
    """(AC, DC) setting from `powercfg /q ... CONSOLELOCK`: the last two 0x hex values, whatever the language."""
    values = re.findall(r"0x([0-9a-fA-F]{8})\b", text)
    return (int(values[-2], 16), int(values[-1], 16)) if len(values) >= 2 else None


def _fix_pip(package: str) -> str:
    return f"{VENV_PYTHON} -m pip install {package}"


# ---- the checks ----------------------------------------------------------------------------------------------
def check_admin(ctx: Ctx) -> Outcome:
    if ctx.probes.is_admin():
        return _pass("running elevated (administrator)")
    return _fail("not running as an elevated administrator",
                 "Run the check from a terminal opened with 'Run as administrator' (the 'STAR Home' scheduled task "
                 "already is elevated). If STAR's Windows account is not an administrator: Settings > Accounts > "
                 "Other users > her account > Change account type > Administrator.")


def check_install_root(ctx: Ctx) -> Outcome:
    info = ctx.probes.install_info()
    fix_root = "Run installer\\star-home\\setup.cmd -Root D:\\STAR (any folder on the second drive)."
    root = info.get("root") or ""
    if not root:
        return _fail("no STAR install root: STAR_ROOT is not set and this copy is not at <root>\\app", fix_root)
    drive, system = ntpath.splitdrive(root)[0].lower(), str(info["system_drive"]).lower()
    if drive == system:
        return _fail(f"STAR lives on the Windows drive ({root})",
                     fix_root + " It moves app, venv, data, models and workspace to that folder.", **info)
    home = str(info["home"])
    if not ntpath.normcase(ntpath.normpath(home)).startswith(ntpath.normcase(ntpath.normpath(root)) + "\\"):
        return _fail(f"her data folder {home} is outside the root {root}",
                     "Unset the STAR_HOME_DIR environment variable (System Properties > Environment Variables).", **info)
    missing = [name for name in ROOT_DIRS if not info["present"].get(name)]
    if missing:
        return _fail(f"under {root} these folders are missing: {', '.join(missing)}", fix_root, **info)
    return _pass(f"everything lives under {root} (second drive; app, venv, home, workspace, models)", **info)


def check_brain(ctx: Ctx) -> Outcome:
    url = str(ctx.config.get("brain_url") or "")
    if not url:
        return _fail("brain_url is not set", f'Edit {ctx.home / "config.json"} and set "brain_url" to '
                     'http://<server-1-address>:8080 (the lead knows the address).')
    try:
        times = ctx.probes.brain_ping(ctx.config)
    except ValueError:
        return _fail("the brain key file is missing or unreadable",
                     r"Put the key at %USERPROFILE%\.star\server_api_key (the lead copies it with scp from the lead's "
                     "PC; never paste it into a chat or a file in git).")
    except urllib.error.HTTPError as why:
        if why.code in (401, 403):
            return _fail(f"the brain refused the key (HTTP {why.code})",
                         r"The key in %USERPROFILE%\.star\server_api_key is old or wrong: the lead copies the current "
                         "one over with scp.")
        return _fail(f"the brain answered HTTP {why.code}", "Ask the lead whether the brain is restarting; "
                     "run the check again in a few minutes.")
    except (urllib.error.URLError, TimeoutError, OSError) as why:
        return _fail(f"the brain is not reachable ({type(why).__name__})",
                     "Check this PC is on the same network as server 1 and brain_url in config.json is right "
                     "(open <brain_url>/v1/models in a browser: it should answer 401 or a list, not time out).")
    median = statistics.median(times)
    data = {"latencies_s": [round(t, 2) for t in times], "median_s": round(median, 2)}
    if median > BRAIN_MAX_SECONDS:
        return _fail(f"the brain answers but slowly (median {median:.1f} s for a one-word reply)",
                     "The brain is busy or the link is slow. Run the check again when no eval runs on server 1; "
                     "if it stays slow check the network (wired, not Wi-Fi).", **data)
    return _pass(f"reachable, median {median:.2f} s for a one-word reply ({len(times)} tries)", **data)


def check_gpu(ctx: Ctx) -> Outcome:
    info = ctx.probes.gpu_info()
    if not info:
        return _fail("nvidia-smi is not available (no NVIDIA driver)",
                     "Install the current NVIDIA Game Ready driver from nvidia.com/drivers, restart, and check that "
                     "`nvidia-smi` runs in a terminal.")
    detail = f'{info["name"]}, {info["total_mb"]} MB total, {info["free_mb"]} MB free, driver {info.get("driver", "?")}'
    if info["total_mb"] < MIN_GPU_MB:
        return _fail(f"{detail}: under 8 GB", "The voice models and her games need an 8 GB card (RTX 4060 or better).",
                     **info)
    if info["free_mb"] < MIN_FREE_MB:
        return _fail(f"{detail}: not enough free video memory",
                     "Close what is using the card (`nvidia-smi` lists the programs), then run the check again.", **info)
    return _pass(detail, **info)


def check_voice_stack(ctx: Ctx) -> Outcome:
    stack = ctx.probes.load_voice_stack()
    ctx.shared["stack"] = stack
    data = {"load_seconds": stack.timings, "gpu": bool(stack.gpu)}
    if not stack.gpu:
        return _fail("speech to text and voice loaded, but on the CPU (no CUDA provider)",
                     f"{VENV_PYTHON} -m pip uninstall -y onnxruntime  then  {VENV_PYTHON} -m pip install "
                     '"onnxruntime-gpu[cuda,cudnn]==1.26.*"  (the two packages must not be installed together)',
                     **data)
    return _pass("speech to text, end-of-turn model and voice loaded on the GPU: "
                 + ", ".join(f"{k} {v}s" for k, v in stack.timings.items()), **data)


def check_voice_llm(ctx: Ctx) -> Outcome:
    try:
        seconds, text = ctx.probes.voice_llm(FAST_URL)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError) as why:
        return _fail(f"the local voice model does not answer at {FAST_URL} ({type(why).__name__})",
                     f"{VENV_PYTHON} -m star.senses.setup downloads the model and server; then start the server: "
                     "the exact command line is star.senses.fastpath.server_command(profile, server_exe, model_path).")
    if not str(text).strip():
        return _fail("the local voice model answered with an empty reply",
                     "Restart the local model server; check its console for a load error (out of video memory?).")
    return _pass(f"local voice model answered in {seconds:.2f} s", seconds=round(seconds, 2))


def check_voice_speaks(ctx: Ctx) -> Outcome:
    stack = ctx.shared["stack"]
    pcm, rate = stack.speak(TEST_SENTENCE)
    seconds = len(pcm) / 2 / rate if rate else 0.0
    ctx.shared["speech"] = (pcm, rate)
    if seconds < 0.5:
        return _fail(f"the voice produced only {seconds:.2f} s of audio for the test sentence",
                     f"Re-download the voice files: {VENV_PYTHON} -m star.voice.setup_models")
    ctx.shared["recording"] = ctx.probes.speak_and_record(pcm, rate, RECORD_SECONDS)
    return _pass(f"synthesised {seconds:.1f} s and played it into STAR Microphone's cable", seconds=round(seconds, 2))


def check_cable_route(ctx: Ctx) -> Outcome:
    devices = ctx.probes.audio_devices()
    names_in = [d["name"].lower() for d in devices if d["kind"] == "input"]
    names_out = [d["name"].lower() for d in devices if d["kind"] == "output"]
    has_in = any("star microphone" in n for n in names_in)
    cable_in = any("cable output" in n for n in names_in)
    has_out = any("cable input" in n or "vb-audio virtual cable" in n for n in names_out)
    if has_in and has_out:
        return _pass('virtual cable present: playback "CABLE Input", recording "STAR Microphone"')
    if not has_out or not (has_in or cable_in):
        return _fail("the virtual audio cable (VB-CABLE) is not installed",
                     "winget install --id VB-Audio.Cable --silent (or the VBCABLE_Driver_Pack from vb-audio.com), "
                     "restart Windows, then rename it with the script in the next check's fix.")
    return _fail('the cable is installed but its recording side is not named "STAR Microphone"',
                 f"{VENV_PYTHON} -m star.senses.routes script > setup-mic.ps1  then in an elevated PowerShell: "
                 "powershell -ExecutionPolicy Bypass -File setup-mic.ps1")


def check_mic_default(ctx: Ctx) -> Outcome:
    name = ctx.probes.default_recording()
    if "star microphone" in name.lower():
        return _pass(f'the default Windows recording device is "{name}"')
    return _fail(f'the default recording device is "{name or "none"}", not STAR Microphone',
                 "Settings > System > Sound > Input: pick STAR Microphone (it is her voice to Discord and games); or "
                 f"run {VENV_PYTHON} -m star.senses.routes script, save it and run it elevated: it sets the default "
                 "recording and communications device.")


def check_mic_recording(ctx: Ctx) -> Outcome:
    recorded, rate = ctx.shared["recording"]
    import numpy as np
    from ..senses.audio import StreamResampler, float_to_pcm
    mono = np.asarray(recorded, dtype=np.float32)
    rms = float(np.sqrt(np.mean(mono ** 2))) if mono.size else 0.0
    if rms < 0.003:
        return _fail(f"the {RECORD_SECONDS:.0f} s recording from STAR Microphone is silent (level {rms:.4f})",
                     "The cable is not passing sound: close apps that hold it exclusively (Sound settings > the "
                     "device > Advanced > untick 'Allow applications to take exclusive control'), then run again.",
                     rms=round(rms, 4))
    pcm16k = float_to_pcm(StreamResampler(rate, 1).process(mono))
    transcript = ctx.shared["stack"].transcribe(pcm16k)
    hits = speech_hits(transcript)
    data = {"rms": round(rms, 4), "transcript": transcript[:200], "words_heard": hits}
    if len(hits) < SPEECH_NEEDED:
        return _fail(f'the recording has sound but not the test speech: heard "{transcript[:80]}"',
                     "Set the STAR Microphone format to 2 channel, 24 bit, 48000 Hz (Sound > Recording > Properties > "
                     "Advanced) and turn off its enhancements, then run again.", **data)
    return _pass(f'3 s recording from STAR Microphone contains the test speech: "{transcript[:80]}"', **data)


def check_hearing_tone(ctx: Ctx) -> Outcome:
    samples, rate = ctx.probes.hear_tone(TONE_HZ)
    report = tone_report(samples, rate, TONE_HZ)
    if report["ok"]:
        return _pass(f'the loopback heard the {TONE_HZ} Hz tone played to the speakers (level {report["rms"]})', **report)
    return _fail(f'the loopback did not hear the {TONE_HZ} Hz test tone (level {report["rms"]}, loudest '
                 f'{report["peak_hz"]} Hz)',
                 "Make sure the default output device is the real speakers/headset and not muted, and that the "
                 f"'soundcard' package is installed ({VENV_PYTHON} -m pip show soundcard); stop other loud audio and "
                 "run again.", **report)


def check_echo_exclusion(ctx: Ctx) -> Outcome:
    pcm, rate = ctx.shared["speech"]
    stats = echo_stats(ctx.probes.echo_test(pcm, rate))
    if stats["frames"] == 0:
        return _fail("the loopback heard none of the test sentence played through the speakers",
                     "Unmute the default output device (the echo test plays the sentence there) and run again.", **stats)
    if stats["own_ratio"] >= 0.6 or stats["reduction_db"] >= 10:
        return _pass(f'her own voice is excluded: {stats["reduction_db"]} dB removed, '
                     f'{int(stats["own_ratio"] * 100)}% of frames flagged as hers', **stats)
    return _fail(f'her own voice is still heard: only {stats["reduction_db"]} dB removed, '
                 f'{int(stats["own_ratio"] * 100)}% of frames flagged',
                 "Use headphones or the cable route (STAR's voice only goes to the cable); on speakers lower the "
                 "volume and keep the PC's microphone away from them, then run again.", **stats)


def check_discord_installed(ctx: Ctx) -> Outcome:
    if ctx.probes.discord_state()["installed"]:
        return _pass("Discord is installed")
    return _fail("the Discord app is not installed", "winget install --id Discord.Discord --silent")


def check_discord_signed_in(ctx: Ctx) -> Outcome:
    state = ctx.probes.discord_state()
    if not state["installed"]:
        return _fail("Discord is not installed", "winget install --id Discord.Discord --silent")
    titles = state["titles"]
    if not titles:
        return _fail("Discord is installed but has no window open",
                     "Start Discord (and leave it open, not only in the tray) and sign in once; tick 'remember me'.")
    if not discord_signed_in(titles):
        return _fail('Discord shows its sign-in screen (window titled just "Discord")',
                     "Sign in to STAR's Discord account in the app once yourself (STAR never types the password); "
                     "the session then persists.")
    return _pass(f'Discord window present and signed in ("{titles[0][:60]}")')


def check_notifications(ctx: Ctx) -> Outcome:
    status = ctx.probes.notification_access()
    if status == "Allowed":
        return _pass("notification listener permission: Allowed")
    return _fail(f"notification listener permission is {status or 'unknown'}",
                 "Settings > Privacy & security > Notifications: set 'Notification access' (apps that read "
                 "notifications) to On for STAR / Python; or run her listener once and press Allow when Windows asks.")


def check_roblox(ctx: Ctx) -> Outcome:
    path = ctx.probes.find_roblox()
    if path:
        return _pass(f"Roblox player installed ({Path(path).parent.name})")
    return _fail("Roblox is not installed", "Install Roblox from roblox.com/download (or 'Roblox' in the Microsoft "
                 "Store) and sign in to STAR's account once.")


def check_minecraft(ctx: Ctx) -> Outcome:
    state = ctx.probes.minecraft_state()
    if not state["launcher"]:
        return _fail("the Minecraft Launcher is not installed",
                     "winget install --id Mojang.MinecraftLauncher --silent, then open it, sign in to STAR's Microsoft "
                     "account and press Play once for Java Edition.")
    if not state["versions"]:
        return _fail("the launcher is installed but no Java Edition version has been downloaded",
                     r"Open the Minecraft Launcher, choose Java Edition and press Play once so %APPDATA%\.minecraft"
                     r"\versions gets a version; then close the game.")
    return _pass(f'Minecraft Launcher and Java Edition {state["versions"][0]} installed')


def check_node_mineflayer(ctx: Ctx) -> Outcome:
    state = ctx.probes.node_state()
    if not state["node"]:
        return _fail("Node.js is not installed", "winget install --id OpenJS.NodeJS.LTS --silent, then open a new "
                     "terminal and run the check again.")
    if state["major"] < 18:
        return _fail(f'Node.js {state["version"]} is too old for Mineflayer (needs 18 or newer)',
                     "winget upgrade --id OpenJS.NodeJS.LTS --silent")
    if not state["mineflayer"]:
        return _fail(f'Node {state["version"]} is installed but Mineflayer is not',
                     f'cd /d "{state["folder"]}" && npm install')
    return _pass(f'Node {state["version"]} and Mineflayer installed ({state["folder"]})')


def check_camera(ctx: Ctx) -> Outcome:
    if not ctx.probes.camera_module():
        return _skip("the camera module (star.vtuber) is not in this copy of STAR yet")
    if "star camera" in (n.lower() for n in ctx.probes.camera_devices()):
        return _pass('a camera device named "STAR Camera" exists')
    return _fail('no camera device named "STAR Camera"',
                 "Run the camera module's setup (it registers the STAR Camera virtual webcam; see its notes under "
                 "docs/agents/), then run the check again. Discord only lists it after Discord was restarted.")


def check_screenshot(ctx: Ctx) -> Outcome:
    shot = ctx.probes.screenshot_stats()
    detail = f'{shot["width"]}x{shot["height"]}, {shot["distinct"]} distinct tones'
    if shot["width"] < 640 or shot["height"] < 480 or shot["distinct"] <= 2:
        return _fail(f"the screenshot is blank or tiny ({detail})",
                     "The desktop must be unlocked and showing: sign in at the PC itself (a disconnected remote "
                     "session or a locked screen gives a black picture), then run again.", **shot)
    return _pass(f"screenshot readable ({detail})", **shot)


def check_uia(ctx: Ctx) -> Outcome:
    names = ctx.probes.uia_windows()
    if not names:
        return _fail("UI Automation returned no named top-level windows",
                     "Run the check inside her signed-in desktop session (the 'STAR Home' task does) and not in a "
                     "service or over SSH; Windows PowerShell 5.1 must be available.")
    return _pass(f"UI Automation reads {len(names)} named windows ({', '.join(names[:3])[:80]})", windows=len(names))


def check_human_input(ctx: Ctx) -> Outcome:
    result = ctx.probes.input_test(INPUT_LINE)
    if not result.get("pyautogui", True):
        return _fail("pyautogui is not installed (her click/type actions need it)", _fix_pip("pyautogui pillow"))
    if not result["moved_inside"]:
        return _fail(f'the human-like mouse path ended outside the test window (dropped events: {result["dropped"]})',
                     "Another window took the focus or input is blocked: close pop-ups and run the check with nobody "
                     "touching the mouse. If a game or an elevated window is in front, close it.", **result)
    if not result["typed_ok"]:
        return _fail(f'the test line was not typed correctly (got "{result["typed"][:40]}")',
                     "Keyboard input is blocked or a different keyboard layout is active: switch to the English "
                     "(US) layout (Win+Space) and run again.", **result)
    return _pass(f'moved the mouse along {result["path_points"]} points into the test window and typed the line '
                 f'in {result["seconds"]} s', **result)


def check_autologon(ctx: Ctx) -> Outcome:
    on = ctx.probes.reg_value("HKLM", WINLOGON, "AutoAdminLogon")
    user = ctx.probes.reg_value("HKLM", WINLOGON, "DefaultUserName")
    me = ctx.probes.user_name()
    if str(on) == "1" and str(user or "").lower() == me.lower():
        return _pass(f"auto sign-in is on for {me} (password not read)")
    if str(on) == "1":
        return _fail(f'auto sign-in is on but for "{user}", not {me}',
                     "Run Autologon64.exe from <install root>\\tools\\Autologon (setup.cmd downloads it), enter "
                     f"{me}, her domain and password, press Enable.")
    return _fail("auto sign-in is not set up",
                 "Run installer\\star-home\\setup.cmd again and answer Y to the automatic sign-in question (type "
                 "her password into Microsoft Autologon's own window and press Enable).")


def check_lock_screen(ctx: Ctx) -> Outcome:
    lock = ctx.probes.consolelock()
    secure = ctx.probes.reg_value("HKCU", r"Control Panel\Desktop", "ScreenSaverIsSecure")
    idle = ctx.probes.reg_value("HKLM", POLICY_SYSTEM, "InactivityTimeoutSecs")
    problems = []
    if lock is None:
        problems.append("could not read the 'require sign-in on wake' setting")
    elif lock != (0, 0):
        problems.append(f"sign-in on wake is on (AC {lock[0]}, DC {lock[1]})")
    if str(secure or "0") != "0":
        problems.append("the screen saver asks for the password")
    if idle not in (None, 0):
        problems.append(f"the machine locks after {idle} s idle (policy InactivityTimeoutSecs)")
    if problems:
        return _fail("; ".join(problems),
                     "Run installer\\star-home\\setup.cmd again and answer Y to 'No lock screen...'. By hand, in an "
                     f"elevated PowerShell: powercfg -attributes SUB_NONE {CONSOLELOCK_GUID} -ATTRIB_HIDE; "
                     f"powercfg /setacvalueindex SCHEME_CURRENT SUB_NONE {CONSOLELOCK_GUID} 0; "
                     f"powercfg /setdcvalueindex SCHEME_CURRENT SUB_NONE {CONSOLELOCK_GUID} 0; powercfg /setactive "
                     "SCHEME_CURRENT; Set-ItemProperty 'HKCU:\\Control Panel\\Desktop' ScreenSaverIsSecure 0; "
                     "Remove-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System' "
                     "InactivityTimeoutSecs -ErrorAction SilentlyContinue")
    return _pass("no sign-in on wake, no secure screen saver, no idle lock policy")


def check_uac(ctx: Ctx) -> Outcome:
    admin = ctx.probes.reg_value("HKLM", POLICY_SYSTEM, "ConsentPromptBehaviorAdmin")
    secure = ctx.probes.reg_value("HKLM", POLICY_SYSTEM, "PromptOnSecureDesktop")
    if admin == 0 and secure == 0:
        return _pass("admin actions run without a Yes/No prompt (ConsentPromptBehaviorAdmin 0, no secure desktop)")
    return _fail(f"admin prompt is still on (ConsentPromptBehaviorAdmin {admin}, PromptOnSecureDesktop {secure})",
                 "Run installer\\star-home\\setup.cmd again and answer Y to 'No lock screen... no admin prompts'. By "
                 "hand, in an elevated PowerShell: $p='HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\"
                 "System'; Set-ItemProperty $p ConsentPromptBehaviorAdmin 0 -Type DWord; Set-ItemProperty $p "
                 "PromptOnSecureDesktop 0 -Type DWord")


class _NoBackend:
    """Executor backend for the STOP test: any call would mean a refused action ran."""

    def __getattr__(self, name):
        raise AssertionError(f"backend.{name} was called while stopped")


def check_stop(ctx: Ctx) -> Outcome:
    from .activities import Registry
    from .host import Executor
    from .loop import cycle
    box = ctx.sandbox / "stop-test"
    box.mkdir(parents=True, exist_ok=True)
    control.stop(box, "acceptance")
    if not control.stopped(box):
        return _fail("the STOP file could not be created", "Check that the folder is writable by this account.")
    refused = Executor(box, _NoBackend(), dry_run=False).do("shell", {"command": "Get-Date"})
    paused = cycle(box, {}, Registry(), None, Executor(box, _NoBackend()), None)
    control.resume(box)
    if control.stopped(box):
        return _fail("the STOP file could not be removed", "Delete it by hand: " + str(control.stop_path(box)))
    after = Executor(box, _NoBackend(), dry_run=True).do("shell", {"command": "Get-Date"})
    if refused.ok or "stop" not in refused.text:
        return _fail("an action ran while the STOP file existed", "This is a bug in star/home/host.py: tell the lead.")
    if paused.get("state") != "stopped":
        return _fail(f'her loop did not pause on STOP (state "{paused.get("state")}")',
                     "This is a bug in star/home/loop.py: tell the lead.")
    if not after.ok:
        return _fail("actions stayed refused after STOP was removed", "Tell the lead: star/home/host.py.")
    notes = ["actions refused and the loop paused while STOP existed, both ran again after it was removed"]
    if ctx.mode == "dry":
        notes.append("real folder untouched (dry run)")
    elif control.stopped(ctx.home):
        notes.append("the owner's STOP file is on right now: left alone")
    else:
        control.stop(ctx.home, "acceptance")
        made = control.stopped(ctx.home)
        control.resume(ctx.home)
        if not made or control.stopped(ctx.home):
            return _fail(f"the real STOP file in {ctx.home} could not be created and removed",
                         f"Make sure the STAR Home folder is writable by this account: icacls {ctx.home}")
        notes.append("real STOP file created and removed")
        missing = [n for n in ("STAR STOP.cmd", "STAR RESUME.cmd") if n not in ctx.probes.desktop_files()]
        if missing:
            return _fail("the desktop buttons are missing: " + ", ".join(missing),
                         "Run installer\\star-home\\setup.cmd again (it creates STAR STOP.cmd and STAR RESUME.cmd).")
    return _pass("; ".join(notes))


def check_action_log(ctx: Ctx) -> Outcome:
    home = ctx.state_home
    token = f"acceptance-{int(time.time())}"
    secret = "A" * 24
    control.log_action(home, "acceptance", "done", detail=f"{token} Bearer {secret}")
    rows = [r for r in control.read_log(home, 20) if token in str(r.get("detail", ""))]
    log = home / control.LOG_NAME
    text = log.read_text(encoding="utf-8") if log.exists() else ""
    if not rows:
        return _fail(f"the action log {log} did not take the new line",
                     f"Check the folder is writable by this account: icacls {home}")
    if secret in text:
        return _fail("the action log kept a key-shaped value unredacted", "Tell the lead: star/redact.py.")
    return _pass(f"a line was appended to {control.LOG_NAME} and key-shaped text was redacted")


SPECS = (
    Spec("admin", "Elevated administrator", check_admin),
    Spec("install_root", "STAR lives in one folder on the second drive", check_install_root),
    Spec("brain", "Brain reachable, latency", check_brain, "net", would="send three one-word requests to the brain"),
    Spec("gpu", "GPU and video memory", check_gpu),
    Spec("voice_stack", "Voice stack loads (speech to text, end-of-turn, voice)", check_voice_stack, "heavy",
         would="load the voice models on the GPU"),
    Spec("voice_llm", "Local voice model answers", check_voice_llm, "heavy", would="ask the local voice model one word"),
    Spec("cable_route", "Virtual cable installed", check_cable_route),
    Spec("mic_default", "STAR Microphone is the default recording device", check_mic_default),
    Spec("voice_speaks", "She speaks the test sentence into STAR Microphone", check_voice_speaks, "heavy",
         ("voice_stack", "cable_route"), "speak a test sentence into the cable and record 3 s from STAR Microphone"),
    Spec("mic_recording", "A 3 s recording from STAR Microphone contains the speech", check_mic_recording, "heavy",
         ("voice_speaks",), "transcribe the recording"),
    Spec("hearing_tone", "Loopback hearing hears a test tone", check_hearing_tone, "heavy",
         would="play a quiet 1 kHz tone on the speakers and capture it from the loopback"),
    Spec("echo_exclusion", "Echo exclusion removes her own voice", check_echo_exclusion, "heavy", ("voice_speaks",),
         "play the test sentence on the speakers and run the echo canceller on the loopback"),
    Spec("discord_installed", "Discord installed", check_discord_installed),
    Spec("discord_signed_in", "Discord signed in (window present)", check_discord_signed_in),
    Spec("notifications", "Notification listener permission", check_notifications),
    Spec("roblox", "Roblox installed", check_roblox),
    Spec("minecraft", "Minecraft installed", check_minecraft),
    Spec("node_mineflayer", "Node and Mineflayer installed", check_node_mineflayer),
    Spec("camera", "STAR Camera device", check_camera, optional=True),
    Spec("screenshot", "Screenshot readable", check_screenshot),
    Spec("uia", "UI Automation readable", check_uia),
    Spec("human_input", "Human-like mouse and typing in a test window", check_human_input, "heavy",
         would="open Notepad on a temp file, move the mouse into it along a human-like path and type a test line"),
    Spec("autologon", "Auto sign-in configured", check_autologon),
    Spec("lock_screen", "Lock screen off", check_lock_screen),
    Spec("uac", "Admin prompt (UAC) off", check_uac),
    Spec("stop", "STOP file pauses her", check_stop),
    Spec("action_log", "Action log writes", check_action_log),
)
_PIP_NAMES = {"numpy": "numpy", "sounddevice": "sounddevice", "soundcard": "soundcard", "PIL": "pillow",
              "faster_whisper": "faster-whisper", "kokoro_onnx": "kokoro-onnx"}


def _closure(only: list[str]) -> set[str]:
    by_id = {s.id: s for s in SPECS}
    unknown = [i for i in only if i not in by_id]
    if unknown:
        raise SystemExit(f"unknown check(s): {', '.join(unknown)}. Known: {', '.join(by_id)}")
    chosen: set[str] = set()
    todo = list(only)
    while todo:
        item = todo.pop()
        if item not in chosen:
            chosen.add(item)
            todo.extend(by_id[item].after)
    return chosen


def _crash_outcome(why: Exception, spec: Spec) -> Outcome:
    if isinstance(why.__cause__, ModuleNotFoundError):       # e.g. "Voice features are not set up" wraps a missing package
        why = why.__cause__
    if isinstance(why, ModuleNotFoundError):
        package = _PIP_NAMES.get((why.name or "").split(".")[0], why.name or "<the missing package>")
        return _fail(f"a Python package is missing: {why.name}", _fix_pip(package))
    text = str(why)
    match = re.search(r"pip install ([\w.\-\[\],]+)", text)
    if match:
        return _fail(f"{type(why).__name__}: {text[:200]}", _fix_pip(match.group(1)))
    return _fail(f"{type(why).__name__}: {text[:200]}",
                 f"Fix the cause named in the detail, then run: python -m star.home acceptance {spec.id}")


def run_check(spec: Spec, ctx: Ctx, results: dict) -> dict:
    row = {"id": spec.id, "title": spec.title, "status": SKIP, "detail": "", "fix": "", "seconds": 0.0, "data": {}}
    gate = ""
    if spec.level == "heavy" and ctx.mode != "full":
        flag = "dry-run" if ctx.mode == "dry" else "quick"
        gate = f"skipped in --{flag}" + (f" (would: {spec.would})" if spec.would else "")
    elif spec.level == "net" and ctx.mode == "dry":
        gate = f"skipped in --dry-run (would: {spec.would})"
    else:
        blocked = [d for d in spec.after if results.get(d, {}).get("status") != PASS]
        if blocked:
            gate = f"needs {', '.join(blocked)} to pass first"
    if gate:
        row["detail"] = gate
        return row
    started = time.perf_counter()
    try:
        outcome = spec.run(ctx)
    except Exception as why:
        outcome = _crash_outcome(why, spec)
    row.update(status=outcome.status, detail=redact_text(outcome.detail), fix=outcome.fix,
               data=json.loads(json.dumps(outcome.data, default=str)), seconds=round(time.perf_counter() - started, 2))
    if outcome.status == SKIP and spec.optional:
        row["data"]["optional"] = True
    return row


def run_acceptance(probes, *, mode: str = "full", home: Path | None = None, config: dict | None = None,
                   only: list[str] | None = None, progress=None) -> dict:
    home = Path(home or control.home_dir())
    config = control.load_config(home) if config is None else config
    chosen = _closure(only) if only else {s.id for s in SPECS}
    sandbox = Path(tempfile.mkdtemp(prefix="star-acceptance-"))
    ctx = Ctx(mode, home, config, probes, sandbox)
    results: dict[str, dict] = {}
    started = time.time()
    try:
        for spec in SPECS:
            if spec.id not in chosen:
                continue
            results[spec.id] = run_check(spec, ctx, results)
            if progress:
                progress(results[spec.id])
    finally:
        stack = ctx.shared.get("stack")
        if stack is not None and hasattr(stack, "close"):
            stack.close()
        shutil.rmtree(sandbox, ignore_errors=True)
    rows = list(results.values())
    count = {s: sum(1 for r in rows if r["status"] == s) for s in (PASS, FAIL, SKIP)}
    required_skips = [r["id"] for r in rows if r["status"] == SKIP and not r["data"].get("optional")]
    if count[FAIL]:
        verdict = f"NOT READY: {count[FAIL]} check(s) failed"
    elif required_skips:
        verdict = f"INCOMPLETE: {len(required_skips)} check(s) skipped ({mode} mode); run without --quick/--dry-run"
    else:
        verdict = "READY: every check passed"
    return {"version": 1, "mode": mode, "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
            "seconds": round(time.time() - started, 1), "computer": probes.computer(), "verdict": verdict,
            "counts": count, "checks": rows}


def render_markdown(report: dict, title: str = "STAR Home acceptance report") -> str:
    c = report["counts"]
    lines = [f"# {title}", "",
             f'- Verdict: **{report["verdict"]}**',
             f'- Run: {report["started"]} ({report["mode"]} mode, {report["seconds"]} s) on '
             f'{report["computer"].get("computer", "?")} as {report["computer"].get("user", "?")}',
             f'- pass {c[PASS]}, fail {c[FAIL]}, skip {c[SKIP]}', "",
             "| Check | Result | Detail |", "|---|---|---|"]
    for r in report["checks"]:
        detail = r["detail"].replace("|", "\\|").replace("\n", " ")
        lines.append(f'| {r["title"]} (`{r["id"]}`) | {r["status"].upper()} | {detail} |')
    fails = [r for r in report["checks"] if r["status"] == FAIL]
    if fails:
        lines += ["", "## Fixes", ""]
        for r in fails:
            lines += [f'**{r["title"]}** (`{r["id"]}`): {r["detail"]}', "", f'Fix: {r["fix"]}', ""]
    skips = [r for r in report["checks"] if r["status"] == SKIP]
    if skips:
        lines += ["", "## Skipped", ""] + [f'- `{r["id"]}`: {r["detail"]}' for r in skips]
    return "\n".join(lines) + "\n"


def write_report(report: dict, out_dir: Path, prefix: str = "acceptance", title: str = "STAR Home acceptance report"
                 ) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    texts = {"json": json.dumps(report, indent=1, ensure_ascii=False) + "\n", "md": render_markdown(report, title)}
    made = []
    for suffix, text in texts.items():
        target = out_dir / f"{prefix}-{stamp}.{suffix}"
        target.write_text(text, encoding="utf-8", newline="\n")
        (out_dir / f"latest-{prefix}.{suffix}" if prefix != "acceptance" else out_dir / f"latest.{suffix}").write_text(
            text, encoding="utf-8", newline="\n")
        made.append(target)
    return made[0], made[1]


# ---- scenario dm-call: the owner's first live test ------------------------------------------------------------
# The owner sends STAR a Discord DM and talks to her. The harness decides nothing for her and types nothing: it only
# watches the real PC and records, with timestamps, what STAR did on her own:
#   dm_received    a new unread conversation / message shows in Discord's window (read through UI Automation)
#   replied        a new message of hers appears in Discord, or her action log shows type_text then enter
#   call_started   Discord's window shows a call (ringing / calling / voice connected), started after the DM
#   call_connected the call stops ringing (the owner picked up) and Discord holds the microphone
#   audio_out      speech level on "STAR Microphone" (the cable) during the call: her voice goes out
#   audio_in       speech-like level on the speaker loopback during the call: the owner's voice comes in
@dataclass
class ScenarioOpts:
    from_name: str = ""             # the owner's Discord name; narrows DM detection (otherwise any new unread)
    her_name: str = "Star"
    wait_dm_s: float = 1800.0
    reply_s: float = 180.0
    call_start_s: float = 300.0
    connect_s: float = 180.0
    listen_s: float = 40.0
    poll_s: float = 3.0
    level_threshold: float = 0.01
    out_seconds_needed: float = 1.0
    in_seconds_needed: float = 1.5
    join_grace_s: float = 3.0       # call join / ring sounds in the first seconds of the loopback are ignored


SCENARIO_STEPS = ("dm_received", "replied", "call_started", "call_connected", "audio_out", "audio_in")
# Anchored and short on purpose: a chat message that merely contains the word "calling" is not a call.
_RINGING = re.compile(r"^\s*(ringing|calling)\b.{0,40}$", re.I)
_IN_CALL = re.compile(r"^\s*(voice connected|disconnect|call connected)\b", re.I)
_UNREAD = re.compile(r"unread|new message|mention", re.I)
ACCESSIBILITY_FIX = (r'Discord shows nothing to UI Automation. Close Discord and start it with accessibility on: '
                     r'"%LOCALAPPDATA%\Discord\Update.exe" --processStart Discord.exe --process-start-args '
                     r'"--force-renderer-accessibility"')


def detect_dm(before: set, names: list[str], from_name: str = "") -> dict | None:
    """A DM showed up: a name in Discord's window that was not there before and carries the sender's name (or, with
    no sender given, says unread / new message / mention)."""
    new = [n for n in names if n not in before]
    if from_name:
        hits = [n for n in new if from_name.lower() in n.lower()]
    else:
        hits = [n for n in new if _UNREAD.search(n)]
    return {"elements": [h[:120] for h in hits[:3]]} if hits else None


def call_state(names: list[str]) -> str:
    """"ringing" (calling, nobody picked up), "in_call" (call UI without ringing) or "none"."""
    if any(_RINGING.search(n) for n in names):
        return "ringing"
    return "in_call" if any(_IN_CALL.search(n) for n in names) else "none"


def levels(samples, rate: int, step: float = 0.1) -> list[float]:
    import numpy as np
    x = np.asarray(samples, dtype=np.float32)
    n = max(1, int(rate * step))
    return [float(np.sqrt(np.mean(x[i:i + n] ** 2))) for i in range(0, len(x) - n + 1, n)]


def voiced_seconds(values: list[float], step: float = 0.1, threshold: float = 0.01, skip_s: float = 0.0) -> float:
    return round(sum(step for v in values[int(skip_s / step):] if v >= threshold), 2)


def _epoch(ts: str) -> float:
    return float(calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")))


def typed_reply_in_log(rows: list[dict], since: float) -> bool:
    """Her own action log: text typed (finished) and Enter pressed (started) after `since`."""
    typed = enter = False
    for r in rows:
        try:
            if _epoch(r["ts"]) < since:
                continue
        except (KeyError, ValueError):
            continue
        if r.get("action") == "type_text" and r.get("phase") == "done":
            typed = True
        elif (r.get("action") == "key" and r.get("phase") == "start"
              and str((r.get("args") or {}).get("keys", "")).strip().lower() == "enter"):
            enter = True
    return typed and enter


class _Steps:
    """Ordered step log: every event gets a timestamp, goes to the screen and to a JSONL file."""

    def __init__(self, path: Path, clock, say) -> None:
        self.path, self.clock, self.say = path, clock, say
        self.rows: list[dict] = []
        path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, step: str, event: str, detail: str = "", **data) -> dict:
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.clock())), "step": step, "event": event,
               "detail": redact_text(detail), **data}
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        self.say(f'{row["ts"]}  {step:15} {event:8} {row["detail"]}\n')
        self.rows.append(row)
        return row


def run_dm_call(probes, *, home: Path, out_dir: Path, opts: ScenarioOpts | None = None, mode: str = "full",
                clock=time.time, sleep=time.sleep, say=lambda text: None, now_rows=None) -> dict:
    """Run the scenario and return the report dict (steps with status/detail/fix/evidence + the timestamped log)."""
    opts = opts or ScenarioOpts()
    started = clock()
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(started))
    steps = _Steps(out_dir / f"dm-call-{stamp}.jsonl", clock, say)
    rows_of_log = now_rows or (lambda: control.read_log(home, 2000))
    results: dict[str, dict] = {}

    def finish(step: str, status: str, detail: str, fix: str = "", **data) -> bool:
        results[step] = {"id": step, "title": step.replace("_", " "), "status": status, "detail": detail, "fix": fix,
                         "seconds": round(clock() - started, 1), "data": data}
        steps.log(step, status, detail, **data)
        return status == PASS

    def wait_for(step: str, seconds: float, probe) -> tuple[object, list[str]]:
        """Poll probe(names) every poll_s until it returns something or `seconds` passed. Aborts on STOP."""
        deadline = clock() + seconds
        names: list[str] = []
        while clock() < deadline:
            if control.stopped(home):
                return "stopped", names
            names = probes.discord_snapshot()["names"]
            found = probe(names)
            if found:
                return found, names
            sleep(opts.poll_s)
        return None, names

    def skip_rest(after: str, why: str) -> None:
        for step in SCENARIO_STEPS[SCENARIO_STEPS.index(after) + 1:]:
            if step not in results:
                results[step] = {"id": step, "title": step.replace("_", " "), "status": SKIP, "detail": why,
                                 "fix": "", "seconds": 0.0, "data": {}}

    def verdict() -> dict:
        rows = [results[s] for s in SCENARIO_STEPS if s in results]
        count = {s: sum(1 for r in rows if r["status"] == s) for s in (PASS, FAIL, SKIP)}
        if count[FAIL]:
            text = f"NOT PASSED: {count[FAIL]} step(s) failed"
        elif count[SKIP]:
            text = "INCOMPLETE: " + ", ".join(r["id"] for r in rows if r["status"] == SKIP) + " not run"
        else:
            text = "PASSED: she answered the DM, called, and audio flowed both ways"
        report = {"version": 1, "scenario": "dm-call", "mode": mode, "started": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)), "seconds": round(clock() - started, 1),
            "computer": probes.computer(), "verdict": text, "counts": count, "checks": rows, "log": steps.rows}
        write_report(report, out_dir, "dm-call", "STAR Home scenario: DM, reply, call")
        return report

    if control.stopped(home):
        finish("dm_received", FAIL, "the owner's STOP file is on", "Run 'STAR RESUME.cmd' (or python -m star.home resume).")
        skip_rest("dm_received", "needs dm_received")
        return verdict()
    first = probes.discord_snapshot()
    baseline = set(first["names"])
    if not first["titles"] or len(baseline) < MIN_UI_ELEMENTS:
        finish("dm_received", FAIL, "Discord's window is missing or unreadable (no UI Automation elements)",
               ACCESSIBILITY_FIX if first["titles"] else "Start Discord and sign in; leave its window open.")
        skip_rest("dm_received", "needs dm_received")
        return verdict()
    if call_state(first["names"]) != "none":
        finish("dm_received", FAIL, "a Discord call is already on screen before the test began",
               "End the call and run the scenario again.")
        skip_rest("dm_received", "needs dm_received")
        return verdict()
    steps.log("start", "ready", f'Discord readable ({len(baseline)} elements); mic in use by Discord: '
              f'{probes.mic_in_use()}')
    if mode == "dry":
        for step in SCENARIO_STEPS:
            results[step] = {"id": step, "title": step.replace("_", " "), "status": SKIP, "detail":
                             "skipped in --dry-run: only checked that Discord's screen is readable", "fix": "",
                             "seconds": 0.0, "data": {}}
        return verdict()

    say(f"\nNow send STAR a Discord DM{' from ' + opts.from_name if opts.from_name else ''}. Ask her to call you. "
        f"Waiting up to {opts.wait_dm_s / 60:.0f} minutes. When she calls, pick up and talk to her for a while.\n")
    found, names = wait_for("dm_received", opts.wait_dm_s, lambda n: detect_dm(baseline, n, opts.from_name))
    if found == "stopped":
        finish("dm_received", FAIL, "the owner's STOP file appeared: scenario aborted", "Run 'STAR RESUME.cmd'.")
        skip_rest("dm_received", "aborted by STOP")
        return verdict()
    if not found:
        finish("dm_received", FAIL, f"no new DM seen in Discord within {opts.wait_dm_s / 60:.0f} minutes",
               "Send the DM from your account to STAR's account (check the name given with --from), with Discord "
               "open; if the window reads as empty, start Discord with --force-renderer-accessibility.")
        skip_rest("dm_received", "needs dm_received")
        return verdict()
    t_dm = clock()
    finish("dm_received", PASS, "a new DM shows in Discord: " + "; ".join(found["elements"]), **found)
    at_dm = set(names)

    her = re.compile(rf"\b{re.escape(opts.her_name)}\b", re.I)
    ui_log: dict = {}

    def reply_seen(n: list[str]):
        new = [x for x in n if x not in at_dm and her.search(x)]
        ui = bool(new)
        typed = typed_reply_in_log(rows_of_log(), t_dm)
        if ui or typed:
            ui_log.update(ui=ui, action_log=typed, elements=[x[:120] for x in new[:2]])
            return ui_log
        return None
    found, names = wait_for("replied", opts.reply_s, reply_seen)
    if found == "stopped" or not found:
        finish("replied", FAIL, "the owner's STOP file appeared" if found == "stopped" else
               f"she did not answer within {opts.reply_s:.0f} s of the DM",
               "Look at her action log (python -m star.home log --last 40) and her Discord activity: it must be on "
               "and her loop running (the 'STAR Home' task). The harness never types for her.")
        skip_rest("replied", "needs replied")
        return verdict()
    finish("replied", PASS, f'she answered {clock() - t_dm:.0f} s after the DM (evidence: '
           f'{"UI" if found["ui"] else ""}{" + " if found["ui"] and found["action_log"] else ""}'
           f'{"action log" if found["action_log"] else ""})', **found)

    def call_seen(n: list[str]):
        state = call_state(n)
        return {"state": state} if state != "none" else None
    found, names = wait_for("call_started", opts.call_start_s, call_seen)
    if found == "stopped" or not found:
        finish("call_started", FAIL, "the owner's STOP file appeared" if found == "stopped" else
               f"no outgoing call appeared within {opts.call_start_s:.0f} s after her reply",
               "Ask her in the DM to call you. Her call needs the Discord activity to find the call button "
               "(computer-use wiring) and 'STAR Microphone' as Discord's input device.")
        skip_rest("call_started", "needs call_started")
        return verdict()
    t_call = clock()
    finish("call_started", PASS, f'Discord shows a call ({found["state"]}) {t_call - t_dm:.0f} s after the DM', **found)

    def connected(n: list[str]):
        return {"state": "in_call", "mic_in_use": probes.mic_in_use()} if call_state(n) == "in_call" else None
    deadline = clock() + opts.connect_s
    stable = 0
    while clock() < deadline and stable < 2:
        if control.stopped(home):
            break
        stable = stable + 1 if connected(probes.discord_snapshot()["names"]) else 0
        if stable < 2:
            sleep(opts.poll_s)
    if stable < 2:
        finish("call_connected", FAIL, f"the call never stopped ringing within {opts.connect_s:.0f} s",
               "Pick up the call on your side within the time, then run the scenario again.")
        skip_rest("call_connected", "needs call_connected")
        return verdict()
    mic = probes.mic_in_use()
    finish("call_connected", PASS, f"the call is connected (ringing over; Discord holds the microphone: {mic})",
           mic_in_use=mic)

    say(f"\nCall connected. Talk to her now for {opts.listen_s:.0f} s and let her answer.\n")
    out_audio, in_audio = probes.listen(opts.listen_s)
    out_levels = levels(out_audio[0], out_audio[1])
    in_levels = levels(in_audio[0], in_audio[1])
    spoke = voiced_seconds(out_levels, 0.1, opts.level_threshold)
    heard = voiced_seconds(in_levels, 0.1, opts.level_threshold, opts.join_grace_s)
    heard_text = probes.transcribe(in_audio) if heard else ""
    said_text = probes.transcribe(out_audio) if spoke else ""
    if spoke >= opts.out_seconds_needed:
        finish("audio_out", PASS, f'her voice went out through STAR Microphone: {spoke} s of speech'
               + (f', transcript "{said_text[:80]}"' if said_text else ""), voiced_s=spoke, transcript=said_text[:300])
    else:
        finish("audio_out", FAIL, f"only {spoke} s of speech on STAR Microphone during the call",
               "In Discord: Settings > Voice & Video > Input Device = STAR Microphone; her loop must speak "
               "(settings voice_route 'virtual-mic'); run `acceptance voice_speaks` to test the cable alone.",
               voiced_s=spoke)
    if heard >= opts.in_seconds_needed:
        finish("audio_in", PASS, f"the call's sound reached the loopback: {heard} s after the first "
               f'{opts.join_grace_s:.0f} s' + (f', transcript "{heard_text[:80]}"' if heard_text else ""),
               voiced_s=heard, transcript=heard_text[:300])
    else:
        finish("audio_in", FAIL, f"only {heard} s of sound from the call on the speaker loopback",
               "Discord's output device must be the Windows default output (the loopback listens to it), the volume "
               "up, and you must speak; run `acceptance hearing_tone` to test the loopback alone.", voiced_s=heard)
    return verdict()


class ScenarioProbes:  # pragma: no cover - reads Discord's window and the audio devices of the real PC
    def computer(self) -> dict:
        return SystemProbes().computer()

    def discord_snapshot(self) -> dict:
        out = SystemProbes()._ps(
            "Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes; "
            "$A=[System.Windows.Automation.AutomationElement]; $T=[System.Windows.Automation.TreeScope]; "
            "$C=[System.Windows.Automation.ControlType]; $P=$A::ControlTypeProperty; "
            "$wins=$A::RootElement.FindAll($T::Children,[System.Windows.Automation.Condition]::TrueCondition); "
            "$titles=@(); $names=@(); "
            "foreach($w in $wins){ $n=$w.Current.Name; if($n -match 'Discord$'){ $titles+=$n; "
            "$cond=New-Object System.Windows.Automation.OrCondition("
            "(New-Object System.Windows.Automation.PropertyCondition($P,$C::Text)),"
            "(New-Object System.Windows.Automation.PropertyCondition($P,$C::Button)),"
            "(New-Object System.Windows.Automation.PropertyCondition($P,$C::ListItem))); "
            "$i=0; foreach($e in $w.FindAll($T::Descendants,$cond)){ $x=$e.Current.Name; if($x){$names+=$x}; "
            "$i++; if($i -ge 1500){break} } } }; "
            "ConvertTo-Json -InputObject @{titles=$titles;names=$names} -Compress -Depth 3", 120)
        try:
            data = json.loads(out)
        except ValueError:
            return {"titles": [], "names": []}
        def as_list(value) -> list[str]:
            return [str(x) for x in value] if isinstance(value, list) else ([str(value)] if value else [])
        return {"titles": as_list(data.get("titles")), "names": as_list(data.get("names"))}

    def mic_in_use(self) -> bool | None:
        out = SystemProbes()._ps(
            "$k='HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\"
            "microphone\\NonPackaged'; if(Test-Path $k){ Get-ChildItem $k | Where-Object { $_.PSChildName -like "
            "'*Discord*' } | ForEach-Object { (Get-ItemProperty $_.PSPath).LastUsedTimeStop } } else { 'none' }", 20)
        values = [v.strip() for v in out.splitlines() if v.strip()]
        if not values or values == ["none"]:
            return None
        return "0" in values

    def listen(self, seconds: float):
        import numpy as np
        from ..senses.audio import RATE, pcm_to_float
        from ..senses.capture import LoopbackSource
        from ..senses.routes import find_route, query_devices
        from ..voice.devices import _sounddevice
        sd = _sounddevice()
        recording = find_route(query_devices(sd)).recording
        buf = sd.rec(int(seconds * recording["rate"]), samplerate=recording["rate"],
                     channels=min(2, recording["channels"]), device=recording["index"], dtype="float32")
        source = LoopbackSource()
        frames = []
        try:
            for count, frame in enumerate(source.frames()):
                frames.append(pcm_to_float(frame))
                if count >= int(seconds * RATE / 512):
                    break
        finally:
            source.close()
        sd.wait()
        return ((np.asarray(buf, dtype=np.float32).mean(axis=1), recording["rate"]),
                (np.concatenate(frames) if frames else np.zeros(0, dtype=np.float32), RATE))

    def transcribe(self, audio) -> str:
        """Speech to text of a (samples, rate) clip with the voice stack; "" when the stack is not available."""
        try:
            from ..senses.audio import StreamResampler, float_to_pcm
            if not hasattr(self, "_stack"):
                self._stack = SystemProbes().load_voice_stack()
            samples, rate = audio
            return self._stack.transcribe(float_to_pcm(StreamResampler(rate, 1).process(samples)))
        except Exception:
            return ""


# ---- command line ----------------------------------------------------------------------------------------------
def cli(argv: list[str] | None = None, *, probes=None, scenario_probes=None, out_stream=None, sleep=time.sleep) -> int:
    parser = argparse.ArgumentParser(prog="python -m star.home acceptance")
    parser.add_argument("checks", nargs="*", help="only these checks: " + ", ".join(s.id for s in SPECS))
    parser.add_argument("--quick", action="store_true", help="no audio, model loads or desktop input")
    parser.add_argument("--dry-run", action="store_true", help="read-only; STOP/log checks in a throw-away folder")
    parser.add_argument("--out", default="", help="report folder (default <home>\\acceptance)")
    parser.add_argument("--scenario", choices=["dm-call"], help="the owner's live test instead of the checks")
    parser.add_argument("--from", dest="from_name", default="", help="scenario: the owner's Discord name")
    parser.add_argument("--her-name", default="Star", help="scenario: STAR's display name in Discord")
    parser.add_argument("--wait-minutes", type=float, default=30.0, help="scenario: how long to wait for the DM")
    parser.add_argument("--listen-seconds", type=float, default=40.0, help="scenario: length of the audio window")
    args = parser.parse_args(argv)
    stream = out_stream or sys.stdout
    say = stream.write
    mode = "dry" if args.dry_run else "quick" if args.quick else "full"
    out_dir = Path(args.out) if args.out else control.home_dir() / "acceptance"
    if args.scenario:
        opts = ScenarioOpts(from_name=args.from_name, her_name=args.her_name, wait_dm_s=args.wait_minutes * 60,
                            listen_s=args.listen_seconds)
        report = run_dm_call(scenario_probes or ScenarioProbes(), home=control.home_dir(), out_dir=out_dir,
                             opts=opts, mode=mode, say=say, sleep=sleep)
        say(f'\n{report["verdict"]}\n')
        for row in report["checks"]:
            if row["status"] == FAIL:
                say(f'  {row["id"]}: {row["detail"]}\n      fix: {row["fix"]}\n')
        say(f"reports in {out_dir}\n")
        return 1 if report["counts"][FAIL] else 0

    def show(row: dict) -> None:
        say(f'{row["status"].upper():5} {row["id"]:18} {row["detail"]}\n')
        if row["status"] == FAIL:
            say(f'      fix: {row["fix"]}\n')

    report = run_acceptance(probes or SystemProbes(), mode=mode, only=args.checks, progress=show)
    json_path, md_path = write_report(report, out_dir)
    say(f'\n{report["verdict"]}\nreport: {md_path}\n        {json_path}\n')
    return 1 if report["counts"][FAIL] else 0


# ---- the real PC ----------------------------------------------------------------------------------------------
class VoiceStack:  # pragma: no cover - loads the real models on her GPU
    def __init__(self, engines, gpu: bool) -> None:
        self.engines, self.gpu, self.timings = engines, gpu, dict(engines.load_seconds)

    def speak(self, text: str) -> tuple[bytes, int]:
        chunks = list(self.engines.tts.synthesize(text))
        rate = chunks[0][1]
        return b"".join(pcm for pcm, r in chunks if r == rate), rate

    def transcribe(self, pcm16k: bytes) -> str:
        return str(self.engines.asr.transcribe(pcm16k, 16000))

    def close(self) -> None:
        self.engines = None


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


class SystemProbes:  # pragma: no cover - every method touches the real PC; exercised by running the command there
    def computer(self) -> dict:
        return {"computer": platform.node(), "user": self.user_name(), "python": sys.version.split()[0],
                "windows": platform.platform()}

    def user_name(self) -> str:
        return getpass.getuser()

    def _ps(self, script: str, timeout: float = 60.0) -> str:
        done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-Command", script], capture_output=True, text=True, timeout=timeout,
                              creationflags=_no_window(), encoding="utf-8", errors="replace")
        return (done.stdout or "").strip()

    def is_admin(self) -> bool:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())

    def install_info(self) -> dict:
        root = paths.root()
        home = control.home_dir()
        present = {name: bool(root and (root / name).is_dir()) for name in ROOT_DIRS}
        return {"root": str(root) if root else "", "system_drive": os.environ.get("SystemDrive", "C:"),
                "home": str(home), "present": present}

    def brain_ping(self, config: dict) -> list[float]:
        from .brain import http_chat
        chat = http_chat(config)
        times = []
        for _ in range(3):
            started = time.perf_counter()
            reply = chat([{"role": "user", "content": "Reply with the word ready."}], [])
            if not str(reply.get("content") or "").strip():
                raise OSError("empty reply")
            times.append(time.perf_counter() - started)
        return times

    def gpu_info(self) -> dict | None:
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version",
                                  "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15,
                                 creationflags=_no_window()).stdout.splitlines()[0]
            name, total, free, driver = [p.strip() for p in out.split(",")]
            return {"name": name, "total_mb": int(total), "free_mb": int(free), "driver": driver}
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            return None

    def load_voice_stack(self) -> VoiceStack:
        from ..senses.instant import apply_preset
        from ..voice.engines import add_nvidia_dll_dirs, gpu_available
        from ..voice.runtime import Engines
        add_nvidia_dll_dirs()
        return VoiceStack(Engines.load(apply_preset()), gpu_available())

    def voice_llm(self, base: str) -> tuple[float, str]:
        import urllib.request
        body = json.dumps({"model": "local", "messages": [{"role": "user", "content": "Say ready."}],
                           "max_tokens": 8, "temperature": 0}).encode()
        request = urllib.request.Request(base + "/v1/chat/completions", data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
        started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=30) as response:
            reply = json.loads(response.read().decode())
        return time.perf_counter() - started, reply["choices"][0]["message"].get("content") or ""

    def audio_devices(self) -> list[dict]:
        from ..senses.routes import query_devices
        return query_devices()

    def default_recording(self) -> str:
        from ..voice.devices import _sounddevice
        sd = _sounddevice()
        wasapi = next((a for a in sd.query_hostapis() if "wasapi" in a["name"].lower()), None)
        index = wasapi["default_input_device"] if wasapi else sd.default.device[0]
        return str(sd.query_devices(index)["name"]) if index is not None and index >= 0 else ""

    def _default_output(self, sd) -> dict:
        wasapi = next((a for a in sd.query_hostapis() if "wasapi" in a["name"].lower()), None)
        index = wasapi["default_output_device"] if wasapi else sd.default.device[1]
        info = sd.query_devices(index)
        return {"index": index, "rate": int(info["default_samplerate"]),
                "channels": min(2, int(info["max_output_channels"]))}

    def speak_and_record(self, pcm: bytes, rate: int, seconds: float):
        import numpy as np
        from ..senses.routes import find_route, open_voice_output, query_devices
        from ..voice.devices import _sounddevice
        sd = _sounddevice()
        devices = query_devices(sd)
        recording = find_route(devices).recording
        channels = min(2, recording["channels"])
        with open_voice_output(devices) as speaker:
            buf = sd.rec(int(seconds * recording["rate"]), samplerate=recording["rate"], channels=channels,
                         device=recording["index"], dtype="float32")
            time.sleep(0.15)
            speaker.play(pcm, rate)
            sd.wait()
            speaker.stop()
        return np.asarray(buf, dtype=np.float32).mean(axis=1), recording["rate"]

    def hear_tone(self, hz: float):
        import threading
        import numpy as np
        from ..senses.audio import RATE, pcm_to_float
        from ..senses.capture import LoopbackSource
        from ..voice.devices import _sounddevice
        sd = _sounddevice()
        out = self._default_output(sd)
        t = np.arange(int(out["rate"] * 1.2)) / out["rate"]
        tone = (0.2 * np.sin(2 * np.pi * hz * t)).astype(np.float32)
        tone = np.repeat(tone[:, None], out["channels"], axis=1) if out["channels"] > 1 else tone
        source = LoopbackSource()
        collected = []
        want = int(1.8 * RATE / 512)
        try:
            for count, frame in enumerate(source.frames()):
                collected.append(pcm_to_float(frame))
                if count == 2:
                    threading.Thread(target=lambda: (sd.play(tone, out["rate"], device=out["index"]), sd.wait()),
                                     daemon=True).start()
                if count >= want:
                    break
        finally:
            source.close()
        samples = np.concatenate(collected[5:]) if len(collected) > 5 else np.zeros(0, dtype=np.float32)
        return samples, RATE

    def echo_test(self, pcm: bytes, rate: int):
        import threading
        from ..senses.audio import RATE, pcm_to_float, rms
        from ..senses.capture import LoopbackSource
        from ..senses.output import SoundOutput
        from ..senses.reference import EchoCanceller, PlaybackReference, ReferenceSpeaker
        from ..voice.devices import _sounddevice
        sd = _sounddevice()
        out = self._default_output(sd)
        reference = PlaybackReference()
        canceller = EchoCanceller(reference)
        source = LoopbackSource()
        rows = []
        want = int((len(pcm) / 2 / rate + 1.0) * RATE / 512) + 4
        try:
            with SoundOutput(out["index"], rate=out["rate"], channels=out["channels"]) as speaker:
                voice = ReferenceSpeaker(speaker, reference)
                for count, frame in enumerate(source.frames()):
                    raw = pcm_to_float(frame)
                    cleaned, info = canceller.process(raw)
                    rows.append((rms(raw), rms(cleaned), bool(info.own_voice)))
                    if count == 3:
                        threading.Thread(target=voice.play, args=(pcm, rate), daemon=True).start()
                    if count >= want:
                        break
                voice.stop()
        finally:
            source.close()
        return rows

    def discord_state(self) -> dict:
        root = Path(os.environ.get("LOCALAPPDATA", "")) / "Discord"
        installed = (root / "Update.exe").is_file() or any(root.glob("app-*/Discord.exe"))
        out = self._ps("Get-Process Discord -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle } | "
                       "ForEach-Object { $_.MainWindowTitle }", 20)
        return {"installed": installed, "titles": [t for t in out.splitlines() if t.strip()]}

    def notification_access(self) -> str:
        out = self._ps("try { $null=[Windows.UI.Notifications.Management.UserNotificationListener,"
                       "Windows.UI.Notifications,ContentType=WindowsRuntime]; "
                       "[Windows.UI.Notifications.Management.UserNotificationListener]::Current.GetAccessStatus()"
                       ".ToString() } catch { 'error: ' + $_.Exception.Message }", 30)
        return out.splitlines()[-1] if out else ""

    def find_roblox(self) -> str:
        local = os.environ.get("LOCALAPPDATA", "")
        hits = sorted((Path(local) / "Roblox" / "Versions").glob("*/RobloxPlayerBeta.exe")) if local else []
        return str(hits[-1]) if hits else ""

    def minecraft_state(self) -> dict:
        launcher = any(Path(os.environ.get(var, "")).joinpath("Minecraft Launcher", "MinecraftLauncher.exe").is_file()
                       for var in ("ProgramFiles(x86)", "ProgramFiles") if os.environ.get(var))
        if not launcher:
            launcher = bool(self._ps("Get-AppxPackage -Name Microsoft.4297127D64EC6 | Select-Object -First 1 "
                                     "-ExpandProperty Name", 30))
        versions = Path(os.environ.get("APPDATA", "")) / ".minecraft" / "versions"
        found = sorted(p.name for p in versions.iterdir() if p.is_dir()) if versions.is_dir() else []
        return {"launcher": launcher, "versions": found}

    def node_state(self) -> dict:
        import star
        folder = Path(star.__file__).parent / "games" / "mineflayer"
        node = shutil.which("node") or next((str(p) for p in (Path(os.environ.get("ProgramFiles", "")) / "nodejs" /
                                                              "node.exe",) if p.is_file()), "")
        state = {"node": bool(node), "version": "", "major": 0, "mineflayer": False, "folder": str(folder)}
        if not node:
            return state
        version = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=15,
                                 creationflags=_no_window()).stdout.strip()
        state.update(version=version, major=int(re.sub(r"\D.*", "", version.lstrip("v")) or 0))
        if (folder / "node_modules" / "mineflayer").is_dir():
            state["mineflayer"] = subprocess.run([node, "-e", "require('mineflayer')"], cwd=str(folder),
                                                 capture_output=True, timeout=60,
                                                 creationflags=_no_window()).returncode == 0
        return state

    def camera_module(self) -> bool:
        import importlib.util
        for name in ("star.vtuber", "star.camera"):
            try:
                if importlib.util.find_spec(name) is not None:
                    return True
            except (ImportError, ValueError):
                continue
        return False

    def camera_devices(self) -> list[str]:
        out = self._ps(
            "$k='{860BB310-5D01-11d0-BD3B-00A0C911CE86}'; $n=@(); "
            "foreach($r in 'HKLM:\\SOFTWARE\\Classes\\CLSID','HKLM:\\SOFTWARE\\WOW6432Node\\Classes\\CLSID',"
            "'HKCU:\\SOFTWARE\\Classes\\CLSID'){ $p=\"$r\\$k\\Instance\"; if(Test-Path $p){ "
            "Get-ChildItem $p | ForEach-Object { $n+=(Get-ItemProperty $_.PSPath).FriendlyName } } }; "
            "Get-PnpDevice -Class Camera,Image -PresentOnly -ErrorAction SilentlyContinue | "
            "ForEach-Object { $n+=$_.FriendlyName }; $n | Where-Object { $_ } | Sort-Object -Unique", 40)
        return [line.strip() for line in out.splitlines() if line.strip()]

    def screenshot_stats(self) -> dict:
        from PIL import ImageGrab
        image = ImageGrab.grab(all_screens=True)
        small = image.convert("L").resize((64, 36))
        return {"width": image.width, "height": image.height, "distinct": len(set(small.getdata()))}

    def uia_windows(self) -> list[str]:
        out = self._ps("Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes; "
                       "$kids=[System.Windows.Automation.AutomationElement]::RootElement.FindAll("
                       "[System.Windows.Automation.TreeScope]::Children,"
                       "[System.Windows.Automation.Condition]::TrueCondition); "
                       "$names=@(); foreach($k in $kids){ if($k.Current.Name){ $names+=$k.Current.Name } }; "
                       "ConvertTo-Json -InputObject $names -Compress", 60)
        try:
            names = json.loads(out)
        except ValueError:
            return []
        return [str(n) for n in names] if isinstance(names, list) else []

    def input_test(self, line: str) -> dict:
        import ctypes
        import ctypes.wintypes as wt
        import random
        from ..play import humanlike, winput
        try:
            import pyautogui  # noqa: F401  (her click/type actions in host.py use it)
            have_pyautogui = True
        except ImportError:
            have_pyautogui = False
        user32 = ctypes.windll.user32
        folder = Path(tempfile.mkdtemp(prefix="star-acceptance-"))
        target = folder / "star-acceptance.txt"
        target.write_text("", encoding="utf-8")
        subprocess.Popen(["notepad.exe", str(target)])
        windows: list[int] = []

        def enum(h, _):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(h, buf, 256)
            if "star-acceptance" in buf.value.lower() and user32.IsWindowVisible(h):
                windows.append(h)
            return True
        callback = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)(enum)
        deadline = time.time() + 15
        while time.time() < deadline and not windows:
            user32.EnumWindows(callback, 0)
            time.sleep(0.3)
        result = {"pyautogui": have_pyautogui, "moved_inside": False, "typed_ok": False, "typed": "", "dropped": 0,
                  "path_points": 0, "seconds": 0.0}
        if not windows:
            result["typed"] = "(the test window never appeared)"
            shutil.rmtree(folder, ignore_errors=True)
            return result
        hwnd = windows[0]
        try:
            started = time.time()
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.8)
            rect = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            goal = (rect.left + (rect.right - rect.left) * 0.5, rect.top + (rect.bottom - rect.top) * 0.55)
            here = wt.POINT()
            user32.GetCursorPos(ctypes.byref(here))
            sink = winput.SendInputSink(winput.window_guard("star-acceptance"))
            rng = random.Random()
            path = humanlike.pointer_path((here.x, here.y), goal, 40.0, rng, humanlike.HumanProfile())
            began = time.perf_counter()
            for t, x, y in path:
                time.sleep(max(0.0, t - (time.perf_counter() - began)))
                sink.move_to(int(x), int(y))
            user32.GetCursorPos(ctypes.byref(here))
            result["moved_inside"] = rect.left <= here.x <= rect.right and rect.top <= here.y <= rect.bottom
            result["path_points"] = len(path)
            sink.button("left", True)
            time.sleep(0.06)
            sink.button("left", False)
            for ch in line:
                key = "space" if ch == " " else ch
                sink.key(key, True)
                time.sleep(rng.uniform(0.03, 0.06))
                sink.key(key, False)
                time.sleep(rng.uniform(0.04, 0.12))
            for name, down in (("ctrl", True), ("s", True), ("s", False), ("ctrl", False)):
                sink.key(name, down)
                time.sleep(0.05)
            time.sleep(1.2)
            result["dropped"] = sink.dropped
            result["typed"] = target.read_text(encoding="utf-8", errors="replace").strip()
            result["typed_ok"] = result["typed"] == line
            result["seconds"] = round(time.time() - started, 1)
        finally:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)          # WM_CLOSE; the file is saved, so no prompt
            time.sleep(0.8)
            shutil.rmtree(folder, ignore_errors=True)
        return result

    def reg_value(self, hive: str, path: str, name: str):
        import winreg
        root = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}[hive]
        try:
            with winreg.OpenKey(root, path) as key:
                return winreg.QueryValueEx(key, name)[0]
        except OSError:
            return None

    def consolelock(self) -> tuple[int, int] | None:
        for setting in (CONSOLELOCK_GUID, "CONSOLELOCK"):
            out = subprocess.run(["powercfg", "/q", "SCHEME_CURRENT", "SUB_NONE", setting], capture_output=True,
                                 text=True, timeout=20, creationflags=_no_window()).stdout
            found = parse_consolelock(out)
            if found:
                return found
        policy = rf"SOFTWARE\Policies\Microsoft\Power\PowerSettings\{CONSOLELOCK_GUID}"   # group policy form
        ac, dc = (self.reg_value("HKLM", policy, name) for name in ("ACSettingIndex", "DCSettingIndex"))
        return (int(ac), int(dc)) if ac is not None and dc is not None else None

    def desktop_files(self) -> list[str]:
        folder = self._ps("[Environment]::GetFolderPath('Desktop')", 20)
        return os.listdir(folder) if folder and os.path.isdir(folder) else []


if __name__ == "__main__":  # pragma: no cover
    sys.exit(cli(sys.argv[1:]))
