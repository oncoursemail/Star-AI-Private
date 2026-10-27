"""Her personal style: wallpaper, accent colour, cursor, sounds, desktop stickers and how her avatar looks, on HER PC only.

What she changes and how (every system change is one PowerShell script through STAR Home's Executor, so the owner's STOP,
the action log and the dry run apply; no UI is driven):
    wallpaper  SystemParametersInfo(SPI_SETDESKWALLPAPER) + the Desktop registry style; from a drawing in her gallery that fits,
               else a new one from the image pipeline (through studio.make_work, so it lands in the gallery with her commentary)
    accent     HKCU DWM AccentColor/ColorizationColor + Explorer\\Accent, from the palette of her mood
    cursor     her own .cur/.ani files in <workspace>/cursors (Arrow, Hand) + SPI_SETCURSORS; none there = nothing to change
    sounds     .wav files in <workspace>/sounds for a few whitelisted events (HKCU AppEvents schemes)
    stickers   up to 3 png files from <workspace>/stickers copied to a "STAR stickers" folder on her Desktop
    icons      not attempted: there is no stable API to arrange single desktop icons
    avatar     outfit, accessory and default expression chosen from the assets that exist (<root>\\assets\\avatar\\outfits and
               \\accessories), else from a built-in cute catalogue, recorded to <home>/life/extras/avatar-style.json for the VTuber
               lane (ChatGPT's); if star.vtuber ever offers `apply_style(style)` it is called, until then `applied` stays False
    outfit ideas  new outfits drawn into her gallery
Desktop widgets have no third-party API on Windows 11, so a widget she would like is only recorded as a wish in the history.
Every readback decides `status`: "applied" only when the system says it now has her value; a dry run or a failure is
recorded as such. Values are validated before they reach a script (hex colours, whitelisted sound events, absolute paths
under her workspace, no quotes or shell characters), so a model's text can never become a command.

Her taste is `style_prefs` (cute traits: pastel, stars, cats...) in [0.05, 1], moved at most 0.1 per experience: choosing
something uses it up a little (variety), a good experience (her own mood after it, or the owner's reaction) raises the traits
of that choice, and unused traits drift back to their resting level. It feeds every pick, nothing else.

Only on her own PC profile: nothing is applied unless `her_pc()` (STAR Home's folder exists, or STAR_HOME_DIR is set), and the
setting `life_style_enabled` (default on) is true. Limits: a wallpaper and an accent colour once a day (earlier only for a new
occasion such as Halloween), cursor and sounds once a week, the avatar twice a day.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import random
import re
import shutil
import time
from pathlib import Path

from . import mood, studio
from .store import LifeStore, day_of, default_store, flag

CUTE = {"pastel": ("pastel", "soft", "baby"), "stars": ("star", "stars", "starry", "constellation"),
        "cats": ("cat", "cats", "kitten", "kitty"), "moon": ("moon", "crescent"), "clouds": ("cloud", "clouds", "fluffy"),
        "bunnies": ("bunny", "bunnies", "rabbit"), "flowers": ("flower", "flowers", "blossom", "sakura"),
        "sweets": ("candy", "sweets", "cake", "strawberry", "dessert"), "rainbows": ("rainbow", "rainbows"),
        "ocean": ("ocean", "sea", "waves", "jellyfish"), "forest": ("forest", "mushroom", "mushrooms", "leaves"),
        "space": ("space", "planet", "galaxy", "rocket"), "robots": ("robot", "robots"), "cozy": ("cozy", "blanket", "warm"),
        "sparkles": ("sparkle", "sparkles", "glitter")}
BASE_WEIGHT = {"pastel": 0.6, "stars": 0.6, "cats": 0.6, "moon": 0.5, "clouds": 0.5, "bunnies": 0.45, "flowers": 0.45,
               "sweets": 0.4, "rainbows": 0.4, "ocean": 0.35, "forest": 0.35, "space": 0.45, "robots": 0.45, "cozy": 0.5,
               "sparkles": 0.5}
MIN_W, MAX_W, STEP, USE_COST, REST_RATE = 0.05, 1.0, 0.1, 0.02, 0.005
PALETTES = {"sunny": ["#FFC857", "#FF9AA2", "#FFDAC1"], "cloudy": ["#B5B9E8", "#C7CEEA", "#A0C4D8"],
            "stormy": ["#5B5F97", "#3D405B", "#7B6D8D"], "starry": ["#2C3E7B", "#F5D76E", "#9B8CD9"],
            "off": ["#F4A6C0", "#B5EAD7", "#E2F0CB"]}
SOUND_EVENTS = {"notification": "Notification.Default", "asterisk": "SystemAsterisk", "exclamation": "SystemExclamation",
                "question": "SystemQuestion"}
LIMIT_S = {"wallpaper": 86400, "accent": 86400, "cursor": 7 * 86400, "sounds": 7 * 86400, "avatar": 12 * 3600,
           "stickers": 7 * 86400}
OUTFITS = {"cozy hoodie": {"cloudy", "winter", "cozy", "autumn"}, "sundress": {"sunny", "summer", "flowers", "spring"},
           "star pajamas": {"starry", "stars", "moon"}, "rain jacket": {"stormy", "autumn", "spring"},
           "witch hat dress": {"halloween"}, "santa scarf": {"christmas", "winter"}, "heart cardigan": {"valentine", "anniversary"},
           "sailor top": {"summer", "ocean"}, "bunny hoodie": {"bunnies", "spring", "easter"}, "cat ear set": {"cats"}}
ACCESSORIES = {"star clips": {"stars", "starry"}, "cat ears": {"cats"}, "flower crown": {"flowers", "spring", "sunny"},
               "moon pin": {"moon", "starry"}, "ribbon": {"pastel", "valentine", "anniversary"}, "scarf": {"winter", "cloudy"},
               "sunglasses": {"summer", "sunny"}}
FACE = {"sunny": "smile", "cloudy": "soft", "stormy": "pout", "starry": "dreamy", "off": "neutral"}
OCCASIONS = [((10, 29), (11, 1), "halloween"), ((12, 23), (12, 26), "christmas"), ((12, 31), (1, 2), "new year"),
             ((2, 13), (2, 15), "valentine")]
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_UNSAFE = re.compile(r"[\x00-\x1f`$;|&<>\"]")
PRAISE = re.compile(r"\b(love|lovely|cute|pretty|beautiful|adorable|nice|like (?:it|that|your)|amazing|so good)\b", re.I)
DISLIKE = re.compile(r"\b(ugly|hate|too much|too bright|too dark|don'?t like|dislike|bad)\b", re.I)
WALLPAPER_EXT = (".png", ".jpg", ".jpeg", ".bmp")


# ---- where she is -----------------------------------------------------------------------------------------------
def her_pc() -> bool:
    """True only on the PC that STAR Home runs on (never on a development checkout or the owner's PC)."""
    try:
        from ..home.paths import home_dir
        if home_dir() is not None:
            return True
    except ImportError:
        pass
    return bool(os.environ.get("STAR_HOME_DIR", "").strip())


def season_of(now: float) -> str:
    month = time.localtime(now).tm_mon
    return "winter" if month in (12, 1, 2) else "spring" if month in (3, 4, 5) else "summer" if month in (6, 7, 8) else "autumn"


def occasions(now: float, extra: tuple[str, ...] = ()) -> list[str]:
    t = time.localtime(now)
    found = list(extra)
    for (m1, d1), (m2, d2), name in OCCASIONS:
        a, b, c = (m1, d1), (m2, d2), (t.tm_mon, t.tm_mday)
        if (a <= c <= b) if a <= b else (c >= a or c <= b):
            found.append(name)
    return found


# ---- host: the only way she changes the system -------------------------------------------------------------------
class ExecutorHost:
    """`run(script) -> (ok, text)` through STAR Home's Executor ("shell" action): logged, stoppable, dry-run aware."""

    def __init__(self, executor) -> None:
        self.executor = executor
        self.dry_run = bool(getattr(executor, "dry_run", False))

    def run(self, script: str) -> tuple[bool, str]:
        result = self.executor.do("shell", {"command": script, "timeout_s": 60})
        return bool(result.ok), str(result.text)


def ps(value: str) -> str:
    """A PowerShell single-quoted literal; refuses characters that could end it or run something."""
    value = str(value)
    if _UNSAFE.search(value):
        raise ValueError("unsafe character in a value for a script")
    return "'" + value.replace("'", "''") + "'"


def safe_path(path, workspace: Path, exts: tuple[str, ...]) -> Path:
    """An existing, non-empty file of the right type inside her workspace (resolved: no `..` tricks)."""
    p = Path(str(path)).resolve()
    try:
        p.relative_to(Path(workspace).resolve())
    except ValueError:
        raise ValueError("the file is not inside her workspace")
    if p.suffix.lower() not in exts or not p.is_file() or p.stat().st_size <= 0:
        raise ValueError(f"not a usable {'/'.join(exts)} file")
    ps(str(p))
    return p


_SPI = ("Add-Type -TypeDefinition 'using System.Runtime.InteropServices; public class StarW { [DllImport(\"user32.dll\", "
        "CharSet=CharSet.Auto)] public static extern int SystemParametersInfo(int a, int b, string c, int d); }'; ")


def wallpaper_script(path: Path) -> str:
    q = ps(str(path))
    return (f"{_SPI}Set-ItemProperty 'HKCU:\\Control Panel\\Desktop' WallpaperStyle '10'; "
            f"Set-ItemProperty 'HKCU:\\Control Panel\\Desktop' TileWallpaper '0'; [StarW]::SystemParametersInfo(20, 0, {q}, 3) | Out-Null; "
            f"(Get-ItemProperty 'HKCU:\\Control Panel\\Desktop').Wallpaper")


def accent_script(hex_color: str) -> str:
    if not _HEX.match(hex_color):
        raise ValueError("accent must be #RRGGBB")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    abgr = (0xFF << 24) | (b << 16) | (g << 8) | r
    argb = (0xC4 << 24) | (r << 16) | (g << 8) | b
    abgr, argb = (v - (1 << 32) if v >= 1 << 31 else v for v in (abgr, argb))      # the registry DWORD as PowerShell's signed int
    return ("$d = 'HKCU:\\Software\\Microsoft\\Windows\\DWM'; "
            "$e = 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Accent'; New-Item $e -Force | Out-Null; "
            f"Set-ItemProperty $d AccentColor {abgr} -Type DWord; Set-ItemProperty $d ColorizationColor {argb} -Type DWord; "
            f"Set-ItemProperty $e AccentColorMenu {abgr} -Type DWord; Set-ItemProperty $e StartColorMenu {abgr} -Type DWord; "
            "rundll32.exe user32.dll,UpdatePerUserSystemParameters; 'accent=' + (Get-ItemProperty $d).AccentColor")


_SPI_CURSORS = ("Add-Type -TypeDefinition 'using System.Runtime.InteropServices; public class StarC { [DllImport(\"user32.dll\")] "
                "public static extern bool SystemParametersInfo(int a, int b, int c, int d); }'")


def cursor_script(arrow: Path, hand: Path | None) -> str:
    lines = ["$c = 'HKCU:\\Control Panel\\Cursors'", f"Set-ItemProperty $c Arrow {ps(str(arrow))}"]
    if hand is not None:
        lines.append(f"Set-ItemProperty $c Hand {ps(str(hand))}")
    lines += [_SPI_CURSORS, "[StarC]::SystemParametersInfo(87, 0, 0, 3) | Out-Null", "(Get-ItemProperty $c).Arrow"]
    return "; ".join(lines)


def sounds_script(pairs: dict[str, Path]) -> str:
    parts = []
    for event, path in pairs.items():
        key = SOUND_EVENTS[event]
        parts.append(f"$k = 'HKCU:\\AppEvents\\Schemes\\Apps\\.Default\\{key}\\.Current'; New-Item $k -Force | Out-Null; "
                     f"Set-ItemProperty $k '(default)' {ps(str(path))}")
    parts.append("'sounds=' + (Get-ItemProperty 'HKCU:\\AppEvents\\Schemes\\Apps\\.Default\\" + SOUND_EVENTS[next(iter(pairs))] +
                 "\\.Current').'(default)'")
    return "; ".join(parts)


def stickers_script(files: list[Path]) -> str:
    copies = "; ".join(f"Copy-Item -LiteralPath {ps(str(f))} -Destination $t -Force" for f in files)
    return ("$t = Join-Path ([Environment]::GetFolderPath('Desktop')) 'STAR stickers'; New-Item -ItemType Directory $t -Force | Out-Null; "
            f"{copies}; 'stickers=' + (Get-ChildItem $t).Count")


# ---- taste ------------------------------------------------------------------------------------------------------
def traits_in(text: str) -> list[str]:
    words = set(re.findall(r"[a-z]+", str(text).lower()))
    return [t for t, names in CUTE.items() if words & set(names) or t in words]


def prefs(store: LifeStore, now: float | None = None) -> dict[str, float]:
    """Her weights per cute trait; unused traits first drift back to their resting level."""
    now = store.clock() if now is None else now
    have = {t: (w, u) for t, w, u in store.rows("SELECT trait, weight, updated FROM style_prefs")}
    out = {}
    for trait, rest in BASE_WEIGHT.items():
        w, updated = have.get(trait, (rest, now))
        days = max(0.0, now - updated) / 86400.0
        w = min(rest, w + REST_RATE * days) if w < rest else max(rest, w - REST_RATE * days)
        out[trait] = round(min(MAX_W, max(MIN_W, w)), 3)
        if trait not in have or abs(out[trait] - w) > 1e-9 or days >= 1:
            store.run("INSERT OR REPLACE INTO style_prefs (trait, weight, updated) VALUES (?,?,?)", (trait, out[trait], now))
    return out


def experience(store: LifeStore, traits: list[str], delta: float, now: float | None = None) -> dict[str, float]:
    """A good (delta > 0) or bad experience with something that had these traits; at most STEP per trait."""
    now = store.clock() if now is None else now
    current = prefs(store, now)
    step = max(-STEP, min(STEP, float(delta)))
    for trait in traits:
        if trait in current:
            current[trait] = round(min(MAX_W, max(MIN_W, current[trait] + step)), 3)
            store.run("UPDATE style_prefs SET weight = ?, updated = ? WHERE trait = ?", (current[trait], now, trait))
    return current


def owner_reaction(store: LifeStore, text: str, now: float | None = None) -> bool:
    """The owner's words about her latest look: praise raises the traits of her last applied change, a dislike lowers them."""
    last = store.rows("SELECT traits FROM style_history WHERE status = 'applied' ORDER BY id DESC LIMIT 1")
    traits = json.loads(last[0][0]) if last and last[0][0] else []
    if not traits:
        return False
    good, bad = bool(PRAISE.search(text)), bool(DISLIKE.search(text))
    if good == bad:
        return False
    experience(store, traits, 0.08 if good else -0.08, now)
    return True


def top_traits(store: LifeStore, rng: random.Random, n: int = 2, now: float | None = None) -> list[str]:
    weights = prefs(store, now)
    names = sorted(weights)
    picked: list[str] = []
    while len(picked) < min(n, len(names)):
        choice = rng.choices([t for t in names if t not in picked], weights=[weights[t] ** 2 for t in names if t not in picked])[0]
        picked.append(choice)
    return picked


# ---- history ----------------------------------------------------------------------------------------------------
def week_of(ts: float) -> str:
    y, w, _ = dt.date.fromtimestamp(ts).isocalendar()
    return f"{y}-W{w:02d}"


def record(store: LifeStore, kind: str, choice: str, *, why: str, status: str, mood_kind: str = "", season: str = "",
           ref: str = "", traits: list[str] | None = None, now: float | None = None) -> int:
    now = store.clock() if now is None else now
    return store.run("INSERT INTO style_history (ts, kind, choice, why, mood, season, ref, status, week, traits) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)", (now, kind, choice[:200], why[:300], mood_kind, season, ref[:300], status,
                                                       week_of(now), json.dumps(traits or []))).lastrowid


HCOLS = ("id", "ts", "kind", "choice", "why", "mood", "season", "ref", "status", "week", "traits")


def history(store: LifeStore, kind: str | None = None, limit: int = 50) -> list[dict]:
    sql = f"SELECT {', '.join(HCOLS)} FROM style_history" + (" WHERE kind = ?" if kind else "") + " ORDER BY id DESC LIMIT ?"
    return [dict(zip(HCOLS, r)) for r in store.rows(sql, ((kind,) if kind else ()) + (limit,))]


def wallpaper_of_the_week(store: LifeStore, now: float | None = None) -> dict | None:
    """The wallpaper she applied most recently in this ISO week (None when she changed none this week)."""
    now = store.clock() if now is None else now
    week = week_of(now)
    rows = [h for h in history(store, "wallpaper", 20) if h["status"] == "applied" and h["week"] == week]
    return rows[0] if rows else None


def style_text(store: LifeStore, now: float | None = None) -> str:
    """For the owner's journal page: the wallpaper of the week and her latest changes, each with its why."""
    lines = []
    pick = wallpaper_of_the_week(store, now)
    if pick:
        lines.append(f"Wallpaper of the week: {pick['choice']} - {pick['why']}")
    for h in history(store, None, 8):
        lines.append(f"{day_of(h['ts'])} {h['kind']} [{h['status']}]: {h['choice']} - {h['why']}")
    top = sorted(prefs(store, now).items(), key=lambda kv: -kv[1])[:4]
    if top:
        lines.append("I like most right now: " + ", ".join(t for t, _ in top))
    return "\n".join(lines)


def due(store: LifeStore, kind: str, now: float, fresh_occasion: bool = False) -> bool:
    last = store.rows("SELECT max(ts) FROM style_history WHERE kind = ? AND status != 'failed'", (kind,))[0][0] or 0
    if fresh_occasion and now - last > 6 * 3600:
        return True
    return now - last >= LIMIT_S[kind]


# ---- choosing ---------------------------------------------------------------------------------------------------
def why_of(mood_kind: str, season: str, occasion: list[str], traits: list[str], mood_why: str = "") -> str:
    """The reason, built only from the facts that drove the pick."""
    bits = [f"it is {season}", f"I feel {mood_kind}" if mood_kind != "off" else "", f"it is {occasion[0]}" if occasion else "",
            f"I like {' and '.join(traits)}" if traits else ""]
    return "; ".join(b for b in bits if b).capitalize() + "."


def _gallery_pick(store: LifeStore, want: set[str], now: float, workspace: Path) -> Path | None:
    used = {h["ref"] for h in history(store, "wallpaper", 60) if now - h["ts"] < 30 * 86400}
    best, best_score = None, 0.0
    for w in studio.works(store, 80, "drawing"):
        if not w["verified"] or w["path"] in used or Path(w["path"]).suffix.lower() not in WALLPAPER_EXT:
            continue
        words = set(re.findall(r"[a-z]+", f"{w['theme']} {w['title']}".lower()))
        score = len(words & want) / max(1, len(want))
        if score > best_score or best is None:
            best, best_score = w, score
    return (Path(best["path"]), best_score) if best else None


def pick_wallpaper(store: LifeStore, *, mood_kind: str, season: str, occasion: list[str], traits: list[str], now: float,
                   workspace: Path, complete=None, generate=None, rng=None) -> tuple[Path | None, str]:
    """(file in her workspace, where it came from): a fitting drawing from her gallery, else a new one, else any unused one."""
    want = set(traits) | {season, mood_kind} | set(occasion) | {n for t in traits for n in CUTE.get(t, ())}
    found = _gallery_pick(store, want, now, workspace)
    source = ""
    if found and found[1] >= 0.3:
        source, path = "gallery", found[0]
    else:
        path = None
        if generate is not None or complete is not None:
            theme = f"cute {' and '.join(traits)} wallpaper, {season} feeling, {mood_kind} colours" + (f", {occasion[0]}" if occasion else "")
            made = studio.make_work(store, kind="drawing", complete=complete, now=now, rng=rng, theme=theme,
                                    makers={"drawing": studio.make_drawing}, **({"generate": generate} if generate else {}))
            if made.get("verified") and made.get("evidence"):
                source, path = "new drawing", Path(made["evidence"][0])
        if path is None and found:
            source, path = "gallery (nothing fitted better)", found[0]
    if path is None or path.suffix.lower() not in WALLPAPER_EXT or not path.is_file():
        return None, ""
    target = Path(workspace) / "style" / "wallpapers" / f"{day_of(now)}-{re.sub(r'[^a-z0-9]+', '-', path.stem.lower())[:30]}{path.suffix.lower()}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.resolve() != path.resolve():
        shutil.copyfile(path, target)
    return target, source


def choose_avatar(mood_kind: str, season: str, occasion: list[str], pref: dict[str, float], assets: dict | None = None,
                  rng: random.Random | None = None) -> dict:
    """Outfit, accessory and default expression from `assets` ({"outfits": [...], "accessories": [...]}) or the catalogue."""
    rng = rng or random.Random()
    tags = {mood_kind, season, *occasion}
    liked = {t for t, w in pref.items() if w >= 0.5}

    def best(options: dict[str, set], available: list[str] | None) -> str:
        names = [n for n in (available if available else options)]
        def score(name: str) -> float:
            own = options.get(name) or set(re.findall(r"[a-z]+", name.lower()))
            return len(own & set(occasion)) * 4 + len(own & tags) * 2 + len(own & liked) + rng.random() * 0.5   # an event beats a season
        return max(names, key=score) if names else ""
    outfits = (assets or {}).get("outfits") or []
    accessories = (assets or {}).get("accessories") or []
    return {"outfit": best(OUTFITS, outfits), "accessory": best(ACCESSORIES, accessories), "expression": FACE.get(mood_kind, "neutral"),
            "from_assets": bool(outfits)}


def scan_assets(root: Path | None) -> dict:
    out = {}
    for kind in ("outfits", "accessories"):
        folder = Path(root) / "assets" / "avatar" / kind if root else None
        out[kind] = sorted(p.stem for p in folder.iterdir() if p.is_file()) if folder and folder.is_dir() else []
    return out


def apply_avatar(store: LifeStore, style: dict, *, vtuber=None) -> bool:
    """Record her look for the avatar lane; call its interface if it has one. True only when the avatar really applied it."""
    path = store.home / "life" / "extras" / "avatar-style.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(style, indent=1), encoding="utf-8")
    try:
        if vtuber is None:
            from .. import vtuber as vtuber_module
            vtuber = vtuber_module
        hook = getattr(vtuber, "apply_style", None)
        return bool(hook(style)) if callable(hook) else False
    except Exception:
        return False


# ---- one pass of her taste ---------------------------------------------------------------------------------------
def refresh(store: LifeStore, host, *, workspace: Path, now: float | None = None, mood_state: dict | None = None,
            history_events: list | None = None, extra_occasions: tuple[str, ...] = (), complete=None, generate=None,
            rng: random.Random | None = None, assets: dict | None = None, vtuber=None, her_pc_now: bool | None = None,
            home=None, force: tuple[str, ...] = ()) -> dict:
    """Do whatever of her style is due, on her PC only. Returns {kind: status} for what she did."""
    now = store.clock() if now is None else now
    rng = rng or random.Random()
    out: dict = {}
    if not flag("life_style_enabled", home or store.home):
        return {"skipped": "style is switched off"}
    allowed = her_pc() if her_pc_now is None else her_pc_now
    workspace = Path(workspace)
    weather = mood.weather_from(mood_state, history_events or [], now=now)
    season, occasion = season_of(now), occasions(now, extra_occasions)
    fresh = bool(occasion) and not store.rows("SELECT 1 FROM style_history WHERE ts > ? AND why LIKE ?",
                                              (now - 86400, f"%{occasion[0]}%"))
    traits = top_traits(store, rng, 2, now)

    def attempt(kind: str, choice: str, script: str | None, check, ref: str = "", extra_traits=None) -> None:
        why = why_of(weather.kind, season, occasion, extra_traits if extra_traits is not None else traits)
        used = extra_traits if extra_traits is not None else traits
        if not allowed:
            record(store, kind, choice, why="not her PC: nothing was changed", status="skipped", mood_kind=weather.kind,
                   season=season, ref=ref, now=now)
            out[kind] = "skipped"
            return
        ok, text = host.run(script)
        status = "applied" if ok and check(text) else ("dry-run" if ok and getattr(host, "dry_run", False) else "failed")
        record(store, kind, choice, why=why, status=status, mood_kind=weather.kind, season=season, ref=ref, traits=used, now=now)
        out[kind] = status
        if status == "applied":
            experience(store, used, -USE_COST, now)             # using a trait a little uses it up: variety

    if "wallpaper" in force or due(store, "wallpaper", now, fresh):
        path, source = pick_wallpaper(store, mood_kind=weather.kind, season=season, occasion=occasion, traits=traits, now=now,
                                      workspace=workspace, complete=complete, generate=generate, rng=rng)
        if path is not None:
            safe = safe_path(path, workspace, WALLPAPER_EXT)
            attempt("wallpaper", f"{safe.name} ({source})", wallpaper_script(safe), lambda t, p=str(safe): p.lower() in t.lower(), str(safe))
        else:
            out["wallpaper"] = "nothing to use yet"
    if "accent" in force or due(store, "accent", now, fresh):
        colour = rng.choice(PALETTES[weather.kind])
        attempt("accent", colour, accent_script(colour), lambda t: "accent=" in t)
    if "cursor" in force or due(store, "cursor", now):
        cur = sorted((workspace / "cursors").glob("*.cur")) + sorted((workspace / "cursors").glob("*.ani")) if (workspace / "cursors").is_dir() else []
        if cur:
            arrow = safe_path(rng.choice(cur), workspace, (".cur", ".ani"))
            attempt("cursor", arrow.name, cursor_script(arrow, None), lambda t, p=str(arrow): p.lower() in t.lower(), str(arrow))
        else:
            out["cursor"] = "no cursor files of hers yet"
    if "sounds" in force or due(store, "sounds", now):
        folder = workspace / "sounds"
        pairs = {}
        for event in SOUND_EVENTS:
            files = sorted(folder.glob(f"{event}*.wav")) if folder.is_dir() else []
            if files:
                pairs[event] = safe_path(rng.choice(files), workspace, (".wav",))
        if pairs:
            attempt("sounds", ", ".join(f"{e}: {p.name}" for e, p in pairs.items()), sounds_script(pairs), lambda t: "sounds=" in t)
        else:
            out["sounds"] = "no sound files of hers yet (name them notification*.wav, asterisk*.wav ...)"
    if "stickers" in force or due(store, "stickers", now):
        folder = workspace / "stickers"
        files = sorted(folder.glob("*.png"))[:3] if folder.is_dir() else []
        if files:
            files = [safe_path(f, workspace, (".png",)) for f in files]
            attempt("stickers", ", ".join(f.name for f in files), stickers_script(files), lambda t: "stickers=" in t)
        else:
            out["stickers"] = "no sticker files of hers yet"
    if "avatar" in force or due(store, "avatar", now, fresh):
        style = choose_avatar(weather.kind, season, occasion, prefs(store, now), assets if assets is not None else scan_assets(_root()), rng)
        style.update({"mood": weather.kind, "season": season, "occasions": occasion, "chosen": int(now)})
        applied = apply_avatar(store, style, vtuber=vtuber) if allowed else False
        record(store, "avatar", f"{style['outfit']} + {style['accessory']}, {style['expression']} face",
               why=why_of(weather.kind, season, occasion, traits), status="applied" if applied else ("skipped" if not allowed else "recorded"),
               mood_kind=weather.kind, season=season, ref="avatar-style.json", traits=traits, now=now)
        out["avatar"] = "applied" if applied else "recorded"
    return out


def _root():
    try:
        from ..home.paths import root
        return root()
    except ImportError:
        return None


def design_outfit_idea(store: LifeStore, *, complete=None, generate=None, now: float | None = None, rng=None) -> dict:
    """Draw a new outfit idea into her gallery (kind drawing) and note it in her style history."""
    now = store.clock() if now is None else now
    traits = top_traits(store, rng or random.Random(), 2, now)
    theme = f"an outfit idea for me, cute, {' and '.join(traits)}, {season_of(now)}"
    made = studio.make_work(store, kind="drawing", complete=complete, now=now, rng=rng, theme=theme,
                            makers={"drawing": studio.make_drawing}, **({"generate": generate} if generate else {}))
    if made.get("verified"):
        record(store, "outfit_idea", theme, why="a new outfit I want to try: " + made["summary"], status="recorded",
               season=season_of(now), ref=made["evidence"][0], traits=traits, now=now)
    return made


def style_activity(registry):
    """Her "personal style" activity: one refresh pass on her own PC through the Executor."""
    def run(ctx) -> dict:
        runtime = getattr(registry, "runtime", None)
        store = default_store(ctx.home)
        complete = None
        if ctx.chat is not None:
            from ..inner.night import complete_from_chat
            complete = complete_from_chat(ctx.chat)
        state = history_events = None
        try:
            from .. import emotion
            if emotion.enabled():
                state, history_events = emotion.current(), emotion.default_engine().history(20)
        except Exception:
            pass
        workspace = Path(getattr(ctx.executor, "workspace", None) or Path(ctx.home).parent / "workspace")
        done = refresh(store, ExecutorHost(ctx.executor), workspace=workspace, mood_state=state, history_events=history_events,
                       complete=complete, home=ctx.home)
        applied = [k for k, v in done.items() if v == "applied"]
        return {"ok": True, "verified": bool(applied), "evidence": [], "steps": len(done),
                "summary": ("changed her look: " + ", ".join(applied)) if applied else
                           ("nothing due or possible: " + json.dumps(done)[:160])}
    return run
