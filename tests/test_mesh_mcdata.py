"""Minecraft checks driven by the game's own data (server/mesh/mcdata): a tiny hand-made index in the build format
(no Mojang data in the repo), the Brigadier walk (literals, redirects, `run` back to the root), argument grammars,
version selection, pack files, the facts block, the verifier integration and the router hook."""
from __future__ import annotations

import asyncio
import gzip
import http.client
import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from mesh.mcdata import commands, extract, facts, packs, snbt  # noqa: E402
from mesh.mcdata.index import McIndex  # noqa: E402
from mesh.verify import core, service  # noqa: E402
from mesh.verify.apidump import ApiIndex  # noqa: E402

KEY = "test-key-mc"


def lit(children=None, x=False, r=None):
    n = {"t": "l"}
    if x:
        n["x"] = 1
    if children:
        n["c"] = children
    if r is not None:
        n["r"] = r
    return n


def arg(parser, children=None, x=False, props=None, r=None):
    n = {"t": "a", "p": parser}
    if props:
        n["o"] = props
    if x:
        n["x"] = 1
    if children:
        n["c"] = children
    if r is not None:
        n["r"] = r
    return n


def tree(gamerules, attribute_reg="attribute"):
    players = {"type": "players", "amount": "multiple"}
    return {"t": "r", "c": {
        "give": lit({"targets": arg("minecraft:entity", {"item": arg("minecraft:item_stack", {
            "count": arg("brigadier:integer", x=True, props={"min": 1})}, x=True)}, props=players)}),
        "kill": lit({"targets": arg("minecraft:entity", x=True, props={"type": "entities", "amount": "multiple"})}),
        "execute": lit({"as": lit({"targets": arg("minecraft:entity", props={"type": "entities", "amount":
                                                                             "multiple"}, r=["execute"])}),
                        "run": lit()}),
        "gamerule": lit({g: lit({"value": arg("brigadier:bool", x=True)}, x=True) for g in gamerules}),
        "tellraw": lit({"targets": arg("minecraft:entity", {"message": arg("minecraft:component", x=True)},
                                       props=players)}),
        "particle": lit({"name": arg("minecraft:particle", {"pos": arg("minecraft:vec3", x=True)}, x=True)}),
        "setblock": lit({"pos": arg("minecraft:block_pos", {"block": arg("minecraft:block_state", x=True)})}),
        "attribute": lit({"target": arg("minecraft:entity", {"attribute": arg(
            "minecraft:resource", {"base": lit({"set": lit({"value": arg("brigadier:double", x=True)})})},
            props={"registry": "minecraft:" + attribute_reg})}, props={"type": "entities", "amount": "single"})}),
    }}


def version(ver, gamerules, attrs, data_fmt, res_fmt, datapack=True, items_folder=False):
    return {
        "version": ver, "sha1": "x", "pack": {"data": [data_fmt, 0], "resource": [res_fmt, 0]},
        "commands": tree(gamerules),
        "registries": {"minecraft:item": ["minecraft:diamond_pickaxe", "minecraft:stick", "minecraft:diamond",
                                          "minecraft:netherite_ingot"],
                       "minecraft:data_component_type": ["minecraft:custom_name", "minecraft:enchantments",
                                                         "minecraft:lore"],
                       "minecraft:entity_type": ["minecraft:zombie", "minecraft:player"],
                       "minecraft:attribute": ["minecraft:" + a for a in attrs],
                       "minecraft:particle_type": ["minecraft:dust", "minecraft:flame"],
                       "minecraft:recipe_serializer": ["minecraft:crafting_shaped"]},
        "blocks": {"minecraft:oak_sign": {"rotation": [str(i) for i in range(16)], "waterlogged": ["true", "false"]},
                   "minecraft:stone": {}},
        "data": {"enchantment": ["efficiency", "unbreaking"], "tags/block": ["coal_ores"],
                 "loot_table": ["entities/zombie"]},
        "datapack": {"registries": {"minecraft:recipe": {"elements": True, "tags": False},
                                    "minecraft:loot_table": {"elements": True, "tags": False},
                                    "minecraft:block": {"elements": False, "tags": True}},
                     "others": {"function": {"elements": True, "tags": True}}} if datapack else {},
        "assets": {"models": ["block/stone", "item/stick", "item/generated"], "textures": ["block/stone", "item/stick"],
                   **({"items": ["stick"]} if items_folder else {})},
        "sound_events": ["entity.creeper.primed"], "sound_files": ["mob/creeper/say1"], "lang": [],
    }


@pytest.fixture(scope="module")
def idx(tmp_path_factory):
    d = tmp_path_factory.mktemp("mc")
    vers = [version("1.21.1", ["doFireTick", "mobGriefing"], ["generic.scale"], 48, 34, datapack=False),
            version("1.21.4", ["doFireTick", "mobGriefing"], ["scale"], 61, 46, items_folder=True),
            version("1.21.11", ["fire_spread_radius_around_player", "mob_griefing"], ["scale"], 94, 75,
                    items_folder=True)]
    for v in vers:
        (d / f"mc-{v['version']}.json.gz").write_bytes(gzip.compress(json.dumps(v).encode()))
    (d / "mc-examples-1.21.11.json.gz").write_bytes(gzip.compress(json.dumps({
        "data/minecraft/loot_table/entities/zombie.json": '{"type":"minecraft:entity","pools":[]}',
        "lang/en_us.json": json.dumps({"subtitles.entity.creeper.primed": "Creeper hisses"})}).encode()))
    return McIndex.load(d)


def errs(code, idx, prose="", **kw):
    return [p for p in commands.check_commands(code, idx, prose, **kw) if p["severity"] == "error"]


def test_index_loads_versions_newest_first_and_shares_sets(idx):
    assert [v.version for v in idx.java121()] == ["1.21.11", "1.21.4", "1.21.1"]
    a, b = idx.get("1.21.4"), idx.get("1.21.11")
    assert a.registries["item"] is b.registries["item"]           # identical sets are shared
    assert a.has("item", "minecraft:stick") and a.has("item", "ruby") is False and a.has("item", "mypack:x") is None


def test_valid_commands_and_redirects(idx):
    for c in ("give @p diamond_pickaxe 1", "execute as @a run kill @e[type=zombie,distance=..10]",
              "execute as @a as @s run give @s stick", "setblock ~ ~1 ~ oak_sign[rotation=8]",
              "give <player> stick"):                               # a placeholder the reader fills in
        assert errs(c, idx) == [], c


def test_unknown_command_literal_and_ids(idx):
    assert "unknown command '/gvie'" in errs("gvie @p stick", idx)[0]["message"]
    assert errs("give @p ruby", idx)[0]["name"] == "ruby"
    e = errs("setblock ~ ~ ~ oak_sign[facing=north]", idx)[0]
    assert "no block state 'facing'" in e["message"] and "rotation" in e["message"]
    assert "lowercase" in errs("give @p Diamond", idx)[0]["message"]


def test_selector_rules_from_the_argument_properties(idx):
    assert "can select many" in errs("attribute @e minecraft:scale base set 2", idx, "1.21.4")[0]["message"]
    assert "only accepts players" in errs("give @e stick", idx)[0]["message"]
    assert errs("give @e[type=player] stick", idx) == []
    assert "removed in 1.13" in errs("kill @e[r=5]", idx)[0]["message"]
    assert "unknown entity type" in errs("kill @e[type=zombi]", idx)[0]["message"]


def test_item_components_and_nbt(idx):
    assert errs('give @s diamond_pickaxe[custom_name={text:"A"},enchantments={efficiency:5}]', idx, "1.21.11") == []
    e = errs('give @s diamond_pickaxe[enchantments={levels:{efficiency:5}}]', idx, "1.21.11")[0]
    assert "plain map" in e["message"] and e["suggestion"] == "enchantments={efficiency:5}"
    assert errs('give @s diamond_pickaxe[enchantments={levels:{efficiency:5}}]', idx, "1.21.4") == []
    assert "unknown item component" in errs("give @s stick[custom_model=1]", idx)[0]["message"]
    assert "replaced by item components" in errs("give @s stick{display:{}}", idx)[0]["message"]
    assert "unknown enchantment" in errs("give @s stick[enchantments={sharp:5}]", idx, "1.21.11")[0]["message"]


def test_version_is_chosen_per_block_and_named_versions_win(idx):
    assert errs("gamerule doFireTick false", idx) == []              # valid in some 1.21.x
    e = errs("gamerule doFireTick false", idx, "Java 1.21.11")[0]
    assert "1.21.11" in e["message"] and "valid in 1.21.1-1.21.4" in e["message"]
    assert "fire_spread_radius_around_player" in (e["suggestion"] or "")
    # a block that mixes versions: judged in the version where most lines work
    block = "gamerule mobGriefing false\ngamerule doFireTick false\ngamerule mob_griefing false"
    probs = commands.check_commands(block, idx)
    assert [p["kind"] for p in probs] == ["mc_version"] and probs[0]["line"] == 3
    assert errs("attribute @s minecraft:generic.scale base set 2", idx, "1.21.4")[0]["suggestion"] == "minecraft:scale"


def test_text_components_by_version(idx):
    old = 'tellraw @a {"text":"x","clickEvent":{"action":"run_command","value":"/trigger menu"}}'
    new = 'tellraw @a {text:"x",click_event:{action:"run_command",command:"/trigger menu"}}'
    assert errs(old, idx, "1.21.4") == [] and errs(new, idx, "1.21.11") == []
    assert "ignored since 1.21.5" in errs(old, idx, "1.21.11")[0]["message"]
    assert "needs 'command'" in errs('tellraw @a {text:"x",click_event:{action:"run_command",value:"/a"}}', idx,
                                     "1.21.11")[0]["message"]


def test_particle_options_function_slash_and_macros(idx):
    assert "needs its options" in errs("particle dust ~ ~ ~", idx)[0]["message"]
    assert errs("particle dust{color:[1.0,0.0,0.0],scale:1.0} ~ ~ ~", idx) == []
    assert errs("/give @s stick", idx, in_function=True)[0]["kind"] == "mc_function"
    assert errs("/give @s stick", idx, in_function=True, slash="warning") == []
    assert errs("$give @s $(item)\n# comment", idx, in_function=True) == []
    assert errs("give @s \\\n  stick", idx) == []                    # 1.20.2+ line continuation


def test_snbt_reader():
    assert snbt.parse_all('{a:1b,b:[I;1,2],"c d":\'x\',e:true,f:[{}],}') == {
        "a": 1.0, "b": [1.0, 2.0], "c d": "x", "e": True, "f": [{}]}
    with pytest.raises(snbt.SnbtError):
        snbt.parse_all("{a:1")


def test_pack_paths_folders_and_mcmeta(idx):
    p = packs.check_file("data/mypack/functions/load.mcfunction", "kill @e", idx, "1.21.4")
    assert p[0]["kind"] == "mc_datapack" and p[0]["suggestion"] == "data/mypack/function/"
    assert packs.check_file("data/mypack/function/load.mcfunction", "kill @e", idx, "1.21.4") == []
    p = packs.check_file("data/mypack/painting/x.json", "{}", idx, "1.21.4")
    assert "does not read data/mypack/painting/" in p[0]["message"]
    meta = '{"pack":{"pack_format":94,"description":"x"}}'
    assert "min_format" in packs.check_file("pack.mcmeta", meta, idx, "data pack 1.21.11")[0]["message"]
    ok = '{"pack":{"description":"x","min_format":94,"max_format":94}}'
    assert packs.check_file("pack.mcmeta", ok, idx, "data pack 1.21.11") == []
    assert "needs \"pack_format\"" in packs.check_file("pack.mcmeta", ok, idx, "data pack 1.21.4")[0]["message"]
    multi = '{"pack":{"description":"x","pack_format":48,"supported_formats":[48,94],"min_format":48,"max_format":94}}'
    assert packs.check_file("pack.mcmeta", multi, idx, "data pack 1.21") == []
    w = packs.check_file("pack.mcmeta", '{"pack":{"pack_format":48,"description":"x"}}', idx, "data pack 1.21.4")
    assert w[0]["severity"] == "warning" and w[0]["suggestion"] == "61"


def test_pack_json_ids_recipes_and_item_models(idx):
    bad = '{"type":"minecraft:crafting_shaped","key":{"D":{"item":"minecraft:diamond"}},"result":{"id":"minecraft:rubyy"}}'
    probs = packs.check_file("data/mypack/recipe/x.json", bad, idx, "1.21.4")
    msgs = " | ".join(p["message"] for p in probs)
    assert "'minecraft:rubyy' does not exist" in msgs and "since 1.21.2 an ingredient" in msgs
    assert packs.check_file("data/mypack/recipe/x.json", "// a comment\n{}", idx, "1.21.4")[0]["kind"] == "syntax"
    old = '{"parent":"minecraft:item/generated","overrides":[{"predicate":{"custom_model_data":1},"model":"a:b"}]}'
    assert "removed in 1.21.4" in packs.check_file("assets/minecraft/models/item/stick.json", old, idx,
                                                   "1.21.4")[0]["message"]
    defn = '{"model":{"type":"minecraft:range_dispatch","property":"minecraft:custom_model_data","entries":[{"model":{"type":"minecraft:model","model":"a:b"}}]}}'
    assert "threshold" in packs.check_file("assets/minecraft/items/stick.json", defn, idx, "1.21.4")[0]["message"]
    assert packs.check_file("assets/mypack/textures/blocks/a.png", "", idx)[0]["suggestion"] == \
        "assets/mypack/textures/block/"


def test_extract_paths_trees_and_inline_commands():
    ans = ("Folder:\n```\nmypack/\n├── pack.mcmeta\n└── data/\n    └── mypack/\n        └── functions/\n```\n"
           "Put this in `data/mypack/recipe/a.json`:\n```json\n{}\n```\nThen run `/give @p stick 1` in chat.\n"
           "```mcfunction\n# data/mypack/function/load.mcfunction\nsay hi\n```\n")
    cmds, files, tree = extract.extract(ans)
    assert "data/mypack/functions/" in tree
    assert files[0]["path"] == "data/mypack/recipe/a.json" and files[1]["path"] == "data/mypack/function/load.mcfunction"
    assert (-1, 9, "give @p stick 1") in [(b, n, c) for b, n, c in cmds] or any(c == "give @p stick 1" for _, _, c in cmds)


def test_verifier_uses_the_game_data_and_the_question_version(idx):
    v = core.Verifier(ApiIndex({}), None, mc=idx)
    ans = "Use this:\n```mcfunction\ngamerule doFireTick false\n```\nAlso `/give @p rubyy 1`."
    rep = v.verify(ans)
    assert rep["blocks"][0]["ok"] and rep["problems"][0]["kind"] == "mc_inline"
    rep = v.verify(ans, None, "Minecraft Java 1.21.11: stop fire")
    assert not rep["blocks"][0]["ok"]
    ans = "In `data/mypack/recipe/x.json`:\n```json\n{\"type\":\"minecraft:crafting_shaped\",\"result\":{\"id\":\"minecraft:nope\"}}\n```"
    rep = v.verify(ans)
    assert rep["blocks"][0]["path"] == "data/mypack/recipe/x.json" and not rep["ok"]
    # without an index the old hand-written checks still run
    assert core.Verifier(ApiIndex({})).verify("```mcfunction\n/scoreboards x\n```")["ok"] is False


def test_fix_loop_only_renames_datapack_paths(idx):
    v = core.Verifier(ApiIndex({}), None, mc=idx)
    ans = "Put it in data/mypack/functions/a.mcfunction and run `/give @p rubyy`."
    out = v.fix(ans, lambda m: "```\nnothing\n```")
    assert "data/mypack/function/a.mcfunction" in out["answer"] and "`/give @p rubyy`" in out["answer"]


def test_facts_block(idx, tmp_path):
    f = facts.Facts(idx, None, tmp_path / "none.json")
    assert f.block("how do I make a door in roblox")["text"] == ""
    b = f.block("Minecraft Java 1.21.11: what command stops fire from spreading and mobs griefing?")
    assert b["version"] == "1.21.11" and "fire_spread_radius_around_player" in b["text"] and "mob_griefing" in b["text"]
    b = f.block("Minecraft 1.21.4 data pack: shaped recipe with a diamond pickaxe")
    assert '"pack_format": 61' in b["text"] and "data/<ns>/recipe/" in b["text"] and "diamond_pickaxe" in b["text"]
    b = f.block("Minecraft data pack: make zombies drop more loot")
    assert b["version"] == "1.21.11" and "min_format" in b["text"] and "no version was named" in b["text"]


@pytest.fixture()
def mc_server(idx, tmp_path):
    (tmp_path / "keys").write_text(KEY + "\n")
    (tmp_path / "api.json").write_text(json.dumps({"meta": {}, "classes": {}}))
    cfg = {**service.DEFAULTS, "port": 0, "index": str(tmp_path / "api.json"), "client_keys_file":
           str(tmp_path / "keys"), "mc_index": str(Path(list(idx.versions.values())[0].version and tmp_path)),
           "luau_analyze": None}
    cfg["mc_index"] = str(tmp_path / "mc")
    (tmp_path / "mc").mkdir()
    for v in ("1.21.4", "1.21.11"):
        (tmp_path / "mc" / f"mc-{v}.json.gz").write_bytes(gzip.compress(json.dumps(
            version(v, ["doFireTick"] if v == "1.21.4" else ["mob_griefing"], ["scale"], 61 if v == "1.21.4" else 94,
                    46)).encode()))
    srv = service.serve(cfg)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


def _call(port, path, body):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("POST", path, json.dumps(body).encode(), {"Content-Type": "application/json",
                                                           "Authorization": f"Bearer {KEY}"})
    r = conn.getresponse()
    data = json.loads(r.read())
    conn.close()
    return r.status, data


def test_service_facts_and_question_field(mc_server):
    st, out = _call(mc_server, "/mesh/mc/facts", {"question": "Minecraft 1.21.11 gamerule to stop mob griefing?"})
    assert st == 200 and out["version"] == "1.21.11" and "mob_griefing" in out["text"]
    st, out = _call(mc_server, "/mesh/verify", {"answer": "```mcfunction\ngamerule doFireTick false\n```",
                                                "question": "Minecraft Java 1.21.11"})
    assert st == 200 and out["ok"] is False


def test_router_puts_minecraft_facts_on_top(mc_server, tmp_path):
    from test_mesh_router import Fake, call, setup

    async def go():
        node = Fake("owner-pc", tok_s=30.0, words=("ok",))
        r, port, brain = await setup(tmp_path, [node], verify_url=f"http://127.0.0.1:{mc_server}", docs=False)
        q = "Minecraft Java 1.21.11: how do I stop mob griefing?"
        chat = {"model": "litha", "stream": True, "messages": [{"role": "system", "content": "You are Litha."},
                                                               {"role": "user", "content": q}]}
        st, headers, _ = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", chat)
        sent = node.requests[-1]["messages"]
        assert st == 200 and headers["X-Mesh-Mc"].startswith("1.21.11")
        assert sent[0] == chat["messages"][0] and sent[-1]["content"].startswith("Minecraft Java 1.21.11 facts")
        assert sent[-1]["content"].endswith("---\n" + q) and "mesh_mc" not in node.requests[-1]
        chat["messages"][-1]["content"] = "how do I make a door in roblox?"
        st, headers, _ = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", chat)
        assert "X-Mesh-Mc" not in headers
        chat["messages"][-1]["content"] = q
        st, headers, _ = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", {**chat, "mesh_mc": False})
        assert "X-Mesh-Mc" not in headers and node.requests[-1]["messages"][-1]["content"] == q
        r.cfg["verify_url"] = "http://127.0.0.1:9"
        st, headers, _ = await asyncio.to_thread(call, port, "POST", "/v1/chat/completions", chat)
        assert st == 200 and headers.get("X-Mesh-Mc") == "late"

    sys.path.insert(0, str(ROOT / "tests"))
    try:
        asyncio.run(asyncio.wait_for(go(), 30))
    finally:
        sys.path.remove(str(ROOT / "tests"))
