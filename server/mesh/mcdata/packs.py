"""Data pack and resource pack file checks against the game's own data (folder names from the datapack report, vanilla
ids, client asset names, pack formats), for the version(s) an answer targets.

    problems = check_file(path, code, index, prose)       # path like data/ns/recipe/x.json, assets/ns/models/...
    problems = check_tree(paths, index, prose)            # paths from a folder-tree block
"""
from __future__ import annotations

import json
import re

from .commands import check_commands, suggest
from .index import McIndex, McVersion, short

OLD_DATA = {"functions": "function", "advancements": "advancement", "loot_tables": "loot_table",
            "predicates": "predicate", "recipes": "recipe", "structures": "structure", "item_modifiers": "item_modifier",
            "tags/functions": "tags/function", "tags/blocks": "tags/block", "tags/items": "tags/item",
            "tags/entity_types": "tags/entity_type", "tags/fluids": "tags/fluid", "tags/game_events": "tags/game_event"}
OLD_ASSETS = {"textures/blocks": "textures/block", "textures/items": "textures/item", "models/blocks": "models/block",
              "models/items": "models/item"}
ASSET_ROOT_FILES = {"sounds.json", "regional_compliancies.json", "gpu_warnlist.json"}
ITEM_MODEL_TYPES = {"model", "range_dispatch", "select", "condition", "composite", "special", "empty",
                    "bundle/selected_item"}
ATLAS_SOURCES = {"directory", "single", "filter", "unstitch", "paletted_permutations"}
FONT_PROVIDERS = {"bitmap", "ttf", "space", "unihex", "reference", "legacy_unicode"}
ID_STR = re.compile(r"^#?minecraft:[a-z0-9_./-]+$")


def _p(kind, message, suggestion=None, name=None, severity="error", line=None) -> dict:
    return {"kind": kind, "severity": severity, "name": name, "message": message, "suggestion": suggestion,
            "line": line}


def targets(index: McIndex, prose: str) -> list[McVersion]:
    from .index import VERSION_RE
    named = set(VERSION_RE.findall(prose or ""))
    vs = index.resolve(prose)
    if named:
        t = [v for v in vs if v.version in named or ("1.21" in named and v.version.startswith("1.21"))]
        if t:
            return t
    return index.java121() or vs[:1]


def split_path(path: str) -> tuple[str, str, str, str] | None:
    """data/<ns>/<folder...>/<file> -> (root, ns, rest-without-file-ext..., ext)."""
    m = re.match(r"^(data|assets)/([^/]+)/(.+)$", path)
    if not m:
        return None
    rest = m.group(3)
    ext = rest.rsplit(".", 1)[-1] if "." in rest.rsplit("/", 1)[-1] else ""
    return m.group(1), m.group(2), rest, ext


def data_folder(rest: str, folders: set[str]) -> str | None:
    """Longest known folder that the path starts with (worldgen/biome, tags/block, function ...)."""
    best = None
    for f in folders:
        if rest.startswith(f + "/") and (best is None or len(f) > len(best)):
            best = f
    return best


def check_path(path: str, index: McIndex, prose: str = "") -> list[dict]:
    sp = split_path(path)
    if not sp:
        return []
    root, ns, rest, ext = sp
    out = []
    if not re.fullmatch(r"[a-z0-9_.-]+", ns):
        out.append(_p("mc_pack", f"namespace '{ns}' must be lowercase letters, digits, _ . -", ns.lower(), ns))
    if re.search(r"[A-Z ]", rest):
        out.append(_p("mc_pack", f"file and folder names must be lowercase without spaces: '{rest}'",
                      rest.lower().replace(" ", "_"), rest))
    ts = targets(index, prose)
    if root == "data":
        for old, new in OLD_DATA.items():
            if rest.startswith(old + "/"):
                out.append(_p("mc_datapack", f"since Java 1.21 the folder is '{new}', not '{old}' (the game ignores "
                                             f"'{old}/')", f"data/{ns}/{new}/", f"data/{ns}/{old}/"))
                return out
        okv = [v for v in ts if data_folder(rest, v.datapack_folders())]
        if not okv:
            folder = rest.split("/")[0] if not rest.startswith("tags/") else "/".join(rest.split("/")[:2])
            allf = sorted(ts[0].datapack_folders())
            elsewhere = [v.version for v in index.versions.values() if data_folder(rest, v.datapack_folders())]
            msg = f"the game does not read data/{ns}/{folder}/ in {ts[0].version}"
            if elsewhere:
                msg += f" (it exists in {elsewhere[0]}-{elsewhere[-1]})"
            out.append(_p("mc_datapack", msg, " or ".join(suggest(folder, allf)) or None, folder))
    else:
        if rest in ASSET_ROOT_FILES:
            return out
        for old, new in OLD_ASSETS.items():
            if rest.startswith(old + "/"):
                out.append(_p("mc_resourcepack", f"the folder is '{new}', not '{old}' (the game will not find it)",
                              f"assets/{ns}/{new}/", f"assets/{ns}/{old}/"))
                return out
        kind = rest.split("/")[0]
        kinds = set()
        for v in ts:
            kinds |= set(v.assets) | {"lang", "sounds", "texts", "shaders"}
        if kinds and kind not in kinds:
            out.append(_p("mc_resourcepack", f"assets/{ns}/{kind}/ is not a folder the game reads in "
                                             f"{ts[0].version}", " or ".join(suggest(kind, kinds)) or None, kind))
        if kind == "items" and all(v.key < (1, 21, 4) for v in ts):
            out.append(_p("mc_resourcepack", "item model definitions (assets/<ns>/items/) exist since 1.21.4; "
                                             "older versions use models/item overrides", None, "items", "warning"))
        if kind == "lang" and ext == "json" and not re.fullmatch(r"lang/[a-z]{2,3}_[a-z]{2,3}\.json", rest):
            out.append(_p("mc_resourcepack", f"language files are lowercase like lang/en_us.json, not {rest}",
                          "lang/" + rest.split("/")[-1].lower(), rest))
    return out


def check_tree(paths: list[str], index: McIndex, prose: str = "") -> list[dict]:
    out, seen = [], set()
    for p in paths:
        p = p.rstrip("/")
        if not p.startswith(("data/", "assets/")):
            continue
        sp = split_path(p + ("/x.json" if "." not in p.rsplit("/", 1)[-1] else ""))
        if not sp:
            continue
        for prob in check_path(sp[0] + "/" + sp[1] + "/" + sp[2], index, prose):
            if prob["message"] not in seen and prob["kind"] in ("mc_datapack", "mc_resourcepack") and \
                    (prob["severity"] == "error"):
                seen.add(prob["message"])
                out.append(prob)
    return out


CLIENT_KEYS = {"type", "property", "when", "source"}     # client-side registries (item model types ...): not in reports


def _ids(obj, skip=frozenset()):
    if isinstance(obj, str):
        if ID_STR.match(obj):
            yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k not in skip:
                yield from _ids(v, skip)
    elif isinstance(obj, list):
        for v in obj:
            yield from _ids(v, skip)


# PackFormat.lastPreMinorVersion: above these, 1.21.9+ needs min_format/max_format (checked with the game's codec)
LAST_PRE_MINOR = {"data": 81, "resource": 64}


def _fmt(x):
    if isinstance(x, list) and x and isinstance(x[0], int):
        return x[0]
    return x if isinstance(x, int) else None


def meta_problem(pack: dict, v: McVersion, kind: str) -> str | None:
    """Why this version's game would refuse the pack section (None = it loads), same rules as the game's codec."""
    if "description" not in pack:
        return "pack.mcmeta needs a \"description\""
    fmt, lo, hi = _fmt(pack.get("pack_format")), _fmt(pack.get("min_format")), _fmt(pack.get("max_format"))
    sup = pack.get("supported_formats")
    sup_hi = (sup[-1] if isinstance(sup, list) and sup else sup.get("max_inclusive") if isinstance(sup, dict)
              else sup if isinstance(sup, int) else None)
    if v.key < (1, 21, 9):
        if fmt is None:
            return f"{v.version} needs \"pack_format\" (min_format/max_format are only read since 1.21.9)"
        return None
    top = max([x for x in (fmt, sup_hi, hi) if isinstance(x, int)] or [0])
    if top > LAST_PRE_MINOR[kind] and (lo is None or hi is None):
        return (f"since 1.21.9 a pack for format {top} needs \"min_format\" and \"max_format\" (pack_format alone "
                f"is only for formats up to {LAST_PRE_MINOR[kind]})")
    if fmt is None and lo is None:
        return "pack.mcmeta needs min_format and max_format"
    return None


def check_pack_mcmeta(code: str, index: McIndex, prose: str, is_resource: bool | None) -> list[dict]:
    try:
        data = json.loads(code)
    except ValueError as e:
        return [_p("syntax", f"pack.mcmeta is not valid JSON: {e}", None, "pack.mcmeta")]
    pack = data.get("pack") if isinstance(data, dict) else None
    if not isinstance(pack, dict):
        return [_p("mc_pack", "pack.mcmeta needs {\"pack\": {\"pack_format\": <number>, \"description\": ...}}", None,
                   "pack.mcmeta")]
    ts = targets(index, prose)
    kinds = ["resource"] if is_resource else ["data"] if is_resource is False else ["data", "resource"]
    probs = {(v.version, k): meta_problem(pack, v, k) for v in ts for k in kinds}
    okv = [(v, k) for v in ts for k in kinds if probs[(v.version, k)] is None]
    if not okv:
        v, k = ts[0], kinds[0]
        f = (v.pack.get(k) or [None, 0])
        ex = (f'{{"pack": {{"description": "...", "min_format": {f[0]}, "max_format": {f[0]}}}}}' if v.key >= (1, 21, 9)
              else f'{{"pack": {{"pack_format": {f[0]}, "description": "..."}}}}')
        return [_p("mc_pack", f"{v.version} will not load this pack: {probs[(v.version, k)]}", ex, "pack.mcmeta")]
    out = []
    fmt = _fmt(pack.get("pack_format")) or _fmt(pack.get("min_format"))
    hi = _fmt(pack.get("max_format"))
    sup = pack.get("supported_formats")
    if isinstance(fmt, int) and not sup:
        fits = [(v, k) for v, k in okv if (v.pack.get(k) or [None])[0] is not None and
                (fmt <= v.pack[k][0] <= hi if isinstance(hi, int) else fmt == v.pack[k][0])]
        if not fits:
            v, k = okv[0]
            want = v.pack[k][0]
            other = [x.version for x in index.versions.values() if (x.pack.get(k) or [None])[0] == fmt]
            out.append(_p("mc_pack", f"format {fmt} is not {v.version}'s {k} pack format ({want})"
                                     + (f"; {fmt} is {other[0]}" + (f"-{other[-1]}" if len(other) > 1 else "")
                                        if other else "") + ": the game marks the pack as made for another version",
                          str(want), str(fmt), "warning"))
    return out


def check_file(path: str | None, code: str, index: McIndex, prose: str = "", lang: str = "") -> list[dict]:
    """Problems of one file of an answer. path=None: only the content (JSON syntax, ids)."""
    out = []
    path = path or ""
    if path:
        out += check_path(path, index, prose)
    name = path.rsplit("/", 1)[-1]
    if name == "pack.mcmeta" or (not path and '"pack_format"' in code):
        is_res = True if re.search(r"resource ?pack|assets/", prose, re.I) and not re.search(r"data ?pack", prose,
                                                                                          re.I) else \
            False if re.search(r"data ?pack", prose, re.I) and not re.search(r"resource ?pack", prose, re.I) else None
        return out + check_pack_mcmeta(code, index, prose, is_res)
    if path.endswith(".mcfunction"):
        return out + check_commands(code, index, prose, in_function=True)
    if not (path.endswith((".json", ".mcmeta")) or lang == "json"):
        return out
    stripped = code.strip()
    if stripped.startswith("//") or stripped.startswith("#"):
        out.append(_p("syntax", "JSON files cannot have comments: remove the first line", None, stripped.split("\n")[0]))
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
    try:
        data = json.loads(stripped)
    except ValueError as e:
        if "..." in stripped:
            return out
        return out + [_p("syntax", f"not valid JSON: {e}", None, None)]
    ts = targets(index, prose)
    # every minecraft: id must exist in the target version (registries, vanilla data files, assets, sounds)
    bad = []
    for rid in dict.fromkeys(_ids(data, CLIENT_KEYS if path.startswith("assets/") else frozenset())):
        key = short(rid.lstrip("#"))
        if rid.startswith("#"):
            if not any(key in v.data.get(f, ()) for v in ts for f in v.data if f.startswith("tags/")):
                bad.append(rid)
        elif not any(key in v.all_ids() for v in ts):
            bad.append(rid)
    for rid in bad[:4]:
        pool = ts[0].all_ids() if not rid.startswith("#") else frozenset().union(
            *[ts[0].data[f] for f in ts[0].data if f.startswith("tags/")])
        out.append(_p("mc_id", f"'{rid}' does not exist in {ts[0].version}",
                      " or ".join(("#" if rid.startswith("#") else "") + "minecraft:" + s
                                  for s in suggest(short(rid.lstrip("#")), pool)) or None, rid))
    sp = split_path(path) if path else None
    if sp and sp[0] == "data":
        out += _check_data_json(sp[2], data, ts)
    elif sp and sp[0] == "assets":
        out += _check_asset_json(sp[2], data, ts, path)
    return out


def _check_data_json(rest: str, data, ts: list[McVersion]) -> list[dict]:
    out = []
    if rest.startswith("recipe/") and isinstance(data, dict):
        new = all(v.key >= (1, 21, 2) for v in ts)
        old = all(v.key < (1, 21, 2) for v in ts)
        ings = []
        if isinstance(data.get("key"), dict):
            ings += list(data["key"].values())
        if "ingredients" in data and isinstance(data["ingredients"], list):
            ings += data["ingredients"]
        if "ingredient" in data:
            ings.append(data["ingredient"])
        for ing in ings:
            if new and isinstance(ing, dict):
                out.append(_p("mc_recipe", "since 1.21.2 an ingredient is just the id string (\"minecraft:diamond\"),"
                                           " a list of ids, or a tag string \"#minecraft:planks\"",
                              json.dumps(ing.get("item") or ("#" + ing["tag"] if ing.get("tag") else None)),
                              json.dumps(ing)[:60]))
                break
            if old and isinstance(ing, str):
                out.append(_p("mc_recipe", "before 1.21.2 an ingredient is {\"item\": \"minecraft:x\"} or "
                                           "{\"tag\": \"minecraft:y\"}", None, ing))
                break
        res = data.get("result")
        if isinstance(res, dict) and "item" in res and "id" not in res:
            out.append(_p("mc_recipe", "since 1.20.5 the recipe result uses \"id\", not \"item\"", None, "item"))
        if data.get("type") in ("minecraft:shaped", "shaped", "minecraft:shapeless", "shapeless"):
            out.append(_p("mc_recipe", f"unknown recipe type {data['type']}",
                          "minecraft:crafting_" + short(data["type"]), data["type"]))
    if rest.startswith("tags/") and isinstance(data, dict) and not isinstance(data.get("values"), list):
        out.append(_p("mc_tag", "a tag file is {\"values\": [ ... ]}", None, "values"))
    return out


def _check_asset_json(rest: str, data, ts: list[McVersion], path: str) -> list[dict]:
    out = []
    if not isinstance(data, dict):
        return out
    kind = rest.split("/")[0]
    if kind == "items":
        model = data.get("model")
        if not isinstance(model, dict):
            out.append(_p("mc_item_model", "an item model definition (assets/<ns>/items/x.json) is "
                                           "{\"model\": {\"type\": \"minecraft:model\", \"model\": \"<ns>:item/x\"}}",
                          None, "model"))
        else:
            out += _item_model(model)
        if "overrides" in data:
            out.append(_p("mc_item_model", "'overrides' belongs to the old models/item files and is ignored in "
                                           "items/ definitions", None, "overrides"))
    if kind == "models":
        if "overrides" in data and all(v.key >= (1, 21, 4) for v in ts):
            out.append(_p("mc_item_model", "model 'overrides' (custom_model_data predicates) were removed in "
                                           "1.21.4: use an item model definition in assets/<ns>/items/ with "
                                           "range_dispatch or select on custom_model_data", None, "overrides"))
    if kind == "atlases":
        for s in data.get("sources") or []:
            t = short(str(s.get("type", ""))) if isinstance(s, dict) else ""
            if t not in ATLAS_SOURCES:
                out.append(_p("mc_atlas", f"unknown atlas source type '{t}'",
                              " or ".join(suggest(t, ATLAS_SOURCES)) or None, t))
            elif t == "directory" and not ("source" in s and "prefix" in s):
                out.append(_p("mc_atlas", "a directory source needs \"source\" and \"prefix\"", None, "directory"))
    if kind == "font":
        for pr in data.get("providers") or []:
            t = short(str(pr.get("type", ""))) if isinstance(pr, dict) else ""
            if t not in FONT_PROVIDERS:
                out.append(_p("mc_font", f"unknown font provider type '{t}'",
                              " or ".join(suggest(t, FONT_PROVIDERS)) or None, t))
            elif t == "bitmap" and not all(k in pr for k in ("file", "chars", "ascent")):
                out.append(_p("mc_font", "a bitmap provider needs file, ascent and chars", None, "bitmap"))
    if kind == "blockstates":
        if "variants" not in data and "multipart" not in data:
            out.append(_p("mc_blockstate", "a blockstate file needs \"variants\" or \"multipart\"", None, None))
        block = rest.split("/")[-1][:-5]
        props = None
        for v in ts:
            props = v.blocks.get(block) if path.startswith("assets/minecraft/") else None
            if props is not None:
                break
        if props is not None and isinstance(data.get("variants"), dict):
            for key in data["variants"]:
                for part in filter(None, key.split(",")):
                    k, _, val = part.partition("=")
                    if k and k not in props:
                        out.append(_p("mc_blockstate", f"{block} has no block state '{k}'"
                                                       + (f" (it has: {', '.join(props)})" if props else
                                                          " (it has none: use \"\")"), None, k))
                        break
    if rest == "sounds.json" or path.endswith("/sounds.json"):
        for ev, body in data.items():
            if not isinstance(body, dict) or not isinstance(body.get("sounds"), list):
                out.append(_p("mc_sounds", f"sound event '{ev}' needs {{\"sounds\": [\"<ns>:path/without_ogg\"]}}",
                              None, ev))
                break
            for snd in body["sounds"]:
                name = snd.get("name") if isinstance(snd, dict) else snd
                if isinstance(name, str) and name.endswith(".ogg"):
                    out.append(_p("mc_sounds", f"sound names have no .ogg ending: '{name}'", name[:-4], name))
                    break
    if path.endswith(".png.mcmeta") or (path.endswith(".mcmeta") and "textures/" in path):
        an = data.get("animation")
        if an is not None and not isinstance(an, dict):
            out.append(_p("mc_texture", "\"animation\" must be an object like {\"frametime\": 2}", None, "animation"))
    return out


def _item_model(m: dict, depth: int = 0) -> list[dict]:
    if depth > 6 or not isinstance(m, dict):
        return []
    out = []
    t = short(str(m.get("type", "")))
    if t not in ITEM_MODEL_TYPES:
        out.append(_p("mc_item_model", f"unknown item model type '{m.get('type')}'",
                      " or ".join("minecraft:" + s for s in suggest(t, ITEM_MODEL_TYPES)) or None, str(m.get("type"))))
        return out
    need = {"model": ["model"], "range_dispatch": ["property", "entries"], "select": ["property", "cases"],
            "condition": ["property", "on_true", "on_false"], "composite": ["models"], "special": ["model", "base"]}
    for k in need.get(t, []):
        if k not in m:
            out.append(_p("mc_item_model", f"item model type {t} needs '{k}'", None, k))
    for e in (m.get("entries") or []) if t == "range_dispatch" else []:
        if isinstance(e, dict):
            if "threshold" not in e:
                out.append(_p("mc_item_model", "each range_dispatch entry needs 'threshold' and 'model'", None,
                              "threshold"))
            out += _item_model(e.get("model"), depth + 1)
    for c in (m.get("cases") or []) if t == "select" else []:
        if isinstance(c, dict):
            if "when" not in c:
                out.append(_p("mc_item_model", "each select case needs 'when' and 'model'", None, "when"))
            out += _item_model(c.get("model"), depth + 1)
    for k in ("on_true", "on_false", "fallback"):
        if isinstance(m.get(k), dict):
            out += _item_model(m[k], depth + 1)
    return out
