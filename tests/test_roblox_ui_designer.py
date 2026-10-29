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
            ' "items": [{"name": "X", "kind": "doohickey", "rarity": "ultra", "price": -5, "owned": "yes"}],' \
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


def test_leaderboard_keeps_time_strings():
    plan = D.parse_plan({"screen": "leaderboard", "entries": [{"name": "Velocity_X", "value": "1:23.45"},
                                                              {"name": "B", "value": "12,500"}, {"name": "C", "value": 900}],
                         "you": {"name": "Me", "value": "01:22.45", "rank": 12}})
    assert [e["value"] for e in plan["entries"]] == ["1:23.45", 12500, 900]
    assert plan["you"]["value"] == "01:22.45"
    src = D.emit_luau(plan)
    assert '"1:23.45"' in src and "showValue(e.value)" in src and "formatNumber(e.value" not in src


def test_rewards_calendar_has_all_days_amounts_and_special_last_day():
    raw = {"screen": "rewards", "today": 4, "items": [
        {"name": "Treat", "kind": "food", "amount": 1}, {"name": "Coins", "kind": "coin", "amount": 50},
        {"name": "Box", "kind": "chest", "rarity": "rare", "amount": 0}, {"name": "Egg", "kind": "pet", "rarity": "legendary"}]}
    plan = D.parse_plan(raw, "Daily login rewards calendar for a pet simulator (7 days, day 4 is today)")
    days = plan["items"]
    assert len(days) == 7 and all(d["amount"] > 0 for d in days)
    assert days[-1]["special"] is True and sum(1 for d in days if d.get("special")) == 1
    assert days[-1]["kind"] == "chest" and days[-1]["rarity"] == "mythic"
    assert len(D.parse_plan(raw, "a 5-day login streak")["items"]) == 5
    assert len(D.parse_plan(raw)["items"]) == 7  # the screen's default week
    assert "DAY \" .. i .. \"  BONUS" in D.emit_luau(plan)


def test_dialog_respects_the_number_of_choices_the_brief_asks_for():
    brief = "NPC dialogue: an old blacksmith offers to upgrade your sword for 500 gold; three answer choices."
    plan = D.parse_plan({"screen": "dialog", "body": "Upgrade?", "options": ["I'll take the upgrade!",
                         "Maybe next time, smith.", "How much does it cost again?"]}, brief)
    assert plan["actions"] == ["I'll take the upgrade!", "Maybe next time, smith.", "How much does it cost again?"]
    plan = D.parse_plan({"screen": "dialog", "body": "Upgrade?", "actions": ["Continue"]}, brief)
    assert len(plan["actions"]) == 3 and plan["actions"][1] == "Deal! (500 gold)"
    assert D.parse_plan({"screen": "dialog", "body": "Hi"})["actions"] == ["Continue"]


def test_results_labels_not_cut_mid_word_rewards_kept_and_no_orphan_tile_rule():
    plan = D.parse_plan({"screen": "results", "actions": ["Play Again", "Return to Lobby"],
                         "stats": [{"label": "Placement", "value": "1st"}] * 4,
                         "rewards": [{"name": "Credits", "amount": 5000}, {"name": "XP", "amount": 1200}]})
    assert plan["actions"] == ["Play Again", "Return to Lobby"]
    assert [(i["kind"], i["amount"]) for i in plan["items"]] == [("coin", 5000), ("gem", 1200)]
    assert D._clean_text("Return to the Lobby now", 14) == "Return to the"  # word boundary, never "Lobb"
    src = D.emit_luau(plan)
    assert "shown <= 4 and shown or math.ceil(shown / 2)" in src  # 4 -> one row, 5 -> 3 + 2, 6 -> 3 + 3


def test_survival_style_is_picked_for_zombie_briefs_and_horror_stays_horror():
    zombie = "HUD for a zombie survival shooter: health, stamina, a 4-weapon hotbar"
    restyled = D.parse_plan({"screen": "hud", "style": "scifi", "accent": "#00FFFF",
                             "currencies": [{"name": "Scrap", "amount": 5, "color": "#00FFFF"}]}, zombie)
    assert restyled["style"] == "survival" and "accent" not in restyled  # sci-fi cyan is dropped with the style
    assert "color" not in restyled["currencies"][0]
    assert D.parse_plan({"screen": "shop", "style": "vaporwave", "accent": "#3FA7FF"})["accent"] == "#3FA7FF"
    assert D.parse_plan({"screen": "loading", "style": "horror"}, "horror game in an abandoned hospital")["style"] == "horror"
    assert D.parse_plan({"screen": "loading", "style": "cartoon"}, "a haunted house loading screen")["style"] == "horror"
    assert D.parse_plan({"screen": "shop", "style": "cartoon"}, "a pet shop")["style"] == "cartoon"
    tokens = D.design(D.parse_plan({"screen": "hud"}, zombie))
    assert tokens["worn"] is True and tokens["fonts"]["display"]["family"] == "Oswald"
    assert "T.worn" in D.emit_luau(D.parse_plan({"screen": "hud"}, zombie))


def test_cars_and_guns_get_their_own_art_instead_of_gem_placeholders():
    plan = D.parse_plan({"screen": "shop", "items": [
        {"name": "Aurelius GT", "kind": "gem"}, {"name": "Velocita S", "kind": "car"}, {"name": "Titan Truck"},
        {"name": "Pulse Laser", "kind": "sword"}, {"name": "Iron Sword", "kind": "sword"}, {"name": "Gold Pile"}],
        "hotbar": [{"kind": "shotgun"}, {"kind": "rifle"}, {"kind": "melee"}]})
    assert [i["kind"] for i in plan["items"]] == ["car", "car", "car", "gun", "sword", "coin"]
    assert [h["kind"] for h in plan["hotbar"]] == ["gun", "gun", "sword"]
    src = D.emit_luau(plan)
    car = src[src.index("MODELS.car = function"):src.index("MODELS.gun = function")]
    assert car.count('"Cylinder"') == 2 and "Glass" in car and "Neon" in car  # wheels + hubs, windows, lights


def test_phone_layout_keeps_the_detail_panel():
    src = D.emit_luau(_plan())
    assert src.count('"Buy", compact)') == 1 and src.count('"Equip", compact)') == 1
    assert "if not compact then\n\t\tlocal _, s = detailPane" not in src
