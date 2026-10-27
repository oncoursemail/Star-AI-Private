"""Read-only checks against the REAL RC tools and backend on this PC. Skipped unless RC_LIVE=1.

Runs only: discover, list, plan (never launch), verify (read-only hashing), backend /healthz /readyz /capabilities.
It proves the module's reading of RC's real JSON matches what RC actually prints. It does not start any game.
"""
import os

import pytest

from launcher.rc.module import RcModule
from launcher.rc.paths import Paths

pytestmark = pytest.mark.skipif(os.environ.get("RC_LIVE") != "1", reason="set RC_LIVE=1 to read the real RC install")


@pytest.fixture(scope="module")
def mod(tmp_path_factory):
    home = tmp_path_factory.mktemp("launcher-home")
    paths = Paths(home, Paths.from_env().rc_home)  # real RC folder, throwaway launcher folder (settings/logs/cache)
    return RcModule(paths)


def test_overview_reads_real_state(mod):
    ov = mod.call("overview")
    assert ov["tools"]["installed"], "no RC tools found"
    by = {c["key"]: c for c in ov["clients"]}
    print({k: (v["state"], v["installRoot"]) for k, v in by.items()})
    assert "steam" in by and ov["backend"]["state"] in ("running", "stopped", "disabled", "not_installed", "unhealthy", "conflict")
    print("backend", {k: ov["backend"][k] for k in ("state", "task", "ready", "nativeClientReady", "actualGameClientVerified")})
    assert ov["backend"]["actualGameClientVerified"] is False


def test_real_plan_matches_rc(mod):
    c = {e["key"]: e for e in mod.call("clients.list")["clients"]}["steam"]
    if not c["installationId"]:
        pytest.skip("Steam client not registered in RC's catalog")
    plan = mod.cli.plan(c["installationId"], mode="vr")
    assert plan["arguments"] == ["+forcemode:vr"] and plan["canExecuteOnCurrentPlatform"] is True


def test_real_verify(mod):
    c = {e["key"]: e for e in mod.call("clients.list")["clients"]}["steam"]
    if not c["installationId"]:
        pytest.skip("Steam client not registered in RC's catalog")
    res = mod.cli.verify(c["installationId"])
    assert "isValid" in res and "issues" in res
