"""The "Minecraft facts" block: exact, version-specific facts for the question, read from the game's own data, put in
front of the user's question (like the docs block does for Roblox).

    f = Facts(index, examples_dir, templates_path)
    f.block(question, extra="") -> {"text": "...", "version": "1.21.11", "parts": ["pack", "ids", ...]} or text ""

Contents (only what the question needs): version + pack formats + the exact pack.mcmeta the game accepts, data/resource
pack folder names of that version, command usages from the real command tree, exact ids (items, blocks + states,
entities, effects, enchantments, attributes, particles, sounds, gamerules), syntax templates checked with the game's
own parser for that version (templates.json), and vanilla files of that version as examples (loot tables, item model
definitions, blockstates, equipment, atlases, sounds.json entries ...).
"""
from __future__ import annotations

import gzip
import json
import re
from collections import OrderedDict
from pathlib import Path

from .index import VERSION_RE, McIndex, McVersion, short, vkey

MC = re.compile(r"\bminecraft\b|\bmcfunction\b|\bdata ?packs?\b|\bresource ?packs?\b|pack\.mcmeta|\bcommand block\b|"
                r"\bredstone\b|\bcreeper\b|\bnether(ite)?\b|\bmc ?java\b|\b(/give|/tp|/execute|/summon|/tellraw)\b", re.I)
DATAPACK = re.compile(r"data ?pack|\bfunction\b|recipe|loot|advancement|predicate|item modifier|enchantment|"
                      r"painting|jukebox|\btag\b|pack\.mcmeta|macro", re.I)
RESPACK = re.compile(r"resource ?pack|texture|model|blockstate|sound|\.ogg|language file|lang\b|font|emoji|atlas|"
                     r"animated|hotbar|gui\b|equippable|armor that looks|custom armor", re.I)
WORD = re.compile(r"[a-z0-9]+")
STOP = set("a an the to of in on for with and or my me i is it do how make that this what which when one all any "
           "every from by be can use using get set into at as are you your their them they its java minecraft "
           "command commands data pack resource add new show only out up has have".split())
COMMAND_WORDS = {
    "give": ["give", "gives"], "summon": ["summon", "spawn"], "tp": ["teleport", "tp"], "kill": ["kill"],
    "scoreboard": ["scoreboard", "score", "objective", "tab list", "died", "deaths", "leaderboard"],
    "tellraw": ["tellraw", "chat message", "clickable", "click"], "title": ["title"],
    "bossbar": ["boss bar", "bossbar"], "effect": ["effect"], "particle": ["particle"],
    "playsound": ["playsound", "play the", "sound to"], "setblock": ["setblock", "place a", "place an"],
    "fill": ["fill", "turn only"], "clone": ["clone", "copy"], "gamerule": ["gamerule", "stop fire", "stop mobs",
                                                                               "fire from spreading"],
    "attribute": ["attribute", "bigger", "twice as big", "scale"], "data": ["data merge", "invisible", "nbt"],
    "execute": ["execute", "check if", "within", "if a player"], "random": ["random", "roll"],
    "function": ["function", "macro"], "trigger": ["trigger"], "item": ["item modifier", "/item"],
    "clear": ["at least", "how many"],
}
RANGE_DISPATCH_CMD = ('{"model": {"type": "minecraft:range_dispatch", "property": "minecraft:custom_model_data", '
                      '"index": 0, "fallback": {"type": "minecraft:model", "model": "minecraft:item/stick"}, '
                      '"entries": [{"threshold": 1, "model": {"type": "minecraft:model", "model": '
                      '"mypack:item/magic_wand"}}]}}')


GENERIC_IDS = {"item", "block", "marker", "interaction", "fire", "light", "air", "cloud", "flash", "poof", "note"}
SYNONYM = {"breaking": "griefing", "griefing": "griefing", "spreading": "spread", "spreads": "spread", "mobs": "mob",
           "hiss": "primed", "hisses": "primed", "explode": "explode"}
SOUND_STOP = {"sound", "sounds", "play", "file", "own", "ogg", "replace", "new", "brand", "custom", "playsound"}


def _words(text: str) -> list[str]:
    return [w for w in WORD.findall(text.lower()) if w not in STOP]


def stem(w: str) -> str:
    w = SYNONYM.get(w, w)
    for suf in ("ing", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[:-len(suf)]
    return w


def _template_cmds(t: dict) -> set[str]:
    return set(re.findall(r"(?:^|\n|run )([a-z]+)", t.get("cmd") or t.get("use") or ""))


class Facts:
    def __init__(self, index: McIndex, examples_dir: str | Path | None = None, templates: str | Path | None = None,
                 default_version: str = "1.21.11"):
        self.index = index
        self.dir = Path(examples_dir) if examples_dir else None
        tp = Path(templates) if templates else Path(__file__).with_name("templates.json")
        self.templates = json.loads(tp.read_text(encoding="utf-8")) if tp.is_file() else {"commands": [], "files": []}
        self.default = default_version
        self._ex: OrderedDict[str, dict] = OrderedDict()

    def examples(self, version: str) -> dict:
        if version in self._ex:
            self._ex.move_to_end(version)
            return self._ex[version]
        ex = {}
        f = self.dir / f"mc-examples-{version}.json.gz" if self.dir else None
        if f and f.is_file():
            ex = json.loads(gzip.decompress(f.read_bytes()))
        self._ex[version] = ex
        while len(self._ex) > 3:
            self._ex.popitem(last=False)
        return ex

    def version_for(self, text: str) -> tuple[McVersion | None, bool]:
        """(version, named): the specific version the text names, else the default (latest 1.21.x)."""
        for m in VERSION_RE.findall(text or ""):
            if m != "1.21" and m in self.index.versions:
                return self.index.versions[m], True
        v = self.index.get(self.default) or (self.index.java121() or [self.index.newest()])[0]
        return v, False

    # ---------- parts ----------
    def pack_part(self, v: McVersion, q: str, data: bool, res: bool) -> list[str]:
        out = []
        df, rf = (v.pack.get("data") or [None])[0], (v.pack.get("resource") or [None])[0]
        multi = re.search(r"every version|all versions|multiple versions|from 1\.21 to|1\.21\.\d+ to 1\.21", q, re.I)
        for kind, f, on in (("data", df, data), ("resource", rf, res)):
            if not on or f is None:
                continue
            if multi:
                lo = self.index.get("1.21") or v
                lf = (lo.pack.get(kind) or [f])[0]
                hi = (self.index.get(self.default) or v).pack.get(kind, [f])[0]
                meta = (f'{{"pack": {{"description": "My pack", "pack_format": {lf}, "supported_formats": [{lf}, {hi}], '
                        f'"min_format": {lf}, "max_format": {hi}}}}}')
                out.append(f"{kind} pack pack.mcmeta for 1.21 ({lf}) up to {self.default} ({hi}), accepted by every "
                           f"1.21.x (the game's codec; 1.21.9+ needs min_format/max_format, older ones read "
                           f"pack_format + supported_formats): {meta}")
            elif v.key >= (1, 21, 9):
                out.append(f'{kind} pack format {f}; pack.mcmeta (since 1.21.9 min_format/max_format are required): '
                           f'{{"pack": {{"description": "My pack", "min_format": {f}, "max_format": {f}}}}}')
            else:
                out.append(f'{kind} pack format {f}; pack.mcmeta: {{"pack": {{"pack_format": {f}, '
                           f'"description": "My pack"}}}}')
        if data:
            folders = v.datapack_folders()
            want = ["function", "tags/function", "advancement", "recipe", "loot_table", "predicate", "item_modifier",
                    "tags/block", "tags/item", "enchantment", "painting_variant", "jukebox_song", "damage_type"]
            have = [f for f in want if f in folders]
            out.append("data pack folders (singular since 1.21): " + ", ".join(f"data/<ns>/{f}/" for f in have)
                       + "; load/tick: data/minecraft/tags/function/load.json and tick.json {\"values\": [\"ns:fn\"]}")
        if res:
            kinds = set(v.assets)
            want = ["blockstates", "models/block", "models/item", "items", "textures/block", "textures/item",
                    "equipment", "atlases", "font", "lang", "shaders"]
            have = [k for k in want if k.split("/")[0] in kinds or k == "lang"]
            out.append("resource pack folders: " + ", ".join(f"assets/<ns>/{k}/" for k in have)
                       + ", sounds in assets/<ns>/sounds.json + assets/<ns>/sounds/*.ogg"
                       + ("; item model definitions live in assets/<ns>/items/ (models/item 'overrides' were removed "
                          "in 1.21.4)" if v.key >= (1, 21, 4) else "; custom models use 'overrides' with "
                                                                    "custom_model_data in models/item"))
        return out

    def usage(self, v: McVersion, cmd: str, q: str, limit: int = 4) -> list[str]:
        node = v.tree.get("c", {}).get(cmd)
        if not node:
            return []
        paths: list[list[str]] = []

        def walk(n, parts, depth):
            if len(paths) > 400 or depth > 9:
                return
            if n.get("x") or "r" in n or ("c" not in n):
                paths.append(parts)
            if "r" in n:
                return
            for k, c in (n.get("c") or {}).items():
                if k.startswith("minecraft:"):
                    continue
                label = k if c["t"] == "l" else f"<{k}>"
                walk(c, parts + [label], depth + 1)
        walk(node, [cmd], 0)
        qw = set(_words(q))
        scored = sorted(paths, key=lambda p: (-len(qw & {x.strip("<>") for x in p}), len(p)))
        out, seen = [], set()
        for p in scored:
            s = " ".join(p)
            if s not in seen:
                seen.add(s)
                out.append(s)
            if len(out) >= limit:
                break
        return out

    def ids_part(self, v: McVersion, q: str) -> list[str]:
        words = _words(q)
        grams = set()
        for n in (3, 2, 1):
            for i in range(len(words) - n + 1):
                grams.add("_".join(words[i:i + n]))
        # plural -> singular for 1-grams ("zombies" -> zombie, "emeralds" -> emerald)
        grams |= {g[:-1] for g in grams if g.endswith("s") and "_" not in g}
        regs = [("item", "item"), ("block", "block"), ("entity_type", "entity"), ("mob_effect", "effect"),
                ("enchantment", "enchantment"), ("attribute", "attribute"), ("particle_type", "particle")]
        found: dict[str, list[str]] = {}
        taken = set()
        for g in sorted(grams, key=lambda x: -x.count("_")):
            if any(g in t.split("_") or g in t for t in taken if "_" in t) and "_" not in g:
                continue
            for reg, label in regs:
                if g in GENERIC_IDS or (label == "particle" and "particle" not in q.lower()):
                    continue
                if g in v.entries(reg):
                    found.setdefault(label, [])
                    if g not in found[label]:
                        found[label].append(g)
                        taken.add(g)
        out = []
        for label, ids in found.items():
            if label == "block":
                ids2 = []
                for b in ids[:4]:
                    props = v.blocks.get(b) or {}
                    st = ", ".join(f"{k}={'|'.join(vals[:4])}{'...' if len(vals) > 4 else ''}"
                                   for k, vals in list(props.items())[:4])
                    ids2.append(b + (f" [{st}]" if st else ""))
                ids = ids2
            out.append(f"{label}: " + ", ".join(ids[:6]))
        # sounds: match words against event names and English subtitles ("creeper hiss" -> entity.creeper.primed)
        if re.search(r"sound|hiss|playsound|music|song", q, re.I):
            lang = json.loads(self.examples(v.version).get("lang/en_us.json") or "{}")
            qs = {stem(w) for w in words if w not in SOUND_STOP}
            cands = []
            for ev in v.sound_events:
                sub = lang.get("subtitles." + ev, "")
                toks = {stem(t) for t in re.split(r"[._]", ev)} | {stem(w) for w in _words(sub)}
                score = len(qs & toks)
                if score >= 2:
                    cands.append((score, ev, sub))
            cands.sort(key=lambda x: (-x[0], len(x[1])))
            if cands:
                out.append("sound event: " + ", ".join(f"{ev}" + (f" ({sub})" if sub else "")
                                                       for _, ev, sub in cands[:3]))
        if re.search(r"gamerule|fire|griefing|breaking blocks|keep inventory|daylight|weather cycle|rule", q, re.I):
            rules = [k for k in (v.tree["c"].get("gamerule", {}).get("c") or {}) if not k.startswith("minecraft:")]
            qs = {stem(w) for w in words} - {"stop", "block", "command"}

            def toks(r):
                return {stem(t) for t in re.split(r"_|(?<=[a-z])(?=[A-Z])", r) if t} - {"do"}
            hits = sorted(rules, key=lambda r: (-len(qs & toks(r)), len(r)))
            hits = [r for r in hits if qs & toks(r)][:5]
            if hits:
                out.append(f"gamerules in {v.version} (exact names): " + ", ".join(hits))
        return out

    def template_part(self, v: McVersion, q: str, data: bool, asked: list[str] = ()) -> list[str]:
        ql = q.lower()

        def usable(t):
            if v.version not in t.get("valid", []) or t.get("skip"):
                return False
            if t.get("min") and v.key < vkey(t["min"]):
                return False
            if t.get("max") and v.key > vkey(t["max"]):
                return False
            return True

        def score(t):
            return sum(1 for k in t.get("kw", []) if re.search(r"\b" + re.escape(k) + r"\b", ql))
        out = []
        cmds = sorted((t for t in self.templates.get("commands", []) if usable(t) and score(t)), key=lambda t: -score(t))
        groups = set()
        for t in cmds:
            g = re.sub(r"_(new|old|asset|model|str|int|floats)$", "", t["id"])
            named = bool(_template_cmds(t) & set(asked))
            if g in groups or len(groups) >= 3 or not (score(t) >= 2 or (named and score(t) >= 1)):
                continue
            groups.add(g)
            line = t["cmd"].replace("\n", " | ")
            out.append(f"{line}" + (f"  ({t['note']})" if t.get("note") else ""))
        files = sorted((t for t in self.templates.get("files", []) if usable(t) and score(t) >= 1),
                       key=lambda t: -score(t))
        best = score(files[0]) if files else 0
        fg = set()
        for t in files:
            g = re.sub(r"_(new|old)$", "", t["id"])
            if g in fg or len(fg) >= 2 or (not data and score(t) < 2) or score(t) < max(1, best - 1):
                continue
            fg.add(g)
            out.append(f"{t['path']}: {json.dumps(t['json'], separators=(',', ':'))}"
                       + (f"  then: {t['use']}" if t.get("use") else "") + (f"  ({t['note']})" if t.get("note") else ""))
        return out

    def vanilla_part(self, v: McVersion, q: str, ids: list[str], res: bool, data: bool, room: int) -> list[str]:
        ex = self.examples(v.version)
        if not ex:
            return []
        ql = q.lower()
        picks: list[tuple[str, str]] = []

        def add(path, note=""):
            if path in ex and all(p != path for p, _ in picks):
                picks.append((path, note))
        mobs = [i for i in ids if i.startswith("entity: ")]
        mob_ids = [x.strip() for m in mobs for x in m[8:].split(",")]
        if data and re.search(r"drop|loot", ql):
            for m in mob_ids:
                add(f"data/minecraft/loot_table/entities/{m}.json", "vanilla; keep these pools when you replace it")
        if data and "enchant" in ql and re.search(r"custom|add|new|data pack", ql):
            add("data/minecraft/enchantment/sharpness.json", "vanilla enchantment to copy the structure from")
        if data and "painting" in ql:
            p = sorted((k for k in ex if k.startswith("data/minecraft/painting_variant/")), key=len)
            if p:
                add(p[0], "vanilla painting variant; the image goes in assets/<ns>/textures/painting/<asset_id>.png")
        if data and "jukebox" in ql:
            p = sorted((k for k in ex if k.startswith("data/minecraft/jukebox_song/")), key=len)
            if p:
                add(p[0], "vanilla jukebox song; its sound_event must exist in a resource pack sounds.json")
        if res:
            items = [x.strip() for i in ids if i.startswith("item: ") for x in i[6:].split(",")]
            blocks = [x.strip().split(" ")[0] for i in ids if i.startswith("block: ") for x in i[7:].split(", ")
                      if x.strip() and "=" not in x.split(" ")[0]]
            if v.key >= (1, 21, 4) and re.search(r"model|item_model|custom_model", ql):
                for it in items[:1]:
                    add(f"assets/minecraft/items/{it}.json", "vanilla item model definition")
            if re.search(r"block model|blockstate|block texture|block", ql):
                for b in blocks[:1]:
                    add(f"assets/minecraft/blockstates/{b}.json", "vanilla blockstate")
                    add(f"assets/minecraft/models/block/{b}.json", "vanilla block model")
            if re.search(r"armor|equippable|equipment", ql) and v.key >= (1, 21, 4):
                add("assets/minecraft/equipment/diamond.json", "vanilla equipment asset; textures in "
                    "assets/<ns>/textures/entity/equipment/humanoid/ and humanoid_leggings/")
            if re.search(r"atlas|missing", ql):
                add("assets/minecraft/atlases/blocks.json", "vanilla block atlas")
            if re.search(r"animat", ql):
                p = sorted((k for k in ex if k.endswith(".png.mcmeta") and "/block/" in k), key=len)
                if p:
                    add(p[0], "vanilla animated texture: put <texture>.png.mcmeta next to the png (frames stacked "
                              "vertically)")
        out, used = [], 0
        for path, note in picks:
            body = ex[path]
            try:
                body = json.dumps(json.loads(body), separators=(",", ":"))
            except ValueError:
                pass
            if used + len(body) > room:
                if room - used > 400:
                    body = body[:room - used - 20] + " ...(cut)"
                else:
                    continue
            used += len(body)
            out.append(f"{path} in {v.version} ({note}): {body}")
        return out

    def extra_res(self, v: McVersion, q: str) -> list[str]:
        out = []
        ql = q.lower()
        if v.key >= (1, 21, 4) and "custom_model_data" in ql or ("custom model" in ql and v.key >= (1, 21, 4)):
            out.append("1.21.4+ item model definition selecting on custom_model_data (assets/minecraft/items/stick.json; "
                       "give @s stick[custom_model_data={floats:[1.0]}]): " + RANGE_DISPATCH_CMD)
        if re.search(r"emoji|font|character", ql):
            out.append('font (assets/minecraft/font/default.json adds to the chat font): {"providers": [{"type": '
                       '"bitmap", "file": "mypack:font/emoji.png", "ascent": 7, "height": 8, "chars": ["\\uE000"]}]} '
                       '(png in assets/mypack/textures/font/emoji.png); type it with tellraw @a {"text":"\\uE000"}')
        if "hotbar" in ql and "gui/sprites/hud/hotbar" in v.assets.get("textures", ()):
            out.append("hotbar texture: assets/minecraft/textures/gui/sprites/hud/hotbar.png (and "
                       "hud/hotbar_selection.png); GUI sprites live in textures/gui/sprites/ since 1.20.2")
        if re.search(r"language|lang|item name", ql):
            out.append("language file: assets/minecraft/lang/en_us.json (lowercase), flat {\"item.minecraft.diamond\": "
                       "\"Shiny Rock\"}; keys like item.minecraft.<id>, block.minecraft.<id>")
        if re.search(r"sound|\.ogg", ql):
            out.append('sounds.json (assets/<ns>/sounds.json): {"event.name": {"sounds": ["<ns>:path/file"], '
                       '"replace": true}} (names without .ogg; files in assets/<ns>/sounds/path/file.ogg, mono for '
                       '3D sound); play: playsound <ns>:event.name master @a')
        return out

    # ---------- block ----------
    def block(self, question: str, extra: str = "", budget_chars: int = 3200) -> dict:
        q = question or ""
        if not self.index or not MC.search(q + " " + (extra or "")[-500:]):
            return {"text": "", "version": None, "parts": []}
        v, named = self.version_for(q)
        if v is None:
            return {"text": "", "version": None, "parts": []}
        data, res = bool(DATAPACK.search(q)), bool(RESPACK.search(q))
        if res and re.search(r"resource ?pack", q, re.I) and not re.search(
                r"data ?pack|\bfunction\b|recipe|loot|advancement|predicate", q, re.I):
            data = False                         # "pack.mcmeta" alone in a resource pack question
        parts, lines = [], []
        lines.append(f"Minecraft Java {v.version} facts, read from the game's own files and checked with its own "
                     f"parser (use exactly these ids and syntax"
                     + ("" if named else f"; no version was named: write for {v.version}, the latest 1.21.x, and say so")
                     + "):")
        pk = self.pack_part(v, q, data, res)
        if pk:
            parts.append("pack")
            lines += ["- " + x for x in pk]
        ids = self.ids_part(v, q)
        if ids:
            parts.append("ids")
            lines.append("- ids: " + "; ".join(ids))
        cmds = [c for c, kws in COMMAND_WORDS.items() if any(k in q.lower() for k in kws)]
        cmds += [m for m in re.findall(r"/([a-z]+)", q) if m in v.tree["c"] and m not in cmds]
        us = []
        for c in cmds[:3]:
            if c != "gamerule":                  # the gamerule names are listed with the ids
                us += self.usage(v, c, q, 3 if c in ("execute", "scoreboard", "data", "item") else 2)
        if us:
            parts.append("usage")
            lines.append("- command syntax (real command tree): " + " | ".join(us[:8]))
        tp = self.template_part(v, q, data, cmds)
        if tp:
            parts.append("templates")
            lines.append(f"- checked with the {v.version} parser:")
            lines += ["  " + x for x in tp]
        er = self.extra_res(v, q) if res else []
        if er:
            parts.append("respack")
            lines += ["- " + x for x in er]
        room = budget_chars - sum(len(x) + 1 for x in lines)
        if room > 300:
            van = self.vanilla_part(v, q, ids, res, data, room)
            if van:
                parts.append("vanilla")
                lines += ["- " + x for x in van]
        text = "\n".join(lines)
        if len(text) > budget_chars + 200:
            text = text[:budget_chars] + " ...(cut)"
        return {"text": text, "version": v.version, "parts": parts}
