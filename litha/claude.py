"""Litha's second opinion: Claude, asked only when her local model fails. Paid per token, so every call is priced from
its usage and written to a ledger; she stops asking at the cap (total and per day).
Keys: ~/.star/anthropic.key, then anthropic2.key, ... (one line each, the owner's): the next key is used when one is
out of credit or refused. Caps: ~/.star/litha-claude/cap.json {"total": 300, "day": 30}."""
from __future__ import annotations

import datetime
import json
import os
import time
from pathlib import Path

MODEL = os.environ.get("LITHA_CLAUDE_MODEL", "claude-opus-5-5")
PRICE = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}  # $/1M in, out
KEY = Path.home() / ".star" / "anthropic.key"
HOME = Path.home() / ".star" / "litha-claude"
LEDGER = HOME / "spend.jsonl"
CAPS = {"total": 300.0, "day": 30.0}                 # two keys from the owner; cap.json changes it


def caps() -> dict:
    try:
        return {**CAPS, **json.loads((HOME / "cap.json").read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(CAPS)


def spent() -> tuple[float, float]:
    """(all time, today) in dollars."""
    total = day = 0.0
    today = datetime.date.today().isoformat()
    try:
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            total += row["usd"]
            day += row["usd"] if row["day"] == today else 0.0
    except (OSError, ValueError, KeyError):
        pass
    return total, day


def keys() -> list[Path]:
    return [k for k in [KEY, *sorted(KEY.parent.glob("anthropic[0-9]*.key"))] if k.exists()]


def ready() -> bool:
    if not keys() or os.environ.get("LITHA_CLAUDE") == "off" or "PYTEST_CURRENT_TEST" in os.environ:
        return False
    total, day = spent()
    c = caps()
    return total < c["total"] and day < c["day"]


def cost(usage, model: str = MODEL) -> float:
    i, o = PRICE.get(model, PRICE["claude-opus-5-5"])
    tokens_in = (usage.input_tokens + 1.25 * (getattr(usage, "cache_creation_input_tokens", 0) or 0)
                 + 0.05 * (getattr(usage, "cache_read_input_tokens", 0) or 0))
    return (tokens_in * i + usage.output_tokens * o) / 1e6


def ask(prompt: str, effort: str = "medium", what: str = "") -> str:
    """Her prompt to Claude; the answer text ("" when out of budget or the call failed)."""
    if not ready():
        return ""
    import anthropic
    t = time.time()
    for key in keys():
        client = anthropic.Anthropic(api_key=key.read_text(encoding="utf-8").strip(), max_retries=2, timeout=300)
        try:
            r = client.messages.create(model=MODEL, max_tokens=16000, output_config={"effort": effort},
                                       messages=[{"role": "user", "content": prompt}])
            break
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            print(f"claude: {key.name} refused ({type(e).__name__}), trying the next key", flush=True)
        except anthropic.BadRequestError as e:
            if "credit" not in str(e).lower():
                print(f"claude: BadRequestError: {str(e)[:200]}", flush=True)
                return ""
            print(f"claude: {key.name} is out of credit, trying the next key", flush=True)
        except anthropic.APIError as e:
            print(f"claude: {type(e).__name__}: {str(e)[:200]}", flush=True)
            return ""
    else:
        return ""
    usd = cost(r.usage)
    HOME.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": int(t), "day": datetime.date.today().isoformat(), "model": MODEL, "what": what[:80],
                            "in": r.usage.input_tokens, "out": r.usage.output_tokens, "usd": round(usd, 5),
                            "stop": r.stop_reason, "seconds": round(time.time() - t)}) + "\n")
    if r.stop_reason == "refusal":
        return ""
    return "".join(b.text for b in r.content if b.type == "text")
