"""Engine truth (server/mesh/engine + server/mesh/polyglot/engine.py): which questions get which engine's facts, that every
signature placeholder resolves from the generated data, the pure-Python parts of the container checks (Lua/LOVE rules,
Unreal structural rules, Unity diagnostics), and the verifier routing of Lua / LOVE blocks. No engines are needed here."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from mesh.engine import facts, facts_data  # noqa: E402
from mesh.polyglot import note  # noqa: E402
from mesh.verify import core  # noqa: E402
from mesh.verify.apidump import ApiIndex  # noqa: E402
sys.path.remove(str(ROOT / "server"))     # server/ holds a `discord` folder that would shadow the discord package

# the container-side module is loaded by path, like the runner does (no package, helpers injected)
_spec = importlib.util.spec_from_file_location("pg_engine", ROOT / "server/mesh/polyglot/engine.py")
engine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine)


def _problem(kind, message, line=None, severity="error", name=None, suggestion=None):
    return {"kind": kind, "severity": severity, "name": name, "message": message, "suggestion": suggestion, "line": line}


def _closest(name, names, n=1):
    import difflib
    hits = difflib.get_close_matches(name, list(names), n=n, cutoff=0.6)
    return " or ".join(hits) if hits else None


engine.init({"problem": _problem, "closest": _closest, "elsewhere": lambda n, c, x: False})


# ------------------------------------------------------------------------------------------------ facts routing
def test_family_routing():
    f = facts.family_of
    assert f("Write a Godot 4 GDScript player with coyote time") == "godot"
    assert f("Unity 6 C# projectile pool") == "unity"
    assert f("Unreal Engine 5 C++ actor component with UPROPERTY") == "unreal"
    assert f("Write a complete LÖVE 11 main.lua for a shooter") == "love"
    assert f("love2d how do I draw a circle") == "love"
    assert f("Write a plain Lua 5.4 program that reads numbers from stdin") == "lua"
    for q in ("I love making games with my friends", "Roblox Lua script for a door", "make a Luau module",
              "Minecraft ComputerCraft lua turtle program", "How do I bake bread?", ""):
        assert f(q) is None, q


def test_every_placeholder_resolves_and_the_note_fits():
    for fam, block in facts_data.FACTS.items():
        assert facts.expand(block["core"])                       # KeyError when a signature is missing from the data
        for rx, text in block["topics"]:
            re.compile(rx)
            facts.expand(text)
        for q in ("write a %s program" % fam, "unity godot unreal love lua everything: save load signal timer input ui "
                                              "physics replicate raycast animation audio navigation tilemap"):
            fam2, text, used = facts.facts_for(q if fam in q else q + " " + {"love": "LÖVE", "lua": "plain Lua", "unity": "Unity",
                                                                              "godot": "Godot", "unreal": "Unreal"}[fam])
            assert len(text) <= facts.MAX_CHARS + 400, (fam, len(text))


def test_topics_follow_the_question_and_old_versions_get_a_version_note():
    _, text, used = facts.facts_for("Godot 4: save the settings to a file and apply the audio volume")
    assert "ConfigFile" in text and "AudioServer.set_bus_volume_db" in text
    _, text, _ = facts.facts_for("Unity 6 C# NavMeshAgent patrol")
    assert "pathPending" in text and "FindFirstObjectByType" in text
    fam, text, used = facts.facts_for("Godot 3.5 KinematicBody2D movement")
    assert used == ["old"] and "KinematicBody2D" in text and "CharacterBody2D" not in text.split("Godot 3")[0]
    assert facts.facts_for("Unity 2021 LTS C# script for a door")[2] == ["old"]


def test_only_the_shipped_families_get_the_note_by_default():
    from mesh.router import DEFAULTS as router_defaults
    assert router_defaults["engine_facts_families"] == ["unity"]
    q = "Unity 6 pool script"
    assert facts.apply({"messages": [{"role": "user", "content": q}]}, router_defaults)["X-Mesh-Engine"].startswith("unity")
    for q in ("Godot 4 spawner script", "Unreal Engine 5 C++ actor", "LÖVE 11 shooter in main.lua", "plain Lua 5.4 program"):
        assert facts.apply({"messages": [{"role": "user", "content": q}]}, router_defaults) == {}


def test_grounding_and_notes_in_the_turn_do_not_decide_the_engine_or_version():
    ground = ("Reference answers (verified)\n\n[Q] Unity 2022 LTS door\n[A] In Unity 2022 use FindObjectOfType.\n\n---\n"
              "Question: Unity 6 C# script for a Rigidbody player")
    turn = ground + "\n\n(Build note for Litha, not from the user: complete code.)"
    assert facts.question_of(turn) == "Unity 6 C# script for a Rigidbody player"
    req = {"messages": [{"role": "user", "content": turn}]}
    hdr = facts.apply(req)
    assert hdr["X-Mesh-Engine"].startswith("unity core") and "old" not in hdr["X-Mesh-Engine"]
    assert req["messages"][0]["content"].startswith("Reference answers") and "(Facts for Litha" in req["messages"][0]["content"]
    roblox = "[Q] Unity vs Roblox\n[A] Unity uses C#.\n\n---\nQuestion: Roblox: give a player coins"
    assert facts.apply({"messages": [{"role": "user", "content": roblox}]}) == {}


def test_apply_replaces_polyglot_note_and_respects_flags():
    req = {"messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "Godot 4 enemy spawner script"}]}
    hdr = facts.apply(req)             # no cfg: every family the module knows
    assert hdr["X-Mesh-Engine"].startswith("godot core")
    assert req["messages"][1]["content"].count("(Facts for Litha") == 1 and req["messages"][0]["content"] == "sys"
    assert note.apply(req) == {}                                   # the polyglot note stays out of a facts turn
    off = {"messages": [{"role": "user", "content": "Godot 4 enemy spawner script"}], "mesh_engine": False}
    assert facts.apply(off) == {} and "mesh_engine" not in off and "Facts" not in off["messages"][0]["content"]
    assert facts.apply({"messages": [{"role": "user", "content": "Godot 4 x"}]}, {"engine_facts": False}) == {}
    only_unity = {"engine_facts": True, "engine_facts_families": ["unity"]}
    assert facts.apply({"messages": [{"role": "user", "content": "Godot 4 enemy script"}]}, only_unity) == {}
    assert facts.apply({"messages": [{"role": "user", "content": "Unity 6 enemy script"}]}, only_unity)["X-Mesh-Engine"].startswith("unity")


# ---------------------------------------------------------------------------------------------- Lua / LOVE rules
def test_lua_helpers_split_and_strip():
    assert engine._split_commas('"%d, %d", a, f(b, c), {1, 2}') == ['"%d, %d"', " a", " f(b, c)", " {1, 2}"]
    clean = engine._strip('local s = "string.split" -- table.find\nprint(1)')
    assert "split" not in clean and "find" not in clean and clean.count("\n") == 1


def test_lua_format_int_rule():
    p = engine._format_int_rule('print(string.format("%d of %d (%.1f)", n, total / 2, n / total))')
    assert len(p) == 1 and "float" in p[0]["message"]
    assert not engine._format_int_rule('print(string.format("%d", n // 2), string.format("%d", math.floor(n / 2)))')
    assert not engine._format_int_rule('print(string.format("%.1f", n / 2))')


def test_love_rules_colours_keys_and_mouse_buttons():
    engine.data("love_std.json")
    bad = engine.check_love_rules('love.graphics.setColor(200, 100, 0)\nfunction love.keypressed(key) if key == "enter" then end end')
    msgs = " | ".join(p["message"] for p in bad)
    assert "0 to 1" in msgs and "'enter'" in msgs
    assert any(p["suggestion"] == "return" for p in bad)
    ok = engine.check_love_rules("love.graphics.setColor(c[1] * 2, c[2], c[3], 1)\nlove.graphics.setColor(0.5, 1, 1)\n"
                                 'function love.keypressed(key) if key == "space" or key == "return" then end end')
    assert not ok
    assert engine.check_love_rules('function love.mousepressed(x, y, button) if button == "l" then end end')


def test_unity_diag_and_obsolete_table():
    idx = {"classes": {"Rigidbody", "NavMeshAgent"}}
    p = engine.unity_diag("CS0104", "'Random' is an ambiguous reference between 'UnityEngine.Random' and 'System.Random'",
                          ["Random", "UnityEngine.Random", "System.Random"], 7, "", "", set(), idx)
    assert p["suggestion"] == "UnityEngine.Random"
    p = engine.unity_diag("CS1503", "Argument 1: cannot convert from 'UnityEngine.GameObject' to 'Projectile'",
                          ["UnityEngine.GameObject", "Projectile"], 3, "", "", {"Projectile"}, idx)
    assert p and "component" in p["suggestion"]
    assert engine.unity_diag("CS1503", "cannot convert from 'int' to 'string'", ["int", "string"], 1, "", "", set(), idx) is None
    # an unknown type is only a hint (the user's own class from another file), a near miss of a Unity class is reported
    code = "using UnityEngine;\nclass A : MonoBehaviour { Rigidbdy rb; }"
    p = engine.unity_diag("CS0246", "The type or namespace name 'Rigidbdy' could not be found", ["Rigidbdy"], 2, code, "", {"A"}, idx)
    assert p["severity"] == "error" and p["suggestion"] == "Rigidbody"
    p = engine.unity_diag("CS0246", "The type or namespace name 'PlayerMarker' could not be found", ["PlayerMarker"], 2, code, "", {"A"}, idx)
    assert p["severity"] == "info"
    assert engine.unity_diag("CS0246", "x 'PlayerMarker' y", ["PlayerMarker"], 2, "using TMPro;\n" + code, "", {"A"}, idx) is None
    found = engine.unity_obsolete("var a = FindObjectOfType<Health>();\nvar b = Object.FindObjectsOfType<Enemy>();")
    assert [p["name"] for p in found] == ["FindObjectOfType", "FindObjectsOfType"]
    assert not engine.unity_obsolete("var a = FindFirstObjectByType<Health>();")


# --------------------------------------------------------------------------------------------- Unreal structural rules
HEADER = '''#pragma once
#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "HealthComponent.generated.h"

DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FOnHealthChanged, float, NewHealth, float, Delta);

UCLASS(ClassGroup=(Custom), meta=(BlueprintSpawnableComponent))
class MYGAME_API UHealthComponent : public UActorComponent
{
    GENERATED_BODY()
public:
    UPROPERTY(BlueprintAssignable) FOnHealthChanged OnHealthChanged;
protected:
    virtual void BeginPlay() override;
    UFUNCTION()
    void HandleDamage(AActor* DamagedActor, float Damage, const UDamageType* DamageType, AController* InstigatedBy, AActor* DamageCauser);
};
'''
CPP = '''#include "HealthComponent.h"
void UHealthComponent::BeginPlay()
{
    Super::BeginPlay();
    GetOwner()->OnTakeAnyDamage.AddDynamic(this, &UHealthComponent::HandleDamage);
}
'''


def test_unreal_clean_pair_has_no_problems():
    assert engine.check_unreal(HEADER, CPP)["problems"] == []
    assert engine.check_unreal(CPP, HEADER)["problems"] == []


def test_unreal_rules_catch_what_the_header_tool_and_compiler_reject():
    def msgs(code, ctx=""):
        return " | ".join(p["message"] for p in engine.check_unreal(code, ctx)["problems"])
    wrong_sig = HEADER.replace("const UDamageType* DamageType", "UDamageType* DamageType")
    assert "wrong signature for OnTakeAnyDamage" in msgs(wrong_sig, CPP)
    no_ufunction = HEADER.replace("    UFUNCTION()\n", "")
    assert "must be declared with UFUNCTION()" in msgs(no_ufunction, CPP)
    assert "LAST #include" in msgs(HEADER.replace('#include "HealthComponent.generated.h"\n', "")
                                   .replace('#include "CoreMinimal.h"', '#include "HealthComponent.generated.h"\n#include "CoreMinimal.h"'))
    assert "GENERATED_BODY" in msgs(HEADER.replace("    GENERATED_BODY()\n", ""))
    assert "needs 5 arguments" in msgs(HEADER.replace("TwoParams(FOnHealthChanged, float, NewHealth, float, Delta)",
                                                      "TwoParams(FOnHealthChanged, float, NewHealth)"))
    assert "must start with 'A'" in msgs(HEADER.replace("UHealthComponent : public UActorComponent",
                                                        "UHealthActor : public AActor"))
    assert "Super::BeginPlay" in msgs(CPP.replace("    Super::BeginPlay();\n", ""))
    assert "only valid in the constructor" in msgs('void UFoo::BeginPlay()\n{\n  Super::BeginPlay();\n'
                                                   '  Mesh = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("M"));\n}\n')
    assert "never `new" in msgs("void AFoo::Spawn() { auto* p = new AProjectile(); }")
    rpc = "UFUNCTION(Server, Reliable)\nvoid ServerFire();"
    assert "ServerFire_Implementation" in msgs(rpc) and not msgs(rpc, "void AFoo::ServerFire_Implementation() {}")
    rep = 'UPROPERTY(Replicated)\nint32 Ammo;'
    assert "GetLifetimeReplicatedProps" in msgs(rep)
    assert "Enhanced Input handler" in msgs("void AHero::Setup() { EIC->BindAction(MoveAction, ETriggerEvent::Triggered, this, "
                                            "&AHero::Move); }\nvoid AHero::Move(FVector2D V) {}")
    assert "UPROPERTY" in msgs('#pragma once\nclass AFoo : public AActor {\n    GENERATED_BODY()\n    UStaticMeshComponent* Mesh;\n};')


# ----------------------------------------------------------------------------------------------- verifier routing
class Fake:
    def __init__(self):
        self.langs = []

    def check(self, language, code, context=""):
        self.langs.append(language)
        return {"checked": True, "problems": [], "tool": "fake"}

    def check_many(self, items, context=""):
        return {i: self.check(i[0], i[1], context) for i in items}


def verifier(fake):
    return core.Verifier(ApiIndex({"meta": {}, "classes": {}, "enums": {}}), None, polyglot=fake)


def test_love_blocks_go_to_the_love_checker_and_plain_lua_questions_to_the_lua_checker():
    f = Fake()
    verifier(f).verify("```lua\nfunction love.draw()\n  love.graphics.print('hi')\nend\n```\n")
    assert f.langs == ["love"]
    f = Fake()
    text = "```lua\nlocal s = 'abc'\nprint(s:upper())\n```\n"
    verifier(f).verify(text)                                               # no hint: stays on the Roblox (Luau) checker
    assert f.langs == []
    verifier(f).verify(text, None, "Write a plain Lua 5.4 program that reads a line")
    assert f.langs == ["lua"]
    f = Fake()
    verifier(f).verify("```lua\nlocal p = game:GetService('Players')\n```\n", None, "Write a plain Lua 5.4 script")
    assert f.langs == []                                                   # Roblox code stays Roblox
    f = Fake()
    verifier(f).verify(text, None, "Roblox script that uppercases a string, not plain Lua 5.4")
    assert f.langs == []


def test_runner_loads_engine_module_and_checks_are_wired():
    src = (ROOT / "server/mesh/polyglot/runner.py").read_text(encoding="utf-8")
    assert '"love": check_love_engine' in src and "ENGINE.check_unreal" in src and "hoist_usings" in src
    data = ROOT / "server/mesh/polyglot/data"
    assert json.loads((data / "lua54_std.json").read_text(encoding="utf-8"))["string"]
    love = json.loads((data / "love_std.json").read_text(encoding="utf-8"))
    assert "rectangle" in love["love"]["graphics"] and "return" in love["keys"] and "bit" in love["lj"]
    std = engine.luacheck_std("love")
    assert '"graphics"' in std and std.startswith("std = {")
    assert "setColour" not in std


# ------------------------------------------------------------------------------------------------- Godot / C# helpers
def test_gdscript_extra_checks_with_a_small_api_table():
    engine._GD.clear()
    engine._GD.update({"_": True, "objs": {"Node", "Timer", "SceneTree", "Sprite2D"},
                       "all": {"start", "stop", "timeout", "texture", "queue_free", "create_timer", "change_scene_to_file"},
                       "table": {"Node": ({"queue_free", "name"}, None), "Timer": ({"start", "stop", "timeout"}, "Node"),
                                 "SceneTree": ({"create_timer", "change_scene_to_file"}, "Object"),
                                 "Sprite2D": ({"texture"}, "Node")}})
    code = ('extends Node\n@onready var t: Timer = $Timer\nfunc f():\n\tt.start(2.0)\n\tt.start_timer()\n'
            '\tget_tree().change_scene("res://a.tscn")\n\tget_tree().create_timer(1.0)\n\tvar e = scn.instance()\n'
            '\tvar s: Sprite2D = $S\n\ts.texture = null\n\ts.textur = null\n')
    names = sorted(p["name"] for p in engine.gd_extra(code))
    assert names == ["SceneTree.change_scene", "Sprite2D.textur", "Timer.start_timer", "instance"]
    # a typed PARAMETER may hold a subclass with its own methods: never flagged
    assert not engine.gd_extra("extends Node\nfunc hit(body: Timer):\n\tbody.take_damage(1)\n")
    assert not engine.gd_extra("extends Node\nfunc instance():\n\tpass\nfunc g():\n\tself.instance()\n")
    engine._GD.clear()


def test_runner_helpers_preload_and_hoisted_usings():
    from mesh.polyglot import runner
    src = 'const A = preload("res://a.tscn")\nconst B: Texture2D = preload("res://b.png")\nvar c := preload("res://c.png")\n'
    out = runner.gd_preload_to_load(src)
    assert out.splitlines() == ['var A = load("res://a.tscn")', 'var B: Texture2D = load("res://b.png")',
                                'var c := load("res://c.png")']
    code, shift = runner.hoist_usings("// File: A.cs\nusing UnityEngine;\nclass A : MonoBehaviour {}\n// File: B.cs\nusing System;\n"
                                      "using UnityEngine;\nclass B {}\n")
    assert shift == 1 and code.splitlines()[0] == "using UnityEngine; using System;"
    assert "// using System;" in code and code.count("using UnityEngine;") == 3   # hoisted + first + commented-out late one
    assert runner.hoist_usings("using System;\nclass A {}\n") == ("using System;\nclass A {}\n", 0)
