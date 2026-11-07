"""Which `litha-agent` requests run the agent loop. Build/code tasks do; chat, explanations and general questions go
straight to plain `litha` (same speed as today).

    wants_agent(messages) -> bool
"""
from __future__ import annotations

import re

AGENT_MODEL = "litha-agent"

# asks for something to be made or repaired
MAKE = re.compile(r"\b(write|make|create|build|code|implement|generate|fix|debug|repair|refactor|port|convert|"
                  r"give me|i need|can you (?:do|add)|add)\b", re.I)
# ... and that something is code
THING = re.compile(r"\b(script|program|function|class|module|plugin|mod|data ?pack|datapack|mcfunction|command block|"
                   r"localscript|modulescript|remote ?event|monobehaviou?r|component|api|cli|parser|bot|game|system|"
                   r"code|method|query|algorithm|server|tool|app|gdscript|luau|lua|python|javascript|typescript|"
                   r"node\.?js|java|kotlin|c#|c\+\+|rust|golang|sql|bash|shell)\b|```", re.I)
# a thing to build named outright ("Fabric mod for 1.21.11: /back ...", "Python question. Every line of stdin ...")
ARTIFACT = re.compile(r"\b(plugin|mod|data ?pack|datapack|program|script|localscript|modulescript|server script|"
                      r"monobehaviou?r|stdin)\b|\bfunction `?\w+\(|\bclass `?\w+", re.I)
EXPLAIN = re.compile(r"^\s*(what|why|who|when|where|which|how does|how do(?:es)? .* work|how do i|how can i|how to|"
                     r"can i|should i|explain|tell me about|is it|is there|are there|compare|difference)\b", re.I)


def last_user(messages) -> str:
    for m in reversed(messages or []):
        if isinstance(m, dict) and m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, list):
                c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
            return c if isinstance(c, str) else ""
    return ""


def wants_agent(messages) -> bool:
    text = last_user(messages)
    if not text.strip():
        return False
    if "```" in text and MAKE.search(text):
        return True                       # code to fix / extend
    if EXPLAIN.search(text) and not re.search(r"\b(write|make|create|build|fix|code it)\b", text, re.I):
        return False
    return bool((MAKE.search(text) and THING.search(text)) or ARTIFACT.search(text))
