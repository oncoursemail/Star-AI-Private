"""The one-script installer for STAR's PC (installer/star-home): what it installs must cover what the code imports, the pins
must be exact, and the script must parse and dry-run. Nothing is installed or downloaded by these tests."""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "installer" / "star-home"
SETUP = (HOME / "setup.ps1").read_text(encoding="utf-8")
LOCK = (ROOT / "requirements-home.txt").read_text(encoding="utf-8")
LOCK_TORCH = (ROOT / "requirements-home-torch.txt").read_text(encoding="utf-8")
PINS = json.loads((HOME / "pins.json").read_text(encoding="utf-8"))
POWERSHELL = shutil.which("powershell")
# Packages whose abilities live on her PC. Third-party modules they import (at module level or lazily) must be in the lock.
PACKAGES = ("home", "senses", "social", "games", "play", "computer", "watch", "vtuber", "voice", "inner")
IMPORT_TO_PACKAGE = {"PIL": "pillow", "comtypes": "comtypes", "numpy": "numpy", "pyautogui": "pyautogui", "dxcam": "dxcam",
                     "faster_whisper": "faster-whisper", "httpx": "httpx", "kokoro_onnx": "kokoro-onnx", "mss": "mss",
                     "onnxruntime": "onnxruntime-gpu", "pyvirtualcam": "pyvirtualcam", "soundcard": "soundcard",
                     "sounddevice": "sounddevice", "winsdk": "winsdk", "torch": "torch", "pyworld": "pyworld"}


def locked() -> dict[str, str]:
    return {m.group(1).lower(): m.group(2) for m in re.finditer(r"(?m)^([A-Za-z0-9_.-]+)==([^\s\\;]+)", LOCK + "\n" + LOCK_TORCH)}


def test_every_third_party_import_of_her_abilities_is_installed():
    stdlib = set(sys.stdlib_module_names)
    found: dict[str, str] = {}
    for package in PACKAGES:
        for path in (ROOT / "star" / package).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                         else [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else [])
                for name in names:
                    top = name.split(".")[0]
                    if top not in stdlib and top != "star":
                        found.setdefault(top, f"{path.relative_to(ROOT)}")
    missing = {m: where for m, where in found.items() if m not in IMPORT_TO_PACKAGE}
    assert not missing, f"imported but not in requirements-home.in / IMPORT_TO_PACKAGE: {missing}"
    have = locked()
    assert not [p for m, p in IMPORT_TO_PACKAGE.items() if m in found and p not in have]


def test_the_lock_files_are_exact_and_hashed():
    entries = re.findall(r"(?m)^([A-Za-z0-9_.-]+)==[^\s;]+(?: ; extra != \"star:allow\")? \\\n((?:    --hash=sha256:[0-9a-f]{64}(?: \\)?\n)+)", LOCK + LOCK_TORCH)
    assert len(entries) == len(re.findall(r"(?m)^[A-Za-z0-9_.-]+==", LOCK + LOCK_TORCH)) >= 60
    from packaging.requirements import Requirement
    for line in re.findall(r"(?m)^[A-Za-z0-9_.-]+==[^\\\n]*", LOCK):                    # every logical requirement parses; markers hold
        requirement = Requirement(line.strip())
        assert requirement.marker is None or requirement.marker.evaluate({"extra": ""}), line
    assert "onnxruntime==" not in LOCK and "onnxruntime-gpu==1.26" in LOCK       # the CPU wheel would overwrite the GPU one
    assert "nvidia-cublas-cu12==" in LOCK and "nvidia-cudnn-cu12==" in LOCK       # faster-whisper on the card needs both
    assert "--index-url https://download.pytorch.org/whl/cu" in LOCK_TORCH and re.search(r"(?m)^torch==\d+\.\d+\.\d+\+cu\d+ ", LOCK_TORCH)
    source = (ROOT / "requirements-home.in").read_text(encoding="utf-8")
    direct = {re.match(r"[A-Za-z0-9_.-]+", line).group(0).lower() for line in source.splitlines()
              if line.strip() and not line.startswith("#")}
    assert direct <= set(locked()), direct - set(locked())


def test_pins_json_has_a_size_and_sha256_for_every_model_file():
    for choice in PINS["grounder"].values():
        assert re.fullmatch(r"[0-9a-f]{40}", choice["revision"])
        for file in choice["files"]:
            assert re.fullmatch(r"[0-9a-f]{64}", file["sha256"]) and file["size"] > 100_000_000
        assert {choice["model_file"], choice["mmproj_file"]} == {f["name"] for f in choice["files"]}
    assert PINS["vbcable"]["url"].startswith("https://download.vb-audio.com/") and PINS["vbcable"]["signer_pattern"]
    assert PINS["node"]["winget"] == "OpenJS.NodeJS.LTS" and PINS["python"]["winget"] == "Python.Python.3.12"
    assert PINS["node"]["min_major"] >= 22                                       # mineflayer 4.39 needs Node 22
    package = json.loads((ROOT / "star" / "games" / "mineflayer" / "package.json").read_text(encoding="utf-8"))
    for name, exact in PINS["npm"].items():                                      # the pin satisfies the repo's own range
        assert package["dependencies"][name].lstrip("^") .split(".")[0] == exact.split(".")[0]


def test_every_step_is_declared_documented_and_reported():
    declared = re.search(r"\$StepIds = @\((.*?)\)\n", SETUP, re.S).group(1)
    ids = re.findall(r"'([a-z]+)'", declared)
    used = re.findall(r"(?m)^Invoke-Step '([a-z]+)'", SETUP)
    assert ids == used and len(ids) == len(set(ids))
    for step in ("python", "node", "cable", "camera", "models", "grounder", "discord", "acceptance", "pip", "torch"):
        assert step in ids
    header = "\n".join(SETUP.splitlines()[:25])
    assert all(step in header for step in ids)                                   # the usage text lists every id
    for needle in ("-m star.senses.setup", "star.senses.routes", "--force-renderer-accessibility", "acceptance', '--quick'",
                   "install-camera.ps1", "requirements-home.txt", "requirements-home-torch.txt", "--require-hashes",
                   "Get-AuthenticodeSignature", "VBCABLE_Setup_x64.exe", "pins.json"):
        assert needle in SETUP, needle
    assert SETUP.count("Mark-Failed") >= 15 and "SKIPPED" in SETUP and "DRY-RUN" in SETUP


def test_her_pc_enrols_itself_for_computer_use_with_the_installers_own_home():
    step = SETUP[SETUP.index("Invoke-Step 'enroll'"):SETUP.index("Invoke-Step 'task'")]
    assert "'-m', 'star.computer', 'enroll', '--star-pc', '--home', $Data" in step   # the same home her loop uses
    assert "'check-machine'" in step and "already enrolled" in step                  # idempotent: no second write
    assert "if ($DryRun)" in step and step.index("if ($DryRun)") < step.index("'enroll', '--star-pc'")
    assert "needs the venv" in step                                                  # skipped, not failed, before the venv exists
    ids = re.findall(r"(?m)^Invoke-Step '([a-z]+)'", SETUP)
    assert ids.index("config") < ids.index("enroll") < ids.index("task")             # her home folder exists first


def test_scripts_are_plain_ascii_and_the_cmd_files_keep_crlf():
    for path in (HOME / "setup.ps1", HOME / "setup.cmd", ROOT / "installer" / "star-camera" / "install-camera.ps1",
                 ROOT / "installer" / "star-camera" / "install-camera.cmd", HOME / "pins.json"):
        data = path.read_bytes()
        data.decode("ascii")                                                      # no BOM or smart quotes for Windows PowerShell 5.1
    for path in (HOME / "setup.cmd", ROOT / "installer" / "star-camera" / "install-camera.cmd"):
        assert b"\r\n" in path.read_bytes() and b"\n" not in path.read_bytes().replace(b"\r\n", b"")


def test_camera_installer_follows_the_root_and_can_dry_run():
    text = (ROOT / "installer" / "star-camera" / "install-camera.ps1").read_text(encoding="utf-8")
    assert "[switch]$DryRun" in text and "[string]$Root" in text and "C:\\STAR\\home" not in text


@pytest.mark.skipif(not POWERSHELL, reason="needs Windows PowerShell")
def test_powershell_parses_every_installer_script():
    scripts = [HOME / "setup.ps1", ROOT / "installer" / "star-camera" / "install-camera.ps1"]
    listing = ", ".join("'%s'" % path for path in scripts)
    command = ("foreach ($f in %s) { $e = $null; $t = $null; [void][System.Management.Automation.Language.Parser]::ParseFile("
               "$f, [ref]$t, [ref]$e); \"$($e.Count)\" }" % listing)                   # parse only: the scripts are never run here
    out = subprocess.run([POWERSHELL, "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=120)
    assert out.stdout.split() == ["0", "0"], out.stdout + out.stderr


@pytest.mark.skipif(not POWERSHELL, reason="needs Windows PowerShell")
def test_dry_run_changes_nothing_and_prints_the_plan(tmp_path):
    root = tmp_path / "STAR"
    out = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(HOME / "setup.ps1"), "-DryRun", "-Yes",
                          "-Root", str(root), "-Only", "files,config,enroll,task,controls,cable,camera,grounder", "-Grounder", "ui-tars-2b"],
                         capture_output=True, text=True, timeout=300, cwd=tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    for line in ("DRY RUN: nothing on this PC will be changed", "DRY-RUN  files", "DRY-RUN  cable", "DRY-RUN  grounder", "DRY-RUN  enroll",
                 "SKIPPED  python      not selected (-Only)", "nothing was changed, downloaded or installed"):
        assert line in out.stdout, line
    assert not root.exists()                                                      # not even the folder was created
    assert not (root / "home" / "machine.json").exists()                          # a dry run never enrolls the PC
