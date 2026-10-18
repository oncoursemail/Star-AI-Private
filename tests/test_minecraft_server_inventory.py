"""Offline Minecraft server inventory tests: safety, metadata and no secret disclosure."""
import json
import zipfile

import pytest

from star.minecraft_server_inventory import inspect
from star.workspace import Workspace


def _write_jar(path, filename, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(filename, text)


def test_properties_are_allowlisted_and_secrets_not_returned(tmp_path):
    server = tmp_path / "server"
    server.mkdir()
    (server / "server.properties").write_text(
        "online-mode=false\nview-distance=10\nsimulation-distance=6\nmax-players=100\n"
        "enable-rcon=true\nrcon.password=DO_NOT_LEAK\n"
        "resource-pack=https://user:pass@private.test/mypack.zip\n"
        "server-ip=10.1.1.1\nmotd=Private MOTD\n")
    ws = Workspace(tmp_path)
    r = inspect(ws, "server")
    assert r["recognised"]
    assert r["safe_server_properties"]["view-distance"] == 10
    assert r["safe_server_properties"]["resource-pack-configured"]
    exported = json.dumps(r)
    assert "DO_NOT_LEAK" not in exported
    assert "private.test" not in exported
    assert "10.1.1.1" not in exported
    assert "Private MOTD" not in exported
    assert {m["code"] for m in r["issues"]} >= {"rcon-review", "authentication-review"}
    assert r["observed_running_state"] is False and r["minecraft_version"] is None


def test_inventory_paper_nexo_and_folia_metadata(tmp_path):
    server = tmp_path / "server"
    plugins = server / "plugins"
    plugins.mkdir(parents=True)
    _write_jar(plugins / "Nexo.jar", "plugin.yml",
               "name: Nexo\nversion: '1.28.0'\napi-version: '26.3'\nfolia-supported: true\n")
    r = Workspace(tmp_path).call("workspace_minecraft_inspect", {"path": "server"})
    assert r["family_hint"] == "bukkit-paper-family"
    assert "nexo" in r["pack_managers"]
    jar = r["jars"][0]
    assert jar["name"] == "Nexo" and jar["version"] == "1.28.0"
    assert jar["declares_folia_support"] is True
    assert jar["load_tested"] is False and r["jar_executed"] is False


def test_detects_pack_ownership_conflict(tmp_path):
    p = tmp_path / "p" / "plugins"
    _write_jar(p / "a.jar", "plugin.yml", "name: Nexo\nversion: 1\n")
    _write_jar(p / "b.jar", "paper-plugin.yml", "name: Oraxen\nversion: 2\n")
    r = inspect(Workspace(tmp_path), "p")
    assert "nexo" in r["pack_managers"] and "oraxen" in r["pack_managers"]
    assert "multiple-pack-managers" in {m["code"] for m in r["issues"]}


def test_fabric_and_velocity_hints(tmp_path):
    p = tmp_path / "fabric"
    jar = p / "mods" / "demo.jar"
    _write_jar(jar, "fabric.mod.json", '{"id":"metallic","name":"Metallic","version":"0.1.0"}')
    r = inspect(Workspace(tmp_path), "fabric")
    assert r["family_hint"] == "fabric-neoforge-family"
    assert r["jars"][0]["kind"] == "fabric"
    assert r["jars"][0]["id"] == "metallic"
    proxy = tmp_path / "proxy"
    proxy.mkdir()
    (proxy / "velocity.toml").write_text('forwarding-secret = "DO_NOT_DISCLOSE"')
    r = inspect(Workspace(tmp_path), "proxy")
    assert r["family_hint"] == "velocity-proxy"
    assert "DO_NOT_DISCLOSE" not in json.dumps(r)


def test_symlink_jar_outside_scanned_server_not_read(tmp_path):
    outside = tmp_path / "outside.jar"
    _write_jar(outside, "plugin.yml", "name: SECRET-PLUGIN\n")
    plugins = tmp_path / "server" / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "link.jar").symlink_to(outside)
    r = inspect(Workspace(tmp_path), "server")
    assert r["jars"][0]["error"] == "JAR symlink or escaped server folder; not inspected"
    assert "SECRET-PLUGIN" not in json.dumps(r)


def test_plugin_metadata_zip_invalid_handled(tmp_path):
    p = tmp_path / "server" / "plugins"
    p.mkdir(parents=True)
    (p / "broken.jar").write_text("not a zip")
    r = inspect(Workspace(tmp_path), "server")
    assert "error" in r["jars"][0]


def test_reject_non_directory_and_escape(tmp_path):
    (tmp_path / "single.txt").write_text("abc")
    ws = Workspace(tmp_path)
    with pytest.raises(ValueError):
        inspect(ws, "single.txt")
    (tmp_path.parent / "outside-folder").mkdir(exist_ok=True)
    with pytest.raises(PermissionError):
        inspect(ws, "../outside-folder")
