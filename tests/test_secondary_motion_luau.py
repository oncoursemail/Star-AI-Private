"""Runs scripts/test_secondary_motion.luau (the XPBD kernel and FixedStepper numerical tests) under pytest.

The Luau file is a standalone script, not a *.spec.luau, so scripts/run_luau_specs.py does not pick it up.
The run needs the official `luau` CLI on PATH and skips cleanly without it, like the other Luau tests.
"""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "test_secondary_motion.luau"
LUAU = shutil.which("luau")


def test_the_luau_script_requires_files_that_exist():
    source = SCRIPT.read_text(encoding="utf-8")
    modules = re.findall(r'require\("([^"]+)"\)', source)
    assert len(modules) == 2
    for module in modules:
        assert (SCRIPT.parent / (module + ".luau")).is_file(), module


@pytest.mark.skipif(LUAU is None, reason="needs the Luau CLI on PATH (not available here)")
def test_xpbd_kernel_and_fixed_stepper_pass_their_luau_tests():
    # cwd is scripts/ so the "../star/..." requires resolve whether the CLI is script- or cwd-relative.
    done = subprocess.run([str(LUAU), SCRIPT.name], cwd=SCRIPT.parent, capture_output=True, text=True,
                          timeout=60, check=False)
    cases = len(re.findall(r"^test\(", SCRIPT.read_text(encoding="utf-8"), re.MULTILINE))
    assert cases >= 25
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"RESULT passed={cases} failed=0" in done.stdout, done.stdout
    assert "FAIL" not in done.stdout
