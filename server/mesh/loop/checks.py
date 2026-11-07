"""Cheap signals for picking the better of two answers: the verifier report plus a few regex checks for the mistakes the
strict judges failed most often (docs/agents/litha-distill-20261028.md). No model call; well under a millisecond.

    s = signals(text, report, finish)       # report = /mesh/verify reply (or None when the verifier is down)
    pick(a, b) -> ("A" | "B" | None, why)   # None = tied on every cheap signal
"""
from __future__ import annotations

import re

FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})", re.M)
CODE_BLOCK = re.compile(r"^[ \t]{0,3}(`{3,})[^\n]*\n(.*?)^[ \t]{0,3}\1[ \t]*$", re.M | re.S)

# (name, pattern over the whole answer, pattern that clears the flag when it also matches)
LINT = [
    # a LocalScript placed where it never runs
    ("localscript-never-runs",
     re.compile(r"LocalScript[^.\n]{0,80}\b(in|inside|into|under)\b[^.\n]{0,30}\b(Workspace|ServerScriptService|"
                r"the (door|part|brick|block|button part|ProximityPrompt|coin|pad|NPC))\b", re.I), None),
    # the server adds a client-sent amount to a stat
    ("server-trusts-client-amount",
     re.compile(r"OnServerEvent:Connect\(function\(\s*\w+\s*,\s*(\w*(amount|coins|gold|price|damage|value|power|"
                r"cash|money|points|xp)\w*)\b[^)]*\)(?:(?!\bend\)).){0,600}?\.Value\s*(?:\+|=\s*[^\n]*\+)\s*\1\b",
                re.I | re.S), None),
    # Touched without any debounce or cooldown
    ("touched-no-debounce", re.compile(r"\.Touched:Connect", re.I),
     re.compile(r"debounce|cooldown|touched\s*\[|\bdb\b|last\w*\s*\[|os\.clock|tick\(\)|canTouch|isTouch|"
                r"busy|open(ed)?\s*=\s*true|used\s*\[|\[player\]|\[plr\]|:Disconnect\(|:Destroy\(\)", re.I)),
    # DataStores do not need "Allow HTTP Requests"
    ("datastore-http-myth", re.compile(r"Allow HTTP Requests", re.I), None),
    ("save-on-character-removing", re.compile(r"CharacterRemoving[\s\S]{0,400}?(SetAsync|UpdateAsync)", re.I), None),
    # Unity 6: old Input Manager without saying so; velocity renamed to linearVelocity
    ("unity-old-input-unsaid", re.compile(r"\bInput\.Get(Axis|Key|Button|Mouse)", re.I),
     re.compile(r"Input Manager|Input System|Active Input Handling|Both", re.I)),
    ("unity-velocity-obsolete", re.compile(r"\b(rb|rigidbody|rb2d|body|_rb|rigidBody)\w*\.velocity\b", re.I), None),
    # Minecraft 1.21 data packs
    ("mc-functions-folder", re.compile(r"data/[\w./-]*\bfunctions/", re.I), None),
]


def prose_words(text: str) -> int:
    return len(CODE_BLOCK.sub(" ", text).split())


# a server Script cannot call FireServer: both sides inside ONE code block = client and server code mixed up
SAME_BLOCK = [("fireserver-on-server", re.compile(r"OnServerEvent[\s\S]*:FireServer\(|:FireServer\([\s\S]*"
                                                  r"OnServerEvent"))]


def lint(text: str) -> list[str]:
    out = []
    for name, pat, clear in LINT:
        if pat.search(text) and not (clear and clear.search(text)):
            out.append(name)
    for name, pat in SAME_BLOCK:
        if any(pat.search(m.group(2)) for m in CODE_BLOCK.finditer(text)):
            out.append(name)
    return out


def signals(text: str, report: dict | None = None, finish: str | None = "stop") -> dict:
    """Everything `pick` compares. `report` is the verifier's reply for this answer (None = not checked)."""
    probs = []
    if report:
        probs = [p for b in report.get("blocks") or [] for p in b.get("problems") or []] + list(report.get("problems")
                                                                                                or [])
    errors = sum(p.get("severity") == "error" for p in probs)
    warnings = sum(p.get("severity") == "warning" for p in probs)
    cut = finish not in (None, "stop") or len(FENCE.findall(text)) % 2 == 1
    words = prose_words(text)
    return {"errors": errors, "warnings": warnings, "lint": lint(text), "cut": cut, "words": words,
            "code_blocks": len(CODE_BLOCK.findall(text)), "checked": report is not None,
            "too_long": words > 300, "empty": not text.strip()}


def badness(s: dict) -> tuple:
    """Lower is better, compared in order: broken output, verifier errors, warnings, lint hits, length."""
    return (int(s["empty"]) + int(s["cut"]), s["errors"], s["warnings"], len(s["lint"]), int(s["too_long"]))


def pick(a: dict, b: dict) -> tuple[str | None, str]:
    """Compare two signal dicts; the first differing level decides. None when all levels tie."""
    labels = ("cut/empty", "verifier errors", "verifier warnings", "lint", "length")
    ba, bb = badness(a), badness(b)
    for i, (x, y) in enumerate(zip(ba, bb)):
        if x != y:
            return ("A" if x < y else "B"), f"{labels[i]} {x} vs {y}"
    return None, "tied on cheap signals"


def clean(s: dict) -> bool:
    return badness(s) == (0, 0, 0, 0, 0)
