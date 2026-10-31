"""Local-only paired streaming inference A/B experiments.

Records measurements, not claims of intelligence or permission to enable a setting.
Benchmarks the already-running llama-server; never starts a model or changes settings.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from http.client import HTTPConnection
import json
import math
import os
import platform
from pathlib import Path
from statistics import median
from time import monotonic
from urllib.parse import urlsplit

# Deliberately public, synthetic tasks. Never send a user's messages or projects.
PROMPTS: tuple[tuple[str, str], ...] = (
    ("quick_chat", "Say hello in one short, friendly sentence."),
    ("game_reaction", "You just beat a difficult game level on the third try. React naturally in two sentences."),
    ("game_strategy", "Suggest three short steps to learn the controls of an unfamiliar platform game."),
    ("roblox", "Explain how to validate a Roblox RemoteEvent on the server in two sentences."),
    ("coding", "Write a small Python function that returns the unique integers in a list, preserving order."),
    ("factual", "Explain why the Moon has phases, in three sentences."),
    ("reasoning", "A player has 3 lives and loses one every 4 minutes. How many lives remain after 9 minutes? Explain."),
    ("repetition", "Repeat this exactly three times: amber star silver star amber star."),
)
SUITE_SHA256 = sha256(json.dumps(PROMPTS, separators=(",", ":")).encode()).hexdigest()
MAX_FILE_BYTES = 256_000
MAX_STREAM_BYTES = 512_000


def loopback_endpoint(value: str) -> tuple[str, int]:
    """No LAN, cloud, DNS, redirects, auth in URL, proxies or HTTPS downgrade."""
    url = urlsplit(value)
    try:
        port = url.port or 80
    except ValueError as exc:
        raise ValueError("Invalid local server port") from exc
    if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1"}
            or url.path.rstrip("/") != "/v1" or url.query or url.fragment
            or url.username is not None or url.password is not None or not 1 <= port <= 65535):
        raise ValueError("Use a loopback-only http://127.0.0.1:PORT/v1 endpoint")
    return url.hostname, port


def host_fingerprint() -> str:
    # A stable machine comparison without revealing the machine's hostname.
    parts = (platform.node(), platform.system(), platform.machine(), str(os.cpu_count()))
    return sha256(json.dumps(parts).encode()).hexdigest()


def file_digest(path: str | None) -> str | None:
    if not path:
        return None
    digest = sha256()
    with Path(path).open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def probe(endpoint: str, model: str, prompt: str, *, timeout: float = 60.0) -> dict:
    """Count only real SSE content, require a completed stream, and never log text."""
    host, port = loopback_endpoint(endpoint)
    started = monotonic()
    first: float | None = None
    completed = False
    done = False
    chars = 0
    tokens: int | None = None
    digest = sha256()
    received = 0
    conn = HTTPConnection(host, port, timeout=timeout)  # http.client ignores proxy env vars.
    payload = {"model": model, "stream": True, "temperature": 0,
               "max_tokens": 160,
               "messages": [{"role": "system", "content": "Answer the request accurately and briefly."},
                            {"role": "user", "content": prompt}]}
    try:
        conn.request("POST", "/v1/chat/completions", body=json.dumps(payload).encode(),
                     headers={"Content-Type": "application/json",
                              **({"Authorization": "Bearer " + os.environ["STAR_BENCH_LOCAL_API_KEY"]}
                                 if os.environ.get("STAR_BENCH_LOCAL_API_KEY") else {})})
        response = conn.getresponse()
        if response.status != 200:
            raise RuntimeError(f"Local server returned HTTP {response.status}")
        if "text/event-stream" not in (response.getheader("Content-Type") or "").lower():
            raise RuntimeError("Local server did not return an SSE stream")
        for line in response:
            received += len(line)
            if received > MAX_STREAM_BYTES or monotonic() - started > timeout * 2:
                raise RuntimeError("Stream exceeded safety budget")
            data = line.strip()
            if not data.startswith(b"data:"):
                continue
            data = data[5:].strip()
            if data == b"[DONE]":
                done = True
                break
            try:
                event = json.loads(data)
            except (ValueError, UnicodeDecodeError) as exc:
                raise RuntimeError("Invalid local SSE JSON") from exc
            if not isinstance(event, dict):
                raise RuntimeError("Invalid SSE event shape")
            usage = event.get("usage")
            if isinstance(usage, dict) and type(usage.get("completion_tokens")) is int:
                count = usage["completion_tokens"]
                if 0 <= count <= 160:
                    tokens = count
            choices = event.get("choices") or []
            if not isinstance(choices, list):
                raise RuntimeError("Invalid SSE choices")
            if choices:
                choice = choices[0]
                if not isinstance(choice, dict):
                    raise RuntimeError("Invalid SSE choice")
                if choice.get("finish_reason") is not None:
                    completed = True
                delta = choice.get("delta") or {}
                if not isinstance(delta, dict):
                    raise RuntimeError("Invalid SSE delta")
                text = delta.get("content")
                if text is not None and not isinstance(text, str):
                    raise RuntimeError("Invalid SSE content")
                if text:
                    if first is None:
                        first = monotonic()
                    digest.update(text.encode())
                    chars += len(text)
                    if chars > 32_000:
                        raise RuntimeError("Response was too large")
        if not (done and completed and first is not None and chars > 0):
            raise RuntimeError("Local server returned an incomplete or empty stream")
        ended = monotonic()
        return {"ok": True, "ttft_ms": round((first - started) * 1000, 2),
                "total_ms": round((ended - started) * 1000, 2),
                "characters": chars, "completion_tokens": tokens,
                "output_sha256": digest.hexdigest()}
    except (OSError, TimeoutError, RuntimeError, ValueError) as exc:
        return {"ok": False, "error": type(exc).__name__,
                "ttft_ms": None, "total_ms": round((monotonic() - started) * 1000, 2),
                "characters": 0, "completion_tokens": None, "output_sha256": None}
    finally:
        conn.close()


def run_arm(arm: str, endpoint: str, model: str, *, repeats: int = 2,
            model_file: str | None = None, binary_file: str | None = None,
            probe_fn=probe) -> dict:
    if arm not in {"baseline", "candidate"} or type(repeats) is not int or not 1 <= repeats <= 4:
        raise ValueError("Use baseline/candidate and 1..4 repeats")
    loopback_endpoint(endpoint)
    if not isinstance(model, str) or not 1 <= len(model.strip()) <= 128 or any(ord(c) < 32 for c in model):
        raise ValueError("Invalid model name")
    # Warm-up is measured neither as an experiment nor as a successful trial.
    warmup = probe_fn(endpoint, model, PROMPTS[0][1])
    samples: list[dict] = []
    for repeat in range(repeats):
        for task_id, prompt in PROMPTS:
            row = probe_fn(endpoint, model, prompt)
            samples.append({"task_id": task_id, "repeat": repeat, **row})
    return {"schema": 1, "arm": arm, "model": model, "suite_sha256": SUITE_SHA256,
            "model_sha256": file_digest(model_file), "binary_sha256": file_digest(binary_file),
            "host_sha256": host_fingerprint(), "repeats": repeats, "warmup_ok": bool(warmup["ok"]), "samples": samples,
            "warning": "Operator-controlled test; no ground-truth quality or hardware speedup is proved."}


def _load(path: str) -> dict:
    location = Path(path)
    if location.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Report exceeds size limit")
    report = json.loads(location.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError("Expected a JSON object")
    return report


def _p95(values: list[float]) -> float:
    sorted_values = sorted(values)
    return sorted_values[max(0, math.ceil(0.95 * len(values)) - 1)]


def compare(baseline: dict, candidate: dict) -> dict:
    if (baseline.get("schema") != 1 or candidate.get("schema") != 1
            or baseline.get("arm") != "baseline" or candidate.get("arm") != "candidate"
            or baseline.get("model") != candidate.get("model")
            or baseline.get("suite_sha256") != SUITE_SHA256
            or candidate.get("suite_sha256") != SUITE_SHA256
            or baseline.get("repeats") != candidate.get("repeats")):
        raise ValueError("Incompatible arms, model or synthetic suite")
    for name in ("model_sha256", "binary_sha256", "host_sha256"):
        a, b = baseline.get(name), candidate.get(name)
        if a != b:
            raise ValueError(f"Cannot compare different {name}")
    base_rows = baseline.get("samples")
    cand_rows = candidate.get("samples")
    if not isinstance(base_rows, list) or not isinstance(cand_rows, list):
        raise ValueError("Missing trials")
    if len(base_rows) != len(PROMPTS) * baseline["repeats"] or len(cand_rows) != len(base_rows):
        raise ValueError("Incomplete trial set")
    def index(rows: list[dict]) -> dict:
        out = {}
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Invalid trial")
            key = (row.get("task_id"), row.get("repeat"))
            if key in out:
                raise ValueError("Duplicate trial")
            out[key] = row
        return out
    a, b = index(base_rows), index(cand_rows)
    expected = {(task_id, repeat) for repeat in range(baseline["repeats"])
                for task_id, _prompt in PROMPTS}
    if set(a) != expected or set(b) != expected:
        raise ValueError("Mismatched trial identities")
    pairs = [(a[key], b[key]) for key in sorted(expected)]
    failed = sum(not x.get("ok") or not y.get("ok") for x, y in pairs)
    if failed:
        return {"performance_signal": "invalid_failures", "paired": len(pairs),
                "failed_pairs": failed, "automatic_enablement": False,
                "quality_evaluation": "required"}
    if not baseline.get("warmup_ok") or not candidate.get("warmup_ok"):
        return {"performance_signal": "invalid_warmup", "paired": len(pairs),
                "automatic_enablement": False, "quality_evaluation": "required"}
    for x, y in pairs:
        for row in (x, y):
            if (type(row.get("characters")) is not int or row["characters"] <= 0
                    or type(row.get("total_ms")) not in (int, float)
                    or type(row.get("ttft_ms")) not in (int, float)
                    or not math.isfinite(row["total_ms"]) or not math.isfinite(row["ttft_ms"])
                    or not 0 <= row["ttft_ms"] <= row["total_ms"]):
                raise ValueError("Invalid trial metrics")
    base_total = [x["total_ms"] for x, _ in pairs]
    cand_total = [y["total_ms"] for _, y in pairs]
    base_ttft = [x["ttft_ms"] for x, _ in pairs]
    cand_ttft = [y["ttft_ms"] for _, y in pairs]
    comparable_lengths = all(0.85 <= y["characters"] / x["characters"] <= 1.15 for x, y in pairs)
    total_ratio = median(cand_total) / max(0.001, median(base_total))
    tail_ratio = _p95(cand_total) / max(0.001, _p95(base_total))
    ttft_ratio = median(cand_ttft) / max(0.001, median(base_ttft))
    known_files = bool(baseline["model_sha256"] and baseline["binary_sha256"])
    if not comparable_lengths:
        signal = "not_comparable_output_lengths"
    elif total_ratio >= 1.05 or tail_ratio >= 1.20:
        signal = "regression"
    elif len(pairs) >= 16 and total_ratio <= 0.90 and tail_ratio <= 1.10 and ttft_ratio <= 1.10:
        signal = "promising_only"
    else:
        signal = "inconclusive"
    return {"performance_signal": signal, "paired": len(pairs), "failed_pairs": 0,
            "median_total_ms": {"baseline": round(median(base_total), 2),
                                "candidate": round(median(cand_total), 2)},
            "p95_total_ms": {"baseline": round(_p95(base_total), 2),
                             "candidate": round(_p95(cand_total), 2)},
            "median_ttft_ms": {"baseline": round(median(base_ttft), 2),
                               "candidate": round(median(cand_ttft), 2)},
            "relative_median_total": round(total_ratio, 3),
            "relative_p95_total": round(tail_ratio, 3),
            "identical_model_and_server_binary_hashes": known_files,
            "output_lengths_comparable": comparable_lengths,
            "automatic_enablement": False,
            "quality_evaluation": "required: held-out accuracy, game playtests, speech quality, FPS and VRAM"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measured loopback-only llama.cpp baseline versus candidate")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run one arm against an already-started local server")
    run.add_argument("--arm", choices=("baseline", "candidate"), required=True)
    run.add_argument("--url", default="http://127.0.0.1:8080/v1")
    run.add_argument("--model", required=True)
    run.add_argument("--repeats", type=int, default=2)
    run.add_argument("--model-file", help="Optional GGUF for local SHA-256 verification; no path saved")
    run.add_argument("--binary-file", help="Optional llama-server executable for SHA-256 verification")
    run.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("compare", help="Compare saved files without network or model calls")
    check.add_argument("--baseline", required=True)
    check.add_argument("--candidate", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            report = run_arm(args.arm, args.url, args.model, repeats=args.repeats,
                             model_file=args.model_file, binary_file=args.binary_file)
            args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"arm": args.arm, "samples": len(report["samples"]),
                              "failed": sum(not row["ok"] for row in report["samples"]),
                              "output": str(args.output)}, indent=2))
            return 0 if report["warmup_ok"] and all(row["ok"] for row in report["samples"]) else 1
        print(json.dumps(compare(_load(args.baseline), _load(args.candidate)), indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"Invalid benchmark: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
