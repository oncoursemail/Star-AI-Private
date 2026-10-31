"""STAR computer use, part 2: the human-like hands and the act() loop, on the fake desktop from test_computer_use.py."""
from __future__ import annotations

import json
import math
import random

from PIL import Image, ImageDraw
import pytest

from star.computer import grounding
from star.computer.agent import Guard, json_objects, parse_action
from star.computer.eye import changed_fraction
from star.computer.hands import Hands, Stopped, _spline, stroke_path
from star.computer.winapi import WindowInfo
from star.home import control

from test_computer_use import (BUTTON, EDIT, WINDOW, Clock, Desk, Script, make_computer, node,  # noqa: F401
                               prompt_id)


def hands_for(desk, tmp_path, **kw):
    clock = Clock()
    return Hands(desk, home=tmp_path / "home", clock=clock.now, sleep=clock.sleep, seed=kw.pop("seed", 3), **kw), clock


# ---- hands -----------------------------------------------------------------------------------------------------
def test_click_moves_along_a_path_ends_in_the_target_and_waits_a_reaction_time(tmp_path):
    desk = Desk()
    hands, clock = hands_for(desk, tmp_path)
    t0 = clock.t
    hands.click(600, 400, width=30)
    moves = [c for c in desk.calls if c[0] == "move"]
    assert len(moves) > 15 and math.hypot(moves[-1][1] - 600, moves[-1][2] - 400) < 30
    assert desk.calls.index(("button", "left", True)) > desk.calls.index(moves[-1])
    assert desk.calls[-1] == ("button", "left", False)
    assert clock.t - t0 > 0.35                        # reaction time + Fitts movement time, not an instant jump
    assert max(abs(b[1] - a[1]) for a, b in zip(moves, moves[1:])) < 120


def test_double_click_and_right_click(tmp_path):
    desk = Desk()
    hands, _ = hands_for(desk, tmp_path)
    hands.click(300, 300, button="right")
    assert desk.calls[-2:] == [("button", "right", True), ("button", "right", False)]
    desk.calls.clear()
    hands.click(310, 310, clicks=2)
    assert [c for c in desk.calls if c[0] == "button"] == [("button", "left", True), ("button", "left", False)] * 2


def test_stop_file_refuses_every_action_and_touches_nothing(tmp_path):
    desk = Desk()
    hands, _ = hands_for(desk, tmp_path)
    control.stop(tmp_path / "home")
    for call in (lambda: hands.click(1, 1), lambda: hands.type_text("a"), lambda: hands.key("ctrl+s"),
                 lambda: hands.scroll(3), lambda: hands.drag([(1, 1), (9, 9)]), lambda: hands.move(5, 5)):
        with pytest.raises(Stopped):
            call()
    assert desk.calls == []


def test_stop_during_a_long_move_lets_go_and_stops(tmp_path):
    desk = Desk()
    hands, clock = hands_for(desk, tmp_path)
    home = tmp_path / "home"
    state = {"n": 0}

    def sleep(dt):
        clock.sleep(dt)
        state["n"] += 1
        if state["n"] == 120:
            control.stop(home)

    hands.sleep = sleep
    with pytest.raises(Stopped):
        hands.drag([(100, 100), (900, 600)], speed_px_s=200)
    assert "left" not in desk.held                    # the button was released when the stop came


def test_dry_run_logs_and_does_nothing(tmp_path):
    desk = Desk()
    clock = Clock()
    hands = Hands(desk, home=tmp_path / "home", dry_run=True, clock=clock.now, sleep=clock.sleep)
    hands.click(10, 10)
    hands.type_text("hello")
    hands.key("ctrl+c")
    assert desk.calls == []
    rows = control.read_log(tmp_path / "home", 20)
    assert [r["action"] for r in rows if r["phase"] == "done"] == ["computer.click", "computer.type", "computer.key"]
    assert all(r.get("dry_run") for r in rows)


def test_every_action_is_logged_before_and_after(tmp_path):
    desk = Desk()
    hands, _ = hands_for(desk, tmp_path)
    hands.click(50, 60)
    rows = control.read_log(tmp_path / "home", 5)
    assert [(r["action"], r["phase"]) for r in rows] == [("computer.click", "start"), ("computer.click", "done")]
    assert rows[0]["x"] == 50 and rows[0]["y"] == 60


def test_type_text_delivers_every_character_with_an_uneven_rhythm_and_enter_for_newlines(tmp_path):
    desk = Desk()
    hands, clock = hands_for(desk, tmp_path)
    stamps = []
    orig = desk.type_char
    desk.type_char = lambda ch: (stamps.append(clock.t), orig(ch))
    t0 = clock.t
    hands.type_text("Hello, wörld 😀\nok")
    typed = "".join(c[1] for c in desk.calls if c[0] == "char")
    assert typed == "Hello, wörld 😀ok"
    assert ("key", "enter", True) in desk.calls and ("key", "enter", False) in desk.calls
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert min(gaps) >= 0.04 and max(gaps) - min(gaps) > 0.05
    assert clock.t - t0 > 1.0


def test_key_combo_presses_modifiers_first_and_releases_them_last(tmp_path):
    desk = Desk()
    hands, _ = hands_for(desk, tmp_path)
    hands.key("Ctrl + Shift+s")
    assert [c[1:] for c in desk.calls] == [("ctrl", True), ("shift", True), ("s", True), ("s", False),
                                           ("shift", False), ("ctrl", False)]
    with pytest.raises(ValueError):
        hands.key("")


def test_scroll_sends_the_requested_notches_in_bursts_and_moves_there_first(tmp_path):
    desk = Desk()
    hands, _ = hands_for(desk, tmp_path)
    hands.scroll(-7, at=(500, 300))
    wheels = [c[1] for c in desk.calls if c[0] == "wheel"]
    assert sum(wheels) == -7 and set(wheels) == {-1}
    assert desk.calls[0][0] == "move" and abs(desk.pos[0] - 500) < 40
    desk.calls.clear()
    hands.scroll(4)
    assert sum(c[1] for c in desk.calls if c[0] == "wheel") == 4


def test_hands_step_back_when_someone_else_moves_the_mouse_between_actions(tmp_path):
    desk = Desk()
    clock = Clock()
    hands = Hands(desk, home=tmp_path / "home", clock=clock.now, sleep=clock.sleep, seed=2, watch_pointer=True)
    hands.click(400, 300)
    desk.pos = (desk.pos[0] + 8, desk.pos[1] - 5)                    # a nudge is not a takeover
    hands.click(420, 320)
    calls = len(desk.calls)
    desk.pos = (900, 650)                                            # the owner grabbed the mouse
    with pytest.raises(Stopped, match="someone else"):
        hands.click(100, 100)
    assert len(desk.calls) == calls
    assert control.read_log(tmp_path / "home", 3)[-1]["phase"] == "refused"


def test_stroke_path_is_smooth_monotonic_in_time_and_ends_exactly_on_the_last_point():
    from star.play.humanlike import HumanProfile
    rng = random.Random(5)
    pts = [(100, 100), (200, 140), (300, 100), (400, 180)]
    path = stroke_path(pts, 380, rng, HumanProfile(shake_px=0.0))
    ts = [p[0] for p in path]
    assert ts == sorted(ts) and path[-1][1:] == (400, 180)
    length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
    assert abs(ts[-1] - length / 380) < 0.35 * length / 380 + 0.15
    speeds = [math.hypot(b[1] - a[1], b[2] - a[2]) / (b[0] - a[0]) for a, b in zip(path, path[1:]) if b[0] > a[0]]
    mid = speeds[len(speeds) // 2 - 3:len(speeds) // 2 + 3]
    assert max(speeds[:3]) < max(mid) and max(speeds[-3:]) < max(mid)       # slow start and end, faster middle
    assert all(abs(speeds[i + 1] - speeds[i]) < 0.35 * max(speeds) for i in range(len(speeds) - 1))   # no stop-and-go


def test_spline_passes_through_every_given_point():
    pts = [(0.0, 0.0), (50.0, 80.0), (120.0, 20.0), (200.0, 90.0)]
    curve = _spline(pts)
    for p in pts:
        assert min(math.hypot(c[0] - p[0], c[1] - p[1]) for c in curve) < 1.5


def _dist_to_polyline(pt, poly):
    best = 1e9
    for a, b in zip(poly, poly[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        f = max(0.0, min(1.0, ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(pt[0] - a[0] - f * dx, pt[1] - a[1] - f * dy))
    return best


def test_spline_keeps_sharp_corners_sharp_and_gentle_bends_round():
    triangle = [(0.0, 0.0), (100.0, 0.0), (50.0, 80.0), (0.0, 0.0)]
    assert max(_dist_to_polyline(p, triangle) for p in _spline(triangle)) < 1.0         # corners are not cut
    house = [(15.0, 90.0), (15.0, 45.0), (50.0, 12.0), (85.0, 45.0), (85.0, 90.0), (15.0, 90.0)]   # a 43 degree bend
    assert max(_dist_to_polyline(p, house) for p in _spline(house)) < 1.0                 # measured: 50 degrees bulged the walls
    arc = [(100 * math.cos(i * 0.3), 100 * math.sin(i * 0.3)) for i in range(10)]       # ~17 degrees per vertex
    off = [_dist_to_polyline(p, arc) for p in _spline(arc)]
    assert max(off) < 3 and max(off) > 0.1                                              # smooth, not a polyline


def test_drag_presses_first_moves_inside_the_bounds_then_releases(tmp_path):
    desk = Desk()
    hands, _ = hands_for(desk, tmp_path)
    hands.drag([(300, 300), (400, 340), (500, 300)], speed_px_s=300)
    kinds = [c[0] + (":" + str(c[2]) if c[0] == "button" else "") for c in desk.calls]
    down, up = kinds.index("button:True"), len(kinds) - 1 - kinds[::-1].index("button:False")
    assert all(k == "move" for k in kinds[down + 1:up]) and kinds[up] == "button:False"
    drawn = [(c[1], c[2]) for c in desk.calls[down:up] if c[0] == "move"]
    assert drawn[-1] == (500, 300) and all(280 <= x <= 520 and 280 <= y <= 360 for x, y in drawn)
    assert math.hypot(desk.calls[down - 1][1] - 300, desk.calls[down - 1][2] - 300) < 8   # pressed at the start


# ---- act(): observe, plan, act, verify, recover ------------------------------------------------------------------
class NotesDesk(Desk):
    """Notes with a File menu: File -> Save as... -> a Save As window with a file-name box and a password box."""

    def __init__(self):
        super().__init__()
        self.title, self.exe, self.hwnd = "Notes", "notes.exe", 7
        self.state = "main"
        self.clicks = []
        self.typed = ""
        self.draw()

    def draw(self):
        n = [node("Notes", WINDOW, (0, 0, 1000, 700)), node("File", 50011, (10, 10, 60, 40)),
             node("Dead button", BUTTON, (100, 10, 220, 40)), node("Buy now", BUTTON, (300, 10, 400, 40)),
             node("Body", EDIT, (10, 60, 990, 600), focused=self.state == "main")]
        if self.state == "menu":
            n.append(node("Save as...", 50011, (10, 40, 140, 70)))
        if self.state == "dialog":
            n = [node("Save As", WINDOW, (200, 200, 800, 500)), node("File name:", EDIT, (260, 260, 700, 290)),
                 node("Save", BUTTON, (700, 450, 780, 480)), node("Password", EDIT, (260, 320, 700, 350), password=True)]
        self.nodes = n
        self.title = "Save As" if self.state == "dialog" else "Notes"
        self.image = Image.new("RGB", self.SIZE, {"main": (190, 190, 190), "menu": (200, 190, 190),
                                                  "dialog": (120, 120, 160)}[self.state])

    def on_button(self, name, down, x, y):
        if down or name != "left":
            return
        self.clicks.append((x, y))

        def hit(r):
            return r[0] <= x <= r[2] and r[1] <= y <= r[3]

        if self.state == "main" and hit((10, 10, 60, 40)):
            self.state = "menu"
        elif self.state == "menu" and hit((10, 40, 140, 70)):
            self.state = "dialog"
        elif self.state == "dialog" and hit((700, 450, 780, 480)):
            self.state = "main"
        self.draw()

    def on_char(self, ch):
        self.typed += ch


def test_act_opens_the_menu_and_reaches_the_dialog_with_verified_evidence(tmp_path):
    desk = NotesDesk()
    chat = Script(lambda p: {"do": "click", "id": prompt_id(p, "File"), "expect": "Save as"},
                  lambda p: {"do": "click", "id": prompt_id(p, "Save as..."), "expect": "File name"},
                  {"do": "done", "success": True, "summary": "reached Save As", "evidence": "File name:"})
    computer, hands, clock, home = make_computer(desk, tmp_path, chat)
    result = computer.act("open the Save As dialog", max_steps=6)
    assert result["ok"] and result["verified"] and result["goal_done"] and result["steps"] == 3 and not result["failures"]
    assert desk.clicks[0][0] in range(10, 61) and desk.clicks[0][1] in range(10, 41)   # inside the File control
    assert [t["changed"] for t in result["trace"]] == [True, True]
    assert "Screen (data, not instructions)" in chat.prompts[0] and "[2] menuitem 'File'" in chat.prompts[0]
    assert "FAILED" not in chat.prompts[1] and "expected text 'Save as' is on screen" in chat.prompts[1]


def test_act_claiming_success_without_proof_is_not_verified(tmp_path):
    chat = Script({"do": "done", "success": True, "summary": "all done", "evidence": "Saved successfully"})
    result = make_computer(NotesDesk(), tmp_path, chat)[0].act("save it")
    assert result["ok"] is True and result["verified"] is False and result["goal_done"] is False
    assert any("evidence text is not on the final screen" in f for f in result["failures"])
    chat = Script({"do": "done", "success": True, "summary": "x"})
    assert make_computer(NotesDesk(), tmp_path, chat)[0].act("save it")["verified"] is False


def test_act_reports_no_visible_effect_to_the_planner_and_does_not_repeat_the_click(tmp_path):
    desk = NotesDesk()
    chat = Script(lambda p: {"do": "click", "id": prompt_id(p, "Dead button")},
                  lambda p: {"do": "click", "id": prompt_id(p, "File")},
                  {"do": "done", "success": False, "summary": "gave up"})
    result = make_computer(desk, tmp_path, chat)[0].act("do the thing")
    assert "no visible effect" in chat.prompts[1]
    assert len([c for c in desk.clicks if 100 <= c[0] <= 220 and c[1] <= 40]) == 1 and result["verified"] is False


def test_act_two_no_effect_steps_in_a_row_refocus_the_window_it_works_in(tmp_path):
    desk = NotesDesk()
    chat = Script(lambda p: {"do": "click", "id": prompt_id(p, "Dead button")},
                  {"do": "scroll", "dir": "down", "amount": 1},
                  {"do": "done", "success": False, "summary": "stuck"})
    computer, *_ = make_computer(desk, tmp_path, chat, guard=Guard(desk, {"notes.exe"}))
    computer.act("x", app_exes={"notes.exe"})
    assert desk.hwnd in desk.focused_calls


def test_act_stops_when_the_same_action_is_repeated_three_times(tmp_path):
    chat = Script(*[{"do": "wait", "seconds": 0.1}] * 5)
    result = make_computer(NotesDesk(), tmp_path, chat)[0].act("wait forever", max_steps=10)
    assert result["ok"] is False and "stuck" in result["summary"] and result["steps"] == 3


def test_act_ends_after_three_unusable_replies(tmp_path):
    computer, *_ = make_computer(NotesDesk(), tmp_path, lambda m, t: {"content": "I think you should click it"})
    result = computer.act("anything")
    assert result["ok"] is False and result["steps"] == 3 and "no valid action" in result["summary"]


def test_act_refuses_risky_clicks_and_queues_them_for_the_owner(tmp_path):
    desk = NotesDesk()
    chat = Script(lambda p: {"do": "click", "id": prompt_id(p, "Buy now")},
                  {"do": "done", "success": False, "summary": "needs owner"})
    computer, hands, clock, home = make_computer(desk, tmp_path, chat)
    result = computer.act("buy the thing")
    assert desk.clicks == [] and any("spending money" in f for f in result["failures"])
    queue = [json.loads(line) for line in (home / "approvals.jsonl").read_text(encoding="utf-8").splitlines()]
    assert queue and "Buy now" in queue[0]["action"] and queue[0]["status"] == "waiting"


def test_act_never_types_into_a_password_field(tmp_path):
    desk = NotesDesk()
    desk.state = "dialog"
    desk.draw()
    chat = Script(lambda p: {"do": "type", "id": prompt_id(p, "Password"), "text": "hunter2"},
                  {"do": "done", "success": False, "summary": "refused"})
    result = make_computer(desk, tmp_path, chat)[0].act("log in")
    assert desk.typed == "" and any("password" in f for f in result["failures"])


def test_act_types_into_a_chosen_control_after_clicking_it(tmp_path):
    desk = NotesDesk()
    desk.state = "dialog"
    desk.draw()
    chat = Script(lambda p: {"do": "type", "id": prompt_id(p, "File name:"), "text": "notes.txt"},
                  {"do": "done", "success": True, "summary": "typed", "evidence": "File name"})
    result = make_computer(desk, tmp_path, chat)[0].act("name the file")
    assert desk.typed == "notes.txt" and result["verified"]
    assert 260 <= desk.clicks[0][0] <= 700 and 260 <= desk.clicks[0][1] <= 290


def test_act_with_an_unknown_id_tells_the_planner(tmp_path):
    desk = NotesDesk()
    chat = Script({"do": "click", "id": 99}, {"do": "done", "success": False, "summary": "?"})
    make_computer(desk, tmp_path, chat)[0].act("x")
    assert desk.clicks == [] and "no control with id 99" in chat.prompts[1]


def test_act_uses_a_name_match_before_the_vision_model(tmp_path):
    desk = NotesDesk()
    calls = []
    grounder = type("G", (), {"locate": lambda self, img, q: calls.append(q)})()
    chat = Script({"do": "click", "target": "File"},
                  {"do": "done", "success": True, "summary": "ok", "evidence": "Save as"})
    make_computer(desk, tmp_path, chat, grounder=grounder)[0].act("open the file menu")
    assert calls == [] and desk.state == "menu"


def test_act_falls_back_to_the_vision_model_for_a_control_the_tree_lacks(tmp_path):
    desk = NotesDesk()
    asked = []

    class G:
        def locate(self, image, query):
            asked.append((query, image.size))
            return grounding.Grounded(35, 25, "(35,25)", 0.4)           # where the File menu really is

    chat = Script({"do": "click", "target": "the menu at the top left", "expect": "Save as"},
                  {"do": "done", "success": True, "summary": "ok", "evidence": "Save as"})
    result = make_computer(desk, tmp_path, chat, grounder=G())[0].act("open the menu")
    assert asked == [("the menu at the top left", (1000, 700))] and desk.state == "menu" and result["verified"]


def test_act_without_a_vision_model_says_so_instead_of_guessing(tmp_path):
    desk = NotesDesk()
    chat = Script({"do": "click", "target": "something invisible"}, {"do": "done", "success": False, "summary": "no"})
    make_computer(desk, tmp_path, chat)[0].act("x")
    assert desk.clicks == [] and "no vision model is set up" in chat.prompts[1]


def test_act_thin_screens_tell_the_planner_to_use_targets_or_keys(tmp_path):
    desk = Desk()
    desk.nodes = [node("Game", WINDOW, (0, 0, 1000, 700))]
    chat = Script({"do": "done", "success": False, "summary": "n/a"})
    make_computer(desk, tmp_path, chat)[0].act("x")
    assert "few controls" in chat.prompts[0] and "no vision model" in chat.prompts[0]
    chat = Script({"do": "done", "success": False, "summary": "n/a"})
    make_computer(desk, tmp_path, chat, grounder=object())[0].act("x")
    assert '"target" description' in chat.prompts[0]


def test_act_stops_at_the_owner_stop_file(tmp_path):
    desk = NotesDesk()
    chat = Script(lambda p: {"do": "click", "id": prompt_id(p, "File")})
    computer, hands, clock, home = make_computer(desk, tmp_path, chat)
    control.stop(home)
    result = computer.act("x")
    assert desk.clicks == [] and "stopped by the owner" in result["summary"]


def test_act_open_launches_the_app_waits_for_its_window_and_focuses_it(tmp_path):
    desk = NotesDesk()
    launched = []

    def launch(target):
        launched.append(target)
        desk.extra_windows.append(WindowInfo(55, "Untitled - Paint", 99, "mspaint.exe"))

    desk.launch = launch
    guard = Guard(desk, set())
    chat = Script({"do": "open", "app": "mspaint"}, {"do": "done", "success": False, "summary": "opened"})
    computer, *_ = make_computer(desk, tmp_path, chat, guard=guard)
    result = computer.act("open paint", app_exes={"notes.exe"})
    assert launched == ["mspaint"] and 55 in desk.focused_calls and "mspaint.exe" in guard.exes
    assert result["trace"][0]["ok"] and "Untitled - Paint" in result["trace"][0]["note"]


def test_open_app_reports_failure_when_the_window_cannot_be_brought_to_the_front(tmp_path):
    desk = NotesDesk()
    desk.launch = lambda target: desk.extra_windows.append(WindowInfo(55, "Untitled - Paint", 99, "mspaint.exe"))
    desk.focus = lambda hwnd: False
    computer, *_ = make_computer(desk, tmp_path, None)
    info, message = computer.open_app("mspaint.exe")
    assert info is None and "could not bring it to the front" in message
    info, message = computer.open_app("nonexistent.exe", timeout_s=2)
    assert info is None and "no new window" in message


def test_act_without_a_brain_reports_it(tmp_path):
    computer, *_ = make_computer(NotesDesk(), tmp_path, chat=None)
    assert computer.act("x")["summary"] == "no brain connection"


def test_guard_allows_only_the_chosen_programs():
    desk = Desk()
    assert Guard(desk, None)() is True
    desk.exe = "mspaint.exe"
    assert Guard(desk, {"mspaint.exe"})() is True
    desk.exe = "discord.exe"
    assert Guard(desk, {"mspaint.exe"})() is False
    desk.present = False
    assert Guard(desk, {"mspaint.exe"})() is False


def test_changed_fraction_ignores_a_pointer_sized_change_and_sees_a_real_one():
    a = Image.new("RGB", (800, 600), (200, 200, 200))
    b = a.copy()
    ImageDraw.Draw(b).rectangle((10, 10, 22, 22), fill=(0, 0, 0))             # roughly a pointer
    c = a.copy()
    ImageDraw.Draw(c).rectangle((100, 100, 400, 300), fill=(0, 0, 0))
    assert changed_fraction(a, b) < 0.003 < 0.1 < changed_fraction(a, c)
    assert changed_fraction(a, Image.new("RGB", (10, 10))) == 1.0


def test_parse_action_and_json_objects_cope_with_prose_and_fences():
    assert parse_action('Here you go:\n```json\n{"do":"key","keys":"ctrl+s"}\n```')["keys"] == "ctrl+s"
    assert isinstance(parse_action('{"do":"explode"}'), str)
    assert [d["n"] for d in json_objects('x {"n":1} y {"n": {"deep": "}"}} z')] == [1, {"deep": "}"}]
