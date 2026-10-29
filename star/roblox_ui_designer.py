"""STAR's Roblox game-UI designer: brief -> design plan -> design tokens -> one self-contained LocalScript.

The local model only *chooses* (screen archetype, style, content) in a small JSON plan; everything that makes a
UI look designed rather than generated is deterministic here and in the Luau kit (star/data/roblox_ui/):
an 8 px grid, a modular type scale, curated palettes whose text pairs pass WCAG contrast, a reference canvas
scaled with UIScale (never per-device offsets), a compact phone layout, chunky/glass/outline button families
with hover/press/selection tweens, a gamepad focus ring, ButtonB to close, CoreUISafeInsets, TextTruncate on
every single-line label, and item art built from parts in ViewportFrames (no image assets).

Public API: plan_prompt(brief) -> messages, parse_plan(text) -> plan, design(plan) -> tokens,
emit_luau(plan) -> source, static_check(plan) -> findings, design_notes(tokens) -> text.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

KIT_DIR = Path(__file__).with_name("data") / "roblox_ui"

SCREENS = {
    "shop": "item shop / store with currency, tabs, item cards and a detail panel",
    "inventory": "inventory / backpack grid of item slots with a detail panel",
    "hud": "in-game HUD: currencies, health/stamina bars, ability hotbar with cooldowns, objective tracker",
    "settings": "settings menu with toggles, sliders and choice selectors",
    "menu": "main menu or pause menu: big game title, vertical buttons, news card",
    "dialog": "NPC dialogue box with portrait, speaker name, text and choices",
    "leaderboard": "leaderboard with top-3 podium, ranked rows and your own row",
    "rewards": "daily rewards / login calendar with claimed, today and locked days",
    "quest": "quest log: quest list with progress and a quest detail panel",
    "results": "round results / victory or defeat screen with stats and rewards",
    "loading": "loading screen with title, progress bar and tip",
}
KINDS = ["sword", "shield", "potion", "gem", "coin", "chest", "bow", "staff", "helmet", "pet", "crown", "key",
         "scroll", "bomb", "food", "heart", "boots", "lightning"]
RARITIES = ["common", "uncommon", "rare", "epic", "legendary", "mythic"]

# Each style: palette (hex), fonts (Roblox font family file + weight), shape language and effects. Text pairs are
# checked by static_check (>= 4.5:1 body text, >= 3:1 large/dim text).
STYLES: dict[str, dict[str, Any]] = {
    "cartoon": {
        "about": "bright simulator style: chunky 3D buttons, thick outlined text, rounded panels",
        "fonts": {"display": ("FredokaOne", "Regular"), "label": ("FredokaOne", "Regular"),
                  "body": ("Nunito", "Bold"), "numeric": ("FredokaOne", "Regular")},
        "c": {"surface": "#3049C9", "gradientTo": "#B9C3FF", "surface2": "#1E2C86", "stroke": "#0D1440",
              "strokeSoft": "#8796F0", "text": "#FFFFFF", "textDim": "#D3DAFF", "outline": "#0D1440",
              "accent": "#1E9E45", "accentText": "#FFFFFF", "secondary": "#FFB531", "secondaryText": "#3A2300",
              "good": "#5BE37D", "bad": "#FF4F5E", "currency": "#FFC83D", "track": "#141D5C", "focus": "#FFE45C",
              "vignette": "#0B1036", "bannerTop": "#FFF27A", "bannerBottom": "#FF9F1C", "loadingTop": "#2C46C4",
              "gold": "#FFC83D", "silver": "#D8E0EA", "bronze": "#E09A5C"},
        "radius": 14, "strokeWidth": 3, "strokeAlpha": 0, "surfaceAlpha": 0, "surface2Alpha": 0,
        "panelGradient": True, "doubleStroke": False, "textOutline": True, "button": "chunky", "shadow": "drop",
    },
    "scifi": {
        "about": "sci-fi HUD: dark translucent glass, thin cyan strokes, wide technical type",
        "fonts": {"display": ("Michroma", "Regular"), "label": ("TitilliumWeb", "SemiBold"),
                  "body": ("TitilliumWeb", "Regular"), "numeric": ("RobotoMono", "Medium")},
        "c": {"surface": "#08111F", "gradientTo": "#FFFFFF", "surface2": "#0F1C30", "stroke": "#2DE2E6",
              "strokeSoft": "#2A4A63", "text": "#E6F7FF", "textDim": "#8DB0C4", "outline": "#000000",
              "accent": "#2DE2E6", "accentText": "#03161A", "secondary": "#16324A", "secondaryText": "#CFEFFF",
              "good": "#3EF0A0", "bad": "#FF4D6D", "currency": "#FFC35A", "track": "#0A2236", "focus": "#2DE2E6",
              "vignette": "#02060D", "bannerTop": "#E6FDFF", "bannerBottom": "#2DE2E6", "loadingTop": "#0C2438",
              "gold": "#FFC35A", "silver": "#C9D6E2", "bronze": "#D98A57"},
        "radius": 4, "strokeWidth": 1, "strokeAlpha": 0.35, "surfaceAlpha": 0.12, "surface2Alpha": 0.2,
        "panelGradient": False, "doubleStroke": False, "textOutline": False, "button": "glass", "shadow": "glow",
    },
    "fantasy": {
        "about": "fantasy RPG: dark leather panels, gold double borders, serif blackletter titles",
        "fonts": {"display": ("GrenzeGotisch", "Bold"), "label": ("Merriweather", "Bold"),
                  "body": ("Merriweather", "Regular"), "numeric": ("Merriweather", "Bold")},
        "c": {"surface": "#2A1D13", "gradientTo": "#8C7A66", "surface2": "#3B2A1C", "stroke": "#C9A25A",
              "strokeSoft": "#6E5536", "text": "#F3E6C8", "textDim": "#C2AD8C", "outline": "#140C06",
              "accent": "#D4AA5C", "accentText": "#22160C", "secondary": "#5A3F27", "secondaryText": "#F3E6C8",
              "good": "#8CC27A", "bad": "#D0583F", "currency": "#E8BE5A", "track": "#1A110A", "focus": "#F2D48A",
              "vignette": "#0E0804", "bannerTop": "#FFF0C2", "bannerBottom": "#C9A25A", "loadingTop": "#3A2615",
              "gold": "#E8BE5A", "silver": "#CFCAC0", "bronze": "#C2814A"},
        "radius": 6, "strokeWidth": 2, "strokeAlpha": 0, "surfaceAlpha": 0.04, "surface2Alpha": 0.1,
        "panelGradient": True, "doubleStroke": True, "textOutline": True, "button": "chunky", "shadow": "drop",
    },
    "luxury": {
        "about": "dark luxury: near-black, thin gold hairlines, high-contrast serif display, lots of space",
        "fonts": {"display": ("AccanthisADFStd", "Bold"), "label": ("Montserrat", "SemiBold"),
                  "body": ("Montserrat", "Regular"), "numeric": ("Montserrat", "Medium")},
        "c": {"surface": "#0D0D0F", "gradientTo": "#FFFFFF", "surface2": "#17171B", "stroke": "#B8955A",
              "strokeSoft": "#3A342A", "text": "#F4EFE6", "textDim": "#A59E92", "outline": "#000000",
              "accent": "#D8B26E", "accentText": "#141210", "secondary": "#24231F", "secondaryText": "#F4EFE6",
              "good": "#9BD3A2", "bad": "#E06C5C", "currency": "#D8B26E", "track": "#25231F", "focus": "#F1D9A6",
              "vignette": "#050505", "bannerTop": "#FFF6E0", "bannerBottom": "#C9A060", "loadingTop": "#1A1712",
              "gold": "#D8B26E", "silver": "#CFCFD4", "bronze": "#B98458"},
        "radius": 2, "strokeWidth": 1, "strokeAlpha": 0.25, "surfaceAlpha": 0.06, "surface2Alpha": 0.15,
        "panelGradient": False, "doubleStroke": False, "textOutline": False, "button": "flat", "shadow": "drop",
    },
    "anime": {
        "about": "anime action: deep violet panels, hot pink to orange accents, comic display type",
        "fonts": {"display": ("Bangers", "Regular"), "label": ("GothamSSm", "Bold"),
                  "body": ("GothamSSm", "Medium"), "numeric": ("GothamSSm", "Bold")},
        "c": {"surface": "#1B1033", "gradientTo": "#C9B8FF", "surface2": "#2A1A4E", "stroke": "#FF3D8B",
              "strokeSoft": "#5B3E8F", "text": "#FFFFFF", "textDim": "#CDBDF2", "outline": "#12081F",
              "accent": "#FF3D8B", "accentText": "#FFFFFF", "secondary": "#3D2A6E", "secondaryText": "#FFFFFF",
              "good": "#5CF2B0", "bad": "#FF5470", "currency": "#FFD23F", "track": "#120A24", "focus": "#FFD23F",
              "vignette": "#0A0514", "bannerTop": "#FFE36E", "bannerBottom": "#FF3D8B", "loadingTop": "#2A1050",
              "gold": "#FFD23F", "silver": "#DCD6F0", "bronze": "#F0A070"},
        "radius": 10, "strokeWidth": 2, "strokeAlpha": 0, "surfaceAlpha": 0.06, "surface2Alpha": 0.1,
        "panelGradient": True, "doubleStroke": False, "textOutline": True, "button": "chunky", "shadow": "glow",
    },
    "horror": {
        "about": "horror: near-black, typewriter type, desaturated with one blood-red accent",
        "fonts": {"display": ("SpecialElite", "Regular"), "label": ("SpecialElite", "Regular"),
                  "body": ("SourceSansPro", "Regular"), "numeric": ("SpecialElite", "Regular")},
        "c": {"surface": "#0E0C0B", "gradientTo": "#FFFFFF", "surface2": "#1A1615", "stroke": "#4A2420",
              "strokeSoft": "#3A3230", "text": "#E9E1D8", "textDim": "#A3978D", "outline": "#000000",
              "accent": "#B3261E", "accentText": "#FFFFFF", "secondary": "#2A2321", "secondaryText": "#E9E1D8",
              "good": "#8FB88A", "bad": "#E0463C", "currency": "#C9B07A", "track": "#221C1A", "focus": "#E0463C",
              "vignette": "#000000", "bannerTop": "#F2E8DC", "bannerBottom": "#B3261E", "loadingTop": "#140E0D",
              "gold": "#C9B07A", "silver": "#B9B4AE", "bronze": "#9C6B4C"},
        "radius": 2, "strokeWidth": 1, "strokeAlpha": 0.1, "surfaceAlpha": 0.08, "surface2Alpha": 0.15,
        "panelGradient": False, "doubleStroke": False, "textOutline": False, "button": "outline", "shadow": "drop",
    },
    "minimal": {
        "about": "clean modern: light surfaces, one strong accent, geometric sans, soft depth",
        "fonts": {"display": ("BuilderSans", "Bold"), "label": ("BuilderSans", "SemiBold"),
                  "body": ("BuilderSans", "Medium"), "numeric": ("BuilderSans", "Bold")},
        "c": {"surface": "#FFFFFF", "gradientTo": "#FFFFFF", "surface2": "#F1F3F6", "stroke": "#DADFE6",
              "strokeSoft": "#E3E7ED", "text": "#14171C", "textDim": "#5A6270", "outline": "#FFFFFF",
              "accent": "#3D5AFE", "accentText": "#FFFFFF", "secondary": "#E6E9F0", "secondaryText": "#14171C",
              "good": "#13A05A", "bad": "#E5383B", "currency": "#F2A900", "track": "#E3E7ED", "focus": "#3D5AFE",
              "vignette": "#10131A", "bannerTop": "#FFFFFF", "bannerBottom": "#C9D3FF", "loadingTop": "#1E2A5A",
              "gold": "#D9A400", "silver": "#9AA4B2", "bronze": "#B87333"},
        "radius": 12, "strokeWidth": 1, "strokeAlpha": 0, "surfaceAlpha": 0.02, "surface2Alpha": 0,
        "panelGradient": False, "doubleStroke": False, "textOutline": False, "button": "flat", "shadow": "drop",
    },
    "pixel": {
        "about": "retro pixel: hard corners, 2 px white borders, arcade type, limited palette",
        "fonts": {"display": ("PressStart2P", "Regular"), "label": ("PressStart2P", "Regular"),
                  "body": ("RobotoMono", "Bold"), "numeric": ("PressStart2P", "Regular")},
        "c": {"surface": "#1B1B2F", "gradientTo": "#FFFFFF", "surface2": "#272747", "stroke": "#F2F2F2",
              "strokeSoft": "#5A5A8A", "text": "#F2F2F2", "textDim": "#A9A9CC", "outline": "#000000",
              "accent": "#FFD23F", "accentText": "#1B1B2F", "secondary": "#3E3E6E", "secondaryText": "#F2F2F2",
              "good": "#5CDB5C", "bad": "#FF5555", "currency": "#FFD23F", "track": "#0F0F1F", "focus": "#FFD23F",
              "vignette": "#08081A", "bannerTop": "#FFFFFF", "bannerBottom": "#FFD23F", "loadingTop": "#22224A",
              "gold": "#FFD23F", "silver": "#D0D0E0", "bronze": "#D08850"},
        "radius": 0, "strokeWidth": 2, "strokeAlpha": 0, "surfaceAlpha": 0, "surface2Alpha": 0,
        "panelGradient": False, "doubleStroke": False, "textOutline": False, "button": "chunky", "shadow": "drop",
    },
}
RARITY_COLORS = {"common": "#B4BCC8", "uncommon": "#5BD16E", "rare": "#3D9BFF", "epic": "#B45CFF",
                 "legendary": "#FFB21E", "mythic": "#FF4D8D"}
# Reference-pixel type scale (ratio ~1.25 from 16) and 8 px spacing grid; the canvas UIScale maps them to devices.
TYPE_SCALE = {"caption": 13, "body": 16, "label": 17, "h3": 21, "h2": 27, "h1": 34, "display": 56}
PIXEL_TYPE_SCALE = {"caption": 12, "body": 14, "label": 12, "h3": 15, "h2": 18, "h1": 22, "display": 36}
SPACING = [4, 8, 12, 16, 24, 32]
COMPACT_REF = (800, 360)  # phone canvas; scale on an 844x332 safe area = 0.92 -> 16 px body renders at ~14.7 px


# --------------------------------------------------------------------------- the model's part: a small JSON plan

def plan_prompt(brief: str) -> list[dict]:
    screens = "\n".join(f"- {k}: {v}" for k, v in SCREENS.items())
    styles = "\n".join(f"- {k}: {v['about']}" for k, v in STYLES.items())
    system = (
        "You plan Roblox game UI screens. Reply with ONE JSON object only, no prose, no code.\n"
        f"screen (pick one):\n{screens}\nstyle (pick one that fits the game's genre and mood):\n{styles}\n"
        "Fields: screen, style, accent (optional #RRGGBB only if the brief names a colour), title (short, real "
        "game copy, no emoji), subtitle (optional, <= 60 chars), and the content fields the screen uses:\n"
        "- items: list of {name (<= 18 chars), kind (" + "|".join(KINDS) + "), rarity (" + "|".join(RARITIES) +
        "), price (int), stat (short, e.g. '+12 Attack'), owned (bool), count (int), equipped (bool), amount (int)}\n"
        "- currency: {name, amount}; currencies: list of {name, amount, color #RRGGBB}\n"
        "- tabs: list of short names; actions: button labels, primary first (<= 14 chars each)\n"
        "- options (settings): {label, kind toggle|slider|choice, value, choices}\n"
        "- entries (leaderboard): {name, value}; you: {name, value, rank}\n"
        "- quests: {title, description, progress 0-1, reward int, objectives: [{text, done}]}\n"
        "- stats (results): {label, value}; hotbar (hud): {kind, rarity, key, cooldown 0-1}; health {value,max};"
        " stamina 0-1; objective {label, text, progress}\n"
        "- body (dialog line / news text / loading tip), speaker (dialog), today (rewards day index), progress (loading)\n"
        "Use realistic, specific content for the brief (6-12 items for grids, 7 days for rewards, 8-10 entries)."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": brief}]


def _json_object(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in the reply")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            esc = (ch == "\\") and not esc
            if ch == '"' and not esc:
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unterminated JSON object")


_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")


def _clean_text(value: Any, limit: int) -> str:
    text = _EMOJI.sub("", str(value or "")).strip()
    return text[:limit].rstrip()


def parse_plan(text_or_plan: str | dict) -> dict:
    """Validate and clamp a plan from the model. Unknown values fall back to safe defaults, never raise on content."""
    raw = _json_object(text_or_plan) if isinstance(text_or_plan, str) else dict(text_or_plan)
    plan: dict[str, Any] = {}
    screen = str(raw.get("screen", "menu")).lower().strip()
    plan["screen"] = screen if screen in SCREENS else _nearest_screen(screen)
    style = str(raw.get("style", "cartoon")).lower().strip()
    plan["style"] = style if style in STYLES else "cartoon"
    if isinstance(raw.get("accent"), str) and _HEX.match(raw["accent"]):
        plan["accent"] = raw["accent"].upper()
    plan["title"] = _clean_text(raw.get("title") or plan["screen"].title(), 28) or "Menu"
    if raw.get("subtitle"):
        plan["subtitle"] = _clean_text(raw["subtitle"], 64)
    items = []
    for item in (raw.get("items") or [])[:14]:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "gem")).lower()
        rarity = str(item.get("rarity", "common")).lower()
        clean: dict[str, Any] = {"name": _clean_text(item.get("name", "Item"), 18) or "Item",
                 "kind": kind if kind in KINDS else "gem",
                 "rarity": rarity if rarity in RARITIES else "common"}
        for key in ("price", "count", "amount"):
            if isinstance(item.get(key), (int, float)) and not isinstance(item.get(key), bool):
                clean[key] = int(max(0, min(item[key], 10**9)))
        for key in ("owned", "equipped"):
            if isinstance(item.get(key), bool):
                clean[key] = item[key]
        if item.get("stat"):
            clean["stat"] = _clean_text(item["stat"], 40)
        items.append(clean)
    if items:
        plan["items"] = items
    if isinstance(raw.get("currency"), dict):
        plan["currency"] = {"name": _clean_text(raw["currency"].get("name", "Coins"), 14),
                            "amount": _int(raw["currency"].get("amount"), 0)}
    if isinstance(raw.get("currencies"), list):
        plan["currencies"] = [{"name": _clean_text(c.get("name", ""), 14), "amount": _int(c.get("amount"), 0),
                               **({"color": c["color"].upper()} if isinstance(c.get("color"), str) and _HEX.match(c["color"]) else {})}
                              for c in raw["currencies"][:3] if isinstance(c, dict)]
    for key, limit, count in (("tabs", 12, 5), ("actions", 14, 4)):
        if isinstance(raw.get(key), list):
            plan[key] = [_clean_text(v, limit) for v in raw[key][:count] if _clean_text(v, limit)]
    if isinstance(raw.get("options"), list):
        opts = []
        for o in raw["options"][:8]:
            if not isinstance(o, dict):
                continue
            kind = o.get("kind") if o.get("kind") in ("toggle", "slider", "choice") else "toggle"
            opt = {"label": _clean_text(o.get("label", "Option"), 24), "kind": kind}
            if kind == "toggle":
                opt["value"] = bool(o.get("value", True))
            elif kind == "slider":
                opt["value"] = _frac(o.get("value"), 0.5)
            else:
                choices = [_clean_text(c, 9) for c in (o.get("choices") or ["Low", "Medium", "High"])[:4]]
                opt["choices"] = choices or ["Low", "Medium", "High"]
                if o.get("value") in opt["choices"]:
                    opt["value"] = o["value"]
            opts.append(opt)
        plan["options"] = opts
    if isinstance(raw.get("entries"), list):
        plan["entries"] = [{"name": _clean_text(e.get("name", "Player"), 18), "value": _int(e.get("value"), 0)}
                           for e in raw["entries"][:12] if isinstance(e, dict)]
    if isinstance(raw.get("you"), dict):
        plan["you"] = {"name": _clean_text(raw["you"].get("name", "You"), 18), "value": _int(raw["you"].get("value"), 0),
                       "rank": max(1, _int(raw["you"].get("rank"), 42))}
    if isinstance(raw.get("quests"), list):
        quests = []
        for q in raw["quests"][:8]:
            if isinstance(q, dict):
                quests.append({"title": _clean_text(q.get("title", "Quest"), 30),
                               "description": _clean_text(q.get("description", ""), 160),
                               "progress": _frac(q.get("progress"), 0.0), "reward": _int(q.get("reward"), 0),
                               "objectives": [{"text": _clean_text(o.get("text", ""), 40), "done": bool(o.get("done"))}
                                              for o in (q.get("objectives") or [])[:4] if isinstance(o, dict)]})
        plan["quests"] = quests
    if isinstance(raw.get("stats"), list):
        plan["stats"] = [{"label": _clean_text(s.get("label", ""), 16), "value": _clean_text(s.get("value", ""), 12)}
                         for s in raw["stats"][:6] if isinstance(s, dict)]
    if isinstance(raw.get("hotbar"), list):
        plan["hotbar"] = [{"kind": h.get("kind") if h.get("kind") in KINDS else "gem",
                           "rarity": h.get("rarity") if h.get("rarity") in RARITIES else "common",
                           "key": _clean_text(h.get("key", str(i + 1)), 3) or str(i + 1),
                           "cooldown": _frac(h.get("cooldown"), 0.0)}
                          for i, h in enumerate(raw["hotbar"][:8]) if isinstance(h, dict)]
    if isinstance(raw.get("health"), dict):
        mx = max(1, _int(raw["health"].get("max"), 100))
        plan["health"] = {"value": max(0, min(_int(raw["health"].get("value"), mx), mx)), "max": mx}
    if raw.get("stamina") is not None:
        plan["stamina"] = _frac(raw.get("stamina"), 0.7)
    if isinstance(raw.get("objective"), dict):
        plan["objective"] = {"label": _clean_text(raw["objective"].get("label", "Objective"), 18),
                             "text": _clean_text(raw["objective"].get("text", ""), 36),
                             "progress": _frac(raw["objective"].get("progress"), 0.4)}
    for key, limit in (("body", 220), ("speaker", 20)):
        if raw.get(key):
            plan[key] = _clean_text(raw[key], limit)
    if raw.get("today") is not None:
        plan["today"] = max(1, _int(raw.get("today"), 1))
    if raw.get("progress") is not None:
        plan["progress"] = _frac(raw.get("progress"), 0.6)
    return _fill_defaults(plan)


def _int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _frac(value: Any, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v > 1:
        v = v / 100
    return max(0.0, min(v, 1.0))


def _nearest_screen(name: str) -> str:
    aliases = {"store": "shop", "market": "shop", "backpack": "inventory", "bag": "inventory", "pause": "menu",
               "main": "menu", "title": "menu", "lobby": "menu", "options": "settings", "npc": "dialog",
               "dialogue": "dialog", "ranking": "leaderboard", "daily": "rewards", "calendar": "rewards",
               "login": "rewards", "missions": "quest", "victory": "results", "defeat": "results", "end": "results",
               "game over": "results", "load": "loading", "hotbar": "hud", "health": "hud"}
    for key, value in aliases.items():
        if key in name:
            return value
    return "menu"


def _fill_defaults(plan: dict) -> dict:
    s = plan["screen"]
    if s in ("shop", "inventory", "rewards") and not plan.get("items"):
        plan["items"] = [{"name": n, "kind": k, "rarity": r, "price": p} for n, k, r, p in
                         (("Iron Blade", "sword", "common", 120), ("Oak Shield", "shield", "uncommon", 260),
                          ("Swift Tonic", "potion", "rare", 75), ("Star Gem", "gem", "epic", 900))]
    if s == "rewards" and plan.get("items"):
        for i, item in enumerate(plan["items"]):
            item.setdefault("amount", item.get("price") or (i + 1) * 100)
    if s in ("menu", "results", "rewards", "settings", "quest") and not plan.get("actions"):
        plan["actions"] = {"menu": ["Play", "Settings", "Credits"], "results": ["Play Again", "Lobby"],
                           "rewards": ["Claim"], "settings": ["Apply", "Reset"], "quest": ["Track"]}[s]
    if s == "dialog" and not plan.get("actions"):
        plan["actions"] = ["Continue"]
    if s == "hud" and not plan.get("hotbar"):
        plan["hotbar"] = [{"kind": k, "rarity": "rare", "key": str(i + 1), "cooldown": 0.0}
                          for i, k in enumerate(("sword", "bow", "potion", "bomb"))]
    return plan


# --------------------------------------------------------------------------- deterministic design

def _hex_rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def luminance(h: str) -> float:
    def ch(v: int) -> float:
        x = v / 255
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
    r, g, b = _hex_rgb(h)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    x, y = sorted((luminance(a), luminance(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


def _shade(h: str, amount: float) -> str:
    r, g, b = _hex_rgb(h)
    t = 255 if amount > 0 else 0
    a = abs(amount)
    return "#%02X%02X%02X" % tuple(round(c + (t - c) * a) for c in (r, g, b))


def design(plan: dict) -> dict:
    """Design tokens for the plan: palette (accent override kept legible), fonts, type scale, shape and effects."""
    style = STYLES[plan["style"]]
    c = dict(style["c"])
    if plan.get("accent"):
        accent = plan["accent"]
        c["accent"] = accent
        c["focus"] = accent if contrast(accent, c["surface"]) >= 3 else c["focus"]
        c["accentText"] = "#FFFFFF" if contrast(accent, "#FFFFFF") >= contrast(accent, "#111111") else "#111111"
        if contrast(c["accentText"], accent) < 4.5:  # mid-tone accent: darken until white text passes
            for step in range(1, 8):
                darker = _shade(accent, -0.08 * step)
                if contrast("#FFFFFF", darker) >= 4.5:
                    c["accent"], c["accentText"] = darker, "#FFFFFF"
                    break
    tokens = {
        "style": plan["style"],
        "c": c,
        "fonts": {role: {"family": fam, "weight": weight} for role, (fam, weight) in style["fonts"].items()},
        "type": dict(PIXEL_TYPE_SCALE if plan["style"] == "pixel" else TYPE_SCALE),
        "rarity": dict(RARITY_COLORS),
        "spacing": SPACING,
    }
    for key in ("radius", "strokeWidth", "strokeAlpha", "surfaceAlpha", "surface2Alpha", "panelGradient",
                "doubleStroke", "textOutline", "button", "shadow"):
        tokens[key] = style[key]
    return tokens


def design_notes(tokens: dict) -> str:
    c = tokens["c"]
    pairs = [("text/surface", c["text"], c["surface"]), ("textDim/surface", c["textDim"], c["surface"]),
             ("accentText/accent", c["accentText"], c["accent"]), ("text/surface2", c["text"], c["surface2"])]
    lines = [f"style {tokens['style']} | grid 8 px | radius {tokens['radius']} | buttons {tokens['button']} | "
             f"shadow {tokens['shadow']}",
             "type scale (reference px): " + ", ".join(f"{k} {v}" for k, v in tokens["type"].items()),
             "fonts: " + ", ".join(f"{k} {v['family']} {v['weight']}" for k, v in tokens["fonts"].items()),
             "contrast: " + ", ".join(f"{n} {contrast(a, b):.1f}" for n, a, b in pairs),
             "states: hover scale 1.04 + face +10% light (0.14 s Quad); press 0.97 + face into lip (0.08 s);"
             " gamepad focus ring 3 px; open: UIScale 0.94->1 Back + 18 px rise (0.32 s); ButtonB closes",
             "responsive: reference canvas + UIScale fit; compact layout when the safe area is < 900x560;"
             " CoreUISafeInsets; single-line labels truncate, long text wraps"]
    return "\n".join(lines)


def _lua(value: Any, indent: int = 0) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "nil"
    if isinstance(value, (int, float)):
        return repr(round(value, 4)) if isinstance(value, float) else str(value)
    if isinstance(value, str):
        return '"' + "".join(
            ch if 32 <= ord(ch) < 127 and ch not in '"\\' else "\\" + ch if ch in '"\\'
            else "".join(f"\\{b:03d}" for b in ch.encode("utf-8")) for ch in value) + '"'
    if isinstance(value, (list, tuple)):
        return "{ " + ", ".join(_lua(v, indent) for v in value) + " }"
    if isinstance(value, dict):
        items = []
        for k, v in value.items():
            key = k if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k) else "[" + _lua(k) + "]"
            items.append(f"{key} = {_lua(v, indent + 1)}")
        return "{ " + ", ".join(items) + " }"
    raise TypeError(f"cannot encode {type(value).__name__}")


def emit_luau(plan: dict, *, ui_id: str = "Screen") -> str:
    """One self-contained LocalScript (put it in StarterPlayerScripts or StarterGui)."""
    tokens = design(plan)
    data = {k: v for k, v in plan.items() if k not in ("style", "accent")}
    data["id"] = re.sub(r"[^A-Za-z0-9_]", "", ui_id) or "Screen"
    data["closable"] = plan["screen"] not in ("hud", "loading")
    notes = "\n".join("-- " + line for line in design_notes(tokens).splitlines())
    head = (f"--!nonstrict\n-- STAR UI: {plan['screen']} | {plan['title']}\n{notes}\n"
            "-- Client presentation only: purchases and rewards must be validated on the server.\n"
            f"local T = {_lua(tokens)}\nlocal DATA = {_lua(data)}\n")
    kit = (KIT_DIR / "kit.luau").read_text(encoding="utf-8")
    screens = (KIT_DIR / "screens.luau").read_text(encoding="utf-8")
    return head + kit + "\n" + screens


# --------------------------------------------------------------------------- static checks (before any render)

def static_check(plan: dict) -> list[dict]:
    """Findings that need no render: contrast of the text pairs the screen uses, phone text size, touch size."""
    tokens = design(plan)
    c = tokens["c"]
    findings = []
    for name, fg, bg, need in (("body text on panel", c["text"], c["surface"], 4.5),
                               ("dim text on panel", c["textDim"], c["surface"], 3.0),
                               ("text on inner panel", c["text"], c["surface2"], 4.5),
                               ("primary button label", c["accentText"], c["accent"], 3.0),
                               ("secondary button label", c["secondaryText"], c["secondary"], 3.0)):
        ratio = contrast(fg, bg)
        if ratio < need:
            findings.append({"rule": "contrast", "detail": f"{name} {ratio:.2f} < {need}", "severity": "error"})
    phone_scale = min((844 - 16) / COMPACT_REF[0], (332 - 12) / COMPACT_REF[1])
    smallest = min(tokens["type"].values()) * phone_scale
    if smallest < 10:
        findings.append({"rule": "phone_text", "detail": f"smallest text {smallest:.1f} px on a phone",
                         "severity": "warn"})
    if 40 * phone_scale < 34:
        findings.append({"rule": "touch_target", "detail": "close button below 34 px on a phone", "severity": "warn"})
    return findings
