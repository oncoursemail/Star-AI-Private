"""The Lua 5.4 standard library's names from the official reference manual (https://www.lua.org/manual/5.4/manual.html,
the pdf-* anchors; the sha256 of the page is recorded in docs/agents/engine-truth-20261029.md).
Writes data/lua54_std.json: {"string": [...], "math": [...], ..., "_G": [...], "file": [...]}.

    python lua54_std.py manual.html > ../data/lua54_std.json
"""
import json
import re
import sys

text = open(sys.argv[1], encoding="latin-1").read()
libs = {}
for n in sorted(set(re.findall(r"pdf-([\w.:]+)", text))):
    if n.startswith(("lua_", "luaL_", "LUA", "lua.h", "lualib")) or n in ("lua.h", "lualib.h", "lauxlib.h"):
        continue
    if n.startswith("file:"):
        libs.setdefault("file", []).append(n[5:])
    elif "." in n:
        lib, f = n.split(".", 1)
        libs.setdefault(lib, []).append(f)
    else:
        libs.setdefault("_G", []).append(n)
libs.pop("lua", None)
libs.pop("lualib", None)
libs["_G"] = [n for n in libs.get("_G", []) if not n.startswith(("luaopen_", "_PROMPT"))]
json.dump(libs, sys.stdout, indent=0, sort_keys=True)
