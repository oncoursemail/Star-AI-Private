"""Explicit, loopback-only Ollama inference microbenchmark for Litha.

Uses a small public synthetic suite; no real chats, project files, secrets,
model responses or prompt text are persisted. Never downloads or configures
models. Reports latency and Ollama's *measured* nanosecond counters, not a
promise of quality or 100% GPU offload. Run only when the operator requests it.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from http.client import HTTPConnection
import json
import math
import re
from statistics import median
from time import monotonic
from typing import Callable

PROMPTS = (
    ("greeting", "Reply with one friendly greeting, no more than 10 words."),
    ("logic", "A game round starts with 4 lives and costs one life every 3 minutes. How many remain after 7 minutes?"),
    ("code", "Write a short Python function that finds the maximum of an integer list without calling max()."),
    ("tools", 'Return JSON only with keys "action" and "reason" for choosing to inspect a failing unit test before editing.'),
    ("roblox", "In two sentences, explain why a Roblox RemoteEvent needs server-side validation."),
)
SUITE_SHA256 = sha256(json.dumps(PROMPTS, separators=(",", ":")).encode("utf-8")).hexdigest()
MAX_STREAM_BYTES = 512_000
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")


def _positive_int(value: object, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in {low}..{high}")
    return value


def _model(model: str) -> str:
    if type(model) is not str or not MODEL_RE.fullmatch(model) or "://" in model:
        raise ValueError("Invalid Ollama model tag")
    return model


def _metric(data: dict, field: str, *, positive: bool = False) -> int:
    number = data.get(field)
    if type(number) is not int or number < (1 if positive else 0):
        raise ValueError(f"Missing or invalid Ollama {field}")
    return number


def probe(
    model: str, prompt: str, *, port: int = 11434, num_ctx: int = 4096,
    num_predict: int = 160, timeout: float = 120.0,
    connection_factory: Callable[..., HTTPConnection] = HTTPConnection,
    clock: Callable[[], float] = monotonic,
) -> dict:
    """Measure a completed response; fail closed on partial/malformed streams.

    Only HTTP/127.0.0.1 is supported: no external URL, DNS, proxy, redirect,
    bearer token, environment-based destination, or arbitrary remote content.
    """
    _model(model)
    _positive_int(port, "port", 1024, 65535)
    _positive_int(num_ctx, "num_ctx", 512, 32768)
    _positive_int(num_predict, "num_predict", 1, 256)
    if type(prompt) is not str or not 1 <= len(prompt) <= 2048:
        raise ValueError("Synthetic prompt must be 1..2048 characters")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 1 <= timeout <= 600:
        raise ValueError("Invalid timeout")
    payload = {
        "model": model, "prompt": prompt, "stream": True, "keep_alive": "5m",
        "options": {"num_ctx": num_ctx, "num_predict": num_predict, "temperature": 0},
    }
    start = clock()
    conn = connection_factory("127.0.0.1", port, timeout=timeout)
    first = None
    done = None
    output_chars = 0
    received = 0
    try:
        conn.request("POST", "/api/generate", body=json.dumps(payload).encode("utf-8"),
                     headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        if response.status != 200:
            raise RuntimeError("Local Ollama returned a non-200 status")
        for raw in response:
            received += len(raw)
            if received > MAX_STREAM_BYTES or clock() - start > 2 * timeout:
                raise RuntimeError("Ollama stream exceeded a safety budget")
            if not raw.strip():
                continue
            try:
                data = json.loads(raw)
            except (UnicodeError, ValueError) as exc:
                raise RuntimeError("Malformed Ollama JSONL stream") from exc
            if not isinstance(data, dict) or "error" in data:
                raise RuntimeError("Ollama returned an invalid/error event")
            chunk = data.get("response", "")
            if not isinstance(chunk, str):
                raise RuntimeError("Nontext Ollama response event")
            if chunk:
                if first is None:
                    first = clock()
                output_chars += len(chunk)
                if output_chars > 32768:
                    raise RuntimeError("Ollama response too large")
            if data.get("done") is True:
                done = data
                break
        if done is None or first is None or output_chars == 0:
            raise RuntimeError("Incomplete or empty Ollama stream")
        end = clock()
        count = _metric(done, "eval_count", positive=True)
        ns = _metric(done, "eval_duration", positive=True)
        prefill_count = _metric(done, "prompt_eval_count")
        prefill_ns = _metric(done, "prompt_eval_duration")
        load_ns = _metric(done, "load_duration")
        total_ns = _metric(done, "total_duration", positive=True)
        # Some Ollama versions omit this counter entirely.
        cached = _metric(done, "prompt_eval_cached_count") if "prompt_eval_cached_count" in done else None
        if cached is not None and cached > prefill_count:
            raise RuntimeError("Invalid prompt-cache counter")
        uncached = prefill_count - (cached or 0)
        return {
            "ok": True, "ttft_ms": round((first - start) * 1000, 2),
            "wall_ms": round((end - start) * 1000, 2),
            "ollama_total_ms": round(total_ns / 1e6, 2),
            "load_ms": round(load_ns / 1e6, 2),
            "output_tokens": count,
            "decode_tps": round(count * 1e9 / ns, 2),
            "prompt_tokens": prefill_count,
            "cached_prompt_tokens": cached,
            "uncached_prefill_tps": round(uncached * 1e9 / prefill_ns, 2) if uncached and prefill_ns else None,
        }
    except (OSError, TimeoutError, RuntimeError, ValueError, UnicodeError) as exc:
        return {"ok": False, "error_type": type(exc).__name__}
    finally:
        conn.close()


def _p95(data: list[float]) -> float:
    values = sorted(data)
    return values[math.ceil(len(values) * 0.95) - 1]


def summarize(samples: list[dict]) -> dict:
    """Never treat failures or incomplete generated counts as valid benchmark data."""
    if not samples:
        raise ValueError("No benchmark observations")
    successes = [x for x in samples if x.get("ok") is True]
    valid = len(successes) == len(samples) and all(
        type(x.get("output_tokens")) is int and x["output_tokens"] > 0
        and all(type(x.get(key)) in (float, int) and math.isfinite(x[key]) and x[key] >= 0
                for key in ("ttft_ms", "wall_ms", "decode_tps", "ollama_total_ms", "load_ms"))
        and x["decode_tps"] > 0 and x["wall_ms"] >= x["ttft_ms"]
        for x in successes
    )
    result = {"requests": len(samples), "successful": len(successes),
              "failed": len(samples) - len(successes), "valid": valid}
    if not valid:
        return {**result, "decision": "INVALID: rerun; do not compare or deploy"}
    for field in ("ttft_ms", "wall_ms", "decode_tps", "load_ms"):
        values = [float(x[field]) for x in successes]
        result[field] = {"p50": round(median(values), 2), "p95": round(_p95(values), 2)}
    return {**result, "decision": "MEASURED: performance only; held-out quality and VRAM checks required"}


def run(model: str, *, port: int = 11434, num_ctx: int = 4096, repeats: int = 1,
        num_predict: int = 160, probe_fn=probe) -> dict:
    _model(model)
    _positive_int(repeats, "repeats", 1, 5)
    _positive_int(port, "port", 1024, 65535)
    _positive_int(num_ctx, "num_ctx", 512, 32768)
    _positive_int(num_predict, "num_predict", 1, 256)
    # The warmup is reported, but not counted as a benchmark result.
    warmup = probe_fn(model, "Warm up: respond with OK.", port=port,
                      num_ctx=num_ctx, num_predict=16)
    samples = []
    for trial in range(repeats):
        for case, prompt in PROMPTS:
            result = probe_fn(model, f"{prompt}\nSynthetic trial={trial}, case={case}.",
                              port=port, num_ctx=num_ctx, num_predict=num_predict)
            samples.append({"task_id": case, "trial": trial, **result})
    summary = summarize(samples)
    if not warmup.get("ok"):
        summary["valid"] = False
        summary["decision"] = "INVALID: warmup failed"
    return {"schema": 1, "engine": "ollama-local", "model": model,
            "context_tokens_configured": num_ctx, "num_predict_limit": num_predict,
            "suite_sha256": SUITE_SHA256, "warmup_ok": bool(warmup.get("ok")),
            "summary": summary, "samples": samples,
            "gpu_fit_verified": False,
            "limitations": "Synthetic loopback-only runs; no model outputs saved. Check ollama ps, "
                           "nvidia-smi dedicated VRAM high-water, prefill and held-out correctness "
                           "separately. Do not compare across different machines, model hashes, "
                           "context sizes, thermal states, or other active GPU workloads."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Opt-in localhost Ollama response benchmark")
    parser.add_argument("--model", required=True, help="Already installed Ollama model tag")
    parser.add_argument("--port", type=int, default=11434)
    parser.add_argument("--context", type=int, default=4096)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--num-predict", type=int, default=160)
    args = parser.parse_args(argv)
    try:
        report = run(args.model, port=args.port, num_ctx=args.context,
                     repeats=args.repeats, num_predict=args.num_predict)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report["summary"]["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
