import json

import pytest

from star import roblox_ui_check as C
from star import roblox_ui_designer as D


def _plan(**over):
    raw = {"screen": "shop", "style": "cartoon", "title": "Pet Shop",
           "items": [{"name": "Ember Fox", "kind": "pet", "rarity": "legendary", "price": 25000}]}
    raw.update(over)
    return D.parse_plan(raw)


def test_every_style_passes_its_own_contrast_rules():
    for style in D.STYLES:
        for screen in D.SCREENS:
            assert D.static_check(_plan(style=style, screen=screen)) == [], (style, screen)


def test_parse_plan_extracts_json_from_chatty_reply_and_clamps():
    reply = 'Sure!\n```json\n{"screen": "store", "style": "vaporwave", "title": "Shop \U0001F525 of Wonders and More Long",' \
            ' "items": [{"name": "X", "kind": "laser", "rarity": "ultra", "price": -5, "owned": "yes"}],' \
            ' "options": [{"label": "Vol", "kind": "slider", "value": 80}]}\n```'
    plan = D.parse_plan(reply)
    assert plan["screen"] == "shop" and plan["style"] == "cartoon"
    assert "\U0001F525" not in plan["title"] and len(plan["title"]) <= 28
    item = plan["items"][0]
    assert item["kind"] == "gem" and item["rarity"] == "common" and item["price"] == 0 and "owned" not in item
    assert plan["options"][0]["value"] == 0.8


def test_parse_plan_without_json_raises():
    with pytest.raises(ValueError):
        D.parse_plan("no json here")


def test_accent_override_keeps_button_text_legible():
    plan = _plan(accent="#FFD400")  # bright yellow: white text would fail
    tokens = D.design(plan)
    assert D.contrast(tokens["c"]["accentText"], tokens["c"]["accent"]) >= 4.5
    plan = _plan(accent="#3FA7FF")  # mid blue: darkened until white text passes
    tokens = D.design(plan)
    assert D.contrast(tokens["c"]["accentText"], tokens["c"]["accent"]) >= 4.5


def test_emit_luau_is_self_contained_and_data_is_escaped():
    plan = _plan(title='He said "hi" \\ bye', subtitle="Ünïcode ok")
    src = D.emit_luau(plan, ui_id="Shop 1!")
    assert src.startswith("--!nonstrict")
    assert 'local T = {' in src and 'local DATA = {' in src
    assert 'id = "Shop1"' in src
    assert '\\"hi\\" \\\\ bye' in src
    assert "SCREENS.shop" in src and "focusFirst" in src and "ButtonB" in src
    assert "rbxassetid://" not in src  # no image assets: item art is built from parts
    assert src.count("(") == src.count(")")


def test_defaults_fill_missing_content():
    plan = D.parse_plan({"screen": "hud"})
    assert plan["hotbar"] and plan["style"] == "cartoon"
    plan = D.parse_plan({"screen": "rewards"})
    assert all("amount" in i for i in plan["items"])


def test_design_notes_lists_tokens():
    notes = D.design_notes(D.design(_plan(style="scifi")))
    assert "type scale" in notes and "contrast" in notes and "Michroma" in notes


def test_lab_client_substitutes_placeholders():
    src = C.lab_client("abcd1234", ["StarShop"])
    assert "__" not in src.replace("__index", "")
    assert '"abcd1234"' in src and '["StarShop"] = true' in src
    install = C.install_luau("print('x')", "abcd1234")
    assert "StarUiVfx_Item" in install and "SetAttribute" not in install and ".Enabled = false" not in install.split("item.Source")[0]


def test_parse_console_and_score():
    m = {"device": "phone", "w": 844, "h": 390, "x0": 304, "y0": 202, "vw": 1452, "vh": 795,
         "elements": 10, "counts": {"text_cut": 2, "small_target": 1}}
    console = "\n".join([
        "[StarUiLab] r1 client-ready",
        "[StarUiLab] r1 sources 1 StarUI_x",
        "[StarUiLab] r1 measure " + json.dumps(m),
        "[StarUiLab] r1 READY phone",
        "[StarUiLab] other measure {}",
        "Players.P.PlayerScripts.StarUiVfx_Item:12: attempt to index nil",
    ])
    parsed = C.parse_console(console, "r1")
    assert parsed["ready"] == ["phone"] and parsed["sources"] == 1
    assert parsed["measures"]["phone"]["counts"]["text_cut"] == 2
    assert parsed["errors"] and "StarUiVfx_Item" in parsed["errors"][0]
    s = C.score(parsed["measures"])
    assert s["per_device"]["phone"] == 3 and s["missing"] == ["desktop", "tablet"] and s["total"] == 103


def test_crop_uses_device_box():
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (1452, 795), (10, 20, 30)).save(buf, "JPEG")
    out = C.crop(buf.getvalue(), {"x0": 304, "y0": 202, "w": 844, "h": 390, "vw": 1452, "vh": 795})
    assert Image.open(BytesIO(out)).size == (844, 390)


def test_play_server_not_ready_accepts_new_studio_wording_only():
    from star.studio_loop import _server_not_ready

    def res(text, error=True):
        return {"isError": error, "content": [{"type": "text", "text": text}]}
    new = ("Network action ExecuteLuau.loadCode sent to DMN_ID_PLAYSERVER failed - Target is not reachable "
           "(ExecuteLuau.loadCode, DMN_ID_PLAYSERVER). No OnInvoke handler responded for this action. "
           "Sender: DMN_ID_STANDALONE.")
    assert _server_not_ready(res(new))
    assert _server_not_ready(res("Target is not reachable"))
    assert not _server_not_ready(res(new, error=False))
    assert not _server_not_ready(res("Target is not reachable (ExecuteLuau.loadCode, DMN_ID_PLAYSERVER) script error"))


def test_parse_console_ignores_errors_of_earlier_runs():
    console = "\n".join([
        "Players.P.PlayerGui.StarUiVfx_Item:5: old error",
        "[StarUiLab] old1 READY phone",
        "Players.P.PlayerGui.StarUiVfx_Item:9: new error",
        "[StarUiLab] r2 client-ready",
    ])
    parsed = C.parse_console(console, "r2")
    assert len(parsed["errors"]) == 1 and "new error" in parsed["errors"][0]
