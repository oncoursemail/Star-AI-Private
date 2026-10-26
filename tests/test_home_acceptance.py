"""python -m star.home acceptance: checks, modes, report, scenario dm-call, install root. Fake probes only; the
STOP / action-log / install-root logic runs for real on temporary folders."""
from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import time
import urllib.error

import pytest

from star.home import acceptance as acc
from star.home import control, paths

HEARD = "hello this is star acceptance test"


def _np():
    return pytest.importorskip("numpy")


class FakeStack:
    gpu = True
    timings = {"speech to text": 1.2, "voice": 0.8}

    def __init__(self, heard=HEARD, speech_s=1.0):
        self.heard, self.speech_s = heard, speech_s
        self.closed = False

    def speak(self, text):
        return b"\x01\x02" * int(24000 * self.speech_s), 24000

    def transcribe(self, pcm):
        return self.heard

    def close(self):
        self.closed = True


GOOD = {
    "admin": True,
    "install": {"root": "D:\\STAR", "system_drive": "C:", "home": "D:\\STAR\\home",
                "present": {n: True for n in acc.ROOT_DIRS}},
    "brain": [0.4, 0.5, 0.45],
    "gpu": {"name": "NVIDIA GeForce RTX 4060", "total_mb": 8188, "free_mb": 7000, "driver": "560.1"},
    "stack": None,
    "llm": (0.3, "ready"),
    "devices": [{"kind": "input", "name": "STAR Microphone (VB-Audio Virtual Cable)", "index": 1},
                {"kind": "output", "name": "CABLE Input (VB-Audio Virtual Cable)", "index": 2}],
    "default_mic": "STAR Microphone (VB-Audio Virtual Cable)",
    "discord": {"installed": True, "titles": ["#general | Friends - Discord"]},
    "notify": "Allowed",
    "roblox": "C:\\Users\\star\\AppData\\Local\\Roblox\\Versions\\version-1\\RobloxPlayerBeta.exe",
    "minecraft": {"launcher": True, "versions": ["1.21.4"]},
    "node": {"node": True, "version": "v22.1.0", "major": 22, "mineflayer": True, "folder": "x"},
    "camera_module": False,
    "camera_devices": [],
    "shot": {"width": 1920, "height": 1080, "distinct": 40},
    "uia": ["Task Bar", "Discord", "Notepad"],
    "input": {"pyautogui": True, "moved_inside": True, "typed_ok": True, "typed": acc.INPUT_LINE, "dropped": 0,
              "path_points": 55, "seconds": 6.2},
    "regs": {"AutoAdminLogon": "1", "DefaultUserName": "star", "ScreenSaverIsSecure": "0",
             "ConsentPromptBehaviorAdmin": 0, "PromptOnSecureDesktop": 0},
    "lock": (0, 0),
    "desktop": ["STAR STOP.cmd", "STAR RESUME.cmd"],
    "recording": "speech",
    "tone": "tone",
    "echo": [(0.05, 0.001, True)] * 20,
}


class FakeProbes:
    """Same methods as SystemProbes. A value that is an Exception is raised instead of returned."""

    def __init__(self, **over):
        self.v = {**GOOD, **over}
        self.calls = []

    def _v(self, name):
        self.calls.append(name)
        value = self.v[name]
        if isinstance(value, BaseException):
            raise value
        return value

    def computer(self): return {"computer": "STAR-PC", "user": "star"}
    def user_name(self): return "star"
    def is_admin(self): return self._v("admin")
    def install_info(self): return self._v("install")
    def brain_ping(self, config): return self._v("brain")
    def gpu_info(self): return self._v("gpu")
    def load_voice_stack(self): return self._v("stack") or FakeStack()
    def voice_llm(self, base): return self._v("llm")
    def audio_devices(self): return self._v("devices")
    def default_recording(self): return self._v("default_mic")

    def speak_and_record(self, pcm, rate, seconds):
        np = _np()
        kind = self._v("recording")
        t = np.arange(int(48000 * seconds)) / 48000
        wave = 0.1 * np.sin(2 * np.pi * 300 * t) if kind == "speech" else np.zeros_like(t)
        return wave.astype(np.float32), 48000

    def hear_tone(self, hz):
        np = _np()
        t = np.arange(int(16000 * 1.5)) / 16000
        kind = self._v("tone")
        return (0.1 * np.sin(2 * np.pi * (hz if kind == "tone" else 440) * t)).astype(np.float32), 16000

    def echo_test(self, pcm, rate): return self._v("echo")
    def discord_state(self): return self._v("discord")
    def notification_access(self): return self._v("notify")
    def find_roblox(self): return self._v("roblox")
    def minecraft_state(self): return self._v("minecraft")
    def node_state(self): return self._v("node")
    def camera_module(self): return self._v("camera_module")
    def camera_devices(self): return self._v("camera_devices")
    def screenshot_stats(self): return self._v("shot")
    def uia_windows(self): return self._v("uia")
    def input_test(self, line): return self._v("input")
    def reg_value(self, hive, path, name): return self._v("regs").get(name)
    def consolelock(self): return self._v("lock")
    def desktop_files(self): return self._v("desktop")


def run(tmp_path, probes=None, mode="full", only=None):
    home = tmp_path / "home"
    return acc.run_acceptance(probes or FakeProbes(), mode=mode, home=home, config={"brain_url": "http://brain.test"},
                              only=only), home


def by_id(report):
    return {r["id"]: r for r in report["checks"]}


# ---- the full run ------------------------------------------------------------------------------------------------
def test_full_run_passes_every_check_and_says_ready(tmp_path):
    _np()
    report, home = run(tmp_path)
    rows = by_id(report)
    assert [r["id"] for r in report["checks"]] == [s.id for s in acc.SPECS]
    assert {r["status"] for i, r in rows.items() if i != "camera"} == {"pass"}, \
        {i: r["detail"] for i, r in rows.items() if r["status"] != "pass"}
    assert rows["camera"]["status"] == "skip" and rows["camera"]["data"]["optional"]
    assert report["verdict"].startswith("READY")
    assert (home / "actions.jsonl").exists()          # the log check wrote into the real home in a full run
    assert not (home / "STOP").exists()               # and the STOP round trip left nothing behind


FAILURES = [
    ("admin", {"admin": False}, "not running as an elevated"),
    ("install_root", {"install": {**GOOD["install"], "root": "C:\\STAR", "home": "C:\\STAR\\home"}}, "Windows drive"),
    ("install_root", {"install": {**GOOD["install"], "root": ""}}, "no STAR install root"),
    ("install_root", {"install": {**GOOD["install"], "home": "C:\\ProgramData\\STAR\\home"}}, "outside the root"),
    ("install_root", {"install": {**GOOD["install"], "present": {**GOOD["install"]["present"], "venv": False}}},
     "venv"),
    ("brain", {"brain": urllib.error.URLError("down")}, "not reachable"),
    ("brain", {"brain": ValueError("key")}, "key file"),
    ("brain", {"brain": urllib.error.HTTPError("u", 401, "no", None, None)}, "refused the key"),
    ("brain", {"brain": [14.0, 15.0, 16.0]}, "slowly"),
    ("gpu", {"gpu": None}, "nvidia-smi"),
    ("gpu", {"gpu": {**GOOD["gpu"], "total_mb": 6000}}, "under 8 GB"),
    ("gpu", {"gpu": {**GOOD["gpu"], "free_mb": 900}}, "video memory"),
    ("voice_llm", {"llm": urllib.error.URLError("refused")}, "does not answer"),
    ("voice_llm", {"llm": (0.2, " ")}, "empty reply"),
    ("cable_route", {"devices": []}, "not installed"),
    ("cable_route", {"devices": [{"kind": "input", "name": "CABLE Output (VB-Audio Virtual Cable)"},
                                 {"kind": "output", "name": "CABLE Input (VB-Audio Virtual Cable)"}]},
     "not named"),
    ("mic_default", {"default_mic": "Microphone (Realtek)"}, "not STAR Microphone"),
    ("mic_recording", {"recording": "silent"}, "silent"),
    ("hearing_tone", {"tone": "wrong"}, "did not hear"),
    ("echo_exclusion", {"echo": [(0.05, 0.05, False)] * 20}, "still heard"),
    ("echo_exclusion", {"echo": []}, "none of the test sentence"),
    ("discord_installed", {"discord": {"installed": False, "titles": []}}, "not installed"),
    ("discord_signed_in", {"discord": {"installed": True, "titles": []}}, "no window"),
    ("discord_signed_in", {"discord": {"installed": True, "titles": ["Discord"]}}, "sign-in screen"),
    ("notifications", {"notify": "Denied"}, "Denied"),
    ("roblox", {"roblox": ""}, "Roblox is not installed"),
    ("minecraft", {"minecraft": {"launcher": False, "versions": []}}, "Launcher is not installed"),
    ("minecraft", {"minecraft": {"launcher": True, "versions": []}}, "no Java Edition"),
    ("node_mineflayer", {"node": {**GOOD["node"], "node": False}}, "Node.js is not installed"),
    ("node_mineflayer", {"node": {**GOOD["node"], "major": 16, "version": "v16.0.0"}}, "too old"),
    ("node_mineflayer", {"node": {**GOOD["node"], "mineflayer": False}}, "Mineflayer is not"),
    ("camera", {"camera_module": True, "camera_devices": ["Integrated Webcam"]}, "no camera device"),
    ("screenshot", {"shot": {"width": 1920, "height": 1080, "distinct": 1}}, "blank"),
    ("uia", {"uia": []}, "no named"),
    ("human_input", {"input": {**GOOD["input"], "moved_inside": False, "dropped": 7}}, "outside the test window"),
    ("human_input", {"input": {**GOOD["input"], "typed_ok": False, "typed": "sta"}}, "not typed correctly"),
    ("human_input", {"input": {**GOOD["input"], "pyautogui": False}}, "pyautogui"),
    ("autologon", {"regs": {**GOOD["regs"], "AutoAdminLogon": None}}, "not set up"),
    ("autologon", {"regs": {**GOOD["regs"], "DefaultUserName": "other"}}, "not star"),
    ("lock_screen", {"lock": (1, 1)}, "sign-in on wake is on"),
    ("lock_screen", {"regs": {**GOOD["regs"], "ScreenSaverIsSecure": "1"}}, "screen saver"),
    ("uac", {"regs": {**GOOD["regs"], "ConsentPromptBehaviorAdmin": 5}}, "admin prompt is still on"),
    ("stop", {"desktop": []}, "desktop buttons"),
]


@pytest.mark.parametrize("check_id,over,fragment", FAILURES, ids=[f"{c}-{i}" for i, (c, _o, _f) in enumerate(FAILURES)])
def test_each_failure_is_reported_with_an_exact_fix_and_nothing_else_breaks(tmp_path, check_id, over, fragment):
    _np()
    report, _ = run(tmp_path, FakeProbes(**over))
    row = by_id(report)[check_id]
    assert row["status"] == "fail" and fragment in row["detail"], row
    assert len(row["fix"]) > 20
    expected = [check_id] + (["discord_signed_in"] if check_id == "discord_installed" else [])
    assert [i for i, r in by_id(report).items() if r["status"] == "fail"] == expected
    assert report["verdict"].startswith("NOT READY")


def test_wrong_words_in_the_recording_fail_with_what_was_heard(tmp_path):
    _np()
    report, _ = run(tmp_path, FakeProbes(stack=FakeStack(heard="thanks for watching")))
    row = by_id(report)["mic_recording"]
    assert row["status"] == "fail" and "thanks for watching" in row["detail"] and "48000" in row["fix"]


def test_voice_on_the_cpu_fails_and_blocks_what_depends_on_it(tmp_path):
    cpu = FakeStack()
    cpu.gpu = False
    report, _ = run(tmp_path, FakeProbes(stack=cpu))
    rows = by_id(report)
    assert rows["voice_stack"]["status"] == "fail" and "onnxruntime-gpu" in rows["voice_stack"]["fix"]
    for dependent in ("voice_speaks", "mic_recording", "echo_exclusion"):
        assert rows[dependent]["status"] == "skip" and "needs" in rows[dependent]["detail"]


def test_a_crashing_probe_becomes_a_failure_not_a_crash(tmp_path):
    report, _ = run(tmp_path, FakeProbes(shot=RuntimeError("boom Bearer " + "Q" * 30)))
    row = by_id(report)["screenshot"]
    assert row["status"] == "fail" and "RuntimeError" in row["detail"] and "Q" * 30 not in row["detail"]
    assert "acceptance screenshot" in row["fix"]


def test_a_missing_package_gets_the_pip_line(tmp_path):
    report, _ = run(tmp_path, FakeProbes(shot=ModuleNotFoundError("No module named 'PIL'", name="PIL")))
    row = by_id(report)["screenshot"]
    assert row["status"] == "fail" and "pip install pillow" in row["fix"]
    wrapped = RuntimeError("Voice features are not set up on this computer yet.")
    wrapped.__cause__ = ModuleNotFoundError("No module named 'sounddevice'", name="sounddevice")
    report, _ = run(tmp_path, FakeProbes(default_mic=wrapped))
    assert "pip install sounddevice" in by_id(report)["mic_default"]["fix"]
    report, _ = run(tmp_path, FakeProbes(tone=RuntimeError("Hearing the PC's sound needs the 'soundcard' package: "
                                                           "pip install soundcard")))
    assert "pip install soundcard" in by_id(report)["hearing_tone"]["fix"]


# ---- modes ----------------------------------------------------------------------------------------------------
HEAVY = {"voice_stack", "voice_llm", "voice_speaks", "mic_recording", "hearing_tone", "echo_exclusion",
         "human_input"}


def test_quick_mode_skips_audio_models_and_input_but_still_asks_the_brain(tmp_path):
    probes = FakeProbes()
    report, _ = run(tmp_path, probes, "quick")
    rows = by_id(report)
    for hid in HEAVY:
        assert rows[hid]["status"] == "skip" and "--quick" in rows[hid]["detail"] and "would:" in rows[hid]["detail"] or \
            rows[hid]["detail"].startswith("needs")
    assert rows["brain"]["status"] == "pass" and rows["gpu"]["status"] == "pass"
    assert not {"load_voice_stack", "speak_and_record", "hear_tone", "echo_test", "input_test"} & set(probes.calls)
    assert report["verdict"].startswith("INCOMPLETE")


def test_dry_run_touches_neither_the_brain_nor_her_real_folder(tmp_path):
    probes = FakeProbes()
    report, home = run(tmp_path, probes, "dry")
    rows = by_id(report)
    assert rows["brain"]["status"] == "skip" and "--dry-run" in rows["brain"]["detail"]
    assert "brain" not in probes.calls
    assert rows["stop"]["status"] == "pass" and "untouched" in rows["stop"]["detail"]
    assert rows["action_log"]["status"] == "pass"
    assert not home.exists()                          # STOP and log checks used the throw-away folder only


def test_only_runs_the_named_checks_and_the_ones_they_need(tmp_path):
    _np()
    report, _ = run(tmp_path, only=["mic_recording"])
    assert [r["id"] for r in report["checks"]] == ["voice_stack", "cable_route", "voice_speaks", "mic_recording"]
    with pytest.raises(SystemExit):
        run(tmp_path, only=["nonsense"])


# ---- the real STOP / log logic ---------------------------------------------------------------------------------
def test_owner_stop_file_is_left_alone(tmp_path):
    home = tmp_path / "home"
    control.stop(home, "owner")
    report = acc.run_acceptance(FakeProbes(), mode="full", home=home, config={}, only=["stop"])
    row = by_id(report)["stop"]
    assert row["status"] == "pass" and "left alone" in row["detail"]
    assert (home / "STOP").exists()


def test_stop_check_fails_if_an_action_ran_while_stopped(tmp_path, monkeypatch):
    from star.home import host
    monkeypatch.setattr(host.Executor, "do", lambda self, action, args=None: host.Result(True, "ran"))
    report = acc.run_acceptance(FakeProbes(), mode="dry", home=tmp_path / "h", config={}, only=["stop"])
    assert by_id(report)["stop"]["status"] == "fail" and "ran while the STOP" in by_id(report)["stop"]["detail"]


def test_stop_check_fails_if_the_loop_does_not_pause(tmp_path, monkeypatch):
    from star.home import loop
    monkeypatch.setattr(loop, "cycle", lambda *a, **k: {"state": "worked"})
    report = acc.run_acceptance(FakeProbes(), mode="dry", home=tmp_path / "h", config={}, only=["stop"])
    assert "did not pause" in by_id(report)["stop"]["detail"]


def test_action_log_check_fails_when_a_key_is_not_redacted(tmp_path, monkeypatch):
    real = control.log_action

    def leaky(home, action, phase, **fields):
        path = Path(home) / control.LOG_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"action": action, "phase": phase, **fields}) + "\n", encoding="utf-8")
    monkeypatch.setattr(control, "log_action", leaky)
    report = acc.run_acceptance(FakeProbes(), mode="full", home=tmp_path / "h", config={}, only=["action_log"])
    assert by_id(report)["action_log"]["status"] == "fail"
    monkeypatch.setattr(control, "log_action", real)
    report = acc.run_acceptance(FakeProbes(), mode="full", home=tmp_path / "h2", config={}, only=["action_log"])
    assert by_id(report)["action_log"]["status"] == "pass"


# ---- reports and command line ---------------------------------------------------------------------------------------
def test_reports_are_written_as_json_and_markdown_with_fixes(tmp_path):
    _np()
    report, _ = run(tmp_path, FakeProbes(notify="Denied"))
    json_path, md_path = acc.write_report(report, tmp_path / "out")
    assert json.loads(json_path.read_text(encoding="utf-8"))["counts"]["fail"] == 1
    text = md_path.read_text(encoding="utf-8")
    assert "NOT READY" in text and "## Fixes" in text and "Notification access" in text and "STAR-PC" in text
    assert (tmp_path / "out" / "latest.json").read_text(encoding="utf-8") == json_path.read_text(encoding="utf-8")
    assert (tmp_path / "out" / "latest.md").exists()


def test_command_line_exit_code_and_report_folder(tmp_path):
    out = io.StringIO()
    code = acc.cli(["--dry-run", "--out", str(tmp_path / "r"), "gpu", "admin"], probes=FakeProbes(), out_stream=out)
    assert code == 0 and "PASS  gpu" in out.getvalue() and "report:" in out.getvalue()
    assert (tmp_path / "r" / "latest.md").exists()
    out = io.StringIO()
    code = acc.cli(["--quick", "--out", str(tmp_path / "r2"), "gpu"], probes=FakeProbes(gpu=None), out_stream=out)
    assert code == 1 and "fix:" in out.getvalue()


def test_module_main_delegates_the_acceptance_subcommand(tmp_path, monkeypatch):
    from star.home import __main__ as entry
    monkeypatch.setattr(acc, "SystemProbes", FakeProbes)
    assert entry.main(["acceptance", "--dry-run", "--out", str(tmp_path / "o"), "admin"]) == 0
    assert (tmp_path / "o" / "latest.json").exists()


# ---- pure helpers -----------------------------------------------------------------------------------------------------
def test_tone_report_accepts_the_tone_and_rejects_silence_noise_and_another_pitch():
    np = _np()
    t = np.arange(16000) / 16000
    assert acc.tone_report(0.1 * np.sin(2 * np.pi * 1000 * t), 16000)["ok"]
    assert not acc.tone_report(np.zeros(16000), 16000)["ok"]
    assert not acc.tone_report(0.1 * np.sin(2 * np.pi * 440 * t), 16000)["ok"]
    assert not acc.tone_report(np.random.default_rng(1).normal(0, 0.1, 16000), 16000)["ok"]


def test_echo_stats_and_speech_hits_and_signed_in_and_consolelock():
    assert acc.echo_stats([(0.1, 0.01, False)] * 10)["reduction_db"] == 20.0
    assert acc.echo_stats([(0.001, 0.001, False)])["frames"] == 0
    assert acc.speech_hits("Hello! This is Star. Acceptance test.") == list(acc.SPEECH_WORDS)
    assert acc.speech_hits("thanks for watching") == []
    assert acc.discord_signed_in(["#general | Server - Discord"]) and not acc.discord_signed_in(["Discord"])
    english = "Current AC Power Setting Index: 0x00000000\n    Current DC Power Setting Index: 0x00000001\n"
    german = "Aktuelle Gleichstromeinstellung: 0x00000000\nAktuelle Wechselstromeinstellung: 0x00000000"
    assert acc.parse_consolelock("Power Setting GUID: x\n" + english) == (0, 1)
    assert acc.parse_consolelock(german) == (0, 0) and acc.parse_consolelock("nothing") is None
    assert acc.CONSOLELOCK_GUID in (Path(__file__).resolve().parents[1] / "installer" / "star-home" /
                                    "setup.ps1").read_text(encoding="utf-8")      # setup and the check use one setting


# ---- install root (paths.py) -----------------------------------------------------------------------------------------
def test_root_comes_from_the_environment_or_from_the_install_venv(tmp_path, monkeypatch):
    monkeypatch.delenv("STAR_ROOT", raising=False)
    assert paths.root() is None                      # a development checkout has no root
    monkeypatch.setenv("STAR_ROOT", str(tmp_path / "D"))
    assert paths.root() == tmp_path / "D" and paths.home_dir() == tmp_path / "D" / "home"
    assert paths.models_dir() == tmp_path / "D" / "models" and paths.acceptance_dir() == tmp_path / "D" / "home" / "acceptance"
    monkeypatch.delenv("STAR_ROOT")
    scripts = tmp_path / "S" / "venv" / "Scripts"
    scripts.mkdir(parents=True)
    monkeypatch.setattr(sys, "executable", str(scripts / "python.exe"))
    assert paths.root() is None                      # a venv without app next to it is not an install
    (tmp_path / "S" / "app").mkdir()
    assert paths.root() == tmp_path / "S"
    monkeypatch.setattr(sys, "executable", str(tmp_path / "elsewhere" / "python.exe"))
    assert paths.root() is None


def test_data_and_models_follow_the_root_unless_overridden(tmp_path, monkeypatch):
    from star.voice import engines
    monkeypatch.delenv("STAR_HOME_DIR", raising=False)
    monkeypatch.delenv("STAR_VOICE_MODELS", raising=False)
    monkeypatch.setenv("STAR_ROOT", str(tmp_path / "D"))
    assert control.home_dir() == tmp_path / "D" / "home"
    assert engines.models_dir() == tmp_path / "D" / "models" / "voice"
    monkeypatch.setenv("STAR_HOME_DIR", str(tmp_path / "other"))
    monkeypatch.setenv("STAR_VOICE_MODELS", str(tmp_path / "m"))
    assert control.home_dir() == tmp_path / "other" and engines.models_dir() == tmp_path / "m"
    monkeypatch.delenv("STAR_HOME_DIR")
    monkeypatch.delenv("STAR_ROOT")
    monkeypatch.delenv("STAR_VOICE_MODELS")
    monkeypatch.setenv("ProgramData", str(tmp_path / "PD"))
    assert control.home_dir() == tmp_path / "PD" / "STAR" / "home"      # no root: the old default


def test_setup_script_takes_a_root_and_keeps_everything_under_it():
    text = (Path(__file__).resolve().parents[1] / "installer" / "star-home" / "setup.ps1").read_text(encoding="utf-8")
    assert "[string]$Root" in text and "DriveType=3" in text and "$env:SystemDrive" in text
    for name in ("STAR_ROOT", "STAR_VOICE_MODELS", "HF_HOME"):
        assert name in text
    assert "ProgramData 'STAR" not in text and "C:\\STAR\\home" not in text
    assert "Join-Path $Root 'tools\\Autologon'" in text
    assert "star.home acceptance" in text.strip().splitlines()[-1]
    assert "ProgramData 'ssh" in text                                   # Windows' own sshd folder stays where it is


# ---- scenario dm-call -------------------------------------------------------------------------------------------------
class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


BASE = ["Home", "Direct Messages", "Mute", "Deafen", "Alex", "Friends", "Nitro", "Shop", "Settings", "Inbox", "Help",
        "Add Friends to DM"]
DM = "Alex, 1 unread message"
REPLY = "Star, Today at 1:00 PM, hey! sure, calling you now"
RINGING = ["Calling Alex...", "Voice Connected"]
IN_CALL = ["Voice Connected", "Disconnect", "Alex"]


class FakeScenarioProbes:
    def __init__(self, clock, timeline, out="speech", inbound="speech", titles=("Friends - Discord",)):
        self.clock, self.timeline, self.out, self.inbound, self.titles = clock, timeline, out, inbound, titles
        self.start = clock()

    def computer(self): return {"computer": "STAR-PC", "user": "star"}

    def discord_snapshot(self):
        dt = self.clock() - self.start
        names = list(BASE)
        for at, extra, drop in self.timeline:
            if dt >= at:
                names = [n for n in names if n not in drop] + list(extra)
        return {"titles": list(self.titles), "names": names}

    def mic_in_use(self): return True

    def listen(self, seconds):
        np = _np()
        t48, t16 = np.arange(int(48000 * seconds)) / 48000, np.arange(int(16000 * seconds)) / 16000
        loud = lambda t, hz: (0.1 * np.sin(2 * np.pi * hz * t)).astype(np.float32)
        out = loud(t48, 300) if self.out == "speech" else np.zeros_like(t48, dtype=np.float32)
        if self.inbound == "speech":
            heard = loud(t16, 500)
        elif self.inbound == "join_sound_only":
            heard = loud(t16, 500) * (t16 < 2.5)
        else:
            heard = np.zeros_like(t16, dtype=np.float32)
        return (out, 48000), (heard, 16000)

    def transcribe(self, audio): return "hello there"


FULL = [(30, [DM], []), (50, [REPLY], []), (80, RINGING, []), (95, IN_CALL, ["Calling Alex..."])]
OPTS = acc.ScenarioOpts(from_name="Alex", wait_dm_s=120, reply_s=60, call_start_s=60, connect_s=60, listen_s=6,
                        poll_s=3)


def scenario(tmp_path, timeline, mode="full", opts=OPTS, **kw):
    clock = Clock()
    probes = FakeScenarioProbes(clock, timeline, **kw)
    home = tmp_path / "home"
    report = acc.run_dm_call(probes, home=home, out_dir=tmp_path / "out", opts=opts, mode=mode, clock=clock,
                             sleep=clock.sleep, say=lambda text: None)
    return report, home


def steps(report):
    return {r["id"]: r for r in report["checks"]}


def test_scenario_passes_when_she_replies_calls_and_audio_flows_both_ways(tmp_path):
    report, _ = scenario(tmp_path, FULL)
    rows = steps(report)
    assert [rows[s]["status"] for s in acc.SCENARIO_STEPS] == ["pass"] * 6, {k: v["detail"] for k, v in rows.items()}
    assert report["verdict"].startswith("PASSED")
    assert "UI" in rows["replied"]["detail"] and rows["audio_out"]["data"]["transcript"] == "hello there"
    log = [json.loads(line) for line in (tmp_path / "out").glob("dm-call-*.jsonl").__next__().read_text().splitlines()]
    assert [r["step"] for r in log if r["event"] == "pass"] == list(acc.SCENARIO_STEPS)
    assert all(r["ts"].endswith("Z") for r in log) and log == sorted(log, key=lambda r: r["ts"])
    assert (tmp_path / "out" / "latest-dm-call.md").exists()


def test_scenario_fails_when_no_dm_arrives_and_skips_the_rest(tmp_path):
    report, _ = scenario(tmp_path, [])
    rows = steps(report)
    assert rows["dm_received"]["status"] == "fail" and "--from" in rows["dm_received"]["fix"]
    assert all(rows[s]["status"] == "skip" for s in acc.SCENARIO_STEPS[1:])
    assert report["verdict"].startswith("NOT PASSED")


@pytest.mark.parametrize("timeline,failed,fragment", [
    ([(30, [DM], [])], "replied", "did not answer"),
    ([(30, [DM], []), (50, [REPLY], [])], "call_started", "no outgoing call"),
    ([(30, [DM], []), (50, [REPLY], []), (80, RINGING, [])], "call_connected", "never stopped ringing"),
])
def test_scenario_stops_at_the_first_thing_she_did_not_do(tmp_path, timeline, failed, fragment):
    report, _ = scenario(tmp_path, timeline)
    rows = steps(report)
    assert rows[failed]["status"] == "fail" and fragment in rows[failed]["detail"] and rows[failed]["fix"]
    later = acc.SCENARIO_STEPS[acc.SCENARIO_STEPS.index(failed) + 1:]
    assert all(rows[s]["status"] == "skip" for s in later)


def test_scenario_does_not_fake_her_decisions_it_never_acts(tmp_path):
    class Spy(FakeScenarioProbes):
        def __getattr__(self, name):
            raise AssertionError(f"scenario used {name}")
    clock = Clock()
    probes = Spy(clock, FULL)
    report = acc.run_dm_call(probes, home=tmp_path / "h", out_dir=tmp_path / "o", opts=OPTS, clock=clock,
                             sleep=clock.sleep)
    assert report["verdict"].startswith("PASSED")      # only computer/snapshot/mic/listen/transcribe were needed


def test_scenario_accepts_her_action_log_as_evidence_of_the_reply(tmp_path):
    clock = Clock()
    home = tmp_path / "home"
    timeline = [(30, [DM], []), (80, RINGING, []), (95, IN_CALL, ["Calling Alex..."])]
    probes = FakeScenarioProbes(clock, timeline)
    now = clock()

    def stamp(offset):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + offset))
    rows = [{"ts": stamp(40), "action": "type_text", "phase": "done"},
            {"ts": stamp(42), "action": "key", "phase": "start", "args": {"keys": "enter"}}]
    report = acc.run_dm_call(probes, home=home, out_dir=tmp_path / "o", opts=OPTS, clock=clock, sleep=clock.sleep,
                             now_rows=lambda: rows if clock() >= now + 45 else [])
    assert steps(report)["replied"]["status"] == "pass" and "action log" in steps(report)["replied"]["detail"]


def test_scenario_audio_failures_say_which_direction(tmp_path):
    report, _ = scenario(tmp_path, FULL, out="silent")
    rows = steps(report)
    assert rows["audio_out"]["status"] == "fail" and "Input Device = STAR Microphone" in rows["audio_out"]["fix"]
    assert rows["audio_in"]["status"] == "pass"
    report, _ = scenario(tmp_path, FULL, inbound="join_sound_only")       # the join sound must not count
    assert steps(report)["audio_in"]["status"] == "fail" and steps(report)["audio_out"]["status"] == "pass"


def test_scenario_refuses_to_start_under_stop_and_aborts_on_stop(tmp_path):
    home = tmp_path / "home"
    control.stop(home, "owner")
    clock = Clock()
    report = acc.run_dm_call(FakeScenarioProbes(clock, FULL), home=home, out_dir=tmp_path / "o", opts=OPTS,
                             clock=clock, sleep=clock.sleep)
    assert steps(report)["dm_received"]["status"] == "fail" and "STOP" in steps(report)["dm_received"]["detail"]
    control.resume(home)

    class StopsLater(FakeScenarioProbes):
        def discord_snapshot(self):
            if self.clock() - self.start > 10:
                control.stop(home, "owner")
            return super().discord_snapshot()
    clock = Clock()
    report = acc.run_dm_call(StopsLater(clock, FULL), home=home, out_dir=tmp_path / "o2", opts=OPTS, clock=clock,
                             sleep=clock.sleep)
    assert "aborted" in steps(report)["dm_received"]["detail"]


def test_scenario_explains_an_unreadable_discord_and_dry_run_only_checks_readability(tmp_path):
    clock = Clock()

    class Blind(FakeScenarioProbes):
        def discord_snapshot(self):
            return {"titles": ["Friends - Discord"], "names": ["Minimize", "Maximize", "Close"]}
    report = acc.run_dm_call(Blind(clock, FULL), home=tmp_path / "h", out_dir=tmp_path / "o", opts=OPTS, clock=clock,
                             sleep=clock.sleep)
    assert "force-renderer-accessibility" in steps(report)["dm_received"]["fix"]
    report, _ = scenario(tmp_path, FULL, mode="dry")
    assert all(r["status"] == "skip" and "dry-run" in r["detail"] for r in report["checks"])
    assert report["verdict"].startswith("INCOMPLETE")


def test_scenario_helpers():
    assert acc.detect_dm({"a"}, ["a", "Alex, 2 unread messages"], "Alex")["elements"]
    assert acc.detect_dm({"a"}, ["a", "Mallory, hi"], "Alex") is None
    assert acc.detect_dm(set(), ["Bob, 3 unread messages"]) and acc.detect_dm(set(), ["Bob"]) is None
    assert acc.call_state(["Calling Alex..."]) == "ringing" and acc.call_state(["Voice Connected"]) == "in_call"
    assert acc.call_state(["Start Voice Call"]) == "none"
    assert acc.voiced_seconds([0.0, 0.5, 0.5, 0.5], 0.1, 0.01, skip_s=0.1) == 0.3
    _np()
    assert len(acc.levels([0.1] * 1000, 1000, 0.1)) == 10
    rows = [{"ts": "2026-10-26T10:00:05Z", "action": "type_text", "phase": "done"},
            {"ts": "2026-10-26T10:00:06Z", "action": "key", "phase": "start", "args": {"keys": "Enter"}}]
    since = acc._epoch("2026-10-26T10:00:00Z")
    assert acc.typed_reply_in_log(rows, since) and not acc.typed_reply_in_log(rows, since + 60)
    assert not acc.typed_reply_in_log(rows[:1], since)
    assert acc.SCENARIO_STEPS == ("dm_received", "replied", "call_started", "call_connected", "audio_out", "audio_in")


def test_scenario_through_the_command_line(tmp_path):
    clock = Clock()
    out = io.StringIO()
    code = acc.cli(["--scenario", "dm-call", "--dry-run", "--out", str(tmp_path / "o")], out_stream=out,
                   scenario_probes=FakeScenarioProbes(clock, FULL), sleep=clock.sleep)
    assert code == 0 and "INCOMPLETE" in out.getvalue()
