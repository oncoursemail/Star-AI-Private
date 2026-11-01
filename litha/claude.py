"""Litha's second opinion: Claude, asked only when her local model fails. Paid per token, so every call is priced from
its usage and written to a ledger; she stops asking at the cap (total and per day).
Key: ~/.star/anthropic.key (one line, the owner's). Caps: ~/.star/litha-claude/cap.json {"total": 150, "day": 20}."""
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
CAPS = {"total": 150.0, "day": 20.0}                 # of the owner's $200: room left for his own use


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


def ready() -> bool:
    if not KEY.exists() or os.environ.get("LITHA_CLAUDE") == "off" or "PYTEST_CURRENT_TEST" in os.environ:
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
    client = anthropic.Anthropic(api_key=KEY.read_text(encoding="utf-8").strip(), max_retries=2, timeout=300)
    t = time.time()
    try:
        r = client.messages.create(model=MODEL, max_tokens=16000, output_config={"effort": effort},
                                   messages=[{"role": "user", "content": prompt}])
    except anthropic.APIError as e:
        print(f"claude: {type(e).__name__}: {str(e)[:200]}", flush=True)
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
