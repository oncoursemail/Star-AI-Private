"""STAR computer use (star/computer): screens, UI Automation parsing, grounding, human-like hands, the act() loop and the
draw activity. Everything runs on fakes: a fake desktop receives the same sink calls the real SendInput sink would, and
reports UI Automation nodes and screenshots that change when it is clicked or typed into. No real input, no real UIA."""
from __future__ import annotations

import io
import json

from PIL import Image
import pytest

from star.computer import grounding, risk, settings
from star.computer.agent import Computer
from star.computer.hands import Hands
from star.computer.screen import Element, Screen
from star.computer.uia import RawNode, elements_from
from star.computer.winapi import WindowInfo
from star.home.host import Executor


# ---- fakes ----------------------------------------------------------------------------------------------------
class Clock:
    def __init__(self):
        self.t = 100.0

    def now(self):
        return self.t

    def sleep(self, dt):
        self.t += max(0.0, dt)


class Desk:
    """A fake desktop: sink + windows + UI Automation + screenshots in one object. Subclasses react to input."""
    SIZE = (1000, 700)

    def __init__(self):
        self.calls = []
        self.pos = (0, 0)
        self.held = set()
        self.mods = set()
        self.title, self.exe, self.hwnd = "Desktop", "explorer.exe", 1
        self.nodes: list[RawNode] = []
        self.image = Image.new("RGB", self.SIZE, (190, 190, 190))
        self.extra_windows: list[WindowInfo] = []
        self.focused_calls = []
        self.present = True

    # sink
    def position(self):
        return self.pos

    def move_to(self, x, y):
        self.calls.append(("move", x, y))
        self.pos = (x, y)
        self.on_move(x, y)

    def move_rel(self, dx, dy):
        self.move_to(self.pos[0] + dx, self.pos[1] + dy)

    def button(self, name, down):
        self.calls.append(("button", name, down))
        (self.held.add if down else self.held.discard)(name)
        self.on_button(name, down, *self.pos)

    def key(self, name, down):
        self.calls.append(("key", name, down))
        if name in ("ctrl", "shift", "alt"):
            (self.mods.add if down else self.mods.discard)(name)
        elif down:
            self.on_key("+".join(sorted(self.mods) + [name]))

    def type_char(self, ch):
        self.calls.append(("char", ch))
        self.on_char(ch)

    def wheel(self, notches):
        self.calls.append(("wheel", notches))

    # hooks
    def on_move(self, x, y): ...
    def on_button(self, name, down, x, y): ...
    def on_key(self, combo): ...
    def on_char(self, ch): ...
    def launch(self, target): ...

    # windows
    def foreground(self):
        return WindowInfo(self.hwnd, self.title, 10 + self.hwnd, self.exe, (0, 0, *self.SIZE)) if self.present else None

    def windows(self):
        return ([self.foreground()] if self.present else []) + self.extra_windows

    def info(self, hwnd):
        return next(w for w in self.windows() if w.hwnd == hwnd)

    def focus(self, hwnd):
        self.focused_calls.append(hwnd)
        return True

    def screen_size(self):
        return self.SIZE

    # uia + eye
    def snapshot(self, hwnd):
        return list(self.nodes)

    def grab(self, region=None):
        return self.image.copy()


def node(name, ctype, rect, **kw):
    return RawNode(name, ctype, rect, **kw)


BUTTON, EDIT, WINDOW, LISTITEM, RADIO, GROUP = 50000, 50004, 50032, 50007, 50013, 50026


def make_computer(desk, tmp_path, chat=None, grounder=None, settle=0.0, guard=None, clock=None, seed=1):
    clock = clock or Clock()
    home = tmp_path / "home"
    backend = type("B", (), {"launch": lambda self, t, a: desk.launch(t), "run": lambda *a: (0, ""),
                             "screenshot": lambda *a: None})()
    executor = Executor(home, backend)
    hands = Hands(desk, home=home, clock=clock.now, sleep=clock.sleep, seed=seed)
    cfg = settings.load(home)
    cfg["settle_s"] = settle
    computer = Computer(hands, windows=desk, uia=desk, eye=desk, grounder=grounder, chat=chat, executor=executor,
                        guard=guard, settings=cfg, home=home, clock=clock.now, sleep=clock.sleep, seed=seed)
    return computer, hands, clock, home


def prompt_id(prompt, name):
    """The id the screen listing gives to a control called `name` (what a real model reads)."""
    for line in prompt.splitlines():
        if f"'{name}'" in line and line.startswith("["):
            return int(line[1:line.index("]")])
    raise AssertionError(f"{name!r} not in the listing:\n{prompt}")


class Script:
    """A fake planner: each turn it is called with the messages and returns the next scripted action (a dict, or a
    function of the screen listing returning a dict)."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.prompts = []

    def __call__(self, messages, tools):
        listing = messages[-1]["content"]
        self.prompts.append(listing)
        step = self.steps.pop(0) if self.steps else {"do": "done", "success": False, "summary": "script ended"}
        action = step(listing) if callable(step) else step
        return {"content": "Sure.\n```json\n" + json.dumps(action) + "\n```"}


# ---- screen ---------------------------------------------------------------------------------------------------
def els(*specs):
    return [Element(i, n, r, rect, "uia", **kw) for i, (n, r, rect, kw) in enumerate(specs, 1)]


def test_screen_find_ranks_exact_then_substring_then_fuzzy():
    s = Screen(els(("Save as", "button", (0, 0, 40, 20), {}), ("Save", "button", (50, 0, 90, 20), {}),
                   ("Safe mode", "text", (0, 30, 80, 50), {}), ("Open", "button", (0, 60, 40, 80), {})))
    hits = [e.name for _, e in s.find("save")]
    assert hits[0] == "Save" and hits[1] == "Save as"
    assert s.find("zzzz", limit=1)[0][0] < 0.5
    assert s.find("") == []


def test_screen_difference_and_text_checks():
    a = Screen(els(("File", "menuitem", (0, 0, 40, 20), {})), "Notes", hwnd=1)
    same = Screen(els(("File", "menuitem", (0, 0, 40, 20), {})), "Notes", hwnd=1)
    moved = Screen(els(("File", "menuitem", (0, 0, 40, 20), {}), ("Save", "menuitem", (0, 20, 40, 40), {})), "Notes", hwnd=1)
    other = Screen(els(("File", "menuitem", (0, 0, 40, 20), {})), "Save As", hwnd=2)
    assert a.difference(same) == 0.0
    assert 0.3 < a.difference(moved) < 0.7
    assert a.difference(other) == 1.0
    assert moved.has_text("save") and not a.has_text("save") and a.has_text("notes")


def test_screen_prompt_lists_ids_flags_and_hides_password_values():
    s = Screen(els(("Name", "edit", (0, 0, 80, 20), {"value": "alex", "focused": True}),
                   ("Secret", "edit", (0, 30, 80, 50), {"value": "hunter2", "password": True}),
                   ("Go", "button", (0, 60, 40, 80), {"enabled": False})), "Form", "app.exe", 5, (1000, 700))
    text = s.prompt()
    assert "[1] edit 'Name' = 'alex' focused" in text
    assert "hunter2" not in text and "password" in text
    assert "[3] button 'Go' disabled" in text
    assert "window 'Form'" in text and "1000x700" in text
    assert "more elements" in Screen(els(*[(f"b{i}", "button", (0, i, 9, i + 9), {}) for i in range(10)])).prompt(limit=4)


def test_screen_thin_means_fewer_than_four_interactive_controls():
    assert Screen(els(("a", "text", (0, 0, 9, 9), {}))).thin
    assert not Screen(els(*[(f"b{i}", "button", (0, i, 9, i + 9), {}) for i in range(4)])).thin


# ---- UI Automation parsing -------------------------------------------------------------------------------------
def test_elements_from_filters_numbers_and_prefers_interactive_under_the_cap():
    nodes = [node("Title", 50020, (0, 0, 100, 20)),
             node("Hidden", BUTTON, (0, 0, 50, 20), offscreen=True),
             node("Tiny", BUTTON, (0, 0, 1, 1)),
             node("Far", BUTTON, (5000, 0, 5050, 20)),
             node("", 50020, (0, 30, 50, 50)),                           # unnamed text: nothing to say
             node("", EDIT, (0, 60, 90, 80), auto_id="query"),           # unnamed edit: kept, named by automation id
             node("OK", BUTTON, (0, 100, 40, 120)),
             node("OK", BUTTON, (0, 100, 40, 120)),                      # duplicate
             node("Label  two\nlines", 50020, (0, 130, 90, 150))]
    out = elements_from(nodes, (1000, 700))
    assert [(e.id, e.role, e.name) for e in out] == [(1, "text", "Title"), (2, "edit", "query"), (3, "button", "OK"),
                                                     (4, "text", "Label two lines")]
    capped = elements_from([node(f"t{i}", 50020, (0, i * 20, 80, i * 20 + 18)) for i in range(20)] +
                           [node("Go", BUTTON, (0, 500, 40, 520))], (1000, 700), max_elements=5)
    assert any(e.name == "Go" for e in capped) and len(capped) == 5
    assert [e.id for e in capped] == [1, 2, 3, 4, 5]


# ---- grounding -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("<|box_start|>(412,300)<|box_end|>", (412, 300)),
    ("click(start_box='<|box_start|>(10, 20)<|box_end|>')", (10, 20)),
    ("[512, 288]", (512, 288)),
    ("<point>12.5 80</point>", (12.5, 80)),
    ('<tool_call>{"name":"computer_use","arguments":{"action":"left_click","coordinate":[640, 360]}}</tool_call>',
     (640, 360)),
    ('{"x": 5, "y": 9}', (5, 9)),
    ("(100, 200, 300, 400)", (200, 300)),
])
def test_parse_point_reads_every_known_answer_style(text, expected):
    assert grounding.parse_point(text) == expected


def test_parse_point_none_when_no_numbers():
    assert grounding.parse_point("I cannot see it") is None


def test_smart_resize_matches_qwen_rules():
    assert grounding.smart_resize(1080, 1920) == (1092, 1932)
    assert grounding.smart_resize(10, 10) == (56, 56)
    h, w = grounding.smart_resize(4000, 6000)
    assert h % 28 == 0 and w % 28 == 0 and h * w <= 16384 * 28 * 28


def test_to_pixels_conventions():
    assert grounding.to_pixels((500, 500), (1000, 600), "unit1000") == (500, 300)
    assert grounding.to_pixels((0.5, 0.5), (1000, 600), "unit1") == (500, 300)
    assert grounding.to_pixels((10, 20), (1000, 600), "pixels") == (10, 20)
    rh, rw = grounding.smart_resize(600, 1000)
    assert grounding.to_pixels((rw / 2, rh / 2), (1000, 600), "resized") == (500, 300)
    assert grounding.to_pixels((5000, 5000), (1000, 600), "pixels") == (999, 599)       # clamped to the image


@pytest.mark.parametrize("fmt", grounding.FORMATS)
def test_detect_format_recovers_the_convention_that_produced_the_answers(fmt):
    size = (1280, 720)
    truth = [(256, 144), (896, 108), (576, 324), (192, 540), (1024, 432), (704, 612)]
    sx = {"pixels": (1, 1), "unit1000": (1000 / 1280, 1000 / 720), "unit1": (1 / 1280, 1 / 720)}
    rh, rw = grounding.smart_resize(720, 1280)
    sx["resized"] = (rw / 1280, rh / 720)
    raw = [(x * sx[fmt][0], y * sx[fmt][1]) for x, y in truth]
    best, errors = grounding.detect_format(raw, truth, size)
    assert best == fmt and errors[fmt] < 2


def test_vlm_grounder_sends_the_image_and_maps_the_point_back_to_screen_pixels():
    seen = {}

    class Reply:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self.body

    def opener(request, timeout):
        seen["payload"] = json.loads(request.data.decode())
        seen["url"] = request.full_url
        return Reply(json.dumps({"choices": [{"message": {"content": "(500, 250)"}}]}).encode())

    g = grounding.VlmGrounder("http://127.0.0.1:8081", "m", fmt="unit1000", max_side=640, opener=opener)
    found = g.locate(Image.new("RGB", (1920, 1080)), "the red heart")
    assert seen["url"] == "http://127.0.0.1:8081/v1/chat/completions"
    content = seen["payload"]["messages"][0]["content"]
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "the red heart" in content[1]["text"] and seen["payload"]["temperature"] == 0
    sent = Image.open(io.BytesIO(__import__("base64").b64decode(content[0]["image_url"]["url"].split(",", 1)[1])))
    assert max(sent.size) == 640
    assert (found.x, found.y) == (960, 270)


def test_vlm_grounder_none_when_the_model_names_no_point():
    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "no such element"}}]}).encode()

    assert grounding.VlmGrounder("http://x/v1", "m", opener=lambda r, timeout: Reply()).locate(
        Image.new("RGB", (100, 100)), "x") is None


def test_settings_defaults_unknown_keys_and_grounder_factory(tmp_path):
    assert settings.load(tmp_path)["grounder"]["kind"] == "none"
    assert settings.make_grounder(settings.load(tmp_path)) is None
    (tmp_path / "computer.json").write_text(json.dumps({
        "grounder": {"kind": "vlm", "url": "http://h:1/v1", "model": "ui-tars-2b", "format": "unit1000", "evil": 1},
        "settle_s": 0.1, "bogus": True, "speed_px_s": "fast"}), encoding="utf-8")
    cfg = settings.load(tmp_path)
    assert cfg["settle_s"] == 0.1 and cfg["speed_px_s"] == 380 and "evil" not in cfg["grounder"]
    g = settings.make_grounder(cfg)
    assert g.fmt == "unit1000" and g.model == "ui-tars-2b"
    assert {"ui-tars-1.5-7b", "ui-tars-2b", "qwen3-vl-4b"} <= set(grounding.MODELS)


# ---- risk ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name,why", [("Buy now", "spending money"), ("Place your order", "spending money"),
                                      ("Sign up", "creating an account"), ("Delete my account", "deleting an account"),
                                      ("Post", "posting publicly")])
def test_risky_click_names(name, why):
    assert risk.risky_click(Element(1, name, "button", (0, 0, 9, 9))) == why


def test_ordinary_controls_are_not_risky_and_passwords_are_refused():
    for name in ("Save", "Open file", "Postpone", "Compose post draft", "Brush"):
        assert risk.risky_click(Element(1, name, "button", (0, 0, 9, 9))) == ""
    assert risk.refuses_typing(Element(1, "Password", "edit", (0, 0, 9, 9), password=True))
    assert risk.refuses_typing(Element(1, "Name", "edit", (0, 0, 9, 9))) == ""
    assert risk.refuses_typing(None) == ""


def test_calibrate_measures_the_convention_of_a_model_that_answers_in_0_to_1000(tmp_path):
    image, truth = grounding.synthetic_screen((1280, 720))
    where = {label: pos for label, pos in truth}

    class Reply:
        def __init__(self, text):
            self.text = text

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": self.text}}]}).encode()

    def opener(request, timeout):
        question = json.loads(request.data.decode())["messages"][0]["content"][1]["text"]
        label = next(k for k in where if k in question)
        x, y = where[label]
        return Reply(f"<|box_start|>({round(x / 1280 * 1000)},{round(y / 720 * 1000)})<|box_end|>")

    g = grounding.VlmGrounder("http://h/v1", "m", fmt="auto", max_side=640, opener=opener)
    assert g.fmt == "pixels"                                   # until measured
    fmt, errors = g.calibrate()
    assert fmt == "unit1000" and g.fmt == "unit1000" and errors["unit1000"] < 2 < errors["pixels"]
    found = g.locate(image, "the button labelled Echo")
    assert abs(found.x - where["Echo"][0]) < 3 and abs(found.y - where["Echo"][1]) < 3
