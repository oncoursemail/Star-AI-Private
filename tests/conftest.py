"""Suite-wide isolation.

STAR reads the owner's Roblox API key from a key file in the home folder (star/roblox_cloud.py). No
test may depend on, or use, the key of the machine it runs on: the file path points nowhere here.
The one live test names the real file itself.

CI may run the suite as parallel shards (STAR_TEST_SHARD="i/N", see tests/sharding.py). Unset, the
whole suite runs, as it always did.
"""
import os

import pytest


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    spec = os.environ.get("STAR_TEST_SHARD", "").strip()
    if not spec:
        return
    from tests.sharding import split_items
    kept, dropped = split_items(items, spec)
    if dropped:
        config.hook.pytest_deselected(items=dropped)
    items[:] = kept
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        files = len({item.nodeid.split("::", 1)[0] for item in kept})
        reporter.write_line(f"STAR_TEST_SHARD {spec}: {len(kept)} of {len(kept) + len(dropped)} tests in {files} files")


@pytest.fixture(autouse=True)
def _no_owner_roblox_key(monkeypatch, tmp_path_factory):
    for name in ("ROBLOX_OPEN_CLOUD_API_KEY", "ROBLOX_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("STAR_ROBLOX_KEY_FILE", str(tmp_path_factory.getbasetemp() / "no-roblox-key.env"))


@pytest.fixture(autouse=True)
def _fresh_web_research_memory():
    """star.web_research keeps searches (15 min) and robots.txt (6 h) in process memory; no test sees another's."""
    import sys
    module = sys.modules.get("star.web_research")
    for cache in (getattr(module, "_SEARCHES", None), getattr(module, "_ROBOTS", None)):
        if cache is not None:
            cache.clear()


@pytest.fixture(autouse=True)
def _own_curiosity_queue(monkeypatch, tmp_path):
    """No test writes to the machine's real curiosity queue (star/curiosity.py)."""
    monkeypatch.setenv("STAR_CURIOSITY_FILE", str(tmp_path / "curiosity-queue.jsonl"))


@pytest.fixture(autouse=True)
def _default_slot_pinning(monkeypatch):
    """The slot rules are tested as the app ships them, whatever the machine's environment says."""
    monkeypatch.delenv("STAR_SERVER_SLOT_PINNING", raising=False)


@pytest.fixture(autouse=True)
def _no_resource_planner(monkeypatch):
    """No test may talk to a real resource planner (star/planner_client.py reads $STAR_PLANNER_URL or
    ~/.star/planner_url). Tests of the planner hand in their own URL or client."""
    monkeypatch.setenv("STAR_PLANNER_URL", "off")
    monkeypatch.setenv("STAR_NS_PLANNER_URL", "off")


@pytest.fixture(autouse=True)
def _offline_slot_probe(monkeypatch):
    """Before a chat turn on STAR Server the app asks the server which slots are busy (issue 118).
    No test may reach a real address for that: by default the page answers "not here", which is the
    probe's no-change path. Tests of the probe install their own transport."""
    import httpx
    import star.providers as providers

    def clear():
        providers._BUSY_SLOTS.clear()
        providers._NO_SLOTS_PAGE.clear()
        providers._OWN_WARMS.clear()
    clear()
    monkeypatch.delenv("STAR_SERVER_SLOT_PROBE", raising=False)
    monkeypatch.setattr(providers, "_SLOT_PROBE_TRANSPORT", httpx.MockTransport(lambda request: httpx.Response(404)))
    yield
    clear()


@pytest.fixture(autouse=True)
def pc_clock_is_daytime(monkeypatch):
    """"Automatically turn on at night" (star/gpu_helper.py) must not make a test depend on the hour it runs at."""
    from star import gpu_helper
    monkeypatch.setattr(gpu_helper, "local_hour", lambda: 14)


@pytest.fixture(autouse=True)
def _no_mesh_router(monkeypatch):
    """No test may send a chat to the real mesh router (star/general_mode.py's GPU lane reads STAR_MESH_URL or
    ~/.star/mesh_url). Tests of the lane set their own address and fakes."""
    monkeypatch.setenv("STAR_MESH_URL", "off")
