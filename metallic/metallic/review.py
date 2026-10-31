"""AI review by STAR's own brain (OpenAI-compatible /v1/chat/completions). It only comments: its result is never
blocking, and a brain that is down or slow gives a "skip", not a failure.

Operator configuration (environment, never in the repo): METALLIC_BRAIN_URL (or STAR_BRAIN_URL), METALLIC_BRAIN_KEY_FILE
(default ~/.star/server_api_key), METALLIC_REVIEW_MODEL (default star-fast). The URL and key are never printed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import time
import urllib.request

from .checks import INFO, PASS, SKIP, CheckResult, finding

MAX_DIFF_CHARS = 16000
PROMPT = ("You review a code change for the owner's projects. Report only concrete problems a reviewer would block "
          "or ask about: bugs, behaviour changes without a test, security problems, leftover debug code. At most 5. "
          "Answer with a JSON array only, each item {\"file\": str, \"line\": int, \"comment\": str}. "
          "Answer [] when there is nothing concrete. Do not praise, do not summarise.")


def review(diff: str, *, url: str | None = None, key_file: str | None = None, model: str | None = None,
           timeout: float = 240.0, opener=None) -> CheckResult:
    url = (url or os.environ.get("METALLIC_BRAIN_URL") or os.environ.get("STAR_BRAIN_URL") or "").rstrip("/")
    if not url:
        return CheckResult("ai-review", SKIP, "no brain configured (METALLIC_BRAIN_URL)", blocking=False)
    if not diff.strip():
        return CheckResult("ai-review", PASS, "empty diff", blocking=False)
    path = Path(key_file or os.environ.get("METALLIC_BRAIN_KEY_FILE") or Path.home() / ".star" / "server_api_key")
    try:
        token = path.read_text(encoding="utf-8").split()[0].strip()
    except (OSError, IndexError):
        token = ""
    clipped = diff[:MAX_DIFF_CHARS] + ("\n[diff clipped]" if len(diff) > MAX_DIFF_CHARS else "")
    body = json.dumps({"model": model or os.environ.get("METALLIC_REVIEW_MODEL") or "star-fast", "temperature": 0.2,
                       "max_tokens": 700, "messages": [{"role": "system", "content": PROMPT},
                                                       {"role": "user", "content": clipped}]}).encode()
    req = urllib.request.Request(url + "/v1/chat/completions", data=body, method="POST", headers={
        "Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    started = time.monotonic()
    try:
        with (opener or urllib.request.urlopen)(req, timeout=timeout) as resp:
            text = json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"] or ""
    except Exception as e:                       # never echo the URL or the key
        return CheckResult("ai-review", SKIP, f"brain not reachable ({type(e).__name__})", blocking=False,
                           seconds=round(time.monotonic() - started, 1))
    items = _items(text)
    out = [finding(str(i.get("file", "")), int(i.get("line") or 0), "ai-review", str(i.get("comment", ""))[:500], INFO)
           for i in items[:5] if isinstance(i, dict) and i.get("comment")]
    return CheckResult("ai-review", INFO if out else PASS, f"{len(out)} comment(s) from the brain", out,
                       seconds=round(time.monotonic() - started, 1), blocking=False)


def _items(text: str) -> list:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return []
    return data if isinstance(data, list) else []
