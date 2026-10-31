"""Retrieval evaluation: recall@k, MRR@10 and latency for each search mode.

A question counts as answered at rank r when the r-th returned passage comes from one of the
question's expected source files. All modes use the same post-processing (max 2 passages per page).

Mode names: a base (`bm25`, `vector`, `hybrid`) plus optional flags joined with `+`:
  `+q`         use the generated questions (study.py) in both generators
  `+fallback`  vector mode on a partly embedded index: embed BM25's top unembedded chunks at query time
  `+rerank`    hybrid only: rerank the head of the list with the reranker model (seconds per query)
  `+f`         long queries are also searched sentence by sentence (search.split_facets); `+frrf`
               merges the sentence rankings by rank instead of by best cosine
A mode without `+q` ignores generated questions even when the index has them.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
import statistics

from .quiet import wait_while_locked
from .search import Searcher


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def load_questions(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("//"):
            row = json.loads(line)
            if not row.get("id") or not row.get("question") or not row.get("expected"):
                raise ValueError("question needs id, question, expected")
            rows.append(row)
    return rows


def parse_mode(mode: str) -> tuple[str, dict]:
    base, *flags = mode.split("+")
    weights = [f for f in flags if re.fullmatch(r"lw\d+(?:\.\d+)?", f)]
    unknown = set(flags) - {"q", "fallback", "rerank", "f", "frrf", "rr"} - set(weights)
    if unknown:
        raise ValueError(f"unknown mode flag in {mode!r}: {sorted(unknown)}")
    options = {"fallback": "fallback" in flags, "questions": "q" in flags, "facets": "f" in flags or "frrf" in flags}
    if "rr" in flags:
        options["remote_rerank_n"] = 10
    if weights:
        options["lexical_weight"] = float(weights[-1][2:])
    if "frrf" in flags:
        options["facet_merge"] = "rrf"
    return base + ("+rerank" if "rerank" in flags else ""), options


def run_eval(db_path: Path, questions_path: Path, modes: list[str], *, scope_embedded: bool = False,
             rerank_n: int = 15, scope_file: Path | None = None, question_scale: float | None = None,
             details: bool = True, reuse_query_vectors: bool = False, per_doc: int = 2) -> dict:
    """scope_file: a list of text hashes; every mode then searches only those chunks, and only the
    questions with at least one expected page inside the scope are counted (`n` says how many)."""
    questions = load_questions(questions_path)
    scope_shas = None
    if scope_file is not None:
        scope_shas = {line.split()[0] for line in scope_file.read_text(encoding="utf-8").splitlines()
                      if line.strip() and not line.startswith("#")}
    searcher = Searcher(db_path, scope_embedded=scope_embedded, scope_shas=scope_shas, question_scale=question_scale,
                        reuse_query_vectors=reuse_query_vectors)
    known = {r[0] for r in searcher.db.execute("SELECT path FROM docs")}
    for q in questions:  # a typo in an expected path must fail loudly, not look like a miss
        for path in q["expected"]:
            if path not in known:
                raise ValueError(f"{q['id']}: expected path not in index: {path}")
        if q.get("answer") and not any(q["answer"] in r[0] for r in searcher.db.execute(
                f"SELECT c.text FROM chunks c JOIN docs d ON d.id=c.doc_id WHERE d.path IN ({','.join('?' * len(q['expected']))})",
                q["expected"])):    # a question with a verbatim answer must be answerable from its expected pages
            raise ValueError(f"{q['id']}: answer not found in its expected pages")
    asked = len(questions)
    if scope_shas is not None:
        in_scope = {r[0] for r in searcher.db.execute("SELECT d.path, c.text_sha FROM chunks c JOIN docs d ON d.id=c.doc_id")
                    if r[1] in scope_shas}
        questions = [q for q in questions if any(path in in_scope for path in q["expected"])]
    summary, rows_by_mode = {}, {}
    for mode in modes:
        wait_while_locked(log=lambda message: print(message, file=sys.stderr))
        real, options = parse_mode(mode)
        ranks, totals, stages = [], [], {}
        rows = []
        for q in questions:
            wait_while_locked(log=lambda message: print(message, file=sys.stderr))
            passages, timing = searcher.search(q["question"], mode=real, top=10, per_doc=per_doc, rerank_n=rerank_n, **options)
            rank = next((p.rank for p in passages if p.path in q["expected"]), None)
            ranks.append(rank)
            totals.append(timing["total_ms"])
            for key, value in timing.items():
                stages.setdefault(key, []).append(value)
            rows.append({"id": q["id"], "type": q.get("type"), "rank": rank, "timing_ms": timing,
                         "top5": [f"{p.path}#{p.heading}" for p in passages[:5]]})
        n = len(questions)
        by_type: dict[str, list] = {}
        for q, rank in zip(questions, ranks):
            by_type.setdefault(q.get("type") or "untyped", []).append(rank)
        summary[mode] = {
            "n": n,
            "recall@1": round(sum(1 for r in ranks if r and r <= 1) / n, 4) if n else None,
            "recall@3": round(sum(1 for r in ranks if r and r <= 3) / n, 4) if n else None,
            "recall@5": round(sum(1 for r in ranks if r and r <= 5) / n, 4) if n else None,
            "recall@10": round(sum(1 for r in ranks if r and r <= 10) / n, 4) if n else None,
            "mrr@10": round(sum(1.0 / r for r in ranks if r) / n, 4) if n else None,
            "hits@5": sum(1 for r in ranks if r and r <= 5),
            "recall@5_by_type": {t: f"{sum(1 for r in rs if r and r <= 5)}/{len(rs)}" for t, rs in sorted(by_type.items())},
            "latency_ms": {"mean": round(statistics.fmean(totals), 1), "median": round(statistics.median(totals), 1),
                           "p95": round(_pct(totals, 0.95), 1), "max": round(max(totals), 1)} if totals else {},
            "stage_mean_ms": {k: round(statistics.fmean(v), 1) for k, v in stages.items() if k != "total_ms"},
            "missed@5": [q["id"] for q, r in zip(questions, ranks) if not r or r > 5],
        }
        rows_by_mode[mode] = rows
    out = {
        "questions_file": str(questions_path), "questions_asked": asked, "questions_counted": len(questions),
        "scope_embedded": scope_embedded, "scope_file": str(scope_file) if scope_file else None,
        "scope_chunks": len(searcher._scope) if searcher._scope is not None else None,
        "chunks_total": searcher.db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
        "chunks_embedded": searcher.embedded_count(),
        "question_vectors": searcher.question_count(), "question_scale": searcher.question_scale,
        "sources": {n: {"commit": s["commit_sha"], "commit_date": s["commit_date"]} for n, s in searcher.sources.items()},
        "rerank_n": rerank_n, "per_doc": per_doc, "summary": summary,
    }
    if details:
        out["details"] = rows_by_mode
    searcher.close()
    return out


def one_line(result: dict) -> str:
    """`bm25 r@5=26/30 mrr=0.672 | vector r@5=...`: the short form the nightly report uses."""
    return " | ".join(f"{mode} r@5={s['hits@5']}/{s['n']} mrr={s['mrr@10']}" for mode, s in result["summary"].items())
