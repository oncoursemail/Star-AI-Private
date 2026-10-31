"""STAR computer use, part 3: the draw activity. A fake Paint paints onto a real image from the drag events it receives,
shows the same UI Automation controls Win11 Paint shows (measured on the dev PC), and saves a real PNG on Ctrl+S."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

import star.computer as star_computer
from star.computer import draw
from star.computer.screen import Element, Screen
from star.home import activities
from star.home.host import Executor
from star.home.life import Life

from test_computer_use import (BUTTON, EDIT, GROUP, LISTITEM, RADIO, WINDOW, Clock, Desk, Script,  # noqa: F401
                               make_computer, node)

PAGE = (150, 120, 850, 620)          # the white page: 700 x 500
VIEW = (100, 100, 900, 650)          # Paint's canvas control (the grey view around the page)


class PaintDesk(Desk):
    def __init__(self, *, paints=True, save_dialog=True):
        super().__init__()
        self.paints, self.save_dialog = paints, save_dialog
        self.color, self.color_log, self.state = "Black", [], "desktop"
        self.typed, self.outside, self.last, self.closed = "", [], None, False
        self.page = Image.new("RGB", self.SIZE, (190, 190, 190))
        ImageDraw.Draw(self.page).rectangle(PAGE, fill=(255, 255, 255))
        self.image = self.page
        self.swatches = {name: (300 + 30 * i, 30, 326 + 30 * i, 54) for i, name in enumerate(draw.PALETTE)}

    def launch(self, target):
        self.title, self.exe, self.hwnd, self.state = "Untitled - Paint", "mspaint.exe", 9, "paint"
        self.refresh()

    def refresh(self):
        if self.state == "dialog":
            self.title = "Save As"
            self.nodes = [node("Save As", WINDOW, (200, 200, 800, 500)), node("File name:", EDIT, (260, 260, 700, 290)),
                          node("Save", BUTTON, (700, 450, 780, 480))]
            return
        self.nodes = ([node(self.title, WINDOW, (0, 0, 1000, 700)), node("Save", BUTTON, (10, 10, 40, 40)),
                       node(f"Color 1: {self.color}", RADIO, (250, 20, 290, 60)),
                       node("Using Brush tool on Canvas", GROUP, VIEW, auto_id="image")] +
                      [node(n, LISTITEM, r) for n, r in self.swatches.items()])

    def in_view(self, x, y):
        return VIEW[0] <= x <= VIEW[2] and VIEW[1] <= y <= VIEW[3]

    def on_button(self, name, down, x, y):
        if name != "left" or self.state != "paint":
            return
        if down:
            for color, r in self.swatches.items():
                if r[0] <= x <= r[2] and r[1] <= y <= r[3]:
                    self.color, self.last = color, None
                    self.color_log.append(color)
                    self.refresh()
                    return
            self.last = (x, y) if self.in_view(x, y) else None
        else:
            self.last = None

    def on_move(self, x, y):
        if "left" in self.held and self.last is not None and self.state == "paint":
            if not self.in_view(x, y):
                self.outside.append((x, y))
            elif self.paints:
                rgb = draw.PALETTE[self.color]
                ImageDraw.Draw(self.page).line([self.last, (x, y)], fill=rgb, width=5)
            self.last = (x, y)

    def on_key(self, combo):
        if self.state == "paint" and combo == "ctrl+s" and self.save_dialog:
            self.state = "dialog"
            self.refresh()
        elif self.state == "dialog" and combo == "enter":
            Path(self.typed).parent.mkdir(parents=True, exist_ok=True)
            self.page.crop(PAGE).save(self.typed)
            self.state, self.title = "paint", "saved - Paint"
            self.refresh()
        elif combo == "alt+f4":
            self.present, self.closed = False, True

    def on_char(self, ch):
        if self.state == "dialog":
            self.typed += ch


def desk_computer(tmp_path, desk, chat=None):
    computer, hands, clock, home = make_computer(desk, tmp_path, chat)
    computer.cfg["speed_px_s"] = 900
    return computer, home


PLAN = draw.Plan("test", (
    draw.Stroke("Black", ((10, 90), (50, 10), (90, 90), (10, 90))),                 # a triangle
    draw.Stroke("Red", ((30, 60), (70, 60), (70, 75), (30, 75), (30, 60)))))        # a box, in another colour


# ---- planning --------------------------------------------------------------------------------------------------
def test_nearest_color_names_and_hex():
    assert draw.nearest_color("red") == "Red" and draw.nearest_color("Dark Red") == "Dark red"
    assert draw.nearest_color("#ed1c24") == "Red" and draw.nearest_color("#fe0000") == "Red"
    assert draw.nearest_color("#0000ff") in ("Indigo", "Blue-gray", "Turquoise")
    assert draw.nearest_color("plaid") == "Black" and draw.nearest_color(None) == "Black"


def test_validate_plan_accepts_good_plans_clamps_and_explains_bad_ones():
    good = draw.validate_plan({"title": "T", "strokes": [{"color": "#ff0000", "points": [[0, 0], [150, -5]]}]})
    assert isinstance(good, draw.Plan) and good.strokes[0].color == "Red" and good.strokes[0].points[-1] == (100.0, 0.0)
    for bad, word in (({}, "strokes"), ({"strokes": []}, "strokes"), ({"strokes": [{"points": [[1, 1]]}]}, "two"),
                      ({"strokes": [{"points": [[1, 1], ["a", 2]]}]}, "numbers"), ([], "strokes")):
        assert word in draw.validate_plan(bad)
    many = draw.validate_plan({"strokes": [{"points": [[0, 0], [1, 1]]}] * 90})
    assert len(many.strokes) == draw.MAX_STROKES


def test_plan_drawing_retries_once_with_the_reason_then_gives_up():
    seen = []

    def chat(messages, tools):
        seen.append(messages[-1]["content"])
        if len(seen) == 1:
            return {"content": '{"strokes": [{"points": [[1, 1]]}]}'}
        return {"content": 'Here:\n{"title": "Cat", "strokes": [{"color": "Gray", "points": [[10, 10], [90, 90]]}]}'}

    plan, error = draw.plan_drawing(chat, "a cat")
    assert plan.title == "Cat" and error == "" and "rejected" in seen[1] and "at least two" in seen[1]
    plan, error = draw.plan_drawing(lambda m, t: {"content": "no idea"}, "a cat")
    assert plan is None and "no JSON" in error


# ---- finding the canvas and checking the picture -------------------------------------------------------------------
def test_largest_light_rect_finds_the_white_page_in_a_grey_window():
    image = Image.new("RGB", (400, 300), (190, 190, 190))
    ImageDraw.Draw(image).rectangle((80, 50, 319, 249), fill=(255, 255, 255))
    ImageDraw.Draw(image).rectangle((10, 10, 40, 30), fill=(255, 255, 255))                 # a smaller white blob
    l, t, r, b = draw.largest_light_rect(image)
    assert abs(l - 80) <= 1 and abs(t - 50) <= 1 and abs(r - 320) <= 1 and abs(b - 250) <= 1
    assert draw.largest_light_rect(Image.new("RGB", (100, 100), (10, 10, 10))) is None


def test_find_canvas_prefers_the_uia_canvas_then_tightens_to_the_white_page():
    desk = PaintDesk()
    desk.launch("mspaint")
    screen = Screen([Element(1, "Paint", "window", (0, 0, 1000, 700)),
                     Element(2, "Using Brush tool on Canvas", "group", VIEW, auto_id="image"),
                     Element(3, "Red", "listitem", (300, 30, 326, 54))])
    assert draw.find_canvas(screen) == VIEW
    tight = draw.find_canvas(screen, desk.page)
    assert all(abs(a - b) <= 1 for a, b in zip(tight, PAGE))


def test_find_canvas_without_a_uia_canvas_uses_the_white_area_of_the_window_or_nothing():
    desk = PaintDesk()
    screen = Screen([Element(1, "Krita", "window", (0, 0, 1000, 700)), Element(2, "Save", "button", (10, 10, 40, 40))])
    found = draw.find_canvas(screen, desk.page)
    assert all(abs(a - b) <= 1 for a, b in zip(found, PAGE))
    assert draw.find_canvas(Screen([Element(2, "Save", "button", (10, 10, 40, 40))]), desk.page) is None
    assert draw.find_canvas(Screen([Element(1, "Krita", "window", (0, 0, 1000, 700))],)) == (0, 0, 1000, 700)


def test_square_and_screen_mapping_keep_every_point_inside_the_page():
    square = draw.square_in(PAGE)
    assert square[0] > PAGE[0] and square[2] < PAGE[2] and square[1] > PAGE[1] and square[3] < PAGE[3]
    assert square[2] - square[0] == square[3] - square[1]
    for _color, pts in draw.to_screen(PLAN, square):
        assert all(square[0] <= x <= square[2] and square[1] <= y <= square[3] for x, y in pts)
    edge = draw.Plan("e", (draw.Stroke("Black", ((0, 0), (100, 100))),))
    (_c, pts), = draw.to_screen(edge, square)
    assert pts[0] == (square[0], square[1]) and pts[1] == (square[2], square[3])


def test_compare_to_plan_matches_the_right_picture_and_rejects_blank_and_different_ones():
    right = draw.render_plan(PLAN, 500)
    assert draw.compare_to_plan(right, PLAN, (0, 0, 1, 1))["match"]
    assert not draw.compare_to_plan(Image.new("RGB", (500, 500), (255, 255, 255)), PLAN, (0, 0, 1, 1))["match"]
    other = draw.Plan("o", (draw.Stroke("Black", ((10, 10), (90, 12), (88, 30), (12, 28), (10, 10))),))
    wrong = draw.compare_to_plan(draw.render_plan(other, 500), PLAN, (0, 0, 1, 1))
    assert not wrong["match"] and wrong["precision"] < 0.5
    shifted = Image.new("RGB", (500, 500), (255, 255, 255))
    shifted.paste(right, (180, 180))
    assert not draw.compare_to_plan(shifted, PLAN, (0, 0, 1, 1))["match"]
    sub = Image.new("RGB", (1000, 600), (255, 255, 255))                       # the plan inside part of a bigger page
    sub.paste(draw.render_plan(PLAN, 400), (300, 100))
    assert draw.compare_to_plan(sub, PLAN, (0.3, 100 / 600, 0.7, 500 / 600))["match"]


# ---- painting ---------------------------------------------------------------------------------------------------
def test_draw_session_paints_chooses_the_colour_saves_and_verifies(tmp_path):
    desk = PaintDesk()
    computer, home = desk_computer(tmp_path, desk)
    gallery = tmp_path / "gallery"
    result = draw.draw_session(computer, PLAN, "a house", gallery)
    assert result["ok"] and result["verified"], result
    saved = [Path(p) for p in result["evidence"]]
    assert saved[0].suffix == ".png" and saved[0].parent == gallery and saved[0].stat().st_size > 0
    side = json.loads(saved[1].read_text(encoding="utf-8"))
    assert side["subject"] == "a house" and side["plan"]["title"] == "test" and side["check"]["match"]
    assert desk.color_log == ["Red"]                                          # Black is already the colour
    assert desk.outside == [] and desk.closed
    with Image.open(saved[0]) as picture:
        assert picture.size == (700, 500)
        px = picture.convert("RGB")
        assert any(px.getpixel((x, y)) == draw.PALETTE["Red"] for x in range(250, 450) for y in range(250, 350))
    assert desk.typed == str(saved[0])


def test_draw_session_reports_a_blank_painting_as_not_verified(tmp_path):
    desk = PaintDesk(paints=False)
    computer, home = desk_computer(tmp_path, desk)
    result = draw.draw_session(computer, PLAN, "a house", tmp_path / "gallery")
    assert result["ok"] is True and result["verified"] is False and "recall 0.0" in result["summary"]


def test_draw_session_reports_when_the_save_box_never_opens(tmp_path):
    desk = PaintDesk(save_dialog=False)
    computer, home = desk_computer(tmp_path, desk)
    result = draw.draw_session(computer, PLAN, "a house", tmp_path / "gallery", close_after=False)
    assert result["ok"] is False and result["verified"] is False and "Save As box did not appear" in result["summary"]
    assert result["evidence"] == []


def test_draw_session_stops_with_the_owner_stop_file(tmp_path):
    from star.home import control
    desk = PaintDesk()
    computer, home = desk_computer(tmp_path, desk)
    control.stop(home)
    result = draw.draw_session(computer, PLAN, "a house", tmp_path / "gallery")
    assert result["verified"] is False and desk.calls == []


def test_select_color_confirms_through_the_color_control(tmp_path):
    desk = PaintDesk()
    desk.launch("mspaint")
    computer, home = desk_computer(tmp_path, desk)
    assert draw.select_color(computer, "Green")[0] and desk.color == "Green"
    ok, why = draw.select_color(computer, "Ultraviolet")
    assert not ok and "no swatch" in why


# ---- the STAR Home plug-in ---------------------------------------------------------------------------------------
def test_register_home_activities_adds_draw_and_use_app():
    registry = activities.default_registry(plugins=("star.computer",))
    assert registry.plugin_errors == {}
    assert registry.items["draw"].interest == "drawing" and registry.items["draw"].needs_brain
    assert registry.items["use_app"].interest == "use_apps"
    assert {"drawing", "use_apps"} <= registry.interests()


# draw_activity stops before planning anywhere but Windows
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="drawing in Paint needs Windows")


def ctx_for(tmp_path, chat, dry=True, goal=None):
    home = tmp_path / "home"
    executor = Executor(home, type("B", (), {})(), dry_run=dry)
    return activities.Context(home=home, config={}, executor=executor, life=Life(home), chat=chat, interest="drawing",
                              goal=goal, practice_topic="")


@windows_only
def test_draw_activity_dry_run_plans_but_paints_nothing(tmp_path):
    chat = Script({"title": "Hut", "strokes": [{"color": "Red", "points": [[10, 10], [90, 90]]}]})
    ctx = ctx_for(tmp_path, chat, goal={"id": "g1", "text": "Draw a hut"})
    out = star_computer.draw_activity(ctx)
    assert out["ok"] is False and "dry run: planned 1 strokes for 'Draw a hut'" in out["summary"]
    assert not (tmp_path / "workspace" / "gallery").exists()
    assert "Subject: Draw a hut" in chat.prompts[0]


@windows_only
def test_draw_activity_picks_a_subject_when_there_is_no_goal_and_reports_a_rejected_plan(tmp_path):
    seen = []

    def chat(messages, tools):
        seen.append(messages[-1]["content"])
        return {"content": "a lighthouse" if len(seen) == 1 else "no json at all"}

    out = star_computer.draw_activity(ctx_for(tmp_path, chat))
    assert "Already drawn lately: nothing yet" in seen[0] and "Subject: a lighthouse" in seen[1]
    assert out["ok"] is False and "no usable sketch plan for 'a lighthouse'" in out["summary"]
    assert out["failures"]
