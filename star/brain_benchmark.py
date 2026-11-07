"""STAR latency benchmark using a real OpenAI-compatible server the owner runs.

Nothing is benchmarked until this command is actually run on the owner's PC.
Loopback HTTP is the default. `--server` measures the owner's STAR Server on
the private LAN instead, with the key read from the OS keyring or the
STAR_SERVER_API_KEY environment variable (never from the command line).
No background jobs, uploads, or model changes.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
import re
import statistics
import time
from urllib.parse import urlsplit

import httpx
from .brain_router import validate_alias


_PROMPTS = {
    "chat": "In two short sentences, explain what a software regression test is.",
    "coding": "Write a small Python function that removes duplicates while preserving order. Include a simple example.",
    "roblox": "Write a short --!strict Luau function that validates a RemoteEvent's integer amount is between 1 and 50.",
}


def local_endpoint(value: str) -> str:
    """Fail closed against arbitrary hosts, credentials, fragments and paths."""
    if not isinstance(value, str):
        raise ValueError("Endpoint must be a URL")
    url = urlsplit(value)
    if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost"}
            or url.username is not None or url.password is not None
            or url.query or url.fragment or url.path.rstrip("/") != "/v1"
            or not re.fullmatch(r"http://(?:127\.0\.0\.1|localhost):\d{2,5}/v1/?", value)):
        raise ValueError("Use a loopback /v1 inference URL with no credentials")
    try:
        if url.port is None or not 1024 <= url.port <= 65535:
            raise ValueError("Local model port must be 1024..65535")
    except ValueError as exc:
        raise ValueError("Invalid local model port") from exc
    return value.rstrip("/")


def benchmark_target(endpoint: str | None, *, server: bool = False) -> tuple[str, str]:
    """Resolve `(endpoint, bearer)` for a loopback brain or the LAN STAR Server.

    The server path reuses STAR's private-IP validation and keyring key. With
    no explicit endpoint it measures the server address saved in Settings.
    """
    if not server:
        return local_endpoint(endpoint or "http://127.0.0.1:8080/v1"), "local-only"
    from .providers import STAR_SERVER, get_api_key, validate_lan_endpoint
    if not endpoint:
        from .desktop_core import Settings, app_data
        endpoint = Settings.load(app_data() / "settings.json").server_endpoint
    target = validate_lan_endpoint(endpoint)
    key = get_api_key(STAR_SERVER)
    if not key:
        raise ValueError("STAR Server needs its API key. Save it in Settings or set STAR_SERVER_API_KEY.")
    return target, key


def parse_sse_data(line: str) -> dict | None:
    """Decode one data event, tolerating comments, [DONE], and bad frames."""
    if not line.startswith("data:"):
        return None
    data = line[5:].strip()
    if not data or data == "[DONE]":
        return None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def measure_one(client: httpx.Client, endpoint: str, model: str, prompt: str,
                *, max_tokens: int = 96, api_key: str = "local-only") -> dict:
    """Observe TTFT and elapsed time; token speed only when the server reports usage."""
    validate_alias(model)
    if not 16 <= max_tokens <= 512:
        raise ValueError("Benchmark output token budget must be 16..512")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    started = time.perf_counter()
    first_visible = None
    output_chars = 0
    actual_tokens = None
    prompt_evaluated = None
    prompt_cached = None
    prompt_ms = None
    with client.stream("POST", endpoint + "/chat/completions", json=payload,
                       headers={"Authorization": f"Bearer {api_key}"}) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            item = parse_sse_data(line)
            if item is None:
                continue
            usage = item.get("usage")
            if isinstance(usage, dict) and type(usage.get("completion_tokens")) is int:
                actual_tokens = usage["completion_tokens"]
            timings = item.get("timings")
            if isinstance(timings, dict):
                if type(timings.get("predicted_n")) is int and timings["predicted_n"] >= 0:
                    actual_tokens = timings["predicted_n"]
                if type(timings.get("prompt_n")) is int and timings["prompt_n"] >= 0:
                    prompt_evaluated = timings["prompt_n"]
                if type(timings.get("cache_n")) is int and timings["cache_n"] >= 0:
                    prompt_cached = timings["cache_n"]
                reported_ms = timings.get("prompt_ms")
                if isinstance(reported_ms, (int, float)) and not isinstance(reported_ms, bool) and math.isfinite(reported_ms) and reported_ms >= 0:
                    prompt_ms = round(reported_ms, 1)
            choices = item.get("choices")
            if not isinstance(choices, list) or not choices:
                continue
            delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
            text = delta.get("content") if isinstance(delta, dict) else None
            if isinstance(text, str) and text:
                if first_visible is None:
                    first_visible = time.perf_counter()
                output_chars += len(text)
    done = time.perf_counter()
    if first_visible is None:
        raise RuntimeError("Model returned no visible text; benchmark not scored")
    total_s = max(done - started, 0.000001)
    generation_s = max(done - first_visible, 0.000001)
    return {
        "ttft_ms": round((first_visible - started) * 1000, 1),
        "total_ms": round(total_s * 1000, 1),
        "output_chars": output_chars,
        "output_chars_per_s": round(output_chars / generation_s, 2),
        "actual_completion_tokens": actual_tokens,
        "prompt_tokens_evaluated": prompt_evaluated,
        "prompt_tokens_cached": prompt_cached,
        "prompt_eval_ms": prompt_ms,
        "approx_tokens_per_s": round(actual_tokens / generation_s, 2)
        if actual_tokens is not None and actual_tokens > 0 else None,
    }


def summarize(measurements: list[dict], *, wall_ms: int | None = None, parallel: int = 1) -> dict:
    """Summarize observed response latency without inferring server queue time.

    Wall-time throughput is only meaningful when requests were measured as a group.
    Optional server cache/timing fields are excluded if the endpoint omits them.
    """
    if not measurements:
        raise ValueError("Provide at least one actual measurement")
    if type(parallel) is not int or not 1 <= parallel <= 4:
        raise ValueError("Parallel slots must be 1..4")
    if wall_ms is not None and (type(wall_ms) is not int or wall_ms <= 0):
        raise ValueError("Wall time must be a positive number of milliseconds")

    def percentile(key: str, p: float) -> float:
        ordered = sorted(float(row[key]) for row in measurements)
        return round(ordered[min(len(ordered) - 1, max(0, math.ceil(p * len(ordered)) - 1))], 1)

    report = {
        "runs": len(measurements),
        "median_ttft_ms": round(statistics.median(row["ttft_ms"] for row in measurements), 1),
        "p95_ttft_ms": percentile("ttft_ms", .95),
        "median_total_ms": round(statistics.median(row["total_ms"] for row in measurements), 1),
        "p95_total_ms": percentile("total_ms", .95),
        "median_output_chars_per_s": round(statistics.median(row["output_chars_per_s"] for row in measurements), 2),
        "note": "TTFT includes queueing, prompt processing, first decode and network. Server prompt/cache counters "
                "are included only when reported; they do not isolate queue time.",
    }
    for key, label in (("prompt_tokens_evaluated", "median_prompt_tokens_evaluated"),
                       ("prompt_tokens_cached", "median_prompt_tokens_cached"),
                       ("prompt_eval_ms", "median_prompt_eval_ms")):
        values = [row[key] for row in measurements if type(row.get(key)) in (int, float)]
        if len(values) == len(measurements):
            report[label] = round(statistics.median(values), 1)
    if wall_ms is not None:
        report.update({
            "wall_ms": wall_ms,
            "parallel": parallel,
            "requests_per_second": round(len(measurements) * 1000 / wall_ms, 3),
        })
        tokens = [row.get("actual_completion_tokens") for row in measurements]
        known_tokens = [n for n in tokens if isinstance(n, int) and not isinstance(n, bool) and n >= 0]
        if len(known_tokens) == len(measurements):
            report["aggregate_output_tokens_per_second"] = round(sum(known_tokens) * 1000 / wall_ms, 2)
    return report


def run_samples(client: httpx.Client, endpoint: str, model: str, prompt: str, *,
                runs: int = 3, parallel: int = 1, max_tokens: int = 96,
                api_key: str = "local-only") -> tuple[list[dict], int]:
    """Benchmark bounded concurrent real requests against a user-selected local brain.

    A shared HTTP client reuses connections; each request is independently streamed.
    The aggregate wall time includes server scheduling and contention. Runs are
    deliberately capped to avoid turning a benchmark into an unbounded load test.
    """
    if type(runs) is not int or not 1 <= runs <= 10:
        raise ValueError("Benchmark requires 1..10 runs")
    if type(parallel) is not int or not 1 <= parallel <= min(runs, 4):
        raise ValueError("Parallel slots must be between 1 and min(runs, 4)")
    if not 16 <= max_tokens <= 512:
        raise ValueError("Benchmark output token budget must be 16..512")

    def request() -> dict:
        return measure_one(client, endpoint, model, prompt, max_tokens=max_tokens, api_key=api_key)

    started = time.perf_counter()
    if parallel == 1:
        results = [request() for _ in range(runs)]
    else:
        # Executor.map preserves input order. Workers share only the connection pool;
        # no model selection, system setting, file write, or agent task is changed.
        with ThreadPoolExecutor(max_workers=parallel) as executor:
            results = list(executor.map(lambda _index: request(), range(runs)))
    return results, max(1, round((time.perf_counter() - started) * 1000))


MAX_REPORT_BYTES = 256_000
_IDENTITY = ("model", "scenario", "target", "endpoint")
_COMPARED = ("ttft_ms", "total_ms")


def _report_measurements(report: object, label: str) -> tuple[dict, list[dict]]:
    if not isinstance(report, dict) or not isinstance(report.get("summary"), dict):
        raise ValueError(f"{label}: not a brain_benchmark report")
    for key in _IDENTITY:
        if not isinstance(report.get(key), str) or not report[key]:
            raise ValueError(f"{label}: missing {key}")
    rows = report.get("measurements")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{label}: no measurements")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"{label}: invalid measurement row")
        for key in (*_COMPARED, "output_chars_per_s"):
            value = row.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{label}: invalid {key}")
    return report, rows


def compare_reports(baseline: object, candidate: object, *, alpha: float = 0.05) -> dict:
    """Paired speed verdict for two reports of the same model, scenario, target and parallelism.

    Sample i of the baseline is paired with sample i of the candidate and scored with the exact sign test and
    cluster bootstrap from star/eval_stats.py (lower time is a win). Any sample count works; with fewer pairs
    than the test can resolve the verdict stays INCONCLUSIVE. Speed only: says nothing about answer quality.
    """
    from . import eval_stats

    baseline, base_rows = _report_measurements(baseline, "baseline")
    candidate, cand_rows = _report_measurements(candidate, "candidate")
    for key in _IDENTITY:
        if baseline[key] != candidate[key]:
            raise ValueError(f"Reports differ in {key}: not a like-for-like comparison")
    if baseline["summary"].get("parallel", 1) != candidate["summary"].get("parallel", 1):
        raise ValueError("Reports differ in parallel requests: not a like-for-like comparison")
    pairs = min(len(base_rows), len(cand_rows))
    metrics, decisions = {}, []
    for key in _COMPARED:
        saved = [float(b[key]) - float(c[key]) for b, c in zip(base_rows, cand_rows)]
        wins, losses = sum(d > 0 for d in saved), sum(d < 0 for d in saved)
        test = eval_stats.sign_test(wins, losses)
        decision = (eval_stats.PROMOTE if test["p_better"] <= alpha else
                    eval_stats.REJECT if test["p_worse"] <= alpha else eval_stats.INCONCLUSIVE)
        low, high = eval_stats.bootstrap_ci(saved, level=1 - 2 * alpha)
        decisions.append(decision)
        metrics[key] = {"decision": decision, "wins": wins, "losses": losses, "ties": pairs - wins - losses,
                        "p_better": round(test["p_better"], 6), "p_worse": round(test["p_worse"], 6),
                        "mean_saved_ms_interval": [round(low, 1), round(high, 1)]}
    overall = (eval_stats.REJECT if eval_stats.REJECT in decisions else
               eval_stats.PROMOTE if eval_stats.PROMOTE in decisions else eval_stats.INCONCLUSIVE)
    notes = ["Arms were run one after the other, so drift between them is not cancelled; "
             "match hardware, model file, load and cache state.",
             "Speed evidence only: run the eval gate for answer quality before changing routing."]
    if pairs < eval_stats.min_resolvable_pairs(alpha):
        notes.append(f"{pairs} pairs cannot reach significance at alpha {alpha:g}; "
                     f"use at least {eval_stats.min_resolvable_pairs(alpha)} runs per arm.")
    if len(base_rows) != len(cand_rows):
        notes.append(f"Unequal run counts: only the first {pairs} samples of each arm are paired.")
    return {"decision": overall, "pairs": pairs, "alpha": alpha,
            **{key: baseline[key] for key in _IDENTITY}, "metrics": metrics,
            "baseline_summary": summarize(base_rows), "candidate_summary": summarize(cand_rows), "notes": notes}


def _load_report(path: str) -> object:
    with open(path, "rb") as file:
        data = file.read(MAX_REPORT_BYTES + 1)
    if len(data) > MAX_REPORT_BYTES:
        raise ValueError(f"{path}: report is larger than {MAX_REPORT_BYTES} bytes")
    return json.loads(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure STAR's local model speed without uploading prompts")
    parser.add_argument("--compare", nargs=2, metavar=("BASELINE", "CANDIDATE"), default=None,
                        help="Compare two saved reports of this command with a paired sign test (no requests sent). "
                             "Exit 0 faster, 1 slower, 2 unusable input, 4 inconclusive")
    parser.add_argument("--alpha", type=float, default=0.05, help="Significance level for --compare")
    parser.add_argument("--endpoint", default=None,
                        help="Loopback /v1 URL (default http://127.0.0.1:8080/v1), or with --server "
                             "the private STAR Server address (default: the one saved in Settings)")
    parser.add_argument("--server", action="store_true",
                        help="Measure STAR Server on the LAN; the key comes from the keyring or STAR_SERVER_API_KEY")
    parser.add_argument("--model", help="Model ID shown in the local server /models endpoint (required to measure)")
    parser.add_argument("--scenario", choices=sorted(_PROMPTS), default="chat")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--parallel", type=int, default=1,
                        help="Concurrent requests, 1..4 and no more than --runs (default 1)")
    parser.add_argument("--tokens", type=int, default=96)
    args = parser.parse_args(argv)
    if args.compare:
        if not 0 < args.alpha < 0.5:
            parser.error("--alpha must be between 0 and 0.5")
        try:
            result = compare_reports(*(_load_report(path) for path in args.compare), alpha=args.alpha)
        except (OSError, ValueError) as exc:
            print(json.dumps({"decision": "UNUSABLE", "error": str(exc)}, indent=2))
            return 2
        print(json.dumps(result, indent=2))
        return {"PROMOTE": 0, "REJECT": 1}.get(result["decision"], 4)
    if not args.model:
        parser.error("--model is required to measure (or use --compare)")
    endpoint, api_key = benchmark_target(args.endpoint, server=args.server)
    validate_alias(args.model)
    if not 1 <= args.runs <= 10:
        parser.error("--runs must be 1..10")
    if not 1 <= args.parallel <= min(args.runs, 4):
        parser.error("--parallel must be between 1 and min(--runs, 4)")
    if not 16 <= args.tokens <= 512:
        parser.error("--tokens must be 16..512")
    # A CPU server can need minutes for one answer; loopback keeps its 180 s limit.
    read_limit = 600.0 if args.server else 180.0
    with httpx.Client(timeout=httpx.Timeout(read_limit, connect=5.0), trust_env=False) as client:
        observations, wall_ms = run_samples(
            client, endpoint, args.model, _PROMPTS[args.scenario],
            runs=args.runs, parallel=args.parallel, max_tokens=args.tokens, api_key=api_key)
    report = {
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "scenario": args.scenario,
        "endpoint": endpoint,
        "target": "star_server" if args.server else "local",
        "measurements": observations,
        "summary": summarize(observations, wall_ms=wall_ms, parallel=args.parallel),
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
