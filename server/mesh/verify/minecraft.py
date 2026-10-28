"""Minecraft Java command checks (syntax since 1.13 / 1.20.5 / 1.21): the common commands get a real argument check,
every other command is only checked for a known name. Function files (.mcfunction) take no leading slash.
"""
from __future__ import annotations

import json
import re

from .apidump import closest

JAVA_VERSION = "1.21.x"
COMMANDS = set("""advancement attribute ban ban-ip banlist bossbar clear clone damage data datapack debug
defaultgamemode deop dialog difficulty effect enchant execute experience fetchprofile fill fillbiome forceload function
gamemode gamerule give help item jfr kick kill list locate loot me msg op pardon pardon-ip particle perf place
playsound publish random recipe reload return ride rotate save-all save-off save-on say schedule scoreboard seed
setblock setidletimeout setworldspawn spawnpoint spectate spreadplayers stop stopsound summon tag team teammsg tell
tellraw test tick time title tm tp transfer trigger version w waypoint weather whitelist worldborder xp
teleport""".split())
SELECTOR_KEYS = {"x", "y", "z", "distance", "dx", "dy", "dz", "type", "name", "team", "tag", "scores", "limit",
                 "sort", "level", "gamemode", "x_rotation", "y_rotation", "nbt", "advancements", "predicate"}
OLD_SELECTOR_KEYS = {"r": "distance=..R", "rm": "distance=RM..", "c": "limit=", "m": "gamemode=", "l": "level=..L",
                     "lm": "level=LM..", "rx": "x_rotation", "rxm": "x_rotation", "ry": "y_rotation",
                     "rym": "y_rotation"}
EXECUTE_SUBS = {"align", "anchored", "as", "at", "facing", "if", "in", "on", "positioned", "rotated", "run",
                "store", "summon", "unless"}
RESLOC = re.compile(r"^#?([a-z0-9_.-]+:)?[a-z0-9_./-]+$")
COORD = re.compile(r"^([~^]?-?(\d+\.?\d*|\.\d+)?|-?(\d+\.?\d*|\.\d+))$")
INT = re.compile(r"^-?\d+$")
# a value the reader fills in: <spawn_x>, <player>, [X], {x}, X_POS, a lone X/Y/Z
PLACEHOLDER = re.compile(r"^(<[^<>]+>|\[[A-Za-z_][\w ]*\]|\{[A-Za-z_][\w ]*\}|[A-Z][A-Z0-9]*(_[A-Z0-9]+)+|[XYZxyz])$")
FILL_MODES = {"destroy", "hollow", "keep", "outline", "replace", "strict"}
SETBLOCK_MODES = {"destroy", "keep", "replace", "strict"}


def split_args(line: str) -> list[str]:
    """Split on spaces, keeping [...], {...} and quoted strings together with what they are attached to."""
    out, cur, depth, quote = [], "", 0, ""
    for ch in line:
        if quote:
            cur += ch
            if ch == quote and not cur.endswith("\\" + quote):
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "[{(":
            depth += 1
        elif ch in "]})":
            depth -= 1
        if ch == " " and depth <= 0 and cur:
            out.append(cur)
            cur = ""
        elif ch != " " or depth > 0:
            cur += ch
    if cur:
        out.append(cur)
    return out


class Checker:
    def __init__(self):
        self.problems: list[dict] = []
        self.line = 0

    def add(self, kind, message, suggestion=None, name=None, severity="error"):
        self.problems.append({"kind": kind, "severity": severity, "name": name, "message": message,
                              "suggestion": suggestion, "line": self.line})

    # ---- argument kinds ----
    def target(self, a: str | None, what="target") -> bool:
        if a is None:
            self.add("mc_syntax", f"missing {what}")
            return False
        if PLACEHOLDER.match(a):
            return True
        if a.startswith("@"):
            m = re.match(r"^@([parsen])(\[(.*)\])?$", a)
            if not m:
                self.add("mc_selector", f"bad selector '{a}'", "@p, @a, @r, @s, @e or @n", a)
                return False
            for part in split_args((m.group(3) or "").replace(",", " ")):
                key = part.split("=", 1)[0].strip()
                if key in OLD_SELECTOR_KEYS:
                    self.add("mc_selector", f"selector argument '{key}' was removed in 1.13",
                             OLD_SELECTOR_KEYS[key], key)
                elif key.startswith("score_"):
                    self.add("mc_selector", f"'{key}' was removed in 1.13", "scores={objective=min..max}", key)
                elif key and key not in SELECTOR_KEYS:
                    self.add("mc_selector", f"unknown selector argument '{key}'",
                             " or ".join(closest(key, SELECTOR_KEYS)) or None, key)
            return True
        if re.match(r"^[A-Za-z0-9_]{1,16}$", a) or re.match(r"^[0-9a-f-]{36}$", a):
            return True
        self.add("mc_syntax", f"'{a}' is not a valid {what}", None, a)
        return False

    def coords(self, args: list[str], i: int, n=3) -> bool:
        triple = args[i:i + n]
        if len(triple) < n:
            self.add("mc_syntax", f"expected {n} coordinates, got {len(triple)}")
            return False
        bad = [c for c in triple if not PLACEHOLDER.match(c) and (not COORD.match(c) or c in ("-", ""))]
        if bad:
            self.add("mc_syntax", f"'{bad[0]}' is not a coordinate", "a number, ~ (relative) or ^ (local)", bad[0])
            return False
        if any(c.startswith("^") for c in triple) and not all(c.startswith("^") for c in triple):
            self.add("mc_syntax", "local (^) and world (~ or numbers) coordinates cannot be mixed", None,
                     " ".join(triple))
            return False
        return True

    def resloc(self, a: str | None, what: str) -> bool:
        if a is None:
            self.add("mc_syntax", f"missing {what}")
            return False
        base = re.split(r"[\[{]", a, 1)[0]
        if not RESLOC.match(base) and not PLACEHOLDER.match(a):
            msg = f"'{base}' is not a valid {what} id"
            sugg = base.lower() if RESLOC.match(base.lower()) else None
            if re.search(r"[A-Z]", base):
                msg += " (ids are lowercase since 1.13)"
            self.add("mc_syntax", msg, sugg, base)
            return False
        return True

    # ---- commands ----
    def command(self, text: str, in_function: bool):
        text = text.strip()
        if text.startswith("/"):
            if in_function:
                self.add("mc_function", "commands in a .mcfunction file have no leading '/'", text[1:].split(" ")[0])
            text = text[1:]
        args = split_args(text)
        if not args:
            return
        cmd, rest = args[0], args[1:]
        if cmd.startswith("minecraft:"):
            cmd = cmd[10:]
        if cmd not in COMMANDS:
            self.add("mc_unknown_command", f"unknown command '/{cmd}'",
                     " or ".join("/" + c for c in closest(cmd, COMMANDS)) or None, cmd)
            return
        fn = getattr(self, "c_" + cmd.replace("-", "_"), None)
        if fn:
            fn(rest)

    def c_give(self, a):
        if not self.target(a[0] if a else None):
            return
        if len(a) < 2:
            return self.add("mc_syntax", "give needs an item")
        item = a[1]
        if "{" in item and "[" not in item.split("{")[0]:
            self.add("mc_syntax", "item NBT like {display:...} was replaced by item components in 1.20.5",
                     "item[component=value], e.g. diamond_sword[enchantments={sharpness:5}]", item)
        self.resloc(item, "item")
        if len(a) >= 3 and not INT.match(a[2]):
            self.add("mc_syntax", f"count must be a whole number, got '{a[2]}'", None, a[2])
        if len(a) >= 4:
            self.add("mc_syntax", "give takes <targets> <item> [count]; data values were removed in 1.13",
                     "use the item's own id, e.g. red_wool", a[3])

    def c_tp(self, a):
        if not a:
            return self.add("mc_syntax", "tp needs a destination")
        if len(a) == 1:
            return self.target(a[0], "destination")
        if len(a) == 3 and COORD.match(a[0]):
            return self.coords(a, 0)
        if not self.target(a[0]):
            return
        if len(a) == 2:
            return self.target(a[1], "destination")
        if self.coords(a, 1) and len(a) > 4:
            if a[4] == "facing":
                if len(a) > 5 and a[5] == "entity":
                    self.target(a[6] if len(a) > 6 else None)
                else:
                    self.coords(a, 5)
            elif len(a) >= 6:
                self.coords(a, 4, 2)

    c_teleport = c_tp

    def c_execute(self, a):
        i = 0
        if a and a[0].startswith("@"):
            return self.add("mc_syntax", "this is the pre-1.13 /execute form", "execute as <targets> at @s run <command>",
                            "execute " + a[0])
        while i < len(a):
            sub = a[i]
            if sub not in EXECUTE_SUBS:
                return self.add("mc_syntax", f"unknown execute subcommand '{sub}'",
                                " or ".join(closest(sub, EXECUTE_SUBS)) or None, sub)
            i += 1
            if sub == "run":
                if i >= len(a):
                    return self.add("mc_syntax", "execute ... run needs a command")
                return self.command(" ".join(a[i:]), False)
            if sub in ("as", "at"):
                self.target(a[i] if i < len(a) else None)
                i += 1
            elif sub == "positioned":
                if i < len(a) and a[i] == "as":
                    self.target(a[i + 1] if i + 1 < len(a) else None)
                    i += 2
                elif i < len(a) and a[i] == "over":
                    i += 2
                else:
                    self.coords(a, i)
                    i += 3
            elif sub == "rotated":
                if i < len(a) and a[i] == "as":
                    self.target(a[i + 1] if i + 1 < len(a) else None)
                    i += 2
                else:
                    self.coords(a, i, 2)
                    i += 2
            elif sub == "facing":
                if i < len(a) and a[i] == "entity":
                    self.target(a[i + 1] if i + 1 < len(a) else None)
                    i += 3
                else:
                    self.coords(a, i)
                    i += 3
            elif sub in ("align", "anchored", "in", "on", "summon"):
                i += 1
            elif sub in ("if", "unless"):
                i = self._condition(a, i)
                if i < 0:
                    return
            elif sub == "store":
                i += 1                                   # result | success
                kind = a[i] if i < len(a) else ""
                i += 1 + {"block": 5, "bossbar": 2, "entity": 4, "score": 2, "storage": 4}.get(kind, 0)
                if kind not in ("block", "bossbar", "entity", "score", "storage"):
                    return self.add("mc_syntax", f"execute store needs block|bossbar|entity|score|storage, got '{kind}'")

    def _condition(self, a, i):
        kind = a[i] if i < len(a) else ""
        i += 1
        if kind == "entity":
            self.target(a[i] if i < len(a) else None)
            return i + 1
        if kind == "block":
            self.coords(a, i)
            return i + 4
        if kind == "blocks":
            return i + 10
        if kind == "score":
            self.target(a[i] if i < len(a) else None)
            op = a[i + 2] if i + 2 < len(a) else ""
            if op == "matches":
                return i + 4
            if op in ("<", "<=", "=", ">", ">="):
                return i + 5
            self.add("mc_syntax", f"score condition needs 'matches' or < <= = > >=, got '{op}'")
            return -1
        if kind in ("data",):
            return i + 3 if i < len(a) and a[i] == "storage" else i + 3 + (2 if i < len(a) and a[i] == "block" else 0)
        if kind in ("predicate", "dimension", "function"):
            return i + 1
        if kind in ("biome",):
            return i + 4
        if kind == "loaded":
            return i + 3
        if kind == "items":
            return i + 3
        self.add("mc_syntax", f"unknown execute condition '{kind}'",
                 " or ".join(closest(kind, ["entity", "block", "blocks", "score", "data", "predicate", "biome",
                                            "dimension", "loaded", "function", "items"])) or None, kind)
        return -1

    def c_summon(self, a):
        if not a:
            return self.add("mc_syntax", "summon needs an entity")
        self.resloc(a[0], "entity")
        if len(a) > 1:
            self.coords(a, 1)

    def c_setblock(self, a):
        if not self.coords(a, 0):
            return
        if len(a) < 4:
            return self.add("mc_syntax", "setblock needs a block")
        self.resloc(a[3], "block")
        if len(a) > 4:
            if INT.match(a[4]):
                self.add("mc_syntax", "block data values were removed in 1.13", "block states like oak_log[axis=x]",
                         a[4])
            elif a[4] not in SETBLOCK_MODES:
                self.add("mc_syntax", f"unknown setblock mode '{a[4]}'", " or ".join(sorted(SETBLOCK_MODES)), a[4])

    def c_fill(self, a):
        if not (self.coords(a, 0) and self.coords(a, 3)):
            return
        if len(a) < 7:
            return self.add("mc_syntax", "fill needs a block")
        self.resloc(a[6], "block")
        if len(a) > 7:
            if INT.match(a[7]):
                self.add("mc_syntax", "block data values were removed in 1.13", "block states", a[7])
            elif a[7] not in FILL_MODES:
                self.add("mc_syntax", f"unknown fill mode '{a[7]}'", " or ".join(sorted(FILL_MODES)), a[7])

    def c_effect(self, a):
        if not a:
            return self.add("mc_syntax", "effect needs give or clear")
        if a[0] not in ("give", "clear"):
            return self.add("mc_syntax", "since 1.13 it is /effect give <targets> <effect> [seconds] [amplifier]",
                            "effect give " + " ".join(a), "effect")
        if a[0] == "clear":
            if len(a) > 1:
                self.target(a[1])
            return
        self.target(a[1] if len(a) > 1 else None)
        if len(a) < 3:
            return self.add("mc_syntax", "effect give needs an effect")
        if INT.match(a[2]):
            return self.add("mc_syntax", "numeric effect ids were removed in 1.13", "an id like speed or regeneration",
                            a[2])
        self.resloc(a[2], "effect")
        if len(a) > 3 and not (INT.match(a[3]) or a[3] == "infinite"):
            self.add("mc_syntax", f"duration must be seconds or 'infinite', got '{a[3]}'", None, a[3])
        if len(a) > 4 and not INT.match(a[4]):
            self.add("mc_syntax", f"amplifier must be a whole number, got '{a[4]}'", None, a[4])

    def c_scoreboard(self, a):
        if not a or a[0] not in ("objectives", "players"):
            return self.add("mc_syntax", "scoreboard needs 'objectives' or 'players'")
        sub = a[1] if len(a) > 1 else ""
        if a[0] == "objectives":
            if sub not in ("add", "remove", "list", "setdisplay", "modify"):
                return self.add("mc_syntax", f"unknown scoreboard objectives action '{sub}'",
                                "add, remove, list, setdisplay or modify", sub)
            if sub == "add" and len(a) < 4:
                self.add("mc_syntax", "scoreboard objectives add <name> <criteria> [displayName]")
            return
        if sub not in ("set", "add", "remove", "reset", "get", "list", "enable", "operation", "display"):
            return self.add("mc_syntax", f"unknown scoreboard players action '{sub}'",
                            " or ".join(closest(sub, ["set", "add", "remove", "reset", "get", "list", "enable",
                                                      "operation", "display"])) or None, sub)
        if sub in ("set", "add", "remove"):
            if len(a) < 5:
                return self.add("mc_syntax", f"scoreboard players {sub} <targets> <objective> <score>")
            if a[2].startswith("@"):        # otherwise a fake player name like #temp
                self.target(a[2])
            if not INT.match(a[4]):
                self.add("mc_syntax", f"score must be a whole number, got '{a[4]}'", None, a[4])
        elif sub == "operation" and len(a) >= 5 and a[4] not in ("+=", "-=", "*=", "/=", "%=", "=", "<", ">", "><"):
            self.add("mc_syntax", f"unknown scoreboard operation '{a[4]}'", "+= -= *= /= %= = < > ><", a[4])

    def c_function(self, a):
        if not a:
            return self.add("mc_syntax", "function needs a name like mypack:start")
        if self.resloc(a[0], "function") and ":" not in a[0]:
            self.add("mc_function", f"'{a[0]}' has no namespace, so it means minecraft:{a[0]}",
                     f"<your namespace>:{a[0]}", a[0], "warning")

    def c_tellraw(self, a):
        if not self.target(a[0] if a else None):
            return
        comp = " ".join(a[1:])
        if not comp:
            return self.add("mc_syntax", "tellraw needs a text component")
        try:
            json.loads(comp)
            return
        except ValueError:
            pass
        if comp[0] not in "{[\"'" or not _balanced(comp):
            self.add("mc_syntax", "tellraw needs a text component, not bare text",
                     '{"text":"..."} or "..."', comp[:30])


def _balanced(s: str) -> bool:
    depth, quote = 0, ""
    for i, ch in enumerate(s):
        if quote:
            if ch == quote and s[i - 1] != "\\":
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0 and not quote


def check_commands(code: str, in_function: bool = False) -> list[dict]:
    c = Checker()
    for n, raw in enumerate(code.splitlines(), 1):
        c.line = n
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        c.command(s, in_function)
    return c.problems


DATAPACK_OLD_DIRS = re.compile(r"data/([a-z0-9_.-]+)/(functions|advancements|loot_tables|predicates|recipes|"
                               r"structures|item_modifiers|tags/functions|tags/blocks|tags/items)/")


def check_datapack_paths(text: str) -> list[dict]:
    """1.21 renamed the plural datapack folders (functions -> function, ...)."""
    out = []
    for m in DATAPACK_OLD_DIRS.finditer(text):
        old = m.group(2)
        new = {"functions": "function", "advancements": "advancement", "loot_tables": "loot_table",
               "predicates": "predicate", "recipes": "recipe", "structures": "structure",
               "item_modifiers": "item_modifier", "tags/functions": "tags/function", "tags/blocks": "tags/block",
               "tags/items": "tags/item"}[old]
        out.append({"kind": "mc_datapack", "severity": "error", "name": m.group(0),
                    "message": f"since Java 1.21 the folder is '{new}', not '{old}' (the game ignores '{old}/')",
                    "suggestion": f"data/{m.group(1)}/{new}/", "line": text.count("\n", 0, m.start()) + 1})
    return out


def check_pack_mcmeta(code: str) -> list[dict]:
    try:
        data = json.loads(code)
    except ValueError as e:
        return [{"kind": "syntax", "severity": "error", "name": "pack.mcmeta", "message": f"not valid JSON: {e}",
                 "suggestion": None, "line": None}]
    pack = data.get("pack") if isinstance(data, dict) else None
    if not isinstance(pack, dict) or not isinstance(pack.get("pack_format"), int) and "min_format" not in pack:
        return [{"kind": "mc_datapack", "severity": "error", "name": "pack.mcmeta",
                 "message": "pack.mcmeta needs {\"pack\": {\"pack_format\": <number>, \"description\": ...}}",
                 "suggestion": None, "line": None}]
    return []
