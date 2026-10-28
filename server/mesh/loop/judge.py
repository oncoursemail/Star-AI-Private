"""Tiny judge on the fast tier: does ONE answer have a real mistake? One call per candidate, grammar "ok" | "bad",
max_tokens 1, and the probability of "bad" from the top logprobs, so two candidates compare by P(bad) without the
strong position bias a two-answer prompt had (measured: gemma said "answer 2" in 38 of 60 pairs; agreement with the
strict judges 25/43 decisive pairs, vs 30/43 for this per-answer form). Cost: ~0.4 s per answer on owner-pc gemma.
"""
from __future__ import annotations

import math

RUBRIC = (
    "You check ONE answer written for kids learning game making (Roblox Luau, Unity C#, Minecraft Java 1.21). "
    "Look for a real mistake: a LocalScript placed where it never runs (Workspace, ServerScriptService) or a server "
    "Script calling FireServer; an invented, wrong or deprecated API (wait(), :connect, BodyVelocity, "
    "Humanoid:LoadAnimation, Rigidbody.velocity in Unity 6, old Input.GetAxis without a note about the Input Manager, "
    "Minecraft functions/ folder); code that does not work as described (no debounce where Touched fires many times, "
    "the server trusting an amount or target sent by a client, DataStore calls without pcall, wrong maths, a missing "
    "step the asker needs); a false claim about settings, defaults or menus; or not answering the whole question. "
    "Ignore style and length. Reply 'bad' if there is any real mistake, else 'ok'.")
GRAMMAR = 'root ::= "ok" | "bad"'


def request(question: str, answer: str) -> dict:
    """Body fields for an OpenAI-style chat request to llama-server (model is added by the caller)."""
    return {"messages": [{"role": "system", "content": RUBRIC},
                         {"role": "user", "content": f"Question:\n{question.strip()}\n\nAnswer:\n{answer.strip()}\n\n"
                                                     "Verdict (ok or bad):"}],
            "max_tokens": 1, "temperature": 0.0, "grammar": GRAMMAR, "logprobs": True, "top_logprobs": 5,
            "stream": False, "cache_prompt": False, "chat_template_kwargs": {"enable_thinking": False}}


def p_bad(response: dict) -> float | None:
    """P("bad") from a llama-server chat response; the plain verdict when logprobs are missing; None if unreadable."""
    try:
        choice = response["choices"][0]
        text = (choice.get("message") or {}).get("content") or ""
    except (KeyError, IndexError, TypeError, AttributeError):
        return None
    probs = {}
    try:
        for e in choice["logprobs"]["content"][0]["top_logprobs"]:
            probs.setdefault(str(e["token"]).strip().lower(), math.exp(float(e["logprob"])))
    except (KeyError, IndexError, TypeError, ValueError):
        pass
    bad, ok = probs.get("bad", 0.0), probs.get("ok", 0.0)
    if bad + ok > 0:
        return bad / (bad + ok)
    text = text.strip().lower()
    return 1.0 if text.startswith("bad") else 0.0 if text.startswith("ok") else None
