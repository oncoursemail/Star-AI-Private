"""Unity C# light checks (no compiler on the server): balanced brackets/strings, Unity message names with the wrong
case (Unity silently never calls `void update()`), physics callbacks with the wrong parameter type, and
MonoBehaviour without `using UnityEngine;`.
"""
from __future__ import annotations

import re

MESSAGES = ["Awake", "Start", "Update", "FixedUpdate", "LateUpdate", "OnEnable", "OnDisable", "OnDestroy",
            "OnTriggerEnter", "OnTriggerExit", "OnTriggerStay", "OnCollisionEnter", "OnCollisionExit",
            "OnCollisionStay", "OnTriggerEnter2D", "OnTriggerExit2D", "OnTriggerStay2D", "OnCollisionEnter2D",
            "OnCollisionExit2D", "OnCollisionStay2D", "OnMouseDown", "OnGUI", "OnValidate", "Reset"]
PARAM = {"OnTriggerEnter": "Collider", "OnTriggerExit": "Collider", "OnTriggerStay": "Collider",
         "OnCollisionEnter": "Collision", "OnCollisionExit": "Collision", "OnCollisionStay": "Collision",
         "OnTriggerEnter2D": "Collider2D", "OnTriggerExit2D": "Collider2D", "OnTriggerStay2D": "Collider2D",
         "OnCollisionEnter2D": "Collision2D", "OnCollisionExit2D": "Collision2D", "OnCollisionStay2D": "Collision2D"}


def _strip(code: str) -> str:
    """Blank out comments and string/char literals (keeps line numbers)."""
    pat = re.compile(r'//[^\n]*|/\*.*?\*/|@"(?:""|[^"])*"|\$?"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])\'', re.S)
    return pat.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), code)


def _p(kind, message, suggestion=None, name=None, line=None, severity="error"):
    return {"kind": kind, "severity": severity, "name": name, "message": message, "suggestion": suggestion,
            "line": line}


def check_csharp(code: str) -> list[dict]:
    problems = []
    clean = _strip(code)
    if re.search(r'"(?:\\.|[^"\\\n])*$', clean, re.M):
        problems.append(_p("syntax", "unterminated string"))
    stack = []
    pairs = {")": "(", "]": "[", "}": "{"}
    for n, line in enumerate(clean.splitlines(), 1):
        for ch in line:
            if ch in "([{":
                stack.append((ch, n))
            elif ch in ")]}":
                if not stack or stack[-1][0] != pairs[ch]:
                    problems.append(_p("syntax", f"unexpected '{ch}'", None, ch, n))
                    return problems
                stack.pop()
    if stack:
        ch, n = stack[-1]
        problems.append(_p("syntax", f"'{ch}' opened here is never closed", None, ch, n))
    lower = {m.lower(): m for m in MESSAGES}
    for m in re.finditer(r"\bvoid\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", clean):
        name, params = m.group(1), m.group(2).strip()
        line = clean.count("\n", 0, m.start()) + 1
        if name not in MESSAGES and name.lower() in lower:
            problems.append(_p("unity_message", f"Unity never calls '{name}': message names are case-sensitive",
                               lower[name.lower()], name, line))
        want = PARAM.get(name)
        if want and params:
            ptype = params.split()[0]
            if ptype != want and ptype in PARAM.values():
                problems.append(_p("unity_message", f"{name} takes a {want}, not a {ptype}", f"{name}({want} other)",
                                   name, line))
    if re.search(r":\s*MonoBehaviour\b", clean) and not re.search(r"\busing\s+UnityEngine\s*;", clean) \
            and "UnityEngine.MonoBehaviour" not in clean:
        problems.append(_p("syntax", "MonoBehaviour needs 'using UnityEngine;' at the top", "using UnityEngine;",
                           "MonoBehaviour"))
    return problems
