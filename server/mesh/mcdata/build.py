"""Build the compact Minecraft index from the game's own data (run where the jars are: the throwaway lab container).

    python3 -m mesh.mcdata.build /srv/mc/<ver> [...] --out /srv/mc/index

Per version directory (see lab/fetch_and_generate.sh): server.jar + generated/reports (data generator), client.jar,
sounds.json, version.json. Writes <out>/mc-<ver>.json.gz and <out>/versions.json. Stdlib only. The output is Mojang
data (EULA): it stays on our machines (lab container, star-mesh) and is never committed.
"""
from __future__ import annotations

import gzip
import io
import json
import re
import sys
import zipfile
from pathlib import Path

# data/<ns>/<folder>/... folders whose vanilla file names we keep (ids a command or a pack can reference)
KEEP_DATA = re.compile(r"^data/minecraft/(?P<folder>[a-z_/]+?)/(?P<path>[a-z0-9_./-]+)\.(json|nbt|mcfunction)$")
ASSET = re.compile(r"^assets/minecraft/(?P<kind>blockstates|models|items|textures|atlases|equipment|font|lang|shaders|"
                   r"particles|post_effect|texts|sounds|waypoint_style)/(?P<path>[^ ]+?)\.(json|png|mcmeta|txt|fsh|vsh|"
                   r"glsl|ogg)$")


def strip_tree(node: dict) -> dict:
    out = {"t": node["type"][0]}                         # r(oot) l(iteral) a(rgument)
    if node.get("executable"):
        out["x"] = 1
    if node.get("parser"):
        out["p"] = node["parser"]
    if node.get("properties"):
        out["o"] = node["properties"]
    if "redirect" in node:
        out["r"] = node["redirect"]
    if node.get("children"):
        out["c"] = {k: strip_tree(v) for k, v in node["children"].items()}
    return out


def inner_jar(server_jar: Path) -> zipfile.ZipFile:
    z = zipfile.ZipFile(server_jar)
    names = [n for n in z.namelist() if n.startswith("META-INF/versions/") and n.endswith(".jar")]
    return zipfile.ZipFile(io.BytesIO(z.read(names[0]))) if names else z


def pack_formats(server_jar: Path) -> dict:
    pv = json.loads(zipfile.ZipFile(server_jar).read("version.json")).get("pack_version") or {}
    if "data" in pv:
        return {"resource": [pv["resource"], 0], "data": [pv["data"], 0]}
    return {"resource": [pv.get("resource_major"), pv.get("resource_minor", 0)],
            "data": [pv.get("data_major"), pv.get("data_minor", 0)]}


def build_version(d: Path) -> dict:
    rep = d / "generated" / "reports"
    ver = d.name
    out: dict = {"version": ver, "sha1": (d / "SHA1").read_text().strip(), "pack": pack_formats(d / "server.jar")}
    out["commands"] = strip_tree(json.loads((rep / "commands.json").read_text()))
    regs = json.loads((rep / "registries.json").read_text())
    out["registries"] = {k: sorted(v["entries"]) for k, v in regs.items()}
    blocks = json.loads((rep / "blocks.json").read_text())
    out["blocks"] = {k: v.get("properties") or {} for k, v in blocks.items()}
    if (rep / "datapack.json").exists():
        dp = json.loads((rep / "datapack.json").read_text())
        out["datapack"] = {"registries": {k: {"elements": v.get("elements", False), "tags": v.get("tags", False)}
                                          for k, v in dp["registries"].items()},
                           "others": dp.get("others", {})}
    # vanilla data-driven entries + tags (enchantments, damage types, loot tables, recipes, advancements, ...)
    data: dict[str, list] = {}
    for n in inner_jar(d / "server.jar").namelist():
        m = KEEP_DATA.match(n)
        if m:
            data.setdefault(m.group("folder"), []).append(m.group("path"))
    out["data"] = {k: sorted(v) for k, v in sorted(data.items())}
    # item default components: the shape of each component's value (keys of a compound) for value checks
    comps: dict[str, set] = {}
    items_json = rep / "items.json"
    if items_json.exists():
        for item in json.loads(items_json.read_text()).values():
            for cname, val in (item.get("components") or {}).items():
                s = comps.setdefault(cname, set())
                if isinstance(val, dict):
                    s.update(val.keys())
    out["component_keys"] = {k: sorted(v) for k, v in comps.items()}
    # client assets
    if (d / "client.jar").exists():
        assets: dict[str, list] = {}
        cz = zipfile.ZipFile(d / "client.jar")
        for n in cz.namelist():
            m = ASSET.match(n)
            if m:
                assets.setdefault(m.group("kind"), []).append(m.group("path"))
        out["assets"] = {k: sorted(v) for k, v in assets.items()}
        try:
            out["lang"] = sorted(json.loads(cz.read("assets/minecraft/lang/en_us.json")))
        except KeyError:
            pass
    if (d / "sounds.json").exists():
        out["sound_events"] = sorted(json.loads((d / "sounds.json").read_text()).keys())
    if (d / "assets.json").exists():
        objs = json.loads((d / "assets.json").read_text()).get("objects") or {}
        out["sound_files"] = sorted(k[len("minecraft/sounds/"):-4] for k in objs
                                    if k.startswith("minecraft/sounds/") and k.endswith(".ogg"))
    return out


EX_DATA_ALL = re.compile(r"^data/minecraft/(enchantment|loot_table/entities|painting_variant|jukebox_song|damage_type|"
                         r"tags/(block|item|entity_type)|dialog|trim_material|trim_pattern|banner_pattern|instrument|"
                         r"wolf_variant)/[^ ]+\.json$")
EX_ASSET_ALL = re.compile(r"^assets/minecraft/(items|equipment|atlases|blockstates|models/block|models/item|font)/[^ ]+\.json$"
                          r"|^assets/minecraft/textures/.+\.png\.mcmeta$")


def build_examples(d: Path) -> dict:
    """Vanilla files of this version that make good exact examples (facts block): every recipe type, every
    advancement trigger, mob loot tables, enchantments, painting/jukebox/damage types, tags; client: item model
    definitions, blockstates, block/item models, equipment, atlases, fonts, animated texture .mcmeta, sounds.json."""
    ex: dict[str, str] = {}
    best_recipe: dict[str, tuple[int, str, str]] = {}
    best_adv: dict[str, tuple[int, str, str]] = {}
    z = inner_jar(d / "server.jar")
    for n in z.namelist():
        if not n.startswith("data/minecraft/") or not n.endswith(".json"):
            continue
        if EX_DATA_ALL.match(n):
            ex[n] = z.read(n).decode()
        elif n.startswith("data/minecraft/recipe/"):
            raw = z.read(n).decode()
            t = (json.loads(raw).get("type") or "") if raw.strip().startswith("{") else ""
            if t not in best_recipe or len(raw) < best_recipe[t][0]:
                best_recipe[t] = (len(raw), n, raw)
        elif n.startswith("data/minecraft/advancement/"):
            raw = z.read(n).decode()
            try:
                trig = {c.get("trigger") for c in (json.loads(raw).get("criteria") or {}).values()}
            except (ValueError, AttributeError):
                continue
            for t in trig:
                if t and (t not in best_adv or len(raw) < best_adv[t][0]):
                    best_adv[t] = (len(raw), n, raw)
    for _, n, raw in list(best_recipe.values()) + list(best_adv.values()):
        ex[n] = raw
    if (d / "client.jar").exists():
        cz = zipfile.ZipFile(d / "client.jar")
        for n in cz.namelist():
            if EX_ASSET_ALL.match(n):
                ex[n] = cz.read(n).decode()
        try:                            # English names/subtitles: "creeper hiss" -> entity.creeper.primed
            lang = json.loads(cz.read("assets/minecraft/lang/en_us.json"))
            ex["lang/en_us.json"] = json.dumps({k: v for k, v in lang.items() if k.startswith(
                ("subtitles.", "item.minecraft.", "block.minecraft.", "entity.minecraft.", "effect.minecraft.",
                 "enchantment.minecraft.", "gamerule."))})
        except KeyError:
            pass
    if (d / "sounds.json").exists():
        ex["assets/minecraft/sounds.json"] = (d / "sounds.json").read_text()
    return ex


def main(argv: list[str]) -> int:
    if "--out" not in argv:
        print(__doc__)
        return 2
    i = argv.index("--out")
    outdir, dirs = Path(argv[i + 1]), [Path(a) for a in argv[:i] + argv[i + 2:] if not a.startswith("--")]
    outdir.mkdir(parents=True, exist_ok=True)
    vers = {}
    for d in dirs:
        idx = build_version(d)
        raw = json.dumps(idx, separators=(",", ":")).encode()
        (outdir / f"mc-{d.name}.json.gz").write_bytes(gzip.compress(raw, 9))
        vers[d.name] = {"sha1": idx["sha1"], "pack": idx["pack"], "bytes": len(raw)}
        print(d.name, len(raw) >> 10, "KB", idx["pack"], flush=True)
        if "--examples" in argv:
            ex = json.dumps(build_examples(d), separators=(",", ":")).encode()
            (outdir / f"mc-examples-{d.name}.json.gz").write_bytes(gzip.compress(ex, 9))
            print(d.name, "examples", len(ex) >> 10, "KB", flush=True)
    old = json.loads((outdir / "versions.json").read_text()) if (outdir / "versions.json").exists() else {}
    old.update(vers)
    (outdir / "versions.json").write_text(json.dumps(old, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
