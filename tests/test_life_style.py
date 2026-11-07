"""STAR's personal style (star/life/style.py) on a fake host: nothing here touches a real Windows desktop or registry."""
import json
import random
import time
from types import SimpleNamespace

import pytest

from star import life
from star.life import studio, style
from star.life.store import LifeStore
from tests.test_life_extras import BASE, DAY, Clock, at, fake_brain


@pytest.fixture
def clock():
    return Clock(at(2026, 10, 26))


@pytest.fixture
def home(tmp_path):
    (tmp_path / "workspace").mkdir()
    return tmp_path


class FakeHost:
    """Pretends to be her Windows: answers each script with what the real readback would print."""

    def __init__(self, ok=True, dry_run=False):
        self.scripts, self.ok, self.dry_run = [], ok, dry_run

    def run(self, script):
        self.scripts.append(script)
        if not self.ok:
            return False, "boom"
        if self.dry_run:
            return True, "dry run, not executed"
        if "SystemParametersInfo(20" in script:
            return True, script.split("SystemParametersInfo(20, 0, '")[1].split("'")[0]
        if "AccentColor" in script:
            return True, "accent=1"
        if "Arrow" in script:
            return True, script.split("Arrow '")[1].split("'")[0]
        if "AppEvents" in script:
            return True, "sounds=2"
        if "STAR stickers" in script:
            return True, "stickers=2"
        return True, "ok"


def new_store(home, clock, sub="home"):
    (home / sub).mkdir(exist_ok=True)
    return LifeStore(home=home / sub, clock=clock)


def drawing(store, home, name="moon-cats.png", theme="a sleepy cat under the moon and stars"):
    path = home / "workspace" / "gallery" / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(b"png")
    studio.add_work(store, "drawing", theme, theme=theme, path=str(path), now=store.clock())
    return path


def refresh(store, home, host, clock, **kw):
    kw.setdefault("her_pc_now", True)
    kw.setdefault("assets", {})
    return style.refresh(store, host, workspace=home / "workspace", now=clock.now, rng=random.Random(2), **kw)


def test_ps_and_safe_path_refuse_anything_that_could_become_a_command(home):
    for bad in ("a`b", "a$(whoami)", "a;b", "a\"b", "a|b", "a\nb"):
        with pytest.raises(ValueError):
            style.ps(bad)
    assert style.ps("C:\\it's.png") == "'C:\\it''s.png'"
    inside = home / "workspace" / "a.png"
    inside.write_bytes(b"x")
    assert style.safe_path(inside, home / "workspace", style.WALLPAPER_EXT) == inside.resolve()
    (home / "b.png").write_bytes(b"x")
    (home / "workspace" / "e.png").write_bytes(b"")
    for bad in (home / "b.png", home / "workspace" / ".." / "b.png", home / "workspace" / "missing.png", home / "workspace" / "e.png"):
        with pytest.raises(ValueError):
            style.safe_path(bad, home / "workspace", style.WALLPAPER_EXT)
    with pytest.raises(ValueError):
        style.safe_path(inside, home / "workspace", (".bmp",))


def test_wallpaper_from_her_gallery_is_set_through_the_host_and_logged_with_a_why(home, clock):
    s = new_store(home, clock)
    drawing(s, home)
    host = FakeHost()
    assert refresh(s, home, host, clock, force=("wallpaper",))["wallpaper"] == "applied"
    script = host.scripts[0]
    assert "SystemParametersInfo(20" in script and "WallpaperStyle" in script and "wallpapers" in script
    copied = list((home / "workspace" / "style" / "wallpapers").iterdir())
    assert len(copied) == 1 and copied[0].read_bytes() == b"png"
    pick = style.wallpaper_of_the_week(s, clock.now)
    assert pick and "gallery" in pick["choice"] and pick["why"].startswith("It is autumn") and pick["status"] == "applied"
    assert "Wallpaper of the week" in style.style_text(s, clock.now)


def test_nothing_is_changed_on_a_pc_that_is_not_hers_or_when_switched_off(home, clock):
    s = new_store(home, clock)
    drawing(s, home)
    host = FakeHost()
    done = refresh(s, home, host, clock, her_pc_now=False)
    assert host.scripts == [] and done["wallpaper"] == "skipped" and done["accent"] == "skipped"
    assert style.wallpaper_of_the_week(s, clock.now) is None
    (home / "home" / "settings.json").write_text(json.dumps({"life_style_enabled": False}))
    assert "switched off" in refresh(s, home, host, clock)["skipped"] and host.scripts == []


def test_her_pc_detection(monkeypatch):
    monkeypatch.delenv("STAR_HOME_DIR", raising=False)
    monkeypatch.setattr("star.home.paths.home_dir", lambda: None)
    assert style.her_pc() is False
    monkeypatch.setenv("STAR_HOME_DIR", "D:/STAR/home")
    assert style.her_pc() is True


def test_dry_run_and_failure_are_recorded_as_such_not_as_applied(home, clock):
    s = new_store(home, clock)
    drawing(s, home)
    assert refresh(s, home, FakeHost(dry_run=True), clock, force=("wallpaper",))["wallpaper"] == "dry-run"
    assert refresh(s, home, FakeHost(ok=False), clock, force=("wallpaper",))["wallpaper"] == "failed"
    assert style.wallpaper_of_the_week(s, clock.now) is None


def test_wallpaper_and_accent_once_a_day_and_a_failure_does_not_use_up_the_day(home, clock):
    s = new_store(home, clock)
    drawing(s, home)
    host = FakeHost()
    first = refresh(s, home, host, clock)
    assert first["wallpaper"] == "applied" and first["accent"] == "applied"
    n = len(host.scripts)
    again = refresh(s, home, host, Clock(clock.now + 3600))
    assert "wallpaper" not in again and "accent" not in again and len(host.scripts) == n
    assert "wallpaper" in refresh(s, home, host, Clock(clock.now + 2 * DAY))
    other = new_store(home, clock, "home2")
    assert refresh(other, home, FakeHost(ok=False), clock)["accent"] == "failed"
    assert refresh(other, home, FakeHost(), clock)["accent"] == "applied"


def test_accent_colour_follows_her_mood_and_is_a_valid_signed_dword(home, clock):
    s = new_store(home, clock)
    stormy = {"emotions": {**BASE, "anger": 0.6}, "valence": -0.3, "arousal": 0.8}
    refresh(s, home, FakeHost(), clock, mood_state=stormy, force=("accent",))
    accent = style.history(s, "accent")[0]
    assert accent["choice"] in style.PALETTES["stormy"] and accent["mood"] == "stormy"
    script = style.accent_script("#FFC857")
    assert script.split("AccentColor ")[1].split(" ")[0].startswith("-")          # signed, as PowerShell's DWord wants
    for bad in ("red; calc", "#12345", "#GGGGGG"):
        with pytest.raises(ValueError):
            style.accent_script(bad)


def test_new_wallpaper_is_drawn_into_the_gallery_when_nothing_fits(home, clock):
    s = new_store(home, clock)
    made = []

    def generate(prompt):
        path = home / "workspace" / "new.png"
        path.write_bytes(b"new")
        made.append(prompt)
        return path

    done = refresh(s, home, FakeHost(), clock, complete=fake_brain(), generate=generate, force=("wallpaper",))
    assert done["wallpaper"] == "applied" and made and "wallpaper" in made[0]
    assert studio.works(s, 5, "drawing") and "new drawing" in style.history(s, "wallpaper")[0]["choice"]
    bare = new_store(home, clock, "bare")
    assert refresh(bare, home, FakeHost(), clock, force=("wallpaper",))["wallpaper"] == "nothing to use yet"


def test_cursor_sounds_stickers_need_her_own_files_and_only_whitelisted_events(home, clock):
    s = new_store(home, clock)
    host = FakeHost()
    none = refresh(s, home, host, clock, force=("cursor", "sounds", "stickers"))
    assert "no cursor" in none["cursor"] and "no sound" in none["sounds"] and "no sticker" in none["stickers"]
    assert not [x for x in host.scripts if "Arrow" in x or "AppEvents" in x or "STAR stickers" in x]
    ws = home / "workspace"
    for folder, name in (("cursors", "paw.cur"), ("sounds", "notification-bell.wav"), ("sounds", "evil.wav"),
                         ("sounds", "asterisk-pop.wav"), ("stickers", "cat.png"), ("stickers", "star.png")):
        (ws / folder).mkdir(exist_ok=True)
        (ws / folder / name).write_bytes(b"x")
    done = refresh(s, home, host, clock, force=("cursor", "sounds", "stickers"))
    assert done["cursor"] == done["sounds"] == done["stickers"] == "applied"
    sounds = [x for x in host.scripts if "AppEvents" in x][0]
    assert "Notification.Default" in sounds and "SystemAsterisk" in sounds and "evil" not in sounds
    assert "paw.cur" in [x for x in host.scripts if "Arrow" in x][0]
    assert [x for x in host.scripts if "STAR stickers" in x]


def test_taste_is_bounded_uses_itself_up_drifts_back_and_hears_the_owner(home, clock):
    s = new_store(home, clock)
    start = style.prefs(s, clock.now)
    assert style.traits_in("a sleepy kitten under the starry sky with pastel clouds") == ["pastel", "stars", "cats", "clouds"]
    after = style.experience(s, ["stars", "nonsense"], 5.0, clock.now)
    assert after["stars"] == round(start["stars"] + style.STEP, 3) and "nonsense" not in after
    for _ in range(30):
        style.experience(s, ["stars"], 1.0, clock.now)
        style.experience(s, ["cats"], -1.0, clock.now)
    now = style.prefs(s, clock.now)
    assert now["stars"] == style.MAX_W and now["cats"] == style.MIN_W
    later = style.prefs(s, clock.now + 400 * DAY)
    assert later["stars"] == style.BASE_WEIGHT["stars"] and later["cats"] == style.BASE_WEIGHT["cats"]       # back to rest
    drawing(s, home, name="a.png", theme="stars everywhere")
    refresh(s, home, FakeHost(), clock, force=("wallpaper",))
    used = json.loads(style.history(s, "wallpaper")[0]["traits"])
    before = style.prefs(s, clock.now)
    assert style.owner_reaction(s, "oh that is so cute, I love it", clock.now) is True
    assert any(style.prefs(s, clock.now)[t] > before[t] for t in used)
    assert style.owner_reaction(s, "hmm ok", clock.now) is False
    before = style.prefs(s, clock.now)
    assert style.owner_reaction(s, "ugly, I hate it", clock.now) is True
    assert any(style.prefs(s, clock.now)[t] < before[t] for t in used)


def test_using_a_choice_uses_its_traits_up_a_little(home, clock):
    s = new_store(home, clock)
    drawing(s, home, theme="pastel stars")
    before = style.prefs(s, clock.now)
    refresh(s, home, FakeHost(), clock, force=("wallpaper",))
    used = json.loads(style.history(s, "wallpaper")[0]["traits"])
    assert used and all(style.prefs(s, clock.now)[t] < before[t] for t in used)


def test_season_and_occasions():
    assert style.season_of(at(2026, 10, 26)) == "autumn" and style.season_of(at(2026, 1, 5)) == "winter"
    assert "halloween" in style.occasions(at(2026, 10, 31)) and "christmas" in style.occasions(at(2026, 12, 25))
    assert "new year" in style.occasions(at(2026, 1, 1)) and style.occasions(at(2026, 6, 15)) == []
    assert style.occasions(at(2026, 6, 15), ("anniversary",)) == ["anniversary"]


def test_avatar_look_follows_mood_season_and_event_and_is_recorded_for_the_vtuber_lane(home, clock):
    s = new_store(home, clock)
    done = refresh(s, home, FakeHost(), Clock(at(2026, 10, 31)), force=("avatar",))
    look = json.loads((s.home / "life" / "extras" / "avatar-style.json").read_text())
    assert look["outfit"] == "witch hat dress" and look["from_assets"] is False and "halloween" in look["occasions"]
    assert done["avatar"] == "recorded" and style.history(s, "avatar")[0]["status"] == "recorded"     # no vtuber interface yet
    picked = style.choose_avatar("starry", "winter", [], {"stars": 0.9},
                                 {"outfits": ["plain tee", "star pajamas"], "accessories": []}, random.Random(1))
    assert picked["outfit"] == "star pajamas" and picked["from_assets"] and picked["expression"] == "dreamy"
    called = []
    assert style.apply_avatar(s, {"outfit": "x"}, vtuber=SimpleNamespace(apply_style=lambda st: called.append(st) or True)) is True
    assert called == [{"outfit": "x"}]
    assert style.apply_avatar(s, {"outfit": "x"}, vtuber=SimpleNamespace()) is False
    assert style.scan_assets(None) == {"outfits": [], "accessories": []}
    root = home / "root"
    (root / "assets" / "avatar" / "outfits").mkdir(parents=True)
    (root / "assets" / "avatar" / "outfits" / "sundress.png").write_bytes(b"x")
    assert style.scan_assets(root)["outfits"] == ["sundress"]


def test_avatar_is_not_pushed_on_a_pc_that_is_not_hers(home, clock):
    s = new_store(home, clock)
    called = []
    refresh(s, home, FakeHost(), clock, force=("avatar",), her_pc_now=False, vtuber=SimpleNamespace(apply_style=called.append))
    assert called == [] and style.history(s, "avatar")[0]["status"] == "skipped"


def test_outfit_idea_is_drawn_into_the_gallery_and_logged(home, clock):
    s = new_store(home, clock)

    def generate(prompt):
        path = home / "workspace" / "outfit.png"
        path.write_bytes(b"o")
        return path

    made = style.design_outfit_idea(s, complete=fake_brain(), generate=generate, now=clock.now, rng=random.Random(1))
    assert made["verified"] and studio.works(s, 3, "drawing")
    assert style.history(s, "outfit_idea")[0]["status"] == "recorded"


def test_executor_host_goes_through_the_executor_shell_action():
    seen = []
    executor = SimpleNamespace(dry_run=True, do=lambda action, args: seen.append((action, args)) or SimpleNamespace(ok=True, text="t"))
    host = style.ExecutorHost(executor)
    assert host.run("Get-Date") == (True, "t") and host.dry_run is True
    assert seen == [("shell", {"command": "Get-Date", "timeout_s": 60})]


def test_style_activity_registration_and_run(home, clock, monkeypatch):
    from star.home.activities import Context, Registry
    life_obj = SimpleNamespace(interests=lambda: {}, set_interest=lambda *a: None)
    registry = Registry(runtime=SimpleNamespace(life=life_obj))
    life.register_home_activities(registry)
    assert "personal style" in registry.items
    (home / "home").mkdir(exist_ok=True)
    s = life.default_store(home / "home")
    drawing(s, home)
    executor = SimpleNamespace(dry_run=False, workspace=home / "workspace",
                               do=lambda action, args: SimpleNamespace(ok=True, text=_readback(args["command"])))
    ctx = Context(home=home / "home", config={}, executor=executor, life=life_obj, chat=None, interest="personal_style", goal=None)
    monkeypatch.setattr(style, "her_pc", lambda: True)
    out = registry.items["personal style"].run(ctx)
    assert out["ok"] and out["verified"] and "wallpaper" in out["summary"]


def _readback(script):
    host = FakeHost()
    return host.run(script)[1]


def test_journal_page_shows_her_style_history(home, clock):
    from star.life import api
    s = new_store(home, clock)
    drawing(s, home)
    refresh(s, home, FakeHost(), clock, force=("wallpaper",))
    text = api.journal_text(home / "home", store=s)
    assert "MY STYLE" in text and "Wallpaper of the week" in text
