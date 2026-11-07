"""G1 API lock (star/api_lock.py): the receiver resolver, the member lookup, the shared C++ cases and the plumbing."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from star import api_lock

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "server" / "api_lock" / "cases.json").read_text(encoding="utf-8"))
FIXTURE = api_lock.Table.from_json(CASES["table"])


def lock(text, mode=api_lock.MODE_ALL, extra=(), table=FIXTURE):
    state = api_lock.Lock(table, mode, tuple(extra))
    state.feed(text)
    return state


@pytest.mark.parametrize("case", CASES["cases"], ids=[c["name"] for c in CASES["cases"]])
def test_shared_cases(case):
    """The same file is run against the C++ patch by `test-api-lock` (llama.cpp tests/test-api-lock.cpp)."""
    state = lock(case["text"], case["mode"], case["extra"])
    assert [p for p in case["allow"] if not state.allows(p)] == []
    assert [p for p in case["deny"] if state.allows(p)] == []
    assert state.forced() == case["forced"]


# --- the resolver -----------------------------------------------------------------------------------------------

def test_receivers_resolve_to_their_class():
    state = lock('local RS = game:GetService("RunService")\nlocal p = Instance.new("Part")\n')
    assert state._receiver('game:GetService("Players")') == ("class", "Players", True)
    assert state._receiver('game:GetService("ReplicatedStorage")') == ("class", "ReplicatedStorage", False)
    assert state._receiver('x = Instance.new("Part")') == ("class", "Part", True)
    assert state._receiver("RS") == ("class", "RunService", True)
    assert state._receiver("  p") == ("class", "Part", True)
    assert state._receiver("game") == ("game",)
    assert state._receiver("Enum") == ("enum_ns",)
    assert state._receiver("Enum.Material") == ("enum", "Material")


def test_unknown_or_ambiguous_receivers_resolve_to_nothing():
    state = lock('local RS = game:GetService("RunService")\n')
    for text in ('game:GetService("NoSuchService")', 'Instance.new("NoSuchClass")', "foo.RS", "RS2", "myRS",
                 'Instance.new(className)', 'f(game:GetService("RunService"))', "Enum.NoSuchEnum", "1RS",
                 "local function f(x: RS"):
        assert state._receiver(text) is None, text


def test_bindings_follow_kills_and_parenting():
    state = lock('local p = Instance.new("Part")\nlocal RS = game:GetService("RunService")\n')
    assert state.bindings["p"].closed and state.bindings["RS"].cls == "RunService"
    state.feed('local child = Instance.new("Part")\nchild.Parent = p\n')
    assert state.bindings["p"].closed is False          # p may have a named child now
    state.feed("RS = nil\nfor _, p in list do\n")
    assert "RS" not in state.bindings and "p" not in state.bindings
    state.feed("local workspace = {}\n")
    assert state._receiver("workspace") is None


def test_comment_and_string_ends_are_not_code():
    assert api_lock._scan('x = 1 -- workspace:')[:2] == (False, 6)
    assert api_lock._scan('print("workspace:')[0] is False
    assert api_lock._scan('s = [[ok]] workspace:') == (True, 21, "")
    assert api_lock._scan("s = [==[ open") == (False, 4, "]==]")
    assert api_lock._scan("--[[ note ]] workspace:")[0] is True


# --- member lookup (sorted lists, prefix search) ------------------------------------------------------------------

def test_prefix_lookup_and_piece_rules():
    names = ("Anchored", "AssemblyMass", "Name", "Parent")
    assert api_lock._has_prefix(names, "Ass") and not api_lock._has_prefix(names, "Asx")
    assert api_lock._contains(names, "Name") and not api_lock._contains(names, "Nam")
    assert api_lock._piece_ok(names, "", "Anch")              # a prefix may continue
    assert api_lock._piece_ok(names, "Anch", "ored =")        # the word ends on a real name
    assert not api_lock._piece_ok(names, "Anch", "or ")       # ...but not on an invented one
    assert api_lock._piece_ok(names, "", " ")                 # nothing started: released
    assert not api_lock._piece_ok(names, "Nam", "(")


def test_forced_only_when_one_name_is_left():
    assert lock('local RS = game:GetService("RunService")\nRS.Heart').forced() == "beat"
    assert lock('local RS = game:GetService("RunService")\nRS:Is').forced() == ""
    assert lock('local RS = game:GetService("RunService")\nRS.').forced() == ""


def test_bundled_table_from_the_real_dump():
    table = api_lock.bundled_table()
    assert "Anchored" in table.members["Part"] and "Destroy" in table.methods["Part"]
    assert "Create" in table.methods["TweenService"] and "Create" not in table.methods["RunService"]
    assert "Players" in table.services and set(table.dot_closed) <= table.services
    assert "Plastic" in table.enums["Material"]
    data = api_lock.build_table()
    assert data["version"] == api_lock.TABLE_VERSION and "ParticleEmitter" in data["classes"]


def test_real_dump_blocks_known_invented_members():
    table = api_lock.bundled_table()
    code = ('```lua\nlocal g = Instance.new("UIGridLayout")\ng.ColumnCount = 3\n'
            'local e = Instance.new("ParticleEmitter")\ne.Shape = Enum.ParticleEmitterShape.Point\n'
            'game:GetService("RunService"):Create()\n```\n')
    names = [b.name for b in api_lock.audit_text(code, table)]
    assert names == ["ColumnCount", "Point", "Create"]


def test_verified_gold_bank_code_has_no_block():
    """384 verified examples: any block here would be the lock refusing correct code."""
    rows = [json.loads(line) for line in (ROOT / "data" / "gold_bank" / "bank.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    table = api_lock.bundled_table()
    blocked = {row["id"]: api_lock.audit_text(row["answer"], table) for row in rows}
    assert {k: v for k, v in blocked.items() if v} == {}


def test_prompt_symbols():
    assert api_lock.prompt_symbols("local h = model.Hitbox\nmodel.Hitbox.Touched") == ("Hitbox", "Touched")


# --- plumbing -----------------------------------------------------------------------------------------------------

def test_setting_is_off_by_default_and_validated():
    from star.desktop_core import Settings
    assert Settings().api_lock_enabled is False
    with pytest.raises(ValueError):
        Settings(api_lock_enabled="yes").validate()


def test_request_field_only_when_enabled():
    from star import providers
    cfg = SimpleNamespace(provider="star_server", server_endpoint="http://127.0.0.1:8080/v1", model="m")
    assert "api_lock" not in providers.llama_request_fields(cfg)
    cfg.api_lock_enabled = True
    assert providers.llama_request_fields(cfg)["api_lock"] is True
    assert providers.llama_request_fields(cfg, background=True)["api_lock"] is True
    cloud = SimpleNamespace(provider="groq", api_lock_enabled=True)
    assert providers.llama_request_fields(cloud) == {}


def test_cli_writes_the_table(tmp_path):
    out = tmp_path / "table.json"
    assert api_lock.main(["table", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["classes"]["Part"]["super"] == "FormFactorPart"
