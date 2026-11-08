"""Explicit local STAR model benchmark (never launched automatically).

python -m scripts.benchmark_star --model your-model --stream-startup
python -m scripts.benchmark_star --model your-model --workload canary --requests 4
# Test only an idle/authorized endpoint; NOT during gameplay or an OBS stream.
"""
from __future__ import annotations

import argparse
import asyncio
import json

from star.inference_benchmark import benchmark_local_model
from star.inference_stream_benchmark import benchmark_stream_startup


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Measure synthetic local model completion or streaming startup"
    )
    parser.add_argument(
        "--endpoint", default="http://127.0.0.1:8080/v1",
        help="Loopback endpoint, or validated private STAR Server with --star-server",
    )
    parser.add_argument("--model", required=True, help="Installed model ID")
    parser.add_argument("--parallel", type=int, default=1,
                        help="Concurrency: max 4 completions or 2 streams")
    parser.add_argument("--requests", type=int, default=4,
                        help="Request count: max 12 completions or 8 streams")
    parser.add_argument("--workload", choices=("mixed", "repeat", "canary"),
                        default="mixed", help="Canary must be sequential")
    parser.add_argument("--stream-startup", action="store_true",
                        help="Measure time until first visible text delta and completed response")
    parser.add_argument("--star-server", action="store_true",
                        help="Use existing private-LAN and keyring authorization checks")
    args = parser.parse_args(argv)
    bench = benchmark_stream_startup if args.stream_startup else benchmark_local_model
    report = asyncio.run(bench(
        args.endpoint, args.model, requests=args.requests,
        parallel=args.parallel, workload=args.workload, server=args.star_server,
    ))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
