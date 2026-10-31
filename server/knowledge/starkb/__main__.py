"""CLI: python -m starkb {build|build-private|stats|subset|embed|search|ask|api-lookup|luau-check|serve|eval|
                         study-plan|study|study-status|refresh|api-coverage|
                         offload-export|offload-import|offload-sample|offload-run|offload-claim|offload-release|watchdog}

Paths default to the deployed layout in the container:
  /opt/star/knowledge/app      this code
  /opt/star/knowledge/sources  git checkouts (fetch.sh)
  /opt/star/knowledge/data     kb.sqlite3
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

HOME = Path(os.environ.get("STAR_KB_HOME", "/opt/star/knowledge"))
APP = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="starkb")
    parser.add_argument("--db", type=Path, default=HOME / "data" / "kb.sqlite3")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("build", help="chunk the checked-out sources and rebuild the FTS5 index (one transaction)")
    p.add_argument("--force", action="store_true", help="accept a result with far fewer chunks than before")
    sub.add_parser("stats", help="print index statistics")

    p = sub.add_parser("build-private", help="index a brain vault (Markdown notes) into the PRIVATE database (--db)")
    p.add_argument("--vault", type=Path, required=True)
    p.add_argument("--force", action="store_true", help="accept a result with far fewer chunks than before")

    p = sub.add_parser("subset", help="write the text hashes of a focus-area subset to a file")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--size", type=int, default=2000)
    p.add_argument("--questions", type=Path, default=APP / "eval" / "questions.jsonl")

    p = sub.add_parser("embed", help="embed chunks that have no embedding yet (resumable)")
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--limit", type=int)
    p.add_argument("--sha-file", type=Path, help="only embed chunks whose text hash is listed here")
    p.add_argument("--max-seconds", type=float)
    p.add_argument("--pause", type=float, default=0.0, help="sleep between batches (seconds)")
    p.add_argument("--duty", type=float, default=1.0,
                   help="fraction of time the embedding server may be busy, e.g. 0.4 (see embed.py)")

    p = sub.add_parser("offload-export", help="print the texts still to embed as JSON lines (embedding on a GPU, offload.py)")
    p.add_argument("--limit", type=int)
    p = sub.add_parser("offload-import", help="load a vectors file from stdin (offload.py format); never replaces vectors")
    p.add_argument("--batch", type=int, default=2000, help="rows per commit")
    p = sub.add_parser("offload-sample", help="print N embedded texts with their stored vectors (check another machine)")
    p.add_argument("--n", type=int, default=200)
    p = sub.add_parser("offload-run", help="embed the pending texts on a LAN worker (the laptop GPU) and store them; "
                                           "resumable, exits at once when nothing is pending (offload.py)")
    p.add_argument("--url", default=os.environ.get("STAR_KB_OFFLOAD_URL", ""), help="worker base URL ($STAR_KB_OFFLOAD_URL)")
    p.add_argument("--key-file", default=os.environ.get("STAR_KB_OFFLOAD_KEY_FILE", ""), help="worker API key file")
    p.add_argument("--owner", default="laptop", help="name on the claim file (the PC's gpu_embed.py uses 'pc')")
    p.add_argument("--batch", type=int, default=8, help="texts per request (8 x 2 in flight measured fastest on the laptop)")
    p.add_argument("--in-flight", type=int, default=2, help="requests at the same time")
    p.add_argument("--max-seconds", type=float, default=3300.0)
    p.add_argument("--small", type=int, default=3000, help="more pending than this = bulk: only inside --hours")
    p.add_argument("--hours", default="0-8", help="local hours (America/Chicago) for a bulk run, START-END")
    p = sub.add_parser("offload-claim", help="take the claim on embedding the pending texts (exit 1 if another holds it)")
    p.add_argument("--owner", required=True)
    p.add_argument("--ttl", type=float, default=43200.0)
    p = sub.add_parser("offload-release", help="give the claim back")
    p.add_argument("--owner", required=True)

    p = sub.add_parser("search", help="search and print cited passages")
    p.add_argument("query")
    p.add_argument("--mode", default="hybrid", help="bm25 | vector | hybrid | hybrid+rerank (rerank adds seconds)")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--json", action="store_true")
    p.add_argument("--context", type=int, default=0, help="print a prompt-ready block capped at N characters")

    p = sub.add_parser("ask", help="retrieve, then answer once with star-fast and report token timings")
    p.add_argument("question")
    p.add_argument("--mode", default="hybrid")
    p.add_argument("--top", type=int, default=4)
    p.add_argument("--max-chars", type=int, default=4200)
    p.add_argument("--max-tokens", type=int, default=220)

    p = sub.add_parser("api-lookup", help="exact engine API symbol check, e.g. TweenService:Create")
    p.add_argument("symbols", nargs="+")

    sub.add_parser("watchdog", help="one health check of the running service; restarts it after 2 failures (timer)")
    p = sub.add_parser("serve", help="run the HTTP service (127.0.0.1:8091 by default; the unit binds 0.0.0.0)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8091)

    p = sub.add_parser("luau-check", help="compile + type-analyse a Luau file (never runs it)")
    p.add_argument("file", type=Path)
    p.add_argument("--mode", choices=["strict", "nonstrict"])

    p = sub.add_parser("study-plan", help="write the first study subset (most-mentioned API, most-linked guides)")
    p.add_argument("--out", type=Path, default=HOME / "data" / "study-subset.txt")
    p.add_argument("--size", type=int, default=1500)

    p = sub.add_parser("study", help="doc2query: write questions each chunk answers (resumable, low priority)")
    p.add_argument("--order-file", type=Path, help="text hashes to study first, in this order (study-plan)")
    p.add_argument("--only-listed", action="store_true", help="stop when the order file is done")
    p.add_argument("--limit", type=int)
    p.add_argument("--max-seconds", type=float)
    p.add_argument("--dry-run", action="store_true", help="print the questions, store nothing")

    sub.add_parser("study-status", help="how far the study job is")

    p = sub.add_parser("refresh", help="nightly: fetch, rebuild, embed changed chunks, check, write a report line")
    p.add_argument("--modes", default="bm25,vector", help="modes for the 30-question check")
    p.add_argument("--max-wait", type=float, default=3 * 3600, help="give up if the server lock is held this long")
    p.add_argument("--report", type=Path)

    p = sub.add_parser("api-coverage", help="is every class and member of the API reference found by api-lookup?")
    p.add_argument("--out", type=Path)

    p = sub.add_parser("eval", help="recall@k / MRR / latency on a question file")
    p.add_argument("--questions", type=Path, default=APP / "eval" / "questions.jsonl")
    p.add_argument("--modes", default="bm25,vector,hybrid,hybrid+rerank",
                   help="comma list; flags: +q (generated questions), +fallback, +rerank")
    p.add_argument("--scope-file", type=Path, help="text hashes: search only these chunks (subset experiments)")
    p.add_argument("--question-scale", type=float, help="override search.QUESTION_SCALE for this run")
    p.add_argument("--per-doc", type=int, default=2, help="passages allowed from one page (the service uses 2)")
    p.add_argument("--scope-embedded", action="store_true",
                   help="restrict every mode to chunks that have an embedding (subset experiments)")
    p.add_argument("--out", type=Path)
    p.add_argument("--rerank-n", type=int, default=15)

    args = parser.parse_args(argv)

    if args.cmd == "build":
        from .store import build
        stats = build(args.db, HOME / "sources", APP / "corpora.json", force=args.force)
        print(json.dumps(stats, indent=2))
        return 0

    if args.cmd == "stats":
        from .store import connect
        db = connect(args.db)
        out = {
            "sources": [dict(r) for r in db.execute("SELECT name, commit_sha, commit_date, licence, indexed_at FROM sources")],
            "docs": db.execute("SELECT COUNT(*) FROM docs").fetchone()[0],
            "chunks": db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
            "chunks_by_kind": dict(db.execute("SELECT kind, COUNT(*) FROM chunks GROUP BY kind").fetchall()),
            "embeddings": dict(db.execute("SELECT model, COUNT(*) FROM embeddings GROUP BY model").fetchall()),
            "generated_questions": db.execute("SELECT COUNT(*) FROM chunk_questions").fetchone()[0],
            "chunks_with_questions": db.execute(
                "SELECT COUNT(*) FROM chunks c WHERE EXISTS (SELECT 1 FROM chunk_questions q WHERE q.text_sha=c.text_sha)").fetchone()[0],
            "chunks_with_embedding": db.execute(
                "SELECT COUNT(*) FROM chunks c WHERE EXISTS (SELECT 1 FROM embeddings e WHERE e.text_sha=c.text_sha)").fetchone()[0],
            "db_bytes": args.db.stat().st_size,
        }
        print(json.dumps(out, indent=2))
        return 0

    if args.cmd == "subset":
        from .subset import write_subset
        print(json.dumps(write_subset(args.db, args.out, args.size, args.questions), indent=2))
        return 0

    if args.cmd == "embed":
        from .embed import run
        print(json.dumps(run(args.db, batch=args.batch, limit=args.limit, sha_file=args.sha_file,
                             max_seconds=args.max_seconds, pause=args.pause, duty=args.duty,
                             log=lambda m: print(m, flush=True)), indent=2))
        return 0

    if args.cmd in ("offload-export", "offload-import", "offload-sample"):
        from . import offload
        from .client import EMBED_MODEL
        if args.cmd == "offload-export":
            count = offload.export_pending(args.db, sys.stdout, EMBED_MODEL, limit=args.limit)
        elif args.cmd == "offload-sample":
            count = offload.sample_existing(args.db, sys.stdout, EMBED_MODEL, n=args.n)
        else:
            count = offload.import_vectors(args.db, sys.stdin.buffer, EMBED_MODEL, batch=args.batch,
                                           log=lambda m: print(m, file=sys.stderr, flush=True))
        print(json.dumps({"model": EMBED_MODEL, "result": count}), file=sys.stderr)
        return 0

    if args.cmd in ("offload-run", "offload-claim", "offload-release"):
        from . import offload
        from .client import EMBED_MODEL
        claim_file = args.db.parent / "offload-claim.json"
        if args.cmd == "offload-claim":
            holder = offload.claim(claim_file, args.owner, args.ttl)
            print(json.dumps({"claimed": not holder, "holder": holder or args.owner}))
            return 1 if holder else 0
        if args.cmd == "offload-release":
            print(json.dumps({"released": offload.release(claim_file, args.owner)}))
            return 0
        if not args.url:
            parser.error("offload-run needs --url or $STAR_KB_OFFLOAD_URL")
        from .client import Brain
        from .quiet import Stopper
        start, end = (int(x) for x in args.hours.split("-"))
        worker = Brain(url=args.url, key_file=args.key_file, retries=1, timeout=120.0)
        stopper = Stopper()
        result = offload.run_on_worker(args.db, worker, EMBED_MODEL, claim_path=claim_file, owner=args.owner,
                                       batch=args.batch, in_flight=args.in_flight, max_seconds=args.max_seconds, small=args.small,
                                       hours=(start, end), stop=stopper, log=lambda m: print(m, flush=True))
        return 0 if result["ok"] else 3

    if args.cmd == "build-private":
        from .private_corpus import build_private
        stats = build_private(args.vault, args.db, force=args.force)
        print(json.dumps(stats["_all"] | {"db": str(args.db)}, indent=2))
        return 0

    if args.cmd == "search":
        from .search import Searcher, context_block
        searcher = Searcher(args.db)
        passages, timing = searcher.search(args.query, mode=args.mode, top=args.top)
        if args.json:
            print(json.dumps({"query": args.query, "mode": args.mode, "timing_ms": timing,
                              "passages": [p.as_dict() for p in passages]}, indent=2, ensure_ascii=False))
        elif args.context:
            print(context_block(passages, max_chars=args.context))
        else:
            for p in passages:
                print(f"[{p.rank}] {p.heading}  (score {p.score})")
                print(f"    {p.url}")
                print(f"    {p.source}@{p.commit[:10]}  {p.path}  licence: {p.licence}")
                print("    " + " ".join(p.text.split())[:240])
            print("timing_ms", timing)
        return 0

    if args.cmd == "ask":
        from .answer import ask
        print(json.dumps(ask(args.db, args.question, mode=args.mode, top=args.top, max_chars=args.max_chars,
                             max_tokens=args.max_tokens), indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "api-lookup":
        from .serve import api_lookup
        from .store import connect
        print(json.dumps(api_lookup(connect(args.db), args.symbols), indent=2))
        return 0

    if args.cmd == "luau-check":
        from .luaucheck import check
        print(json.dumps(check(args.file.read_text(encoding="utf-8"), mode=args.mode), indent=2))
        return 0

    if args.cmd == "watchdog":
        from .watchdog import main as watchdog_main
        return watchdog_main()

    if args.cmd == "serve":
        from .serve import serve
        serve(args.db, host=args.host, port=args.port)
        return 0

    if args.cmd == "study-plan":
        from .study import plan
        order, counts = plan(args.db, HOME / "sources", APP / "corpora.json", size=args.size)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("".join(f"{sha} {reason}\n" for sha, reason in order), encoding="utf-8")
        print(json.dumps({**counts, "out": str(args.out)}, indent=2))
        return 0

    if args.cmd == "study":
        from .study import run
        result = run(args.db, order_file=args.order_file, only_listed=args.only_listed, limit=args.limit,
                     max_seconds=args.max_seconds, dry_run=args.dry_run, log=lambda m: print(m, flush=True))
        print(json.dumps(result, indent=2))
        return 1 if result["status"] == "failed" else 0

    if args.cmd == "study-status":
        from .store import connect
        from .study import progress
        print(json.dumps(progress(connect(args.db)), indent=2))
        return 0

    if args.cmd == "refresh":
        from .refresh import run
        result = run(args.db, HOME, APP, max_wait=args.max_wait, modes=args.modes, report=args.report,
                     log=lambda m: print(m, flush=True))
        return 0 if result["status"] in ("ok", "unchanged", "skipped-lock") else 1

    if args.cmd == "api-coverage":
        from .coverage import run
        result = run(args.db, HOME / "sources", APP / "corpora.json")
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({k: v for k, v in result.items() if k != "missing"}, indent=2))
        return 0

    if args.cmd == "eval":
        from .evaluate import run_eval
        result = run_eval(args.db, args.questions, [m.strip() for m in args.modes.split(",") if m.strip()],
                          scope_embedded=args.scope_embedded, rerank_n=args.rerank_n,
                          scope_file=args.scope_file, question_scale=args.question_scale, per_doc=args.per_doc,
                          reuse_query_vectors=True)
        text = json.dumps(result, indent=2, ensure_ascii=False)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding="utf-8")
        print(json.dumps(result["summary"], indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
