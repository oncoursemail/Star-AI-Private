"""Minecraft plugin/mod checks of the verifier (server/mesh/verify/javamc.py); the javac service is faked."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from mesh.verify import core, javamc  # noqa: E402
from mesh.verify.apidump import ApiIndex  # noqa: E402

# `server/` holds a `discord` folder: leaving it on sys.path would shadow the discord package for tests collected later
sys.path.remove(str(Path(__file__).resolve().parents[1] / "server"))


class FakeJvm:
    """Compiles nothing: reports `sendActionbar` / `sendMesage` on Player and Vault as a missing package, the way
    CompileServer does."""

    def __init__(self):
        self.calls = []

    def compile(self, target, files):
        self.calls.append((target, dict(files)))
        diags = []
        for path, src in files.items():
            for n, line in enumerate(src.splitlines(), 1):
                for bad, good in (("sendActionbar", "sendActionBar"), ("sendMesage", "sendMessage")):
                    if bad + "(" in line:
                        diags.append({"kind": "ERROR", "code": "compiler.err.cant.resolve.location.args",
                                      "file": path, "line": n, "col": 1, "api": True,
                                      "message": f"cannot find symbol\n  symbol:   method {bad}(String)\n"
                                                 "  location: interface org.bukkit.entity.Player",
                                      "symbol": bad, "location": "org.bukkit.entity.Player",
                                      "candidates": [good, "sendRawMessage"]})
                if "import net.milkbowl" in line:
                    diags.append({"kind": "ERROR", "code": "compiler.err.doesnt.exist", "file": path, "line": n,
                                  "col": 1, "message": "package net.milkbowl.vault.economy does not exist"})
                if re.search(r"\bEconomy\b", line) and "import" not in line:
                    diags.append({"kind": "ERROR", "code": "compiler.err.cant.resolve.location", "file": path,
                                  "line": n, "col": 1, "symbol": "Economy", "location": "com.ex.Heal",
                                  "message": "cannot find symbol\n  symbol:   class Economy\n  location: class com.ex.Heal"})
                if "undefinedVar" in line:
                    diags.append({"kind": "ERROR", "code": "compiler.err.cant.resolve.location", "file": path,
                                  "line": n, "col": 1, "symbol": "undefinedVar", "location": path[:-5],
                                  "message": "cannot find symbol\n  symbol:   variable undefinedVar\n  location: class X"})
        return {"ok": not any(d["kind"] == "ERROR" for d in diags), "ms": 5, "diagnostics": diags}


V = core.Verifier(ApiIndex({"classes": {}, "enums": {}, "meta": {}}), None, FakeJvm())

PLUGIN = """package com.ex;

import org.bukkit.entity.Player;
import org.bukkit.plugin.java.JavaPlugin;

public class Heal extends JavaPlugin {
    @Override
    public void onEnable() {
        getCommand("heal").setExecutor((s, c, l, a) -> {
            ((Player) s).sendActionbar("healed");
            return true;
        });
        getCommand("feed").setExecutor((s, c, l, a) -> true);
    }
}
"""


def answer(java=PLUGIN, yml="name: Heal\nversion: 1.0\nmain: com.ex.Heal\napi-version: '1.21'\ncommands:\n  heal:\n"
                            "    description: heal\n  feed:\n    aliases: [eat]\n", ymlname="plugin.yml"):
    return f"Here:\n\n```java\n{java}```\n\n{ymlname}:\n\n```yaml\n{yml}```\n"


def problems(rep, k):
    return [p for p in rep["blocks"][k]["problems"] if p["severity"] != "info"]


def test_compile_error_mapped_with_real_name():
    rep = V.verify(answer())
    assert rep["java"]["target"] == "paper" and rep["java"]["compiled"]
    p = problems(rep, 0)
    assert len(p) == 1 and p[0]["name"] == "sendActionbar" and p[0]["suggestion"] == "sendActionBar"
    assert p[0]["line"] == 10 and p[0]["answer_line"] == rep["blocks"][0]["line"] + 9
    assert problems(rep, 1) == [] and rep["blocks"][1]["checked"]


def test_plugin_yml_checks():
    yml = "name: Heal\nversion: 1.0\nmain: com.ex.HealPlugin\napi-version: 1.21.x\ncommands:\n  heal:\n    usage: /heal\n"
    msgs = [p["message"] for p in problems(V.verify(answer(yml=yml)), 1)]
    assert any("main: com.ex.HealPlugin is not a class" in m and "com.ex.Heal" in m for m in msgs)
    assert any("api-version '1.21.x'" in m for m in msgs)
    assert any('getCommand("feed")' in m for m in msgs) and not any('getCommand("heal")' in m for m in msgs)
    tabbed = "name: Heal\nversion: 1\nmain: com.ex.Heal\ncommands:\n\theal:\n"
    assert any("tab" in p["message"] for p in problems(V.verify(answer(yml=tabbed)), 1))
    # an alias counts as a command
    yml2 = "name: Heal\nversion: 1\nmain: com.ex.Heal\napi-version: '1.21'\ncommands:\n  heal:\n  food:\n    aliases:\n      - feed\n"
    assert problems(V.verify(answer(yml=yml2)), 1) == []


def test_paper_plugin_yml_has_no_commands():
    yml = "name: Heal\nversion: 1.0\nmain: com.ex.Heal\napi-version: '1.21'\n"
    msgs = [p["message"] for p in problems(V.verify(answer(yml=yml, ymlname="paper-plugin.yml")), 1)]
    assert sum("always returns null with paper-plugin.yml" in m for m in msgs) == 2


def test_external_dependency_is_info_only():
    java = PLUGIN.replace("import org.bukkit.entity.Player;", "import org.bukkit.entity.Player;\n"
                          "import net.milkbowl.vault.economy.Economy;").replace(
        "public class Heal extends JavaPlugin {", "public class Heal extends JavaPlugin {\n    private Economy econ;")
    rep = V.verify(answer(java=java))
    infos = [p for p in rep["blocks"][0]["problems"] if p["kind"] == "dependency"]
    assert len(infos) == 1 and infos[0]["severity"] == "info"
    assert [p["name"] for p in problems(rep, 0)] == ["sendActionbar"]       # no Economy error


def test_fragment_only_api_facts():
    frag = "@EventHandler\npublic void onJoin(PlayerJoinEvent e) {\n    e.getPlayer().sendMesage(undefinedVar);\n}\n"
    rep = V.verify(answer() + "\nAlso:\n\n```java\n" + frag + "```\n")
    p = problems(rep, 2)
    assert [x["name"] for x in p] == ["sendMesage"] and p[0]["line"] == 3   # the unknown variable is context


def test_plain_java_not_checked():
    rep = V.verify("```java\npublic class A { void f() { undefinedVar(); } }\n```\n")
    assert rep["blocks"][0]["checked"] is False and "java" not in rep


def test_fabric_and_neoforge_descriptors():
    fab = ("```java\npackage com.ex;\nimport net.fabricmc.api.ModInitializer;\npublic class M implements ModInitializer"
           " { public void onInitialize() {} }\n```\n\n```json\n" + json.dumps(
               {"schemaVersion": 1, "id": "My Mod", "version": "1", "entrypoints": {"main": ["com.ex.Main"]}})
           + "\n```\n")
    rep = V.verify(fab)
    assert rep["java"]["target"] == "fabric"
    msgs = [p["message"] for p in problems(rep, 1)]
    assert any("mod id 'My Mod'" in m for m in msgs) and any("com.ex.Main is not a class" in m for m in msgs)
    nf = ('```java\npackage com.ex;\nimport net.neoforged.fml.common.Mod;\n@Mod(Gem.MODID)\npublic class Gem {\n'
          '    public static final String MODID = "gemcraft";\n}\n```\n\nMETA-INF/mods.toml:\n\n```toml\n'
          'modLoader="javafml"\nloaderVersion="[1,)"\n[[mods]]\nmodId="gems"\n```\n')
    rep = V.verify(nf)
    assert rep["java"]["target"] == "neoforge"
    msgs = [p["message"] for p in problems(rep, 1)]
    assert any("neoforge.mods.toml" in m for m in msgs) and any("does not match @Mod(\"gemcraft\")" in m for m in msgs)


def test_fix_loop_rechecks_in_context():
    calls = []

    def model(messages):
        calls.append(messages)
        code = re.search(r"```java\n(.*?)```", messages[1]["content"], re.S).group(1)
        return "```java\n" + code.replace("sendActionbar", "sendActionBar") + "```"

    out = V.fix(answer(), model)
    assert out["ok"] and "sendActionBar" in out["answer"] and out["after"]["errors"] == 0
    assert "real members of that class you may use" not in calls[0][1]["content"]  # exact suggestion given
    assert "use: sendActionBar" in calls[0][1]["content"]


def test_service_down_keeps_static_checks():
    v = core.Verifier(ApiIndex({"classes": {}, "enums": {}, "meta": {}}), None,
                      type("Down", (), {"compile": lambda self, t, f: None})())
    rep = v.verify(answer(yml="name: Heal\nversion: 1\nmain: com.ex.Nope\napi-version: '1.21'\ncommands:\n  heal:\n"))
    assert rep["java"]["compiled"] is False and problems(rep, 0) == []
    assert any("com.ex.Nope" in p["message"] for p in problems(rep, 1))


def test_platform_from_prose_when_imports_are_missing_or_invented():
    nf = ("For NeoForge 1.21 use this:\n\n```java\n@Mod(\"kit\")\npublic class Kit {\n    public Kit(IEventBus bus) {}\n}\n"
          "```\n")
    vl = ("A Velocity plugin:\n\n```java\nimport com.velocity.api.plugin.Plugin;\npublic class Hub implements Plugin {\n"
          "    public void onEnable() {}\n}\n```\n")
    assert javamc.detect_target(core.extract_blocks(nf)[0]["code"], nf) == "neoforge"
    assert javamc.detect_target(core.extract_blocks(vl)[0]["code"], vl) == "velocity"
    plain = "Java basics:\n\n```java\npublic class A { void f() {} }\n```\n"
    assert javamc.detect_target(core.extract_blocks(plain)[0]["code"], plain) is None
