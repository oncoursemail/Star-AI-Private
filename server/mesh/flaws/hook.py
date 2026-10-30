"""Router side of the flaw loop (litha only, stdlib, no model call, < 1 ms).

1. Signals for the decision log (`log["flaw"]`, no user text): is this turn a follow-up in a coding chat, a re-ask
   ("it doesn't work", "that's wrong", the same question again), a game-build ask without an engine word, a coding
   question that only trips a soft safety word ("weapon", "secret door")? mine.py clusters them with the outcome,
   cut answers (finish_reason "length") and errors.
2. Cheap fixes, each a separately shippable id. The gate (gate.py) ships one by writing it into
   `<flaws_dir>/shipped.json` only after it won its A/B through this router; the hook re-reads that file when it
   changes (no restart) and logs a fix that is eligible but not shipped as "would" (the rollback watch's baseline).
   Per request `X-Mesh-Fixes: none | all | id,id` (or body `mesh_fixes`) overrides the shipped set (the gate's A/B).
3. Flagged turns are kept, truncated, in `<flaws_dir>/samples.jsonl` (STAR's own store on this container, bounded,
   e-mail/phone/key-shaped text redacted) so a cluster can become regression items (items.py).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import time

from ..general import classify

DEFAULTS = {
    "flaws": True,                           # signals in the log + shipped fixes (litha requests only)
    "flaws_dir": "/var/lib/star-mesh/flaws",  # shipped.json (read), samples.jsonl (append)
    "flaws_samples": True,
    "flaws_samples_max_bytes": 2_000_000,
}

# --- what earlier turns say about the chat ----------------------------------------------------------------------
CODE_TEXT = re.compile(r"```|\blocal \w+ *=|\bfunction\s*[\w.:]*\(|game:GetService|\bdef \w+\(|\bpublic (?:class|void|static)\b|"
                       r"\bimport [\w.]+;|\bvoid \w+\(|/(?:give|tp|execute|summon|scoreboard|gamerule)\b|:Connect\(", re.I)
ENGINE = classify.CODE
# --- the last turn ---------------------------------------------------------------------------------------------
REFERS = re.compile(r"^\s*(?:now|also|and|but|then|ok(?:ay)?|so|wait|next|what about|how about|instead|can (?:you|u|it)|"
                    r"could (?:you|u)|make (?:it|them|that|this)|add|change|same)\b|"
                    r"\b(?:it|its|it'?s|that|this|these|those|them|they|the (?:script|code|door|part|gui|button|npc|tool|"
                    r"game|thing|one|same|first|second|last|other|error|line|output))\b|"
                    r"\b(?:again|instead|too|as well|faster|slower|bigger|smaller|longer|shorter)\b", re.I)
REASK = re.compile(r"\b(?:doesn'?t|does not|didn'?t|did not|won'?t|wont|isn'?t|is not|not|aint|ain'?t|cant|can'?t)\s+"
                   r"(?:work|working|run|running|do anything|open|close|show|showing|appear|move|spawn|save|load|fire|"
                   r"happen|load|change|go|play|fix)\b|\bnothing (?:happens|happened|works)\b|"
                   r"\b(?:that'?s|thats|it'?s|its|you'?re|ur|this is|that is|it is)\s+(?:wrong|not right|incorrect|broken|"
                   r"not working|not what)\b|\bwrong\b|\bbroken\b|\bstill (?:not|doesn|broken|the same|same|error|nothing)|"
                   r"\bnot what i\b|\bi (?:said|asked|meant)\b|^\s*(?:no+|nope|nah)\b|attempt to (?:index|call|perform|compare)|"
                   r"is not a valid member|infinite yield|\berror\b|\bred (?:text|line)\b|\bbugged\b|\bit broke\b", re.I)
BUILD = re.compile(r"\b(?:make|making|create|build|code|script|add|give me|set ?up|do|get|have|put|spawn|turn|let|need|"
                   r"want|program|design)\b|\bhow (?:2|to|do|can|would) (?:i|u|you|we)\b|^\s*how (?:2|to)\b", re.I)
GAME = re.compile(r"\b(?:doors?|parts?|bricks?|coins?|badges?|game ?pass(?:es)?|gui|guis|ui|buttons?|leaderboards?|leaderstats?|"
                  r"spawns?|respawn\w*|checkpoints?|kill ?bricks?|lava|obby|obbies|tycoon|simulator|swords?|guns?|tools?|npcs?|"
                  r"pets?|walk ?speed|jump ?power|double jump|teleport\w*|tween\w*|cframe|humanoid|hitbox\w*|frames?|"
                  r"text ?labels?|text ?buttons?|screen ?gui|billboard\w*|proximity ?prompts?|click ?detectors?|cash|gems|"
                  r"currency|shops?|inventory|hotbar|rounds?|lobby|minigames?|cutscenes?|camera|trails?|particles?|glow\w*|"
                  r"neon|press(?:ing|es)? (?:e|f|q|r|space|shift)\b|keybinds?|redstone|creepers?|zombies?|mobs?|villagers?|"
                  r"enchant\w*|crafting|datapacks?|data ?packs?|mcfunction|scoreboards?|boss ?bars?|tellraw|gamemode|"
                  r"gamerule|summon|spawners?|nether|minecart|chests?|blocks?|items?|plugins?|mods?|prefabs?|rigidbody|"
                  r"colliders?|sprites?|players?|characters?|enemies|enemy|health ?bars?|damage|xp|timer|countdown|morphs?|"
                  r"admin|kick|game|games|map|level ?up|dash|sprint|stamina|hit ?box|ragdoll|sound effects?|music player|"
                  r"day ?night|leaderboard|teams?|walls?|stats|data|boards?|diamonds?|potions?|effects?|jump boost)\b",
                  re.I)
# game/engine terms that general questions never use: code even without a "make" verb
STRONG_GAME = re.compile(r"\b(?:datastores?|ordered ?data ?stores?|bindtoclose|fire ?server|fire ?client|remote ?events?|"
                         r"remote ?functions?|roblox studio|in studio|api services|game ?pass(?:es)?|leaderstats|"
                         r"proximity ?prompts?|mcfunction|command ?blocks?|scoreboards?|gamerules?|tp|summon\w*|obby|"
                         r"tycoon|npcs?|hitbox(?:es)?|humanoid|cframe|walk ?speed|jump ?power|kill ?bricks?|spawn ?points?|"
                         r"tween ?service|replicated ?storage|server ?storage|starter ?gui|player ?gui|workspace|mc|"
                         r"remotes?|bindable ?events?|boss ?bars?|(?:fill|clone|execute|give|effect) command)\b|"
                         r"(?:^|\s)/[a-z]+\b", re.I)
NOT_GAME = re.compile(r"\b(?:essay|story|stories|poem|letter|paragraph|homework|cake|cookies?|bake|baking|airplane|friends?|"
                      r"draw|drawing|paint|volcano|science project|board game|card game|real life|in real|at school|"
                      r"my (?:mom|dad|teacher|sister|brother))\b", re.I)
NEW_QUESTION = re.compile(r"^\s*(?:what|what'?s|whats|who|whos|when|where|which|why|how|is|are|was|were|do|does|did|"
                          r"can|could|should|would|will|tell me|explain)\b", re.I)
ASK_ONLY = re.compile(r"^\s*(?:what|what'?s|whats|who|when|which|is|are|does|should|explain|tell me about|why)\b", re.I)
SOFT_SAFETY = re.compile(r"weapon|secret|challenge|address|poison|account|log ?in|password", re.I)
# a real-life situation, not code: another person asking, "my password", "should I"
HARD_VETO = re.compile(r"\b(?:steal\w*|hack\w*|phish\w*|grab\w*|logger|someone'?s|other (?:people|players)'?s?|real "
                       r"(?:password|address)|scam\w*|exploit\w*|cookie|robux|should i|my (?:real |own )?(?:password|"
                       r"address|account|login|pics?|photos?|info)|where i live|pics?|photos?|meet\w*|met|tell (?:him|her|"
                       r"them|someone|anyone|people)|a guy|this (?:kid|guy|girl|person)|someone|somebody|stranger|"
                       r"(?:he|she|they) (?:says?|said|wants?|asked)|asks? me|asked me|keeps asking)\b", re.I)

REASK_NOTE = ("(Fix note for Litha, not from the user: the user says the earlier answer did not work. Name the most "
              "likely cause in one short sentence, then give the corrected code in full, ready to paste, and say where "
              "it goes.)")

FIXES = {
    # id: what it does (the rule that makes it eligible is in eligible())
    "game-build": "a build ask with a game word but no engine word ('make door open press e') is code, not general",
    "code-followup": "a follow-up in a coding chat ('now make it close after 3 seconds') is code, not general",
    "soft-safety": "a coding question that only trips a soft safety word ('weapon', 'secret door') is code",
    "reask-note": "'it doesn't work' in a coding chat gets a find-the-bug-and-give-the-fixed-code note",
    "safety-substring": "a safety word only inside another word ('photosynthesis', 'caterpillar') is not a safety question",
}
SUFFIX = re.compile(r"(?:s|es|d|ed|ing|ous|r|er|ers|ful)?(?![a-z])", re.I)


def _inside_word(text: str, m: re.Match) -> bool:
    return (m.start() > 0 and text[m.start() - 1].isalpha()) or not SUFFIX.match(text, m.end())


def _text(c) -> str:
    if isinstance(c, str):
        return c
    if isinstance(c, list):        # OpenAI content parts
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict) and isinstance(p.get("text"), str))
    return ""


def _question(content: str) -> str:
    """The user's own words: grounding puts reference answers in front of a '---\\nQuestion: ' line."""
    _, sep, q = content.rpartition("\n---\nQuestion: ")
    return q if sep else content


def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", s.lower()))


def signals(messages: list) -> dict:
    """Flags for the last user turn of a chat (pure; the unit tests and the gate call it too)."""
    turns = [m for m in messages if isinstance(m, dict) and m.get("role") in ("user", "assistant")]
    if not turns or turns[-1].get("role") != "user":
        return {}
    last = _question(_text(turns[-1].get("content"))).strip()
    if not last:
        return {}
    earlier = turns[:-1][-6:]
    users = [_text(m.get("content")) for m in earlier if m.get("role") == "user"]
    asst = [_text(m.get("content")) for m in earlier if m.get("role") == "assistant"]
    kind = classify.kind(last)
    flags = set()
    if asst:
        flags.add("multi")
        if CODE_TEXT.search(asst[-1]) or any(ENGINE.search(_question(u)) or CODE_TEXT.search(u) for u in users[-3:]):
            flags.add("codectx")
        n = len(last.split())
        if n <= 30 and (REFERS.search(last) or (n <= 6 and not NEW_QUESTION.search(last))):
            flags.add("followup")
        if REASK.search(last):
            flags.add("reask")
        if users:
            a, b = _words(last), _words(_question(users[-1]))
            if len(a) >= 3 and len(a & b) / max(1, len(a | b)) >= 0.7:
                flags.add("repeat")
    if kind in ("factual", "writing") and not ENGINE.search(last) and not NOT_GAME.search(last) and (
            STRONG_GAME.search(last) or (BUILD.search(last) and GAME.search(last) and
                                         not (ASK_ONLY.search(last) and not re.search(r"\bhow\b", last, re.I)))):
        flags.add("game_build")
    if kind == "safety" and all(_inside_word(last, m) for m in classify.SAFETY.finditer(last)):
        flags.add("safety_substr")
    if kind == "safety" and not HARD_VETO.search(last):
        hits = [m.group(0) for m in classify.SAFETY.finditer(last)]
        if hits and all(SOFT_SAFETY.fullmatch(h) for h in hits) and \
                (ENGINE.search(last) or GAME.search(last) or "codectx" in flags):
            flags.add("soft_safety")
    return {"kind": kind, "flags": sorted(flags), "last": last}


def eligible(sig: dict) -> list[str]:
    """Fix ids whose rule matches this turn."""
    if not sig:
        return []
    f, kind = set(sig["flags"]), sig["kind"]
    out = []
    if "game_build" in f:
        out.append("game-build")
    if "codectx" in f and "followup" in f and kind in ("factual", "writing", "chat", "math") and \
            (kind != "math" or REFERS.search(sig["last"])):
        out.append("code-followup")
    if "soft_safety" in f:
        out.append("soft-safety")
    if "codectx" in f and "reask" in f and kind != "safety":
        out.append("reask-note")
    if "safety_substr" in f and not out:
        out.append("safety-substring")
    return out


class Shipped:
    """`<flaws_dir>/shipped.json` {"fixes": {id: {...}}}, re-read when its mtime changes (checked every 5 s)."""

    def __init__(self):
        self.path, self.mtime, self.ids, self.checked = "", None, frozenset(), 0.0

    def get(self, folder: str) -> frozenset:
        now = time.monotonic()
        path = os.path.join(folder, "shipped.json")
        if path == self.path and now - self.checked < 5.0:
            return self.ids
        self.path, self.checked = path, now
        try:
            mt = os.stat(path).st_mtime
        except OSError:
            self.mtime, self.ids = None, frozenset()
            return self.ids
        if mt != self.mtime:
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
                self.ids = frozenset(k for k in (data.get("fixes") or {}) if k in FIXES)
            except (OSError, ValueError, AttributeError):
                self.ids = frozenset()
            self.mtime = mt
        return self.ids


SHIPPED = Shipped()
REDACT = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d ()-]{8,}\d|\b(?:sk|ghp|gho|xox[bp])[-_][A-Za-z0-9_-]{10,}|"
                    r"\b[A-Za-z0-9_-]{32,}\b")


def _override(req: dict, headers: dict) -> frozenset | None:
    raw = req.pop("mesh_fixes", None)
    if raw is None:
        raw = headers.get("x-mesh-fixes")
    if raw is None:
        return None
    if isinstance(raw, list):
        raw = ",".join(map(str, raw))
    raw = str(raw).strip().lower()
    if raw in ("none", "off", "0", "no", ""):
        return frozenset()
    if raw == "all":
        return frozenset(FIXES)
    return frozenset(x.strip() for x in raw.split(",") if x.strip() in FIXES)


def apply(req: dict, headers: dict, cfg: dict) -> dict:
    """Router hook (litha, before the other notes). Applies the fixes in force; returns the log entry ({} = off)."""
    override = _override(req, headers)
    if not cfg.get("flaws", True) or any(req.get(k) for k in ("tools", "functions", "response_format", "grammar",
                                                                  "json_schema")):
        return {}
    msgs = req.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return {}
    sig = signals(msgs)
    if not sig:
        return {}
    can = eligible(sig)
    active = override if override is not None else SHIPPED.get(cfg.get("flaws_dir") or DEFAULTS["flaws_dir"])
    fire = [x for x in can if x in active]
    for fx in fire:
        if fx == "safety-substring":
            req["mesh_general_kind"] = "factual"             # general.run: the general note without the safety card
            continue
        req["mesh_general"] = False                         # the other fixes say "this turn is code"
        if fx == "reask-note" and isinstance(msgs[-1].get("content"), str) and "(Fix note for Litha" not in msgs[-1]["content"]:
            msgs[-1] = {**msgs[-1], "content": msgs[-1]["content"] + "\n\n" + REASK_NOTE}
    entry = {"id": secrets.token_hex(4), "kind": sig["kind"], "sig": sig["flags"]}
    if fire:
        entry["fire"] = fire
    if [x for x in can if x not in fire]:
        entry["would"] = [x for x in can if x not in fire]
    if override is not None:
        entry["override"] = sorted(override) or ["none"]
    flagged = bool(can) or bool({"reask", "repeat"} & set(sig["flags"]))
    if flagged and cfg.get("flaws_samples", True) and override is None:
        _sample(cfg, entry, msgs, req)
    return entry


def _sample(cfg: dict, entry: dict, msgs: list, req: dict) -> None:
    folder = cfg.get("flaws_dir") or DEFAULTS["flaws_dir"]
    turns = [m for m in msgs if isinstance(m, dict) and m.get("role") in ("user", "assistant")][-5:]
    rec = {"id": entry["id"], "ts": round(time.time(), 1), "kind": entry["kind"], "sig": entry["sig"],
           "can": entry.get("fire", []) + entry.get("would", []),
           "msgs": [{"role": m["role"], "content": REDACT.sub("[x]", _question(_text(m.get("content")))
                                                              .split("\n\n(Fix note for Litha")[0])[:1500]}
                    for m in turns]}
    path = os.path.join(folder, "samples.jsonl")
    try:
        os.makedirs(folder, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if os.path.getsize(path) > int(cfg.get("flaws_samples_max_bytes") or DEFAULTS["flaws_samples_max_bytes"]):
            with open(path, encoding="utf-8") as fh:
                lines = fh.readlines()
            with open(path + ".tmp", "w", encoding="utf-8") as fh:
                fh.writelines(lines[len(lines) // 2:])
            os.replace(path + ".tmp", path)
    except OSError:
        pass
