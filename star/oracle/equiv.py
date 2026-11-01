"""L0: are two configs the same function? Greedy continuations (temperature 0, top-k 1, fixed seed) of fixed prompts,
compared token for token. Meant for perf-only changes (threads, pinning, huge pages, builds, speculative decoding):
identical tokens on every prompt = EQUIVALENT, no quality eval needed. A difference reports the first prompt and
token position where the outputs part (floating-point reordering alone can do that; L1 then measures how far).

A config's `server.url` is used as is (with `server.model` as the request's model), otherwise llama-server is
started from the config (model, lora, ngl, ctx, launch.args, launch.env) on a free local port and stopped afterwards.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request

from .config import Config


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _post(url: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class Server:
    """A running llama-server for one config (started here unless the config names a URL)."""

    def __init__(self, cfg: Config, workdir: Path, *, start_timeout: float = 600.0):
        self.cfg, self.proc, self.log = cfg, None, None
        if cfg.server.get("url"):
            self.url = cfg.server["url"].rstrip("/")
            return
        port = _free_port()
        self.url = f"http://127.0.0.1:{port}"
        cmd = [cfg.tool("llama-server"), "-m", cfg.model, "--host", "127.0.0.1", "--port", str(port),
               "-ngl", str(cfg.ngl), "-c", str(cfg.ctx), "-np", "1"]
        for path in cfg.lora:
            cmd += ["--lora", path]
        if cfg.threads:
            cmd += ["-t", str(cfg.threads)]
        cmd += [str(a) for a in cfg.launch.get("args", [])]
        Path(workdir).mkdir(parents=True, exist_ok=True)
        self.log = open(Path(workdir) / f"{cfg.name}.server.log", "w", encoding="utf-8")
        self.proc = subprocess.Popen(cmd, stdout=self.log, stderr=subprocess.STDOUT,
                                     env={**os.environ, **cfg.launch.get("env", {})})
        deadline = time.monotonic() + start_timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"llama-server for {cfg.name} exited ({self.proc.returncode}); see {self.log.name}")
            try:
                with urllib.request.urlopen(self.url + "/health", timeout=5) as resp:
                    if resp.status == 200:
                        return
            except OSError:
                pass
            time.sleep(2)
        self.close()
        raise RuntimeError(f"llama-server for {cfg.name} did not become ready")

    def greedy(self, prompt: str, n_predict: int, *, timeout: float = 900.0) -> list[int]:
        body = {"prompt": prompt, "n_predict": n_predict, "temperature": 0, "top_k": 1, "seed": 42,
                "return_tokens": True, "cache_prompt": True}
        if self.cfg.server.get("model"):
            body["model"] = self.cfg.server["model"]
        return list(_post(self.url + "/completion", body, timeout).get("tokens") or [])

    def close(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.log is not None:
            self.log.close()


def outputs(cfg: Config, prompts: list[str], workdir: Path, *, n_predict: int = 32, server_cls=Server) -> dict:
    started = time.monotonic()
    server = server_cls(cfg, workdir)
    try:
        tokens = [server.greedy(p, n_predict) for p in prompts]
    finally:
        server.close()
    return {"tokens": tokens, "seconds": round(time.monotonic() - started, 1)}


def compare(base_tokens: list[list[int]], cand_tokens: list[list[int]]) -> dict:
    """EQUIVALENT when every continuation is identical and non-empty; else DIFFERENT with the first divergence."""
    first = None
    differing = 0
    for i, (b, c) in enumerate(zip(base_tokens, cand_tokens)):
        if b == c and b:
            continue
        differing += 1
        if first is None:
            pos = next((j for j, (x, y) in enumerate(zip(b, c)) if x != y), min(len(b), len(c)))
            first = {"prompt": i, "token": pos}
    same = differing == 0 and len(base_tokens) == len(cand_tokens) and bool(base_tokens)
    return {"verdict": "EQUIVALENT" if same else "DIFFERENT", "prompts": len(base_tokens),
            "differing_prompts": differing, "first_difference": first}
