"""Own llama-server for the night (inside a GPU hold): the deployed Litha GGUF, optionally with a LoRA, and a small
thread-pool client for many chat requests."""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

NO_WINDOW, BELOW_NORMAL = 0x08000000, 0x00004000


class Server:
    def __init__(self, exe: str, model: str, port: int = 8197, lora: str = "", parallel: int = 2, ctx: int = 6144,
                 log: str | Path = "server.log", draft: str = ""):
        self.exe, self.model, self.port, self.lora, self.draft = exe, model, port, lora, draft
        self.parallel, self.ctx, self.log = parallel, ctx, Path(log)
        self.proc: subprocess.Popen | None = None
        self.url = f"http://127.0.0.1:{port}"

    def args(self) -> list[str]:
        a = [self.exe, "-m", self.model, "--alias", "litha", "--host", "127.0.0.1", "--port", str(self.port),
             # the node's measured fit (8 GB card, desktop ~0.6 GB): 2 slots, unified q4_0 KV, small micro-batch.
             # 10-29: 4 slots with q8_0 KV (sliding-window cache per slot ~670 MB) spilled into shared memory:
             # prompt 45 tok/s, 5-11 tok/s per slot.
             "-c", str(self.ctx), "-np", str(self.parallel), "-kvu", "-lm", "none", "--fit", "off", "-ngl", "99",
             "-fa", "on", "-ctk", "q4_0", "-ctv", "q4_0", "-b", "512", "-ub", "128", "-t", "4", "--jinja",
             "--reasoning", "off",
             "--no-webui"]
        if self.lora:
            a += ["--lora", self.lora, "--lora-init-without-apply"]
        if self.draft:                      # the node's MTP drafter step (exact: same answers, ~1.8x faster on the card)
            a += ["--model-draft", self.draft, "--spec-type", "draft-mtp", "--spec-draft-n-max", "4", "-ngld", "99"]
        return a

    def start(self, timeout: float = 240) -> None:
        self.log.parent.mkdir(parents=True, exist_ok=True)
        flags = NO_WINDOW | BELOW_NORMAL if os.name == "nt" else 0
        self.proc = subprocess.Popen(self.args(), stdout=open(self.log, "w", encoding="utf-8"),
                                     stderr=subprocess.STDOUT, creationflags=flags)
        end = time.time() + timeout
        while time.time() < end:
            if self.proc.poll() is not None:
                raise RuntimeError(f"llama-server exited ({self.proc.returncode}); see {self.log}")
            try:
                with urllib.request.urlopen(self.url + "/health", timeout=3) as r:
                    if r.status == 200:
                        return
            except Exception:  # noqa: BLE001
                pass
            time.sleep(2)
        raise RuntimeError("llama-server did not become ready")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=30)
        self.proc = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    def chat(self, messages: list[dict], temperature: float = 0.3, max_tokens: int = 1200, seed: int = -1,
             timeout: float = 300, lora_scale: float | None = None) -> dict:
        body = {"model": "litha", "messages": messages, "temperature": temperature, "max_tokens": max_tokens,
                "seed": seed, "chat_template_kwargs": {"enable_thinking": False}}
        if self.lora:                       # one server answers as base (scale 0) and as the adapter (scale 1)
            body["lora"] = [{"id": 0, "scale": float(lora_scale or 0.0)}]
        return post_chat(self.url + "/v1/chat/completions", body, {}, timeout)


def post_chat(url: str, body: dict, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **headers})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        ch = d["choices"][0]
        tm = d.get("timings") or {}
        return {"text": (ch["message"].get("content") or "").strip(), "finish": ch.get("finish_reason"),
                "tokens": d.get("usage", {}).get("completion_tokens"), "s": round(time.time() - t0, 2),
                "error": "", "tok_s": tm.get("predicted_per_second"), "draft_n": tm.get("draft_n"),
                "draft_ok": tm.get("draft_n_accepted")}
    except Exception as e:  # noqa: BLE001
        return {"text": "", "finish": "error", "tokens": 0, "s": round(time.time() - t0, 2), "error": repr(e)[:300]}


class Remote:
    """A mesh node's model port used as the harvest server (e.g. STAR's PC 4060 through its node proxy :8098).
    The node keeps its own busy guard: when its owner is busy it unloads and refuses, so this client never forces
    anything; `available()` asks the node's /status first and the caller waits or stops."""

    def __init__(self, url: str, token_file: str, status_url: str = "", parallel: int = 1):
        self.url = url.rstrip("/")
        self.status_url = status_url
        self.parallel = parallel
        self.lora = ""
        self.token = Path(os.path.expanduser(token_file)).read_text(encoding="utf-8").split()[0]

    def available(self) -> tuple[bool, str]:
        if not self.status_url:
            return True, ""
        try:
            with urllib.request.urlopen(self.status_url, timeout=5) as r:
                st = json.load(r)
        except Exception as e:  # noqa: BLE001
            return False, f"status unreachable: {e!r}"[:200]
        m = (st.get("models") or [{}])[0]
        ok = st.get("state") == "idle" and bool(m.get("loaded"))
        return ok, f"{st.get('state')}: {st.get('reason', '')}"[:200]

    def chat(self, messages: list[dict], temperature: float = 0.3, max_tokens: int = 1200, seed: int = -1,
             timeout: float = 300, lora_scale: float | None = None) -> dict:
        body = {"model": "litha", "messages": messages, "temperature": temperature, "max_tokens": max_tokens,
                "seed": seed, "chat_template_kwargs": {"enable_thinking": False}}
        return post_chat(self.url + "/v1/chat/completions", body, {"Authorization": "Bearer " + self.token}, timeout)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


def run_many(fn, items: list, workers: int, should_stop=lambda: False) -> list:
    """fn(item) for every item with `workers` threads, results in order; items after a stop get None."""
    out: list = [None] * len(items)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {}
        for i, it in enumerate(items):
            futs[ex.submit(lambda x=it: None if should_stop() else fn(x))] = i
        for f, i in futs.items():
            out[i] = f.result()
    return out
