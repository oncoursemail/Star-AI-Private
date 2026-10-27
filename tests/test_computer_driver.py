"""STAR computer use, part 4: the driver (observe -> ground -> act -> verify -> retry), skills, gates, limits, the
owner's stop (file + API), the action log and the machine-identity refusal. All on fake desktops (UIA trees and
screenshots in memory); no real input, no real UI Automation, no real model."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from PIL import ImageDraw
import pytest

from star.computer import identity, skills
from star.computer.actionlog import ActionLog
from star.computer.driver import Driver, Expect, Step
from star.computer.gates import Gated, check_open, check_type, looks_secret
from star.computer.ground import (GroundingChain, StarVisionGrounder, UiaFinder, VisionFinder, bench, default_chain)
from star.computer.grounding import Grounded, synthetic_screen
from star.computer.hands import Stopped
from star.computer.limits import Limited, RateLimits
from star.computer.screen import Element
from star.computer.stopswitch import StopSwitch, owner_token, serve
from star.computer.winapi import WindowInfo
from star.home import control

from test_computer_use import BUTTON, EDIT, WINDOW, Desk, make_computer, node  # noqa: F401

CHECKBOX, TEXT, RADIO = 50002, 50020, 50013
STAR, OTHER = "11111111-aaaa-bbbb-cccc-000000000001", "22222222-aaaa-bbbb-cccc-000000000002"


def inside(rect, x, y):
    return rect[0] <= x < rect[2] and rect[1] <= y < rect[3]


def make_driver(desk, tmp_path, *, enrolled=STAR, here=STAR, chain=None, limits=None):
    computer, hands, clock, home = make_computer(desk, tmp_path)
    if enrolled:
        identity.enroll(home, lambda: enrolled)
    driver = Driver(computer, home=home, chain=chain, limits=limits, read_guid=lambda: here, settle_s=0.0)
    return driver, computer, clock, home


def presses(desk):
    return sum(1 for c in desk.calls if c[:3] == ("button", "left", True))


def approvals(home):
    path = home / "approvals.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


class SettingsDesk(Desk):
    """A Settings window with switches; a click on a switch flips it. `deaf` clicks are ignored (a slow app)."""

    def __init__(self, switches=(("Bluetooth", 0),), deaf=0):
        super().__init__()
        self.title, self.exe, self.hwnd = "Settings", "systemsettings.exe", 5
        self.state = dict(switches)
        self.deaf = deaf
        self.rects = {name: (600, 100 + 60 * i, 660, 130 + 60 * i) for i, name in enumerate(self.state)}
        self.refresh()

    def refresh(self):
        self.nodes = [node("Settings", WINDOW, (0, 0, 1000, 700))] + [
            node(name, BUTTON, self.rects[name], toggle=self.state[name]) for name in self.state] + [
            node("Back", BUTTON, (10, 10, 50, 40)), node("Search", EDIT, (60, 10, 400, 40)),
            node("Home", BUTTON, (10, 50, 50, 80))]

    def on_button(self, name, down, x, y):
        if not down:
            return
        for switch, rect in self.rects.items():
            if inside(rect, x, y):
                if self.deaf > 0:
                    self.deaf -= 1
                    return
                self.state[switch] = 1 - self.state[switch]
                self.refresh()


class FakeGrounder:
    def __init__(self, point=None, boom=False):
        self.point, self.boom, self.calls = point, boom, []

    def locate(self, image, query):
        self.calls.append(query)
        if self.boom:
            raise ConnectionError("server down")
        return Grounded(*self.point, "(x,y)", 0.01) if self.point else None


# ---- machine identity ---------------------------------------------------------------------------------------
def test_driver_refuses_on_any_machine_but_her_enrolled_pc_and_touches_nothing(tmp_path):
    for kw in ({"enrolled": None}, {"enrolled": STAR, "here": OTHER}):
        desk = SettingsDesk()
        with pytest.raises(identity.WrongMachine):
            make_driver(desk, tmp_path / str(len(kw)), **kw)
        assert desk.calls == []


def test_profile_with_another_role_or_garbage_is_refused_and_only_a_hash_is_stored(tmp_path):
    home = tmp_path / "home"
    path = identity.enroll(home, lambda: STAR)
    assert STAR not in path.read_text(encoding="utf-8") and identity.check(home, lambda: STAR) == (True, "")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["role"] = "owner-pc"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert identity.check(home, lambda: STAR)[0] is False
    path.write_text("not json", encoding="utf-8")
    assert identity.check(home, lambda: STAR)[0] is False
    with pytest.raises(identity.WrongMachine):
        identity.fingerprint(lambda: "")


# ---- grounding ----------------------------------------------------------------------------------------------
def test_uia_is_used_first_and_vision_is_never_asked_when_the_tree_has_the_control(tmp_path):
    desk = SettingsDesk()
    local, remote = FakeGrounder((5, 5)), FakeGrounder((5, 5))
    chain = default_chain({}, local=local, remote=remote)
    driver, *_ = make_driver(desk, tmp_path, chain=chain)
    result = driver.run(Step("click", "Bluetooth", expect=Expect(toggle=1)))
    assert result.ok and result.source == "uia" and desk.state["Bluetooth"] == 1
    assert local.calls == [] and remote.calls == []


def test_missing_control_goes_to_local_vision_then_remote_and_a_point_snaps_to_the_uia_control(tmp_path):
    desk = SettingsDesk()
    obs_driver, *_ = make_driver(desk, tmp_path)
    obs = obs_driver.observe()
    local, remote = FakeGrounder(None), FakeGrounder((630, 115))       # remote points inside the Bluetooth switch
    found = GroundingChain([UiaFinder(), VisionFinder(local, "local-vision"),
                            VisionFinder(remote, "remote-vision")]).ground(obs, "the blue toggle at the top")
    assert [n for n, _ in found.tried] == ["uia", "local-vision", "remote-vision"]
    assert found.hit.source == "remote-vision+uia" and found.hit.element.name == "Bluetooth"
    nowhere = FakeGrounder((900, 600))                                  # outside every control: a vision box
    hit = VisionFinder(nowhere).find(obs, "a canvas spot")
    assert hit.element.source == "vision" and hit.element.center == (900, 600)
    assert VisionFinder(FakeGrounder((5000, 5))).find(obs, "x") is None  # off screen = no answer


def test_a_vision_server_that_is_down_is_a_miss_not_a_crash(tmp_path):
    desk = SettingsDesk()
    driver, *_ = make_driver(desk, tmp_path)
    found = GroundingChain([UiaFinder(), VisionFinder(FakeGrounder(boom=True))]).ground(driver.observe(), "Nope")
    assert found.hit is None and found.tried[-1] == ("local-vision", "error ConnectionError")


def test_star_vision_grounder_sends_a_png_and_maps_the_point_back():
    asked = {}

    def ask(settings, question, images, max_tokens, timeout):
        asked["q"], asked["png"] = question, images[0].read_bytes()[:8]
        return type("Seen", (), {"text": 'Here: {"x": 320, "y": 180}'})()

    image, _ = synthetic_screen((2560, 1440))
    found = StarVisionGrounder(object(), ask=ask, max_side=1280).locate(image, "the Alpha button")
    assert asked["png"].startswith(b"\x89PNG") and "1280x720" in asked["q"] and "Alpha" in asked["q"]
    assert (found.x, found.y) == (640, 360)
    assert StarVisionGrounder(object(), ask=lambda *a, **k: "{}").locate(image, "x") is None


def test_bench_scores_each_grounder_on_her_own_cases():
    image, truth = synthetic_screen((1280, 720))
    cases = [{"image": image, "query": label, "rect": [x - 60, y - 20, x + 60, y + 20]} for label, (x, y) in truth]

    class Perfect:
        def locate(self, img, q):
            x, y = dict(truth)[q]
            return Grounded(x, y)

    out = bench(cases, {"perfect": Perfect(), "blind": FakeGrounder(None)})
    assert out["perfect"]["hit_rate"] == 1.0 and out["blind"]["hits"] == 0 and len(out["blind"]["misses"]) == 6


# ---- verify and retry ---------------------------------------------------------------------------------------
def test_a_click_with_no_effect_is_retried_and_verified_on_the_second_attempt(tmp_path):
    desk = SettingsDesk(deaf=1)
    driver, *_ = make_driver(desk, tmp_path)
    result = driver.run(Step("click", "Bluetooth", expect=Expect(toggle=1)))
    assert result.ok and result.attempts == 2 and presses(desk) == 2


def test_a_click_that_changed_something_else_is_not_repeated(tmp_path):
    desk = SettingsDesk(switches=(("Bluetooth", 0), ("Wi-Fi", 0)))
    driver, *_ = make_driver(desk, tmp_path)
    result = driver.run(Step("click", "Bluetooth", expect=Expect(text="Paired devices"), retries=3))
    assert not result.ok and presses(desk) == 1 and desk.state["Bluetooth"] == 1   # one click, never undone


def test_alternative_targets_are_tried_in_order(tmp_path):
    desk = SettingsDesk()
    driver, *_ = make_driver(desk, tmp_path)
    result = driver.run(Step("click", ("Bluetooth & devices toggle", "Bluetooth"), expect=Expect(toggle=1)))
    assert result.ok and result.attempts == 2


def test_gives_up_after_the_retries_and_says_why(tmp_path):
    desk = SettingsDesk(deaf=9)
    driver, *_ = make_driver(desk, tmp_path)
    result = driver.run(Step("click", "Bluetooth", expect=Expect(toggle=1), retries=2))
    assert not result.ok and result.attempts == 3 and "off" in result.detail


# ---- the owner's stop ---------------------------------------------------------------------------------------
def test_stop_file_ends_the_step_before_any_input(tmp_path):
    desk = SettingsDesk()
    driver, _, _, home = make_driver(desk, tmp_path)
    control.stop(home)
    with pytest.raises(Stopped):
        driver.run(Step("click", "Bluetooth"))
    assert desk.calls == []
    assert skills.run_skill(driver, "settings_toggle", page="bluetooth", name="Bluetooth", on=True)["summary"] == \
        "stopped by the owner"


def test_a_trip_mid_move_stops_the_hands(tmp_path):
    desk = SettingsDesk()
    driver, computer, clock, home = make_driver(desk, tmp_path)
    count = {"n": 0}
    original = computer.hands.sleep

    def sleep(dt):
        original(dt)
        count["n"] += 1
        if count["n"] == 40:
            driver.switch.trip("hotkey")

    computer.hands.sleep = sleep
    with pytest.raises(Stopped):
        driver.run(Step("click", "Bluetooth"))
    assert desk.state["Bluetooth"] == 0 and control.stopped(home)


def test_stop_api_needs_the_owner_token_and_resume_is_owner_only(tmp_path):
    home = tmp_path / "home"
    switch = StopSwitch(home)
    server = serve(switch, "127.0.0.1", 0)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        def post(route, token=None):
            request = urllib.request.Request(base + route, data=b"", method="POST",
                                             headers={"X-Owner-Token": token} if token else {})
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.status, json.loads(response.read())
            except urllib.error.HTTPError as err:
                return err.code, {}

        assert post("/stop")[0] == 403 and post("/stop", "wrong-token")[0] == 403 and not control.stopped(home)
        token = owner_token(home)
        assert post("/stop", token) == (200, {"stopped": True}) and control.stopped(home)
        with urllib.request.urlopen(base + "/status", timeout=5) as response:
            assert json.loads(response.read()) == {"stopped": True}
        assert post("/resume", "nope")[0] == 403 and control.stopped(home)
        assert post("/resume", token) == (200, {"stopped": False}) and not control.stopped(home)
        assert owner_token(home) == token
    finally:
        server.shutdown()


# ---- gates --------------------------------------------------------------------------------------------------
def test_buying_is_recorded_for_the_owner_and_never_clicked(tmp_path):
    desk = SettingsDesk()
    desk.nodes.append(node("Buy now", BUTTON, (700, 600, 800, 640)))
    driver, _, _, home = make_driver(desk, tmp_path)
    result = driver.run(Step("click", "Buy now"))
    assert not result.ok and result.gated == "spending money" and presses(desk) == 0
    assert approvals(home)[-1]["reason"] == "spending money"


def test_passwords_and_card_numbers_are_never_typed(tmp_path):
    desk = SettingsDesk()
    desk.nodes += [node("Password", EDIT, (100, 300, 400, 330), password=True),
                   node("Card number", EDIT, (100, 350, 400, 380))]
    driver, *_ = make_driver(desk, tmp_path)
    assert driver.run(Step("type", "Password", text="hunter2")).gated
    assert "secret" in driver.run(Step("type", "Card number", text="abc")).gated
    assert not any(c[0] == "char" for c in desk.calls)
    assert looks_secret("4111 1111 1111 1111") and not looks_secret("call me at 4111 1111 1111 1112")
    with pytest.raises(Gated):
        check_type(Element(1, "Message", "edit", (0, 0, 9, 9)), "my key ghp_abcdefghijklmnopqrstuvwx")


def test_captcha_and_cheat_tools_are_never_handled(tmp_path):
    desk = SettingsDesk()
    desk.nodes.append(node("Verify you are human", TEXT, (100, 500, 400, 530)))
    driver, _, _, home = make_driver(desk, tmp_path)
    result = driver.run(Step("click", "Bluetooth"))
    assert result.gated and "CAPTCHA" in result.gated and presses(desk) == 0
    for name in ("CheatEngine.exe", "Synapse X injector.exe", "autoclicker.exe"):
        with pytest.raises(Gated) as caught:
            check_open(name)
        assert caught.value.never
    assert driver.run(Step("uri", "javascript:alert(1)")).gated


def test_mass_messaging_is_refused():
    clock = {"t": 1000.0}
    limits = RateLimits({"recipients_per_day": 3}, clock=lambda: clock["t"])
    limits.message("ann", "hi! new video up")
    limits.message("bob", "Hi!  new video up")
    with pytest.raises(Gated, match="same text"):
        limits.message("cat", "hi! new video up")
    limits.message("cat", "hey cat, how was the obby?")
    with pytest.raises(Gated, match="different people"):
        limits.message("dan", "hello")
    limits.message("ann", "and one more for ann")                       # people she already talks to are fine
    clock["t"] += 90000
    limits.message("dan", "hello")                                      # a new day


def test_action_pace_is_limited():
    clock = {"t": 0.0}
    limits = RateLimits({"actions_per_minute": 3}, clock=lambda: clock["t"])
    for _ in range(3):
        limits.action()
    with pytest.raises(Limited) as caught:
        limits.action()
    assert 0 < caught.value.retry_after <= 60
    clock["t"] += 61
    limits.action()


# ---- action log ---------------------------------------------------------------------------------------------
def test_every_attempt_is_logged_with_before_and_after_screenshots(tmp_path):
    desk = SettingsDesk(deaf=1)
    driver, _, _, home = make_driver(desk, tmp_path)
    driver.run(Step("click", "Bluetooth", expect=Expect(toggle=1)))
    rows = driver.log.rows()
    assert [r["ok"] for r in rows] == [False, True] and rows[1]["source"] == "uia"
    day = next((home / "computer-log").iterdir())
    for row in rows:
        assert (day / row["before"]).exists() and (day / row["after"]).exists()


def test_old_log_days_are_pruned(tmp_path):
    old = tmp_path / "computer-log" / "20200101"
    old.mkdir(parents=True)
    ActionLog(tmp_path, keep_days=7)
    assert not old.exists()


# ---- skills -------------------------------------------------------------------------------------------------
def test_settings_toggle_reads_the_switch_first_and_clicks_only_when_needed(tmp_path):
    desk = SettingsDesk(switches=(("Bluetooth", 1),))
    desk.launch = lambda target: None
    driver, *_ = make_driver(desk, tmp_path)
    assert skills.settings_toggle(driver, "bluetooth", "Bluetooth", True)["ok"] and presses(desk) == 0
    out = skills.settings_toggle(driver, "bluetooth", "Bluetooth", False)
    assert out["ok"] and desk.state["Bluetooth"] == 0 and presses(desk) == 1


class BrowserDesk(Desk):
    def __init__(self):
        super().__init__()
        self.title, self.exe, self.hwnd = "New tab - Microsoft Edge", "msedge.exe", 7
        self.typed, self.bar = "", False
        self.refresh()

    def refresh(self):
        self.nodes = [node(self.title, WINDOW, (0, 0, 1000, 700)),
                      node("Address and search bar", EDIT, (100, 10, 800, 40), focused=self.bar, value=self.typed)] + [
            node(n, BUTTON, (10 + 30 * i, 10, 35 + 30 * i, 40)) for i, n in enumerate(("Back", "Forward", "Refresh"))]

    def on_key(self, combo):
        if combo == "ctrl+l":
            self.bar, self.typed = True, ""
        elif combo == "enter" and self.bar:
            self.title, self.bar = self.typed.split("//")[-1] + " - Microsoft Edge", False
            ImageDraw.Draw(self.image).rectangle((0, 60, 1000, 700), fill=(255, 255, 255))
        self.refresh()

    def on_char(self, ch):
        if self.bar:
            self.typed += ch
            self.refresh()


def test_browser_go_types_into_the_address_bar_and_sees_the_page(tmp_path):
    desk = BrowserDesk()
    driver, *_ = make_driver(desk, tmp_path)
    out = skills.browser_go(driver, "https://example.org")
    assert out["ok"], out
    assert desk.title == "example.org - Microsoft Edge"
    assert not skills.browser_go(driver, "javascript:alert(1)")["ok"]


class DiscordDesk(Desk):
    def __init__(self):
        super().__init__()
        self.title, self.exe, self.hwnd = "Friends - Discord", "discord.exe", 9
        self.mode, self.typed, self.messages = "", "", []
        self.refresh()

    def refresh(self):
        self.nodes = [node(self.title, WINDOW, (0, 0, 1000, 700)),
                      node("Message", EDIT, (200, 640, 900, 680), focused=self.mode != "switch",
                           value="" if self.mode == "switch" else self.typed),
                      node("Friends", BUTTON, (10, 60, 190, 90))] + (
                         [node("Quick switcher", EDIT, (300, 200, 700, 240), focused=True, value=self.typed)] if self.mode == "switch"
                         else []) + [ node("Nitro", BUTTON, (10, 100, 190, 130)),
                      node("Settings", BUTTON, (10, 640, 50, 680))] + [
            node(m, TEXT, (200, 100 + 30 * i, 900, 125 + 30 * i)) for i, m in enumerate(self.messages)]

    def on_key(self, combo):
        if combo == "ctrl+k":
            self.mode, self.typed = "switch", ""
        elif combo == "enter" and self.mode == "switch":
            self.title, self.mode, self.typed = f"@{self.typed} - Discord", "", ""
            self.messages = [self.title.split(" - ")[0][1:]]
        elif combo == "enter" and self.typed:
            self.messages.append(self.typed)
            self.typed = ""
        self.refresh()

    def on_char(self, ch):
        self.typed += ch
        self.refresh()


def test_discord_dm_and_reply_send_once_each_and_mass_messages_are_refused(tmp_path):
    desk = DiscordDesk()
    driver, _, _, home = make_driver(desk, tmp_path)
    out = skills.discord_dm(driver, "bob", "gg, that obby was fun")
    assert out["ok"], out
    assert desk.messages == ["bob", "gg, that obby was fun"] and desk.title == "@bob - Discord"
    assert skills.discord_reply(driver, "same time tomorrow?")["ok"]
    assert desk.messages[-1] == "same time tomorrow?"
    for who in ("ann", "cat", "dan"):           # the same text to a third person is mass messaging
        result = skills.discord_dm(driver, who, "join my server!")
    assert not result["ok"] and "mass messaging" in result["summary"]
    assert desk.messages == ["dan"]                     # the conversation opened, nothing sent
    assert approvals(home)[-1]["reason"].startswith("the same text")


class InstallerDesk(Desk):
    def __init__(self, serial=False):
        super().__init__()
        self.title, self.exe, self.hwnd = "Setup - Krita", "krita-setup.exe", 11
        self.page, self.offer, self.accepted, self.serial = 0, 1, False, serial
        self.refresh()

    def refresh(self):
        pages = [[node("I accept the agreement", RADIO, (100, 300, 400, 330), toggle=int(self.accepted)),
                  node("I do not accept the agreement", RADIO, (100, 340, 400, 370)),
                  node("Next", BUTTON, (700, 600, 800, 640), enabled=self.accepted)],
                 [node("Install the Yahoo search toolbar (recommended)", CHECKBOX, (100, 300, 500, 330),
                       toggle=self.offer), node("Install", BUTTON, (700, 600, 800, 640))],
                 [node("Krita was installed.", TEXT, (100, 300, 500, 330)), node("Finish", BUTTON, (700, 600, 800, 640))],
                 [node("Krita", TEXT, (100, 300, 500, 330))]]
        extra = [node("Serial key", EDIT, (100, 200, 500, 230))] if self.serial else []
        self.nodes = [node(self.title, WINDOW, (0, 0, 1000, 700)), node("Cancel", BUTTON, (590, 600, 690, 640)),
                      node("Back", BUTTON, (480, 600, 580, 640))] + extra + pages[self.page]

    def on_button(self, name, down, x, y):
        if not down:
            return
        if self.page == 0 and inside((100, 300, 400, 330), x, y):
            self.accepted = True
        elif self.page == 1 and inside((100, 300, 500, 330), x, y):
            self.offer = 0
        elif inside((700, 600, 800, 640), x, y) and (self.page or self.accepted):
            self.page += 1
            self.title = "Krita" if self.page == 3 else self.title
        self.refresh()


def test_install_accepts_the_licence_unticks_the_bundled_offer_and_finishes(tmp_path):
    installer = tmp_path / "krita-setup.exe"
    installer.write_bytes(b"MZ")
    desk = InstallerDesk()
    driver, *_ = make_driver(desk, tmp_path)
    out = skills.install(driver, str(installer))
    assert out["ok"], out
    assert desk.page == 3 and desk.offer == 0 and desk.accepted


def test_install_stops_at_a_serial_key_screen_and_refuses_cheat_tools(tmp_path):
    installer = tmp_path / "tool-setup.exe"
    installer.write_bytes(b"MZ")
    desk = InstallerDesk(serial=True)
    driver, _, _, home = make_driver(desk, tmp_path)
    out = skills.install(driver, str(installer))
    assert not out["ok"] and "secret" in out["summary"] and presses(desk) == 0
    cheat = tmp_path / "CheatEngine75.exe"
    cheat.write_bytes(b"MZ")
    assert "never" in skills.install(driver, str(cheat))["summary"]


def test_roblox_join_opens_the_official_link_and_open_app_focuses_a_running_app(tmp_path):
    desk = SettingsDesk()
    launched = []

    def launch(target):
        launched.append(target)
        desk.extra_windows.append(WindowInfo(20, "Roblox", 30, "robloxplayerbeta.exe", (0, 0, 1000, 700)))

    desk.launch = launch
    driver, *_ = make_driver(desk, tmp_path)
    assert skills.roblox_join(driver, 606849621)["ok"]
    assert launched == ["roblox://experiences/start?placeId=606849621"]
    assert not skills.roblox_join(driver, -1)["ok"]
    desk.focus = lambda hwnd: (setattr(desk, "title", "Roblox"), setattr(desk, "exe", "robloxplayerbeta.exe"), True)[2]
    assert skills.open_app(driver, "RobloxPlayerBeta.exe")["ok"]           # already running: focused, not relaunched
    assert len(launched) == 1 and desk.title == "Roblox"
    assert skills.focus_window(driver, "roblox")["ok"]
    assert skills.run_skill(driver, "nope")["ok"] is False
