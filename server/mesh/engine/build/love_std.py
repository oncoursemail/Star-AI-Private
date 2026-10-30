"""LOVE 11.5 standard names for the checker (luacheck std + key names), from the running engine and the API index.

    python love_std.py lovedump.txt ljdump.txt love-index.json > ../../polyglot/data/love_std.json

lovedump.txt / ljdump.txt are dumps of the running engine (xvfb-run love on a main.lua that walks love.* and the
LuaJIT standard tables, written by deploy.sh engine), love-index.json comes from love_index.lua.
Output: {"lj": {"_G": [...], "string": [...], ...}, "love": {"graphics": [...], ..., "_top": [...]},
         "keys": [...], "scancodes": [...], "callbacks": [...], "methods": [...]}
"""
import json
import sys


def parse(path, prefix=""):
    out = {}
    for line in open(path, encoding="utf-8"):
        key, _, rest = line.strip().partition("=")
        if prefix and not key.startswith(prefix):
            continue
        names = [x.split(":")[0] for x in rest.split(",") if x and not x.startswith("<")]
        if names or not rest.startswith("<"):         # "<nil>": the library is not a global (utf8 needs require)
            out[key[len(prefix):]] = names
    return out


def main(lovedump, ljdump, index):
    love = parse(lovedump)
    lj = parse(ljdump, "LJ.")
    lj.pop("_VERSION", None)
    idx = json.load(open(index, encoding="utf-8"))
    enums = {e["name"]: e["constants"] for m in idx["modules"] for e in m["enums"]}
    methods = sorted({f["n"] for m in idx["modules"] for t in m["types"] for f in t["functions"]})
    top = love.pop("love", [])
    for k in ("_modules", "_version_compat", "arg"):
        love.pop(k, None)
    return {"lj": lj,
            "love": {**love, "_top": sorted(set(top) | {c["n"] for c in idx["callbacks"]} |
                                            {"handlers", "run", "errorhandler", "errhand", "init", "boot", "_version"})},
            "keys": enums.get("KeyConstant", []), "scancodes": enums.get("Scancode", []),
            "callbacks": [c["n"] for c in idx["callbacks"]], "methods": methods}


if __name__ == "__main__":
    json.dump(main(*sys.argv[1:4]), sys.stdout, indent=0, sort_keys=True)
