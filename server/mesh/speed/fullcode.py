"""Full answers for build/code requests (docs/agents/litha-speed2-20261029.md).

The launcher asks Litha for `max_tokens` 600 and its system prompt says "about 100 words plus code ... Only if you left
something out, end with 'Want the full version?'". Good for chat, but multi-part build requests (a shop GUI + server
script, a plugin + plugin.yml, a data pack with five files) came back cut or shortened. For a build/code request this
hook (1) adds a note to the last user turn (the system prompt stays the cached prefix) asking for the complete code and
(2) raises a small `max_tokens` to `full_code_max_tokens`. Chat and general questions are untouched. A build turn also
skips the general-question note (a follow-up such as "now make it close after 3 seconds" has no game word and was
labelled a general question). The note does not start with "(Note for Litha", the marker the polyglot and general hooks
read as "already has a note", so a Python build request still gets the polyglot note after this one.
"""
from __future__ import annotations

import re

DEFAULTS = {
    "full_code": True,              # switch
    "full_code_max_tokens": 1500,   # max_tokens for a build/code request when the client asked for less
}

NOTE = ("(Build note for Litha, not from the user: this is a build request. Give the complete, working code for everything "
        "asked: every script or file in full, ready to paste, each with where it goes. Do not shorten the code, do not "
        "leave parts out for later and do not end with \"Want the full version?\". Keep the words around the code "
        "short.)")

# asks for something to be made / changed (not "what is" / "why")
BUILD = re.compile(r"\b(make|making|create|build|write|code|implement|add|give me|show me how|set ?up|"
                   r"fix|change|turn|let|need)\b", re.I)
# ... that is code: an engine/language word, a code noun, or code in the message
CODEY = re.compile(r"```|\b(roblox|luau|lua|unity|c#|minecraft|paper|spigot|bukkit|velocity|fabric|neoforge|forge|"
                   r"data ?pack|mcfunction|plugin|mod|godot|gdscript|unreal|python|javascript|typescript|java|rust|"
                   r"html|script|localscript|modulescript|function|class|gui|command|system|tool|npc|leaderboard|"
                   r"leaderstats|datastore|remote ?event|game ?pass|obby|inventory|hotbar|shop|controller|recipe|"
                   r"advancement|item|api|app|game)\b", re.I)
# explanations / opinions stay short even when they name an engine
ASK_ONLY = re.compile(r"^\s*(what|what'?s|whats|why|who|when|which|is|are|does|do|should|can i|could|explain|tell me about)\b", re.I)
# refusals stay the model's own: never push "complete code" onto exploit / account / mean-message asks
RISKY = re.compile(r"\b(executor|cheat|hack|aimbot|inject|dupe|steal|grab|logger|password|account|robux|mean|"
                   r"roast|bully|insult)\b|(around|evade|evading|bypass\w*) (a |the |my )?ban|other (people|players)'?s? games?", re.I)
CODE_IN_HISTORY = re.compile(r"```|\blocal \w+ *=|\bfunction\b|\bpublic class\b|\bvoid \w+\(|game:GetService", re.I)


def is_build(msgs: list) -> bool:
    """The last user turn asks for code to be written or changed (or is a short follow-up in a coding chat)."""
    if not isinstance(msgs, list) or not msgs or not isinstance(msgs[-1], dict) or msgs[-1].get("role") != "user":
        return False
    q = msgs[-1].get("content")
    if not isinstance(q, str) or not q.strip() or "(Build note for Litha" in q:
        return False
    if RISKY.search(q):
        return False
    if "```" in q:
        return True
    if not BUILD.search(q) or (ASK_ONLY.search(q) and not re.search(r"\b(how (do|can) i (make|create|build|write|"
                                                                       r"add|code|script))\b", q, re.I)):
        return False
    if CODEY.search(q):
        return True
    # follow-up without a code word ("now make it close after 3 seconds"): the earlier answer had code
    prev = [m.get("content") for m in msgs[:-1] if isinstance(m, dict) and m.get("role") == "assistant"]
    return bool(prev) and isinstance(prev[-1], str) and bool(CODE_IN_HISTORY.search(prev[-1]))


def apply(req: dict, cfg: dict) -> dict:
    """Router hook (litha only, before the other notes). Returns the header for the log ({} = not a build request)."""
    if req.pop("mesh_full_code", None) is False or not cfg.get("full_code", True):
        return {}
    if any(req.get(k) for k in ("tools", "functions", "response_format", "grammar", "json_schema")):
        return {}
    msgs = req.get("messages")
    if not is_build(msgs):
        return {}
    msgs[-1] = {**msgs[-1], "content": msgs[-1]["content"] + "\n\n" + NOTE}
    req.setdefault("mesh_general", False)          # a build turn is never a general question
    cap = int(cfg.get("full_code_max_tokens") or 0)
    mt = req.get("max_tokens")
    if cap and isinstance(mt, int) and 0 < mt < cap:
        req["max_tokens"] = cap
    return {"X-Mesh-Full-Code": str(req.get("max_tokens") or "")}
