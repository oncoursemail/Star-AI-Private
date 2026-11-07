"""Signatures of the LOVE functions the facts note quotes, from love-index.json (build/love_index.lua over the
love2d-community/love-api description of LOVE 11.5; the wiki prose is dropped) cross-checked with the names the running
engine exposes (a dump of love.* under xvfb). Writes data/love_sigs.json: {"graphics.rectangle": "love.graphics.rectangle(...)"}.

    python love_sigs.py love-index.json lovedump.txt ../facts_data.py > ../data/love_sigs.json
"""
import json
import re
import sys


def runtime_names(path: str) -> dict:
    out = {}
    for line in open(path, encoding="utf-8"):
        mod, _, rest = line.strip().partition("=")
        out[mod] = {x.split(":")[0] for x in rest.split(",") if x}
    return out


def sig(module: str, fn: dict) -> str:
    """name(required, [optional...]) per variant (the first one: the shortest form), then the return types. Types are dropped except for
    non-obvious ones (Drawable, DrawMode ...): the argument names are what the model needs."""
    variants = []
    for v in fn["v"][:1]:
        req, opt = [], []
        for a in v["a"]:
            name_type, _, default = a.partition("=")
            name, _, typ = name_type.partition(":")
            label = name if typ in ("number", "string", "boolean", "table", "") else f"{name}: {typ}"
            (opt if default else req).append(label)
        args = ", ".join(req) + ((", " if req else "") + "[" + ", ".join(opt) + "]" if opt else "")
        variants.append(args)
    base = f"love.{module}.{fn['n']}" if module else f"love.{fn['n']}"
    s = " | ".join(f"{base}({a})" for a in dict.fromkeys(variants)) or f"{base}()"
    rets = fn["v"][0]["r"] if fn["v"] else []
    return s + (" -> " + ", ".join(rets) if rets else "")


def main(index_path: str, dump_path: str, facts_py: str) -> dict:
    idx = json.load(open(index_path, encoding="utf-8"))
    rt = runtime_names(dump_path)
    want = sorted(set(re.findall(r"\{l:([\w.]+)\}", open(facts_py, encoding="utf-8").read())))
    table = {m["name"]: {f["n"]: f for f in m["functions"]} for m in idx["modules"]}
    out = {}
    for w in want:
        mod, _, name = w.partition(".")
        fn = table.get(mod, {}).get(name)
        if fn is None:
            raise SystemExit(f"{w}: not in the LOVE API index")
        if name not in rt.get(mod, set()):
            raise SystemExit(f"{w}: not exposed by the running engine")
        out[w] = sig(mod, fn)
    return out


if __name__ == "__main__":
    json.dump(main(*sys.argv[1:4]), sys.stdout, indent=0, ensure_ascii=False, sort_keys=True)
