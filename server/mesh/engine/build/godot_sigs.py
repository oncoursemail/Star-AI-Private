"""Exact Godot 4 member signatures for the facts note, from the engine's own `godot --dump-extension-api`
(extension_api.json of Godot 4.7.2, MIT-licensed engine data). Writes data/godot_sigs.json: {"Class.member": "signature"}.

    python godot_sigs.py extension_api.json ../facts_data.py > ../data/godot_sigs.json
"""
import json
import re
import sys

def wanted(facts_py: str) -> list:
    """Every {g:Class.member} placeholder of the facts text."""
    text = open(facts_py, encoding="utf-8").read()
    return sorted(set(re.findall(r"\{g:([\w.]+)\}", text)))


def fmt_type(t: str) -> str:
    if t.startswith("typedarray::"):
        return "Array[" + t.split("::", 1)[1] + "]"
    return t.replace("enum::", "").replace("bitfield::", "")


def args(m) -> str:
    out = []
    for a in m.get("arguments") or []:
        s = f"{a['name']}: {fmt_type(a['type'])}"
        if "default_value" in a:
            s += f" = {a['default_value']}"
        out.append(s)
    if m.get("is_vararg"):
        out.append("...")
    return ", ".join(out)


def main(path: str, facts_py: str) -> dict:
    api = json.load(open(path, encoding="utf-8"))
    classes = {c["name"]: c for c in api["classes"]}
    builtin = {c["name"]: c for c in api["builtin_classes"]}
    out = {}
    for want in wanted(facts_py):
        cls, _, member = want.partition(".")
        c = classes.get(cls) or builtin.get(cls)
        if c is None:
            continue
        chain, k = [], c
        while k:
            chain.append(k)
            k = classes.get(k.get("inherits")) if k.get("inherits") else None
        found = None
        for k in chain:
            for m in k.get("methods") or []:
                if m["name"] == member:
                    rv = (m.get("return_value") or {}).get("type") or m.get("return_type")
                    found = (("static " if m.get("is_static") else "") + f"{cls}.{member}({args(m)})"
                             + (f" -> {fmt_type(rv)}" if rv else ""))
                    break
            if found:
                break
            for p in k.get("properties") or []:
                if p["name"] == member:
                    found = f"{cls}.{member}: {fmt_type(p['type'])}"
                    break
            if found:
                break
            for s in k.get("signals") or []:
                if s["name"] == member:
                    found = f"signal {cls}.{member}({args(s)})"
                    break
            if found:
                break
            for s in k.get("members") or []:
                if s["name"] == member:
                    found = f"{cls}.{member}: {fmt_type(s['type'])}"
                    break
            if found:
                break
        if found:
            out[want] = found
    return out


if __name__ == "__main__":
    res = main(sys.argv[1], sys.argv[2])
    json.dump(res, sys.stdout, indent=0, ensure_ascii=False, sort_keys=True)
