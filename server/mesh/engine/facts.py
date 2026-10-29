"""Version-specific engine facts for Litha (Unity 6, Godot 4, Unreal 5, LOVE 11, plain Lua 5.4), added to the last user
turn like the other notes (the system prompt stays the cached prefix). One note per question: it replaces the generic
polyglot note for these engines (the polyglot hook skips a turn that already carries "(Facts for Litha").

    family, note = facts_for(question)    # (None, "") when the question is not about one of these engines
    hdr = apply(req)                      # appends the note -> {"X-Mesh-Engine": "godot core+timer+signal"}

The data: facts_data.py (curated text + placeholders for signatures taken from the engine's own data, filled from
data/*.json at import). Docs: docs/agents/engine-truth-20261029.md.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .facts_data import FACTS

DEFAULTS = {"engine_facts": True}
DATA = Path(__file__).with_name("data")
MAX_CHARS = 3000           # the 4 GB nodes have a 4096-token context; the system prompt, the question and the answer share it
HEAD = ("(Facts for Litha, not from the user: {what}. Use exactly these names and signatures, never invent an API; "
        "write complete, working code for the whole task.)\n")

PLACEHOLDER = re.compile(r"\{(g|l|lua):([\w.]+)\}")


def _load(name: str) -> dict:
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


_SIGS = {"g": _load("godot_sigs.json"), "l": _load("love_sigs.json")}
_LUA = _load("lua54_std.json")


def lua_summary() -> str:
    order = ["_G", "string", "table", "math", "io", "os", "utf8", "coroutine"]
    parts = []
    for lib in order:
        names = _LUA.get(lib) or []
        if lib == "_G":
            names = [n for n in names if not n.startswith(("luaopen_", "_PROMPT")) and n not in
                     ("coroutine", "debug", "io", "math", "os", "package", "string", "table", "utf8", "_G")]
        if names:
            parts.append(f"{lib}: " + " ".join(names) if lib != "_G" else "globals: " + " ".join(names))
    return "; ".join(parts)


def expand(text: str) -> str:
    def sub(m):
        kind, key = m.group(1), m.group(2)
        if kind == "lua":
            return lua_summary()
        sig = _SIGS[kind].get(key)
        if sig is None:
            raise KeyError(f"engine facts: no signature for {m.group(0)}")
        return "`" + sig + "`"
    return PLACEHOLDER.sub(sub, text)


# ----------------------------------------------------------------------------------------------- which engine
NOT_LUA = re.compile(r"\broblox\b|\bluau\b|\bstudio\b|\bminecraft\b|\bcomputercraft\b|\bcc: ?tweaked\b|\bgarry|\bgmod\b|"
                     r"\bdefold\b|\bnginx\b|\bopenresty\b|\bneovim\b|\bnvim\b|\bwow\b|\bfivem\b|\bcorona\b|\bsolar2d\b|"
                     r"\bpico-?8\b|\btic-?80\b|\bwireshark\b|\bredis\b|\bawesome\b", re.I)
RULES = [
    ("unreal", re.compile(r"\bunreal\b|\bue ?[45](?:\.\d+)?\b|\bUCLASS\b|\bUPROPERTY\b|\bUFUNCTION\b|\bblueprints?\b.*\bc\+\+|"
                          r"\bc\+\+.*\bblueprints?\b|\bAActor\b|\bUActorComponent\b|\bgameplay ability system\b", re.I)),
    ("godot", re.compile(r"\bgodot\b|\bgdscript\b|\bcharacterbody[23]d\b|\bkinematicbody[23]d\b", re.I)),
    ("love", re.compile(r"(?i:\bl[öo]ve ?2d\b|\bl[öo]ve ?(?:0\.\d+|11(?:\.\d)?)\b|\blove\.(?:update|draw|load|graphics|"
                        r"keyboard|mouse|audio|physics|filesystem)\b)|\bL[ÖO]VE\b|\bLöve\b")),
    ("unity", re.compile(r"\bunity\b|\bmonobehaviou?r\b|\bscriptableobject\b|\bunityengine\b|\bgameobject\b", re.I)),
    ("lua", re.compile(r"\blua\b", re.I)),
]
OLD = {
    "unity": re.compile(r"\bunity ?(?:5|2017|2018|2019|2020|2021|2022)\b|\bunity (?:5\.x|2019 lts|2021 lts|2022 lts)\b", re.I),
    "godot": re.compile(r"\bgodot ?3(?:\.\d+)?\b|\bgdscript ?1\b|\bkinematicbody", re.I),
    "unreal": re.compile(r"\bue ?4\b|\bunreal (?:engine )?4\b", re.I),
    "love": re.compile(r"\bl(?:ö|o)ve ?(?:0\.\d+|2d 0\.\d+)\b", re.I),
}
OLD_NOTE = {
    "unity": "The user asks for an older Unity ({v}): use that version's API (Rigidbody.velocity and FindObjectOfType are "
             "valid there; Awaitable, linearVelocity and Cinemachine 3 names are Unity 6 only). Say so if the version is unclear.",
    "godot": "The user asks for Godot 3.x: use Godot 3 syntax (KinematicBody2D, move_and_slide(velocity, Vector2.UP), yield, "
             "onready var, export var, connect(\"sig\", obj, \"method\"), instance(), OS.get_ticks_msec); say that Godot 4 differs.",
    "unreal": "The user asks for Unreal 4: raw UObject pointers in UPROPERTY are normal there (TObjectPtr is UE5), legacy "
              "BindAxis/BindAction input is the default, Enhanced Input is an optional plugin.",
    "love": "The user asks for an old LÖVE (0.x): colours are 0-255 there, love.graphics.setColor(255, 0, 0), "
            "love.filesystem.exists exists, mouse buttons are strings (\"l\"); say that 11.x differs.",
}
LABEL = {"godot": "Godot 4.x GDScript", "unity": "Unity 6", "unreal": "Unreal Engine 5.x C++", "love": "LÖVE 11.x",
         "lua": "plain Lua 5.4"}
WHAT = {"godot": "checked against the Godot 4.7 engine's own API dump", "unity": "member names checked against Unity 6's "
        "scripting reference", "unreal": "UE5 C++ from Epic's public API docs", "love": "checked against LÖVE 11.5 and the "
        "running engine", "lua": "checked against the Lua 5.4 reference manual"}


def family_of(question: str) -> str | None:
    if not question:
        return None
    for fam, rx in RULES:
        if rx.search(question):
            if fam == "lua" and NOT_LUA.search(question):
                return None
            if fam == "unity" and re.search(r"\bminecraft\b|\broblox\b", question, re.I):
                return None
            return fam
    return None


_COMPILED: dict = {}


def _topics(fam: str) -> list[tuple[re.Pattern, str]]:
    if fam not in _COMPILED:
        _COMPILED[fam] = [(re.compile(rx, re.I), text) for rx, text in FACTS[fam]["topics"]]
    return _COMPILED[fam]


def facts_for(question: str) -> tuple[str | None, str, list[str]]:
    """(family, note, topic ids); the family is None (and the note empty) when the question is not about an engine here."""
    fam = family_of(question)
    if fam is None:
        return None, "", []
    q = question
    old = OLD.get(fam) and OLD[fam].search(q)
    if old:
        return fam, (HEAD.format(what=f"{LABEL[fam]}-version question") + OLD_NOTE[fam].format(v=old.group(0))), ["old"]
    core = expand(FACTS[fam]["core"])
    scored = []
    for i, (rx, text) in enumerate(_topics(fam)):
        n = len(rx.findall(q))
        if n:
            scored.append((-n, i, text))
    scored.sort()
    body, used = [core], ["core"]
    size = len(core)
    for _, i, text in scored:
        t = expand(text)
        if size + len(t) + 1 > MAX_CHARS:
            continue
        body.append(t)
        used.append(f"t{i}")
        size += len(t) + 1
    return fam, HEAD.format(what=WHAT[fam]) + "\n".join(body), used


def core_text(question: str) -> str:
    """The engine's core facts alone (no header, no topics): reference text for the verifier's fix prompt."""
    fam = family_of(question or "")
    if fam is None or (OLD.get(fam) and OLD[fam].search(question)):
        return ""
    return expand(FACTS[fam]["core"])


def apply(req: dict, cfg: dict | None = None) -> dict:
    """Append the note to the last user turn; returns the header for the log. `"mesh_engine": false` in the request
    (internal calls such as the verifier's fix prompt) or `engine_facts: false` in the config skips it."""
    if req.pop("mesh_engine", None) is False or (cfg is not None and not cfg.get("engine_facts", True)):
        return {}
    msgs = req.get("messages")
    if not isinstance(msgs, list) or not msgs or not isinstance(msgs[-1], dict) or msgs[-1].get("role") != "user":
        return {}
    text = msgs[-1].get("content")
    if not isinstance(text, str) or "(Note for Litha" in text or "(Facts for Litha" in text:
        return {}
    fam, note, used = facts_for(text)
    if not fam:
        return {}
    msgs[-1] = {**msgs[-1], "content": text + "\n\n" + note}
    return {"X-Mesh-Engine": f"{fam} {'+'.join(used)} {len(note)}"}
