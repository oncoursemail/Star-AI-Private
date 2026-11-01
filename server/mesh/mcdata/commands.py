"""Minecraft command checker driven by the game's own Brigadier tree (data generator commands.json) and registries.

    problems = check_commands(code, index, versions, in_function=False)

Every literal, every argument type and every id comes from the version's data; nothing is hand-listed except the few
argument grammars Brigadier keeps in code (selectors, coordinates, SNBT, ranges, slots). A command is valid when it
parses in at least one of the target versions (the version the answer names, else any 1.21.x).
"""
from __future__ import annotations

import difflib
import json
import re

from . import snbt
from .index import VERSION_RE, McIndex, McVersion, short

PLACEHOLDER = re.compile(r"<[^<>\s][^<>]{0,30}>|\[[A-Za-z_][\w ]{0,30}\]|\{[A-Za-z_]\w{0,30}\}|[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+")
RESLOC_CH = set("0123456789abcdefghijklmnopqrstuvwxyz_:/.-")
UNQUOTED_CH = set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_-.+")
OLD_SELECTOR_KEYS = {"r": "distance=..R", "rm": "distance=RM..", "c": "limit=N", "m": "gamemode=", "l": "level=..L",
                     "lm": "level=LM..", "rx": "x_rotation=", "rxm": "x_rotation=", "ry": "y_rotation=",
                     "rym": "y_rotation="}
SORTS = {"nearest", "furthest", "random", "arbitrary"}
GAMEMODES = {"survival", "creative", "adventure", "spectator"}
COLORS = {"black", "dark_blue", "dark_green", "dark_aqua", "dark_red", "dark_purple", "gold", "gray", "dark_gray",
          "blue", "green", "aqua", "red", "light_purple", "yellow", "white", "reset"}
HEIGHTMAPS = {"world_surface_wg", "world_surface", "ocean_floor_wg", "ocean_floor", "motion_blocking",
              "motion_blocking_no_leaves"}
OPERATIONS = {"+=", "-=", "*=", "/=", "%=", "=", "<", ">", "><"}
SIMPLE_CRITERIA = {"dummy", "trigger", "deathCount", "playerKillCount", "totalKillCount", "health", "xp", "level",
                   "food", "air", "armor"}
SLOT_RE = re.compile(r"^(container|hotbar|inventory|enderchest|villager|horse|player\.crafting|mob\.inventory)\.(\d+|\*)$"
                     r"|^(weapon|armor|horse|player|contents|saddle|mob)(\.[a-z_*]+)?$")
NEEDS_OPTIONS = {"dust", "dust_color_transition", "block", "block_marker", "falling_dust", "item"}
TEXT_CONTENT = {"text", "translate", "score", "selector", "keybind", "nbt", "type", "object", "sprite", "atlas",
                "player"}
EVENT_FIELD_NEW = {"run_command": "command", "suggest_command": "command", "open_url": "url", "change_page": "page",
                   "copy_to_clipboard": "value", "open_file": "path", "show_dialog": "dialog", "custom": "id"}


class Fail(Exception):
    def __init__(self, pos: int, message: str, suggestion: str | None = None, name: str | None = None):
        super().__init__(message)
        self.pos, self.message, self.suggestion, self.name = pos, message, suggestion, name


def camel_to_snake(s: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", s).lower()


def suggest(name: str, cands, n: int = 3) -> list[str]:
    """Closest candidates; also matches camelCase -> snake_case renames (doFireTick -> fire_tick...)."""
    cands = [c for c in cands if c != name]
    low = {c.lower(): c for c in cands}
    key = short(name).lower()
    out = []
    for k in (key, camel_to_snake(short(name))):
        if k in low and low[k] not in out:
            out.append(low[k])
    for k in (key, camel_to_snake(short(name))):
        for m in difflib.get_close_matches(k, list(low), n=n + 1, cutoff=0.6):
            if low[m] not in out:
                out.append(low[m])
    snake = camel_to_snake(short(name))
    words = set(re.split(r"[_.]", snake)) - {"do", "minecraft", "", "the"}
    if words and len(out) < n:
        scored = sorted(((len(words & set(re.split(r"[_./]", c.lower()))), c) for c in cands), reverse=True)
        out += [c for s, c in scored[:n] if s and c not in out]
    return out[:n]


class Parse:
    def __init__(self, s: str, v: McVersion):
        self.s, self.v = s, v
        self.warn: list[dict] = []

    # ---------- low-level readers ----------
    def end_of_arg(self, pos: int) -> int:
        while pos < len(self.s) and self.s[pos] != " ":
            pos += 1
        return pos

    def placeholder(self, pos: int) -> int | None:
        m = PLACEHOLDER.match(self.s, pos)
        if m and (m.end() == len(self.s) or self.s[m.end()] == " "):
            return m.end()
        return None

    def resloc(self, pos: int, what: str = "id") -> tuple[str, int]:
        end = pos
        while end < len(self.s) and self.s[end] in RESLOC_CH:
            end += 1
        rid = self.s[pos:end]
        if end < len(self.s) and self.s[end].isupper():
            word = self.s[pos:self.end_of_arg(pos)]
            raise Fail(pos, f"'{word}' is not a valid {what}: ids are lowercase", word.lower(), word)
        if not rid or rid.count(":") > 1 or rid.startswith(":") or rid.endswith(":"):
            word = self.s[pos:self.end_of_arg(pos)]
            raise Fail(pos, f"expected a {what} like minecraft:stone, got '{word}'", None, word)
        return rid, end

    def unquoted(self, pos: int) -> tuple[str, int]:
        end = pos
        while end < len(self.s) and self.s[end] in UNQUOTED_CH:
            end += 1
        return self.s[pos:end], end

    def string(self, pos: int) -> tuple[str, int]:
        if pos < len(self.s) and self.s[pos] in "\"'":
            try:
                return snbt._quoted(self.s, pos)
            except snbt.SnbtError as e:
                raise Fail(e.pos, e.message)
        return self.unquoted(pos)

    def number(self, pos: int, integer: bool, props: dict | None = None, what="number") -> tuple[float, int]:
        end = pos
        while end < len(self.s) and self.s[end] in "0123456789.-+eE":
            end += 1
        raw = self.s[pos:end]
        try:
            val = int(raw) if integer else float(raw)
        except ValueError:
            word = self.s[pos:self.end_of_arg(pos)]
            raise Fail(pos, f"expected {'a whole number' if integer else 'a number'} ({what}), got '{word}'", None,
                       word)
        props = props or {}
        if "min" in props and val < props["min"]:
            raise Fail(pos, f"{what} must be at least {props['min']}, got {raw}", None, raw)
        if "max" in props and val > props["max"]:
            raise Fail(pos, f"{what} must be at most {props['max']}, got {raw}", None, raw)
        return val, end

    def snbt_at(self, pos: int):
        try:
            return snbt.parse(self.s, pos)
        except snbt.SnbtError as e:
            raise Fail(e.pos, f"bad SNBT: {e.message}", None, self.s[pos:e.pos + 1][-30:])

    def check_id(self, registry: str, rid: str, pos: int, what: str, tag: bool = False):
        if PLACEHOLDER.fullmatch(rid):
            return
        if tag:
            tags = self.v.tags(registry)
            if tags and ":" not in short(rid) and short(rid) not in tags:
                raise Fail(pos, f"unknown {what} tag '#{rid}' in {self.v.version}",
                           " or ".join("#minecraft:" + c for c in suggest(rid, tags)) or None, "#" + rid)
            return
        ok = self.v.has(registry, rid)
        if ok is False:
            raise Fail(pos, f"unknown {what} '{rid}' in {self.v.version}",
                       " or ".join("minecraft:" + c for c in suggest(rid, self.v.entries(registry))) or None, rid)

    # ---------- tree walk ----------
    def node_children(self, node: dict) -> dict:
        if "r" in node:
            target = self.v.tree
            for step in node["r"]:
                target = target["c"][step]
            return target.get("c", {})
        if "c" not in node and not node.get("x"):
            return self.v.tree["c"]                       # execute ... run: back to the root
        return node.get("c", {})

    def walk(self, node: dict, pos: int, name: str) -> int:
        s = self.s
        if pos >= len(s):
            if node.get("x"):
                return pos
            kids = self.node_children(node)
            exp = ", ".join(_label(k, c) for k, c in list(kids.items())[:8])
            raise Fail(pos, f"incomplete command after '{name}'" + (f"; expected {exp}" if exp else ""))
        if s[pos] != " ":
            raise Fail(pos, f"expected a space after '{name}', found '{s[pos:pos + 20]}'", None, s[pos:pos + 20])
        pos += 1
        kids = self.node_children(node)
        if not kids:
            raise Fail(pos, f"too many arguments: '{s[pos:pos + 30]}' after '{name}'", None, s[pos:pos + 30])
        word = s[pos:self.end_of_arg(pos)]
        lits = {k: c for k, c in kids.items() if c["t"] == "l"}
        if word in lits:
            return self.walk(lits[word], pos + len(word), word)
        args = [(k, c) for k, c in kids.items() if c["t"] == "a"]
        best: Fail | None = None
        for k, c in args:
            mark = len(self.warn)
            try:
                end = self.placeholder(pos)
                if end is None or c.get("p") in ("brigadier:string",) and c.get("o", {}).get("type") == "greedy":
                    end = self.arg(c.get("p", ""), c.get("o") or {}, pos, k)
                return self.walk(c, end, k)
            except Fail as e:
                del self.warn[mark:]
                if best is None or e.pos > best.pos:
                    best = e
        if lits and (best is None or best.pos <= pos):
            names = [k for k in lits if not (k.startswith("minecraft:") and k[10:] in lits)]
            sug = suggest(word, names)
            exp = ", ".join(names[:12]) + (" ..." if len(names) > 12 else "")
            raise Fail(pos, f"'{word}' is not valid after '{name}' in {self.v.version}; expected one of: {exp}",
                       " or ".join(sug) or None, word)
        raise best or Fail(pos, f"unexpected '{word}'", None, word)

    def run(self) -> None:
        s = self.s
        word = s[:self.end_of_arg(0)]
        root = self.v.tree["c"]
        cmd = word[10:] if word.startswith("minecraft:") else word
        if cmd not in root:
            raise Fail(0, f"unknown command '/{cmd}' in {self.v.version}",
                       " or ".join("/" + c for c in suggest(cmd, [k for k in root if ":" not in k])) or None, cmd)
        self.walk(root[cmd], len(word), cmd)

    # ---------- argument types ----------
    def arg(self, parser: str, props: dict, pos: int, name: str) -> int:
        fn = getattr(self, "a_" + parser.split(":")[-1], None)
        if fn is None:
            return self.end_of_arg(pos)
        return fn(pos, props, name)

    def a_integer(self, pos, props, name):
        return self.number(pos, True, props, name)[1]

    a_long = a_integer

    def a_float(self, pos, props, name):
        return self.number(pos, False, props, name)[1]

    a_double = a_float

    def a_bool(self, pos, props, name):
        word = self.s[pos:self.end_of_arg(pos)]
        if word not in ("true", "false"):
            raise Fail(pos, f"{name} must be true or false, got '{word}'", None, word)
        return pos + len(word)

    def a_string(self, pos, props, name):
        kind = props.get("type")
        if kind == "greedy":
            return len(self.s)
        if kind == "phrase":
            return self.string(pos)[1]
        return self.unquoted(pos)[1]

    def a_message(self, pos, props, name):
        return len(self.s)

    def _range(self, pos, name, integer):
        end = pos
        while end < len(self.s) and self.s[end] in "0123456789.-":
            end += 1
        raw = self.s[pos:end]
        num = r"-?\d+" if integer else r"-?(\d+\.?\d*|\.\d+)"
        if not re.fullmatch(rf"({num})?(\.\.({num})?)?", raw) or raw in ("", ".."):
            word = self.s[pos:self.end_of_arg(pos)]
            raise Fail(pos, f"{name}: expected a {'whole-number ' if integer else ''}range like 5, 1..10, ..3 or 2..,"
                            f" got '{word}'", None, word)
        return end

    def a_int_range(self, pos, props, name):
        return self._range(pos, name, True)

    def a_float_range(self, pos, props, name):
        return self._range(pos, name, False)

    def _coords(self, pos, n, name, integer=False, local=True):
        parts, i = [], pos
        for k in range(n):
            if k:
                if i >= len(self.s) or self.s[i] != " ":
                    raise Fail(i, f"{name}: expected {n} coordinates, got {k}")
                i += 1
            ph = self.placeholder(i)
            if ph is not None:
                parts.append("?")
                i = ph
                continue
            j = i
            while j < len(self.s) and self.s[j] in "0123456789.-~^+":
                j += 1
            raw = self.s[i:j]
            if not raw or (j < len(self.s) and self.s[j] != " "):
                word = self.s[i:self.end_of_arg(i)]
                raise Fail(i, f"{name}: '{word}' is not a coordinate (a number, ~ relative or ^ local)", None, word)
            body = raw[1:] if raw[0] in "~^" else raw
            if body:
                try:
                    float(body)
                except ValueError:
                    raise Fail(i, f"{name}: '{raw}' is not a coordinate", None, raw)
                if integer and raw[0] not in "~^" and not re.fullmatch(r"-?\d+", body):
                    raise Fail(i, f"{name}: block coordinates are whole numbers, got '{raw}'", raw.split(".")[0], raw)
            parts.append(raw[0] if raw[0] in "~^" else "n")
            i = j
        real = [p for p in parts if p != "?"]
        if "^" in real and any(p != "^" for p in real):
            raise Fail(pos, f"{name}: local (^) and world (~ or numbers) coordinates cannot be mixed", None,
                       self.s[pos:i])
        if "^" in real and not local:
            raise Fail(pos, f"{name}: local (^) coordinates are not allowed here", None, self.s[pos:i])
        return i

    def a_block_pos(self, pos, props, name):
        return self._coords(pos, 3, name, integer=True)

    def a_vec3(self, pos, props, name):
        return self._coords(pos, 3, name)

    def a_vec2(self, pos, props, name):
        return self._coords(pos, 2, name)

    def a_column_pos(self, pos, props, name):
        return self._coords(pos, 2, name, integer=True, local=False)

    def a_rotation(self, pos, props, name):
        return self._coords(pos, 2, name, local=False)

    def a_angle(self, pos, props, name):
        return self._coords(pos, 1, name, local=False)

    # selectors
    def selector(self, pos, props, name) -> int:
        s = self.s
        kind = s[pos + 1] if pos + 1 < len(s) else ""
        if kind not in "parsen" or not kind:
            word = s[pos:self.end_of_arg(pos)]
            raise Fail(pos, f"bad selector '{word}'", "@p, @a, @r, @s, @e or @n", word)
        i, opts = pos + 2, {}
        if i < len(s) and s[i] == "[":
            i += 1
            while True:
                while i < len(s) and s[i] == " ":
                    i += 1
                if i < len(s) and s[i] == "]":
                    i += 1
                    break
                key, i = self.string(i)
                while i < len(s) and s[i] == " ":
                    i += 1
                if key in OLD_SELECTOR_KEYS:
                    raise Fail(i, f"selector option '{key}' was removed in 1.13", OLD_SELECTOR_KEYS[key], key)
                if key.startswith("score_"):
                    raise Fail(i, f"selector option '{key}' was removed in 1.13", "scores={objective=min..max}", key)
                if i >= len(s) or s[i] != "=":
                    raise Fail(i, f"expected '=' after selector option '{key}'", None, key)
                i += 1
                while i < len(s) and s[i] == " ":
                    i += 1
                i, val = self.sel_value(key, i)
                opts.setdefault(key, []).append(val)
                while i < len(s) and s[i] == " ":
                    i += 1
                if i < len(s) and s[i] == ",":
                    i += 1
                    continue
                if i < len(s) and s[i] == "]":
                    i += 1
                    break
                raise Fail(i, "expected ',' or ']' in the selector", None, s[i:i + 10])
        # amount / type rules (what Brigadier enforces after parsing)
        single = props.get("amount") == "single"
        limit = opts.get("limit", [None])[-1]
        if single and kind in "ae" and limit != 1:
            raise Fail(pos, f"{name} takes one entity, but @{kind} can select many",
                       f"@{kind}[...,limit=1] or @p/@s/@n", s[pos:i])
        if props.get("type") == "players" and kind in "en":
            types = [t for t in opts.get("type", []) if not str(t).startswith("!")]
            if not types or short(str(types[-1])) != "player":
                raise Fail(pos, f"{name} only accepts players, but @{kind} can select other entities",
                           f"@a or @{kind}[type=player]", s[pos:i])
        return i

    def sel_value(self, key: str, i: int) -> tuple[int, object]:
        s = self.s
        neg = i < len(s) and s[i] == "!"
        j = i + 1 if neg else i
        if key in ("distance", "level", "x_rotation", "y_rotation"):
            return self._range(i, key, key == "level"), None
        if key in ("x", "y", "z", "dx", "dy", "dz"):
            return self.number(i, False, None, key)[1], None
        if key == "limit":
            val, end = self.number(i, True, {"min": 1}, "limit")
            return end, val
        if key == "sort":
            word, end = self.unquoted(i)
            if word not in SORTS:
                raise Fail(i, f"sort must be nearest, furthest, random or arbitrary, got '{word}'",
                           " or ".join(suggest(word, SORTS)) or None, word)
            return end, word
        if key == "gamemode":
            word, end = self.unquoted(j)
            if word not in GAMEMODES:
                raise Fail(j, f"unknown gamemode '{word}'", " or ".join(suggest(word, GAMEMODES)) or None, word)
            return end, word
        if key in ("name",):
            return self.string(j)[1], None
        if key in ("tag", "team"):
            return self.unquoted(j)[1], None
        if key == "type":
            tag = j < len(s) and s[j] == "#"
            ph = self.placeholder(j)
            if ph is not None:
                return ph, "?"
            rid, end = self.resloc(j + tag, "entity type")
            self.check_id("tags/entity_type" if tag else "entity_type", rid, j, "entity type")
            return end, ("!" if neg else "") + ("#" if tag else "") + rid
        if key == "nbt":
            val, end = self.snbt_at(j)
            if not isinstance(val, dict):
                raise Fail(j, "nbt= needs a compound {...}")
            return end, None
        if key == "predicate":
            return self.resloc(j, "predicate")[1], None
        if key in ("scores", "advancements"):
            if i >= len(s) or s[i] != "{":
                raise Fail(i, f"{key}= needs {{...}}", None, s[i:i + 10])
            depth, k = 0, i
            while k < len(s):
                depth += {"{": 1, "}": -1}.get(s[k], 0)
                k += 1
                if depth == 0:
                    break
            body = s[i + 1:k - 1]
            if key == "scores":
                for part in filter(None, (p.strip() for p in body.split(","))):
                    if "=" not in part or not re.fullmatch(r"-?\d*(\.\.-?\d*)?", part.split("=", 1)[1].strip()):
                        raise Fail(i, f"scores= entries are objective=range, got '{part}'", None, part)
            return k, None
        word = s[i:self.end_of_arg(i)].split(",")[0].split("]")[0]
        raise Fail(i, f"unknown selector option '{key}'", None, key)

    def a_entity(self, pos, props, name):
        if pos < len(self.s) and self.s[pos] == "@":
            return self.selector(pos, props, name)
        end = self.end_of_arg(pos)
        word = self.s[pos:end]
        if re.fullmatch(r"[0-9a-fA-F]{1,8}-[0-9a-fA-F]{1,4}-[0-9a-fA-F]{1,4}-[0-9a-fA-F]{1,4}-[0-9a-fA-F]{1,12}", word):
            return end
        if not word or len(word) > 16:
            raise Fail(pos, f"'{word}' is not a player name, UUID or selector", None, word)
        return end

    def a_game_profile(self, pos, props, name):
        return self.a_entity(pos, {"type": "players"}, name)

    def a_score_holder(self, pos, props, name):
        if self.s.startswith("*", pos):
            return pos + 1
        if pos < len(self.s) and self.s[pos] == "@":
            return self.selector(pos, props, name)
        end = self.end_of_arg(pos)
        if end == pos:
            raise Fail(pos, f"missing {name}")
        return end

    # ids
    def _registry_arg(self, pos, props, name, tag_ok):
        reg = short(props.get("registry", ""))
        tag = tag_ok and pos < len(self.s) and self.s[pos] == "#"
        rid, end = self.resloc(pos + tag, reg.split("/")[-1].replace("_", " ") or "id")
        if reg:
            self.check_id(reg, rid, pos, reg.split("/")[-1].replace("_", " "), tag=tag)
        return end

    def a_resource(self, pos, props, name):
        return self._registry_arg(pos, props, name, False)

    a_resource_key = a_resource

    def a_resource_or_tag(self, pos, props, name):
        return self._registry_arg(pos, props, name, True)

    a_resource_or_tag_key = a_resource_or_tag
    a_resource_selector = a_resource_or_tag

    def a_resource_location(self, pos, props, name):
        return self.resloc(pos, name)[1]

    def a_function(self, pos, props, name):
        tag = self.s.startswith("#", pos)
        rid, end = self.resloc(pos + tag, "function")
        if ":" not in rid:
            self.warn.append(_p("mc_function", f"'{rid}' has no namespace, so it means minecraft:{rid}",
                                f"<your namespace>:{rid}", rid, "warning"))
        return end

    def a_dimension(self, pos, props, name):
        rid, end = self.resloc(pos, "dimension")
        dims = self.v.data.get("dimension_type")
        if dims and ":" not in short(rid) and short(rid) not in dims:
            raise Fail(pos, f"unknown dimension '{rid}'",
                       " or ".join("minecraft:" + d for d in suggest(rid, dims)) or None, rid)
        return end

    def _inline_or_id(self, pos, registry, what):
        if self.s.startswith("{", pos):
            return self.snbt_at(pos)[1]
        rid, end = self.resloc(pos, what)
        self.check_id(registry, rid, pos, what)
        return end

    def a_loot_table(self, pos, props, name):
        return self._inline_or_id(pos, "loot_table", "loot table")

    def a_loot_modifier(self, pos, props, name):
        return self._inline_or_id(pos, "item_modifier", "item modifier")

    def a_loot_predicate(self, pos, props, name):
        return self._inline_or_id(pos, "predicate", "predicate")

    def a_dialog(self, pos, props, name):
        return self._inline_or_id(pos, "dialog", "dialog")

    def a_particle(self, pos, props, name):
        rid, end = self.resloc(pos, "particle")
        self.check_id("particle_type", rid, pos, "particle")
        if end < len(self.s) and self.s[end] == "{":
            return self.snbt_at(end)[1]
        if short(rid) in NEEDS_OPTIONS and self.v.key >= (1, 20, 5):
            raise Fail(end, f"particle {short(rid)} needs its options in {{...}} since 1.20.5",
                       {"dust": "dust{color:[1.0,0.0,0.0],scale:1.0}", "block": "block{block_state:\"stone\"}",
                        "item": "item{item:\"diamond\"}"}.get(short(rid)), short(rid))
        return end

    # items and blocks
    def components(self, pos, item: str) -> int:
        s, i = self.s, pos + 1
        types = self.v.entries("data_component_type")
        while True:
            while i < len(s) and s[i] == " ":
                i += 1
            if i < len(s) and s[i] == "]":
                return i + 1
            neg = i < len(s) and s[i] == "!"
            kpos = i + neg
            key, i = self.resloc(kpos, "component")
            if types and ":" not in short(key) and short(key) not in types:
                raise Fail(kpos, f"unknown item component '{key}' in {self.v.version}",
                           " or ".join(suggest(key, types)) or None, key)
            if not neg:
                if i >= len(s) or s[i] != "=":
                    raise Fail(i, f"expected '=' after component '{key}'", None, key)
                vpos = i + 1
                val, i = self.snbt_at(vpos)
                self.component_value(short(key), val, vpos)
            while i < len(s) and s[i] == " ":
                i += 1
            if i < len(s) and s[i] == ",":
                i += 1
                continue
            if i < len(s) and s[i] == "]":
                return i + 1
            raise Fail(i, "expected ',' or ']' after an item component", None, s[i:i + 10])

    def component_value(self, key: str, val, pos: int):
        """Checks for the component values that changed shape inside 1.21.x (the commonest silent mistakes)."""
        v = self.v.key
        if key == "enchantments" and isinstance(val, dict):
            if v >= (1, 21, 5) and "levels" in val:
                raise Fail(pos, "since 1.21.5 enchantments is a plain map: enchantments={sharpness:5}",
                           "enchantments={" + ",".join(f"{k}:{_num(n)}" for k, n in (val.get("levels") or {}).items()) + "}",
                           "levels")
            if v < (1, 21, 5) and "levels" not in val and val:
                raise Fail(pos, "before 1.21.5 enchantments needs levels: enchantments={levels:{sharpness:5}}",
                           None, "enchantments")
            ench = self.v.entries("enchantment")
            for k in (val.get("levels") if isinstance(val.get("levels"), dict) else val):
                if ench and k != "levels" and ":" not in short(k) and short(k) not in ench:
                    raise Fail(pos, f"unknown enchantment '{k}'",
                               " or ".join(suggest(k, ench)) or None, k)
        if key in ("custom_name", "item_name", "lore"):
            texts = val if key == "lore" and isinstance(val, list) else [val]
            for t in texts:
                if isinstance(t, str) and v >= (1, 21, 5) and t.strip().startswith(("{", "[", "\"")):
                    raise Fail(pos, f"since 1.21.5 {key} takes a text component as SNBT, not a JSON string",
                               f"{key}={t.strip()}" if key != "lore" else None, key)
                if isinstance(t, str) and v < (1, 21, 5):
                    try:
                        json.loads(t)
                    except ValueError:
                        raise Fail(pos, f"before 1.21.5 {key} is a JSON text string like '{{\"text\":\"Name\"}}'",
                                   None, key)
                if isinstance(t, dict):
                    self.text_component(t, pos)

    def a_item_stack(self, pos, props, name):
        rid, end = self.resloc(pos, "item")
        self.check_id("item", rid, pos, "item")
        if end < len(self.s) and self.s[end] == "[":
            end = self.components(end, rid)
        if end < len(self.s) and self.s[end] == "{":
            raise Fail(end, "item NBT {...} was replaced by item components in 1.20.5",
                       f"{short(rid)}[custom_name=...,enchantments=...]", self.s[end:end + 25])
        return end

    def a_item_predicate(self, pos, props, name):
        s = self.s
        if s.startswith("*", pos):
            end = pos + 1
        else:
            tag = s.startswith("#", pos)
            rid, end = self.resloc(pos + tag, "item")
            self.check_id("item", rid, pos, "item", tag=tag)
        if end < len(s) and s[end] == "[":
            depth, quote, i = 0, "", end
            while i < len(s):
                ch = s[i]
                if quote:
                    if ch == quote and s[i - 1] != "\\":
                        quote = ""
                elif ch in "\"'":
                    quote = ch
                elif ch in "[{":
                    depth += 1
                elif ch in "]}":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
            else:
                raise Fail(end, "unclosed '[' in the item predicate")
            end = i
        if end < len(s) and s[end] == "{":
            raise Fail(end, "item NBT {...} was replaced by item components in 1.20.5", None, s[end:end + 25])
        return end

    def block_body(self, pos, allow_tag) -> int:
        s = self.s
        tag = allow_tag and s.startswith("#", pos)
        rid, end = self.resloc(pos + tag, "block")
        if tag:
            self.check_id("block", rid, pos, "block", tag=True)
            props = None
        else:
            props = self.v.blocks.get(short(rid)) if ":" not in short(rid) else None
            if props is None and ":" not in short(rid) and self.v.blocks:
                raise Fail(pos, f"unknown block '{rid}' in {self.v.version}",
                           " or ".join("minecraft:" + b for b in suggest(rid, self.v.blocks)) or None, rid)
        if end < len(s) and s[end] == "[":
            i = end + 1
            while True:
                while i < len(s) and s[i] == " ":
                    i += 1
                if i < len(s) and s[i] == "]":
                    end = i + 1
                    break
                key, i = self.unquoted(i)
                if i >= len(s) or s[i] != "=":
                    raise Fail(i, f"expected '=' after block state '{key}'", None, key)
                val, i = self.unquoted(i + 1)
                if props is not None:
                    if key not in props:
                        raise Fail(i, f"{short(rid)} has no block state '{key}'"
                                      + (f" (it has: {', '.join(props)})" if props else " (it has none)"),
                                   " or ".join(suggest(key, props)) or None, key)
                    if val not in props[key]:
                        raise Fail(i, f"{short(rid)}[{key}] can be {', '.join(props[key])}, not '{val}'",
                                   " or ".join(suggest(val, props[key])) or None, val)
                while i < len(s) and s[i] == " ":
                    i += 1
                if i < len(s) and s[i] == ",":
                    i += 1
                    continue
                if i < len(s) and s[i] == "]":
                    end = i + 1
                    break
                raise Fail(i, "expected ',' or ']' in block states", None, s[i:i + 10])
        if end < len(s) and s[end] == "{":
            val, end = self.snbt_at(end)
        return end

    def a_block_state(self, pos, props, name):
        return self.block_body(pos, False)

    def a_block_predicate(self, pos, props, name):
        return self.block_body(pos, True)

    # nbt
    def a_nbt_tag(self, pos, props, name):
        return self.snbt_at(pos)[1]

    def a_nbt_compound_tag(self, pos, props, name):
        val, end = self.snbt_at(pos)
        if not isinstance(val, dict):
            raise Fail(pos, f"{name} must be a compound {{...}}", None, self.s[pos:end])
        return end

    def a_nbt_path(self, pos, props, name):
        s, i, depth, quote = self.s, pos, 0, ""
        while i < len(s):
            ch = s[i]
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
                    raise Fail(i, f"unbalanced '{ch}' in NBT path", None, s[pos:i + 1])
            elif ch == " " and depth == 0:
                break
            i += 1
        if depth or quote or i == pos:
            raise Fail(pos, "bad NBT path", None, s[pos:i])
        path = s[pos:i]
        if re.match(r"^[A-Z]", path) is None and path.split(".")[0] in ("count", "id", "components") and False:
            pass
        return i

    # text
    def text_component(self, val, pos):
        v = self.v.key
        if isinstance(val, list):
            for x in val:
                self.text_component(x, pos)
            return
        if not isinstance(val, dict):
            return
        new = v >= (1, 21, 5)
        for old, cur in (("clickEvent", "click_event"), ("hoverEvent", "hover_event")):
            if new and old in val:
                raise Fail(pos, f"'{old}' is ignored since 1.21.5: the key is '{cur}'", cur, old)
            if not new and cur in val:
                raise Fail(pos, f"'{cur}' is ignored before 1.21.5: the key is '{old}'", old, cur)
        ce = val.get("click_event" if new else "clickEvent")
        if isinstance(ce, dict):
            act = ce.get("action")
            field = EVENT_FIELD_NEW.get(act) if new else "value"
            if field and field not in ce:
                raise Fail(pos, f"click event {act} needs '{field}'" + (" since 1.21.5" if new else ""),
                           f"{{action:\"{act}\",{field}:...}}", "click_event")
        he = val.get("hover_event" if new else "hoverEvent")
        if isinstance(he, dict) and he.get("action") == "show_text":
            if new and "value" not in he:
                raise Fail(pos, "hover_event show_text needs 'value' since 1.21.5", None, "hover_event")
        color = val.get("color")
        if isinstance(color, str) and color not in COLORS and not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise Fail(pos, f"unknown text color '{color}'", " or ".join(suggest(color, COLORS)) or None, color)
        if not (set(val) & TEXT_CONTENT):
            self.warn.append(_p("mc_text", "text component without content (text, translate, score, selector, "
                                           "keybind or nbt)", None, None, "warning"))
        for k in ("extra",):
            if k in val:
                self.text_component(val[k], pos)

    def a_component(self, pos, props, name):
        s = self.s
        if s.startswith(("{", "[", "\""), pos):
            try:
                val, end = json.JSONDecoder().raw_decode(s, pos)
            except ValueError:
                if self.v.key < (1, 21, 5) and s.startswith("{", pos):
                    try:
                        val, end = snbt.parse(s, pos)
                    except snbt.SnbtError as e:
                        raise Fail(e.pos, f"bad text component: {e.message}", None, s[pos:pos + 30])
                else:
                    val, end = self.snbt_at(pos)
        else:
            val, end = self.snbt_at(pos)
        self.text_component(val, pos)
        return end

    def a_style(self, pos, props, name):
        return self.snbt_at(pos)[1]

    # small enums
    def _enum(self, pos, values, name):
        word = self.s[pos:self.end_of_arg(pos)]
        if word not in values:
            raise Fail(pos, f"{name}: '{word}' is not one of {', '.join(sorted(values))}",
                       " or ".join(suggest(word, values)) or None, word)
        return pos + len(word)

    def a_gamemode(self, pos, props, name):
        return self._enum(pos, GAMEMODES, name)

    def a_entity_anchor(self, pos, props, name):
        return self._enum(pos, {"eyes", "feet"}, name)

    def a_color(self, pos, props, name):
        return self._enum(pos, COLORS, name)

    def a_heightmap(self, pos, props, name):
        return self._enum(pos, HEIGHTMAPS, name)

    def a_template_rotation(self, pos, props, name):
        return self._enum(pos, {"none", "clockwise_90", "counterclockwise_90", "180"}, name)

    def a_template_mirror(self, pos, props, name):
        return self._enum(pos, {"none", "front_back", "left_right"}, name)

    def a_operation(self, pos, props, name):
        return self._enum(pos, OPERATIONS, name)

    def a_hex_color(self, pos, props, name):
        word = self.s[pos:self.end_of_arg(pos)]
        if not re.fullmatch(r"#?[0-9a-fA-F]{6}", word):
            raise Fail(pos, f"{name}: expected a hex color like FF0000, got '{word}'", None, word)
        return pos + len(word)

    def a_swizzle(self, pos, props, name):
        word = self.s[pos:self.end_of_arg(pos)]
        if not word or set(word) - set("xyz") or len(set(word)) != len(word):
            raise Fail(pos, f"{name}: expected a mix of x, y, z like xz, got '{word}'", None, word)
        return pos + len(word)

    def a_scoreboard_slot(self, pos, props, name):
        word = self.s[pos:self.end_of_arg(pos)]
        ok = word in ("list", "sidebar", "below_name", "belowName") or (
            word.startswith("sidebar.team.") and word[13:] in COLORS)
        if not ok:
            raise Fail(pos, f"display slot '{word}' does not exist", "sidebar, list or below_name", word)
        return pos + len(word)

    def a_time(self, pos, props, name):
        word = self.s[pos:self.end_of_arg(pos)]
        if not re.fullmatch(r"(\d+\.?\d*|\.\d+)[dst]?", word):
            raise Fail(pos, f"{name}: expected a time like 20, 5s or 1d, got '{word}'", None, word)
        return pos + len(word)

    def a_uuid(self, pos, props, name):
        word = self.s[pos:self.end_of_arg(pos)]
        if not re.fullmatch(r"[0-9a-fA-F]{1,8}-[0-9a-fA-F]{1,4}-[0-9a-fA-F]{1,4}-[0-9a-fA-F]{1,4}-[0-9a-fA-F]{1,12}",
                            word):
            raise Fail(pos, f"'{word}' is not a UUID", None, word)
        return pos + len(word)

    def a_objective(self, pos, props, name):
        word, end = self.unquoted(pos)
        if not word:
            raise Fail(pos, f"missing objective name", None, self.s[pos:pos + 10])
        return end

    def a_team(self, pos, props, name):
        return self.a_objective(pos, props, name)

    def a_objective_criteria(self, pos, props, name):
        word = self.s[pos:self.end_of_arg(pos)]
        if word in SIMPLE_CRITERIA:
            return pos + len(word)
        m = re.fullmatch(r"(teamkill|killedByTeam)\.([a-z_]+)", word)
        if m:
            if m.group(2) not in COLORS:
                raise Fail(pos, f"unknown team color in '{word}'", None, word)
            return pos + len(word)
        m = re.fullmatch(r"(?:minecraft\.)?([a-z_]+):(?:minecraft\.)?([a-z0-9_./]+)", word)
        if m:
            stat, rid = m.group(1), m.group(2)
            stats = self.v.entries("stat_type")
            if stats and stat not in stats:
                raise Fail(pos, f"unknown statistic type '{stat}' in criterion '{word}'",
                           " or ".join("minecraft." + x for x in suggest(stat, stats)) or None, word)
            reg = {"mined": "block", "crafted": "item", "used": "item", "broken": "item", "picked_up": "item",
                   "dropped": "item", "killed": "entity_type", "killed_by": "entity_type",
                   "custom": "custom_stat"}.get(stat)
            if reg and self.v.has(reg, rid) is False:
                raise Fail(pos, f"unknown {reg.replace('_', ' ')} '{rid}' in criterion '{word}'",
                           " or ".join(suggest(rid, self.v.entries(reg))) or None, word)
            return pos + len(word)
        raise Fail(pos, f"unknown scoreboard criterion '{word}'",
                   " or ".join(suggest(word, SIMPLE_CRITERIA)) or None, word)

    def a_item_slot(self, pos, props, name):
        word = self.s[pos:self.end_of_arg(pos)]
        if not SLOT_RE.match(word) or ("*" in word and name != "slots"):
            raise Fail(pos, f"'{word}' is not an item slot", "container.0, hotbar.0, weapon.mainhand, armor.head",
                       word)
        return pos + len(word)

    def a_item_slots(self, pos, props, name):
        word = self.s[pos:self.end_of_arg(pos)]
        if not SLOT_RE.match(word):
            raise Fail(pos, f"'{word}' is not an item slot range", "container.*, hotbar.*, weapon.*, armor.*",
                       word)
        return pos + len(word)


def _num(n) -> str:
    return str(int(n)) if isinstance(n, float) and n.is_integer() else str(n)


def _label(k: str, node: dict) -> str:
    return k if node["t"] == "l" else f"<{k}>"


def _p(kind, message, suggestion=None, name=None, severity="error") -> dict:
    return {"kind": kind, "severity": severity, "name": name, "message": message, "suggestion": suggestion}


def parse_line(line: str, v: McVersion) -> tuple[Fail | None, list[dict]]:
    p = Parse(line, v)
    try:
        p.run()
        return None, p.warn
    except Fail as e:
        return e, []
    except RecursionError:
        return Fail(0, "command too deeply nested"), []


def logical_lines(code: str) -> list[tuple[int, str]]:
    """(line number, text) with 1.20.2+ backslash continuations joined."""
    out, buf, start = [], "", 0
    for n, raw in enumerate(code.splitlines(), 1):
        s = raw.strip()
        if buf:
            buf += " " + s.rstrip("\\").strip()
            if not s.endswith("\\"):
                out.append((start, buf))
                buf = ""
            continue
        if s.endswith("\\") and not s.startswith("#"):
            buf, start = s[:-1].strip(), n
            continue
        out.append((n, s))
    if buf:
        out.append((start, buf))
    return out


def span(versions: list[str]) -> str:
    if not versions:
        return ""
    vs = sorted(versions, key=lambda x: tuple(int(t) for t in x.split(".")))
    return vs[0] if len(vs) == 1 else f"{vs[0]}-{vs[-1]}"


def check_commands(code: str, index: McIndex, prose: str = "", in_function: bool = False,
                   slash: str = "error") -> list[dict]:
    """Every command line of a block, checked against the target versions (named in the prose, else every 1.21.x).
    The block is judged in the ONE version where most of its lines are valid (newest on a tie), so an answer that
    mixes 1.21.4 and 1.21.5 syntax is caught."""
    versions = index.resolve(prose)
    named = set(VERSION_RE.findall(prose or ""))
    if named:
        targets = [v for v in versions if v.version in named or ("1.21" in named and v.version.startswith("1.21"))]
    else:
        targets = index.java121() or versions[:1]
    targets = targets or versions[:1]
    others = [v for v in versions if v not in targets]
    out, lines = [], []
    for n, s in logical_lines(code):
        if not s or s.startswith("#") or s.startswith("$"):     # comments; macro lines are checked when they run
            continue
        if s.startswith("/"):
            if in_function:
                out.append({**_p("mc_function", "commands in a .mcfunction file have no leading '/'",
                                 s[1:].split(" ")[0], s.split(" ")[0], slash), "line": n})
            s = s[1:]
        lines.append((n, s, {v.version: parse_line(s, v) for v in targets}))
    if not lines:
        return out
    best = max(targets, key=lambda v: sum(r[v.version][0] is None for _, _, r in lines))
    for n, s, res in lines:
        err, warn = res[best.version]
        if err is None:
            out += [{**w, "line": n} for w in warn]
            continue
        ok_t = [v for v, (e, _) in res.items() if e is None]
        if ok_t:
            out.append({**_p("mc_version", f"valid only in {span(ok_t)}; the rest of this answer is {best.version} "
                                           f"syntax, where: {err.message}", err.suggestion, err.name, "warning"),
                        "line": n, "version": best.version})
            continue
        ok_o = [v.version for v in others if parse_line(s, v)[0] is None]
        msg = err.message + (f" (that form is valid in {span(ok_o)})" if ok_o else "")
        out.append({**_p("mc_syntax", msg, err.suggestion, err.name), "line": n, "version": best.version})
    return out
