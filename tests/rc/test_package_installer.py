import hashlib
import io
import json
import stat
import threading
import zipfile

import pytest

from launcher.rc import package
from launcher.rc.errors import RcError
from launcher.rc.events import EventBus, TaskManager
from launcher.rc.installer import ToolsInstaller
from launcher.rc.package import FolderSource, UrlSource, parse_manifest, unpack, verify_dir
from launcher.rc.paths import TOOLS_EXE

from conftest import manifest_for

noop = lambda f, d: None  # noqa: E731


# -- manifest and unpack ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["../x", "/abs", "a\\b", "C:/x", "a/../b", "a//b", "", "a/./b", "x\x00y"])
def test_manifest_rejects_unsafe_paths(name):
    m = manifest_for({"ok.txt": b"1"})
    m["files"][0]["path"] = name
    with pytest.raises(RcError) as e:
        parse_manifest(json.dumps(m))
    assert e.value.code == "package_invalid"


def test_manifest_rejects_wrong_product_duplicates_and_garbage():
    m = manifest_for({"a": b"1"})
    for bad in ({**m, "product": "Other"}, {**m, "schemaVersion": 2}, {**m, "files": []},
                {**m, "files": m["files"] * 2}, "not json", "[]"):
        with pytest.raises(RcError):
            parse_manifest(json.dumps(bad) if isinstance(bad, dict) else bad)


def _zip(tmp, members: dict, manifest_files: dict | None = None, symlink: str | None = None):
    path = tmp / "p.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for n, d in members.items():
            zf.writestr(n, d)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "target")
        zf.writestr("build-manifest.json", json.dumps(manifest_for(manifest_files if manifest_files is not None else members)))
    return path


def test_unpack_checks_every_file(tmp_path):
    z = _zip(tmp_path, {"a.txt": b"hello", "d/b.bin": b"\x00\x01"})
    out = tmp_path / "out"
    m = unpack(z, out, noop)
    assert (out / "a.txt").read_bytes() == b"hello" and (out / "d" / "b.bin").read_bytes() == b"\x00\x01"
    assert (out / "build-manifest.json").is_file() and len(m.files) == 2


@pytest.mark.parametrize("case", ["extra", "missing", "hash", "link", "slip"])
def test_unpack_refuses_bad_packages(tmp_path, case):
    files = {"a.txt": b"hello"}
    if case == "extra":
        z = _zip(tmp_path, {**files, "evil.dll": b"x"}, manifest_files=files)
    elif case == "missing":
        z = _zip(tmp_path, {}, manifest_files=files)
    elif case == "hash":
        z = _zip(tmp_path, {"a.txt": b"HELLO"}, manifest_files=files)
    elif case == "link":
        z = _zip(tmp_path, files, symlink="ln")
    else:
        z = _zip(tmp_path, {"../escape.txt": b"x"}, manifest_files={"../escape.txt": b"x"} if False else files)
    out = tmp_path / "out"
    with pytest.raises(RcError) as e:
        unpack(z, out, noop)
    assert e.value.code == "package_invalid"
    assert not (tmp_path / "escape.txt").exists()


def test_unpack_refuses_a_non_zip(tmp_path):
    bad = tmp_path / "x.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(RcError) as e:
        unpack(bad, tmp_path / "o", noop)
    assert e.value.code == "package_invalid"


def test_verify_dir_reports_missing_and_changed(tmp_path):
    files = {"a.txt": b"hello", "b.txt": b"world", "c.txt": b"!"}
    m = parse_manifest(json.dumps(manifest_for(files)))
    for n, d in files.items():
        (tmp_path / n).write_bytes(d)
    assert verify_dir(tmp_path, m, noop).ok
    (tmp_path / "a.txt").write_bytes(b"HELLO")  # same size, different content
    (tmp_path / "b.txt").unlink()
    (tmp_path / "c.txt").write_bytes(b"longer")
    rep = verify_dir(tmp_path, m, noop)
    assert not rep.ok and rep.missing == ["b.txt"] and sorted(rep.changed) == ["a.txt", "c.txt"]


# -- sources ----------------------------------------------------------------------------------------------------------
def test_folder_source_picks_the_highest_version_and_skips_missing_zips(world):
    world.make_package("0.2")
    world.make_package("0.10")
    (world.packages / "SHA256SUMS.txt").write_text(
        (world.packages / "SHA256SUMS.txt").read_text() + "f" * 64 + "  Metallic-RC-0.99-tools-win-x64.zip\n"
        + "e" * 64 + "  Metallic-RC-0.2-tools-linux-x64.tar.gz\n")
    rel = FolderSource(world.packages).latest()
    assert rel.version == "0.10" and rel.size > 0 and rel.kind == "folder"


def test_folder_source_without_sums_is_no_source(tmp_path):
    with pytest.raises(RcError) as e:
        FolderSource(tmp_path).latest()
    assert e.value.code == "no_source"


class FakeResponse(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_url_source_reads_release_info_and_downloads(tmp_path):
    payload = b"zipbytes" * 1000
    info = {"version": "0.3", "url": "pkg/Metallic-RC-0.3-tools-win-x64.zip", "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}

    def opener(url, timeout):
        if url.endswith("latest.json"):
            return FakeResponse(json.dumps(info).encode())
        assert url == "https://forge.example/rc/pkg/Metallic-RC-0.3-tools-win-x64.zip"
        return FakeResponse(payload, {"Content-Length": str(len(payload))})
    src = UrlSource("https://forge.example/rc/latest.json", opener)
    rel = src.latest()
    seen = []
    got = src.fetch(rel, tmp_path / "dl.zip", lambda f, d: seen.append(f))
    assert got.read_bytes() == payload and seen[-1] == 1.0 and not (tmp_path / "dl.zip.part").exists()


@pytest.mark.parametrize("url", ["ftp://x/y", "file:///c:/x", "javascript:1", "/relative"])
def test_url_source_only_http(url):
    with pytest.raises(RcError):
        UrlSource(url)


def test_url_source_bad_release_info():
    src = UrlSource("http://lan.example/latest.json", lambda u, t: FakeResponse(b'{"version":"1","url":"file:///x","sha256":"zz"}'))
    with pytest.raises(RcError) as e:
        src.latest()
    assert e.value.code == "download_failed"


# -- installer --------------------------------------------------------------------------------------------------------
def inst_and_run(world, **kw):
    world.legacy = False  # a PC with no RC tools at all, unless the test adds the older build itself
    mod = world.module(**kw)
    return mod, mod.installer


def run_install(mod, inst, **kw):
    snap = mod.tasks.start("tools", "t", [("check", "c"), ("download", "d"), ("verify", "v"), ("unpack", "u"), ("switch", "s")],
                           lambda rep: inst.install(mod._source(), rep, **kw))
    return mod.tasks.wait(snap["id"])


def test_fresh_install_then_idempotent_then_update_keeps_previous(world):
    world.make_package("0.2")
    mod, inst = inst_and_run(world)
    assert inst.status()["installed"] is False and inst.exe() is None
    done = run_install(mod, inst)
    assert done["state"] == "done" and done["result"] == {"version": "0.2", "changed": True}
    st = inst.status()
    assert st["kind"] == "managed" and st["version"] == "0.2" and inst.exe().is_file()
    again = run_install(mod, inst)
    assert again["result"]["changed"] is False
    world.make_package("0.3")
    assert mod.call("tools.check_update")["updateAvailable"] is True
    assert run_install(mod, inst)["result"]["version"] == "0.3"
    st = inst.status()
    assert st["version"] == "0.3" and st["previous"] == "0.2"
    assert mod.call("tools.check_update")["updateAvailable"] is False
    assert inst.rollback()["version"] == "0.2" and inst.status()["version"] == "0.2" and inst.status()["previous"] == "0.3"


def test_hash_mismatch_installs_nothing_and_leaves_the_old_version(world):
    world.make_package("0.2")
    mod, inst = inst_and_run(world)
    run_install(mod, inst)
    world.make_package("0.3", bad_hash=True)
    done = run_install(mod, inst)
    assert done["state"] == "failed" and done["error"]["code"] == "hash_mismatch"
    assert inst.status()["version"] == "0.2"
    assert not list((world.paths.tools_dir / "versions").glob("*.partial"))
    assert not (world.paths.cache_dir / "Metallic-RC-0.3-tools-win-x64.zip").exists()  # the rejected package is thrown away


def test_invalid_package_is_refused_before_any_switch(world):
    world.make_package("0.2")
    mod, inst = inst_and_run(world)
    run_install(mod, inst)
    zpath = world.make_package("0.3")
    with zipfile.ZipFile(zpath, "a") as zf:
        zf.writestr("unlisted.dll", b"x")
    sums = (world.packages / "SHA256SUMS.txt")
    sums.write_text("\n".join(l for l in sums.read_text().splitlines() if "0.3" not in l) + f"\n{hashlib.sha256(zpath.read_bytes()).hexdigest()}  {zpath.name}\n")
    done = run_install(mod, inst)
    assert done["error"]["code"] == "package_invalid" and inst.status()["version"] == "0.2"


def test_smoke_failure_keeps_old_version(world):
    world.make_package("0.2")
    mod, inst = inst_and_run(world)
    run_install(mod, inst)
    world.make_package("0.3")

    def broken(exe):
        raise RcError("tools_corrupt", detail="does not start")
    inst._smoke = broken
    done = run_install(mod, inst)
    assert done["error"]["code"] == "tools_corrupt" and inst.status()["version"] == "0.2"
    assert not (world.paths.tools_dir / "versions" / "0.3").exists()


def test_cancel_during_install_leaves_old_version(world):
    world.make_package("0.2")
    mod, inst = inst_and_run(world)
    run_install(mod, inst)
    world.make_package("0.3")
    mod2 = world.module(spawn=None)  # real thread so we can cancel
    mod2.settings = dict(mod.settings)
    gate = threading.Event()
    real_unpack = package.unpack

    def slow_unpack(zip_path, dest, report, cancelled=None):
        gate.set()
        threading.Event().wait(0.3)
        report(0.5, "x")  # raises Cancelled via the reporter
        return real_unpack(zip_path, dest, report, cancelled)
    package.unpack = slow_unpack
    try:
        snap = mod2.tasks.start("tools", "t", [("check", "c"), ("download", "d"), ("verify", "v"), ("unpack", "u"), ("switch", "s")],
                                lambda rep: mod2.installer.install(mod2._source(), rep))
        assert gate.wait(5)
        mod2.tasks.cancel(snap["id"])
        done = mod2.tasks.wait(snap["id"])
    finally:
        package.unpack = real_unpack
    assert done["state"] == "cancelled" and mod2.installer.status()["version"] == "0.2"
    assert not list((world.paths.tools_dir / "versions").glob("*.partial"))


def test_verify_and_repair_a_damaged_install(world):
    world.make_package("0.2")
    mod, inst = inst_and_run(world)
    run_install(mod, inst)
    folder = inst.exe().parent
    ok = mod.tasks.wait(mod.call("tools.verify")["task"]["id"])
    assert ok["result"]["ok"] is True and ok["result"]["checked"] == 3
    (folder / "lib" / "core.dll").write_bytes(b"tampered")
    (folder / "readme.txt").unlink()
    bad = mod.tasks.wait(mod.call("tools.verify")["task"]["id"])
    assert bad["result"]["ok"] is False and bad["result"]["changed"] == ["lib/core.dll"] and bad["result"]["missing"] == ["readme.txt"]
    fixed = mod.tasks.wait(mod.call("tools.repair")["task"]["id"])
    assert fixed["state"] == "done" and fixed["result"]["repaired"] is True and fixed["result"]["problems"] == 2
    assert (inst.exe().parent / "lib" / "core.dll").read_bytes() == b"core 0.2"
    clean = mod.tasks.wait(mod.call("tools.repair")["task"]["id"])
    assert clean["result"]["repaired"] is False


def test_repair_when_the_exe_is_gone_reinstalls(world):
    world.make_package("0.2")
    mod, inst = inst_and_run(world)
    run_install(mod, inst)
    inst.exe().unlink()
    assert inst.status()["installed"] is False  # no exe: not treated as installed
    done = mod.tasks.wait(mod.call("tools.repair")["task"]["id"])
    assert done["state"] == "done" and inst.exe() and inst.exe().is_file()


def test_adopted_legacy_tools_are_used_in_place_and_verified_but_never_changed(world):
    world.legacy = False
    world.install_legacy_tools()
    mod, inst = inst_and_run(world)
    st = inst.status()
    assert st["kind"] == "adopted" and st["installed"] and str(inst.exe()) == str(world.paths.legacy_tools_exe)
    ok = mod.tasks.wait(mod.call("tools.verify")["task"]["id"])
    assert ok["result"]["ok"] is True and ok["result"]["kind"] == "adopted"
    world.make_package("0.2")
    assert mod.call("tools.check_update")["updateAvailable"] is True  # a managed copy is offered
    before = world.paths.legacy_tools_exe.read_bytes()
    run_install(mod, inst)
    assert inst.status()["kind"] == "managed" and world.paths.legacy_tools_exe.read_bytes() == before


def test_version_names_cannot_escape_the_tools_folder(world):
    _, inst = inst_and_run(world)
    for bad in ("..", "../x", "a/b", "a\\b", "C:x", ""):
        with pytest.raises(RcError):
            inst.version_dir(bad)


def test_no_source_is_a_plain_error(world, tmp_path):
    mod = world.module()
    mod.settings["source"] = {}
    # legacy packages dir does not exist in the fake PC, so there is nowhere to look
    with pytest.raises(RcError) as e:
        mod.call("tools.check_update")
    assert e.value.code == "no_source"
