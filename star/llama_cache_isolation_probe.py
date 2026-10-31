"""Explicit local-only synthetic probe for llama.cpp cache/context bleed.

A confirmed leaked canary is meaningful evidence of context contamination.
An absence of leaks over finitely many synthetic trials is NOT proof of safety.
This module is OFF by default, does not start a server or change configuration,
and never processes real viewers, chats, project secrets, or model memories.
Only the CLI's separately approved transport may send data, to loopback.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
import secrets
import statistics
import time
from typing import Callable
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


_CANARY = re.compile(r"STAR_CANARY_[0-9a-f]{24}\Z")
_ENDPOINT = "/v1/chat/completions"


@dataclass(frozen=True)
class CacheIsolationReport:
    verdict: str
    attempted_pairs: int
    completed_pairs: int
    leak_indicators: int
    unexpected_responses: int
    failed_requests: int
    response_time_p50_ms: float | None
    response_time_p95_ms: float | None
    note: str = (
        "Synthetic same-server canary test only. No leak observed is NOT proof "
        "that prompt/KV caching is safe across sessions or model versions."
    )


def _p(samples: list[float], ratio: float) -> float | None:
    if not samples:
        return None
    values = sorted(samples)
    import math
    return round(values[math.ceil(ratio * len(values)) - 1], 2)


def _payload(system: str, question: str) -> dict[str, object]:
    return {
        "model": "local",  # llama-server generally ignores this with one loaded model
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ],
        "temperature": 0,
        "max_tokens": 40,
        "stream": False,
        "cache_prompt": True,
    }


def run_cache_isolation_probe(
    client: Callable[[dict[str, object]], str], *, pairs: int = 4,
    filler_blocks: int = 32,
    token_factory: Callable[[], str] = lambda: "STAR_CANARY_" + secrets.token_hex(12),
) -> CacheIsolationReport:
    """A/B sequential requests with independent canaries and no sensitive input.

    client() is a trusted synchronous local inference adapter returning ONLY
    generated assistant text. The A canary is never sent in B's request. Both
    canary disclosure and A's response appearing in B are strong warning signs,
    but broad model misbehavior can also cause unexpected output.
    """
    if not callable(client) or not callable(token_factory):
        raise TypeError("trusted client and token factory must be callables")
    if type(pairs) is not int or not 1 <= pairs <= 12:
        raise ValueError("pairs must be 1..12")
    if type(filler_blocks) is not int or not 1 <= filler_blocks <= 256:
        raise ValueError("filler_blocks must be 1..256")
    # Fixed fictional tokens; all private canaries are per-run random. Never
    # generate this input from live viewers, project files or private memories.
    filler = " quiet scenery lamp river compass bicycle cloud brick." * filler_blocks
    timings: list[float] = []
    completed = unexpected = failed = leaks = attempted = 0
    for index in range(pairs):
        marker = token_factory()
        if type(marker) is not str or _CANARY.fullmatch(marker) is None:
            raise ValueError("token factory must issue a synthetic 96-bit canary")
        ack_a = f"ALPHA_OK_{index}"
        ack_b = f"BETA_OK_{index}"
        attempted += 1
        try:
            start = time.monotonic_ns()
            text_a = client(_payload(
                f"Test A: private synthetic marker {marker}. Respond only {ack_a}.",
                f"Return exactly {ack_a}, no explanation.\n{filler}",
            ))
            timings.append((time.monotonic_ns() - start) / 1e6)
            start = time.monotonic_ns()
            text_b = client(_payload(
                f"Test B: independent session. Respond only {ack_b}.",
                f"Return exactly {ack_b}, no explanation.\n{filler}",
            ))
            timings.append((time.monotonic_ns() - start) / 1e6)
        except (OSError, ValueError, RuntimeError, TimeoutError):
            failed += 1
            break
        if type(text_a) is not str or type(text_b) is not str:
            failed += 1
            break
        completed += 1
        if marker in text_b or ack_a in text_b:
            leaks += 1
            break  # do not continue using a potentially contaminated server
        if text_a.strip() != ack_a or text_b.strip() != ack_b:
            unexpected += 1
    status = ("possible_context_leak" if leaks else
              "inconclusive" if failed or unexpected else
              "no_leak_observed_not_proven_safe")
    return CacheIsolationReport(
        status, attempted, completed, leaks, unexpected, failed,
        _p(timings, 0.50), _p(timings, 0.95),
    )


def validate_loopback_endpoint(endpoint: str) -> str:
    """Refuse arbitrary URLs, DNS redirects, query parameters and credentials."""
    if type(endpoint) is not str or len(endpoint) > 180:
        raise ValueError("endpoint must be a bounded URL")
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid loopback endpoint") from exc
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or port is None or parsed.username is not None
            or parsed.password is not None or parsed.path != _ENDPOINT
            or parsed.query or parsed.fragment):
        raise ValueError("only explicit 127.0.0.1 llama-server endpoint is permitted")
    return endpoint


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _local_client(endpoint: str, timeout_seconds: int) -> Callable[[dict[str, object]], str]:
    validated = validate_loopback_endpoint(endpoint)
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120:
        raise ValueError("timeout_seconds must be 1..120")
    opener = build_opener(_NoRedirect())

    def call(payload: dict[str, object]) -> str:
        request = Request(
            validated, data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with opener.open(request, timeout=timeout_seconds) as response:
            raw = response.read(65_537)
            if len(raw) > 65_536:
                raise ValueError("oversized local inference response")
        body = json.loads(raw)
        if type(body) is not dict:
            raise ValueError("invalid inference JSON")
        choices = body.get("choices")
        if type(choices) is not list or not choices:
            raise ValueError("missing inference response")
        first = choices[0]
        if type(first) is not dict or type(first.get("message")) is not dict:
            raise ValueError("invalid assistant message")
        generated = first["message"].get("content")
        if type(generated) is not str or len(generated) > 32_768:
            raise ValueError("invalid bounded assistant content")
        return generated

    return call


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Explicit, synthetic, loopback-only llama.cpp context isolation test"
    )
    parser.add_argument("--endpoint", default="http://127.0.0.1:8080/v1/chat/completions")
    parser.add_argument("--pairs", type=int, default=4)
    parser.add_argument("--filler-blocks", type=int, default=32)
    parser.add_argument("--timeout-seconds", type=int, default=45)
    parser.add_argument("--opt-in-local", action="store_true",
                        help="acknowledge deliberate requests to local llama-server")
    args = parser.parse_args()
    if not args.opt_in_local:
        parser.error("pass --opt-in-local to send synthetic requests to loopback")
    client = _local_client(args.endpoint, args.timeout_seconds)
    report = run_cache_isolation_probe(
        client, pairs=args.pairs, filler_blocks=args.filler_blocks,
    )
    # Only aggregate status and timing; never print canaries or model responses.
    print(json.dumps(asdict(report), sort_keys=True))
    return 2 if report.leak_indicators else 1 if report.failed_requests or report.unexpected_responses else 0


if __name__ == "__main__":
    raise SystemExit(main())
