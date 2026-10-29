"""Client of the star-polyglot checker (server/mesh/polyglot/runner.py, in its own no-network LXD container) for the
verifier: real compilers/type checkers for Python, JavaScript/TypeScript, C# (+ Unity API truth), Java, C/C++, Rust,
Go, GDScript (Godot 4), Lua, SQL and shell. A checker that is down, slow or broken never produces a problem: the
block then counts as not checked, exactly like before.
"""
from __future__ import annotations

import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

LANGUAGES = {"python", "javascript", "typescript", "csharp", "java", "cpp", "c", "rust", "go", "gdscript", "lua", "sql",
             "shell"}


class Polyglot:
    def __init__(self, url: str, token: str, timeout_s: float = 3.0):
        self.url, self.token, self.timeout_s = url.rstrip("/"), token, timeout_s
        self.pool = ThreadPoolExecutor(max_workers=6)

    @classmethod
    def from_config(cls, cfg: dict) -> "Polyglot | None":
        path, url = Path(cfg.get("polyglot_token_file") or ""), cfg.get("polyglot_url") or ""
        url_file = Path(cfg.get("polyglot_url_file") or "")
        if not url and url_file.is_file():
            url = url_file.read_text(encoding="utf-8").strip()
        if not url or not path.is_file():
            return None
        return cls(url, path.read_text(encoding="utf-8").strip(), float(cfg.get("polyglot_timeout_s", 3.0)))

    def check(self, language: str, code: str, context: str = "") -> dict | None:
        """The checker's reply ({checked, problems, tool, mode, ms}) or None when it could not answer."""
        if language not in LANGUAGES:
            return None
        body = json.dumps({"language": language, "code": code, "context": context}).encode()
        req = urllib.request.Request(self.url + "/check", body, {"Content-Type": "application/json",
                                                                 "Authorization": "Bearer " + self.token})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                out = json.loads(r.read())
        except (OSError, ValueError):
            return None
        return out if isinstance(out, dict) and out.get("checked") else None

    def check_many(self, items: list[tuple[str, str]], context: str = "") -> dict[tuple[str, str], dict | None]:
        """{(language, code): reply} for several blocks at once (in parallel)."""
        todo = list(dict.fromkeys(i for i in items if i[0] in LANGUAGES))
        futures = {i: self.pool.submit(self.check, i[0], i[1], context) for i in todo}
        return {i: f.result() for i, f in futures.items()}
