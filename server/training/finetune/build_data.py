"""Fine-tune data: verified worked examples (SFT + exemplar bank) and pass/fail rows (KTO), decontaminated.

    python build_data.py --examples s1/examples.jsonl s2/examples.jsonl pc/examples.jsonl \
        --failures s1/failures.jsonl s2/failures.jsonl pc/failures.jsonl \
        --private-examples outbox/paintball/worked-examples.jsonl --suites evals/roblox \
        [--embed-url http://127.0.0.1:8099] [--public] --out work/ft20/data

Rules (docs/agents/finetune-20261020.md):
- Desirable rows = night school examples (every one passed the practice task's automated checks). One answer per task
  (newest), then one per normalised prompt and per answer. STAR's appended footer is cut off (eval_checks.split_answer).
- Slop (star/slop.py: a hard finding or score >= 30) is dropped from training and from the bank.
- The evaluation suites are never trained on: a row is dropped when its task id is a suite id, or its prompt/answer
  matches any suite text exactly or fuzzily (startrain.decontam: 5-gram Jaccard/containment, shared 8-grams, answer
  vs reference answers) or, with --embed-url, its prompt embedding is within --cosine of a suite prompt. The suites
  (holdout included) are read only to build hashed fingerprints, as startrain's gate G8 does; no suite text is
  written anywhere.
- Private rows (Paintball / River tasks) may train locally; --public drops them from every output file.
- Undesirable rows (KTO) = failing answers on tasks that also have a verified answer (a task nobody solved may be broken),
  at most --max-fail-per-task distinct answers per task, same decontamination as their task.
- The generated "ledger" family is capped at --ledger-share of the SFT train rows (the pilot learned ledger style and
  got worse on hand-written tasks).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for extra in (ROOT, HERE.parent):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

SYSTEM = ("You are STAR, a Roblox game development assistant. Answer the request with complete, working Luau code in "
          "```lua fenced blocks and a short explanation. Use current Roblox APIs (task.wait, not wait).")
VAL_PERCENT = 10
BANK_MAX = 500
PRIVATE = re.compile(r"paintball|river", re.I)
GATE_FILE = re.compile(r"^(golden-tasks-|holdout-).*\.json$")
EMBED_PREFIX = "task: sentence similarity | query: "
# Near-copies found by hand in the W3 A/B (docs/agents/worked-examples-eval.md) that no automatic rule here catches.
KNOWN_NEAR_COPIES = frozenset({"practice-ui-responsive-scale"})
DECONTAM = SimpleNamespace(decontam_jaccard=0.35, decontam_containment=0.50, decontam_code_jaccard=0.50)


def norm_hash(text: str) -> str:
    return hashlib.sha256(" ".join(str(text).lower().split()).encode("utf-8")).hexdigest()


def bucket(salt: str, key: str) -> int:
    return int(hashlib.sha256((salt + ":" + key).encode("utf-8")).hexdigest()[:8], 16) % 100


def family(task: str, category: str) -> str:
    if task.startswith("LG-") or category.startswith("ledger"):
        return "ledger"
    return (category or "other").split("-")[0]


def is_private(task: str, category: str) -> bool:
    return bool(PRIVATE.search(task) or PRIVATE.search(category))


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def first_code(answer: str) -> str:
    blocks = re.findall(r"```[\w+-]*[^\n]*\n(.*?)```", answer, re.S)
    return "\n".join(blocks) if blocks else answer


def gate_suites(source: Path, dest: Path) -> Path:
    """Copy of the gate suites only (golden-tasks-*, holdout-* and their reference answers / unit tests) into `dest`.
    The practice-tasks-* files in the same folder are training material, not gates."""
    import shutil
    ids = set()
    for path in sorted(source.glob("*.json")):
        if GATE_FILE.match(path.name):
            shutil.copyfile(path, dest / path.name)
            ids |= {str(t.get("id")) for t in json.loads(path.read_text(encoding="utf-8")) if isinstance(t, dict)}
    if not ids:
        raise ValueError("no gate suites (golden-tasks-*.json, holdout-*.json) under " + str(source))
    for folder in ("reference", "tests"):
        if (source / folder).is_dir():
            (dest / folder).mkdir()
            for path in sorted((source / folder).iterdir()):
                if path.is_file() and path.name.split(".")[0] in ids:
                    shutil.copyfile(path, dest / folder / path.name)
    for path in source.glob("*.luau"):
        shutil.copyfile(path, dest / path.name)
    return dest


class SuiteGuard:
    """Decontamination against every suite under `suites` (ids, exact/fuzzy text, optional embeddings)."""

    def __init__(self, suites: Path, embed=None, cosine: float = 0.75):
        from startrain import decontam
        with tempfile.TemporaryDirectory(prefix="ft-gate-suites-") as tmp:
            suites = gate_suites(Path(suites), Path(tmp))
            self._init(suites, embed, cosine, decontam)

    def _init(self, suites: Path, embed, cosine: float, decontam) -> None:
        self.index = decontam.build_index(suites)
        self.checker = decontam.Decontaminator(self.index, DECONTAM)
        self.ids = set()
        for _, tasks in decontam._task_lists(suites):
            self.ids |= {str(t.get("id")).upper() for t in tasks if t.get("id")}
        self.embed, self.cosine = embed, cosine
        self.vectors: list[list[float]] = []
        if embed is not None:
            prompts = [t["prompt"] for _, tasks in decontam._task_lists(suites) for t in tasks
                       if isinstance(t.get("prompt"), str)]
            self.vectors = embed([EMBED_PREFIX + p[:2000] for p in prompts])

    def template_shingles(self, prompts: list[str]) -> set[int]:
        """Prompt 8-grams that are boilerplate ("In my Roblox game: write a server script that ..."): in >= 3
        evaluation prompts or >= 5 training prompts. They are ignored by the shared-8-gram rule; the 5-gram Jaccard /
        containment, answer and embedding rules still see the whole text."""
        from startrain import similarity as sim
        seen_eval: dict[int, int] = {}
        for item in self.checker.items:
            if item["kind"] == "prompt":
                for g in item["sh8"]:
                    seen_eval[g] = seen_eval.get(g, 0) + 1
        seen_train: dict[int, int] = {}
        for prompt in prompts:
            for g in sim.shingles(sim.tokens(prompt), 8):
                seen_train[g] = seen_train.get(g, 0) + 1
        return {g for g, n in seen_eval.items() if n >= 3} | {g for g, n in seen_train.items() if n >= 5}

    def reasons(self, rows: list[dict]) -> list[str]:
        """One reason per row ('' = clean). Rows need task, prompt, body."""
        from startrain import similarity as sim
        template = self.template_shingles([r["prompt"] for r in rows])
        out = []
        for row in rows:
            if str(row["task"]).upper() in self.ids or str(row["task"]).upper().startswith("HO-"):
                out.append("task id is an evaluation id")
                continue
            if row["task"] in KNOWN_NEAR_COPIES:
                out.append("known near-copy of an evaluation task")
                continue
            fp = sim.fingerprint(row["prompt"], first_code(row["body"]), "")
            fp["prompt_sh8"] -= template
            out.append(self.checker.check_text(fp))
        if self.embed is not None and self.vectors:
            todo = [i for i, r in enumerate(out) if not r]
            vecs = self.embed([EMBED_PREFIX + rows[i]["prompt"][:2000] for i in todo])
            for i, vec in zip(todo, vecs):
                best = max(sim.cosine(vec, v) for v in self.vectors)
                rows[i]["max_suite_cosine"] = round(best, 4)
                if best >= self.cosine:
                    out[i] = "prompt embedding is close to an evaluation prompt"
        return out


def http_embedder(url: str, batch: int = 32):
    import httpx

    def embed(texts: list[str]) -> list[list[float]]:
        vectors = []
        for start in range(0, len(texts), batch):
            reply = httpx.post(url.rstrip("/") + "/v1/embeddings", json={"input": texts[start:start + batch]},
                               timeout=300, trust_env=False)
            reply.raise_for_status()
            vectors += [d["embedding"] for d in sorted(reply.json()["data"], key=lambda d: d["index"])]
        return vectors
    return embed


def load_export(path: Path, origin: str) -> list[dict]:
    """Rows in the worked-example export format (instruction/response) or plain prompt/answer rows."""
    out = []
    for row in read_jsonl(path):
        prompt = row.get("instruction") or row.get("prompt")
        answer = row.get("response") or row.get("answer")
        task = row.get("group_id") or row.get("task") or row.get("id")
        if isinstance(prompt, str) and isinstance(answer, str) and task:
            out.append({"task": str(task), "category": row.get("task_category") or row.get("category", ""),
                        "prompt": prompt, "answer": answer, "ts": "", "origin": origin,
                        "private": origin == "private"})
    return out


def load_examples(example_files: list[Path], private_files: list[Path]) -> tuple[list[dict], int]:
    rows, read = [], 0
    for path in example_files:
        for row in read_jsonl(path):
            read += 1
            if row.get("verified") is False:
                continue
            rows.append({"task": str(row["task"]), "category": row.get("category", ""), "prompt": row["prompt"],
                         "answer": row["answer"], "ts": str(row.get("ts", "")), "origin": path.parent.parent.name})
    for path in private_files:          # worked-example export format (Paintball outbox)
        found = load_export(path, "private")
        read += len(found)
        rows += found
    return rows, read


def build(example_files, failure_files, private_files, suites: Path, *, embed=None, cosine=0.75, public=False,
          ledger_share=0.35, max_fail_per_task=3, slop_check=None, gold_files=(), gold_weight=2) -> dict:
    from star.eval_checks import split_answer
    if slop_check is None:
        from star.slop import score_answer

        def slop_check(answer, prompt):
            return score_answer(answer, prompt=prompt).slop
    counts: dict[str, int] = {}

    def bump(key, n=1):
        counts[key] = counts.get(key, 0) + n

    raw, counts["example_rows_read"] = load_examples(example_files, private_files)
    for path in gold_files:             # licence-clean verified bank (docs/agents/gold-bank-20261020.md)
        gold = load_export(path, "gold")
        for row in gold:
            row["task"] = "gold:" + row["task"]
        counts["gold_rows_read"] = counts.get("gold_rows_read", 0) + len(gold)
        raw += gold
    newest: dict[str, dict] = {}
    for row in raw:
        row["private"] = bool(row.get("private")) or is_private(row["task"], row["category"])
        if public and row["private"]:
            bump("private_dropped_public")
            continue
        if row["task"] in newest:
            bump("dup_task")
            if row["ts"] <= newest[row["task"]]["ts"]:
                continue
        newest[row["task"]] = row
    guard = SuiteGuard(suites, embed, cosine)
    kept, seen_p, seen_a = [], set(), set()
    for tid, row in sorted(newest.items()):
        row["body"] = split_answer(row["answer"])[0].strip()
        if not row["body"]:
            bump("empty_after_footer")
            continue
        ph, ah = norm_hash(row["prompt"]), norm_hash(row["body"])
        if ph in seen_p or ah in seen_a:
            bump("dup_prompt_or_answer")
            continue
        seen_p.add(ph)
        seen_a.add(ah)
        kept.append(row)
    for row, reason in zip(kept, guard.reasons(kept)):
        row["contam"] = reason
    clean = []
    for row in kept:
        if row["contam"]:
            bump("decontam_dropped")
            continue
        if slop_check(row["body"], row["prompt"]):
            bump("slop_dropped")
            continue
        row["family"] = family(row["task"], row["category"])
        row["split"] = "val" if bucket("ft20-val", row["task"]) < VAL_PERCENT else "train"
        clean.append(row)
    train = [r for r in clean if r["split"] == "train"]
    ledger = sorted((r for r in train if r["family"] == "ledger"), key=lambda r: bucket("ft20-cap", r["task"]))
    other = len(train) - len(ledger)
    allowed = int(ledger_share * other / (1 - ledger_share)) if ledger_share < 1 else len(ledger)
    capped = {r["task"] for r in ledger[allowed:]}
    counts["ledger_capped"] = len(capped)
    sft = {"train": [r for r in train if r["task"] not in capped], "val": [r for r in clean if r["split"] == "val"]}
    # star/worked_examples.py refuses a project with more than 500 rows: gold rows first, then the newest others
    ordered = ([r for r in sft["train"] if r["origin"] == "gold"]
               + sorted((r for r in sft["train"] if r["origin"] != "gold"), key=lambda r: r["ts"], reverse=True))
    bank, counts["bank_refused_by_importer"] = bank_rows(ordered)
    # gold rows weigh more in training: repeated gold_weight times (bank and KTO keep one copy)
    sft["train"] = [r for r in sft["train"] for _ in range(gold_weight if r["origin"] == "gold" else 1)]
    contam_tasks = {r["task"] for r in kept if r["contam"]}
    solved = {r["task"]: r for r in clean}

    # failures -> KTO undesirable rows
    fails: dict[str, list[dict]] = {}
    seen_f = set()
    for path in failure_files:
        for row in read_jsonl(path):
            bump("failure_rows_read")
            tid = str(row["task"])
            if tid in contam_tasks or tid not in solved:
                bump("failure_task_unsolved_or_contaminated")
                continue
            body = split_answer(row.get("answer") or "")[0].strip()
            if not body or norm_hash(body) in seen_f or norm_hash(body) in seen_a:
                bump("failure_empty_or_dup")
                continue
            seen_f.add(norm_hash(body))
            fails.setdefault(tid, []).append({"body": body, "reasons": row.get("reasons") or [],
                                              "ts": str(row.get("ts", ""))})
    kto = {"train": [], "val": []}
    for tid, row in solved.items():
        if tid in capped:
            continue
        split = row["split"]
        kto[split].append(kto_row(row, row["body"], True))
        for fail in sorted(fails.get(tid, []), key=lambda f: f["ts"], reverse=True)[:max_fail_per_task]:
            kto[split].append(kto_row(row, fail["body"], False, fail["reasons"]))
    counts["failure_rows_dropped_over_cap"] = sum(max(0, len(v) - max_fail_per_task) for v in fails.values())
    counts.update(sft_train=len(sft["train"]), sft_val=len(sft["val"]), bank=len(bank),
                  kto_train_desirable=sum(1 for r in kto["train"] if r["label"]),
                  kto_train_undesirable=sum(1 for r in kto["train"] if not r["label"]),
                  kto_val_desirable=sum(1 for r in kto["val"] if r["label"]),
                  kto_val_undesirable=sum(1 for r in kto["val"] if not r["label"]),
                  private_in_train=sum(1 for r in sft["train"] if r["private"]),
                  gold_in_train=sum(1 for r in sft["train"] if r["origin"] == "gold"))
    families: dict[str, int] = {}
    for r in sft["train"]:
        families[r["family"]] = families.get(r["family"], 0) + 1
    cosines = sorted(r.get("max_suite_cosine", 0.0) for r in clean)
    return {"sft": sft, "kto": kto, "bank": bank, "counts": counts,
            "families": dict(sorted(families.items(), key=lambda kv: -kv[1])),
            "contaminated": sorted({(r["task"], r["contam"]) for r in kept if r["contam"]}),
            "max_suite_cosine": {"p50": cosines[len(cosines) // 2], "p95": cosines[int(len(cosines) * 0.95)],
                                 "max": cosines[-1]} if cosines and embed else None,
            "suite_digest": guard.index["suite_digest"]}


def sft_row(row: dict) -> dict:
    return {"id": row["task"], "category": row["category"], "family": row["family"], "origin": row["origin"],
            "private": row["private"],
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": row["prompt"]},
                         {"role": "assistant", "content": row["body"]}]}


def kto_row(row: dict, body: str, label: bool, reasons=()) -> dict:
    return {"id": row["task"], "family": row["family"], "private": row["private"], "label": label,
            "reasons": list(reasons)[:3],
            "prompt": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": row["prompt"]}],
            "completion": [{"role": "assistant", "content": body}]}


def bank_row(row: dict) -> dict:
    """star/worked_examples.py import format (the exemplar bank the live app can retrieve from)."""
    group = re.sub(r"[^A-Za-z0-9_.:-]", "-", row["task"]).lstrip("-_.:")[:100]
    return {"id": "night-school-" + group, "group_id": group, "task_category": (row["category"] or "other")[:80],
            "instruction": row["prompt"], "response": row["body"],
            "evidence": ["night-school automated checks: " + ("gold bank verification" if row.get("origin") == "gold"
                                                             else "practice task checks passed")],
            "source": "night-school-verified", "reviewed": False, "rights_confirmed": False, "lessons_in_context": []}


def bank_rows(rows: list[dict]) -> tuple[list[dict], int]:
    """Bank rows the app's importer accepts (it rejects the whole file on one bad row), at most BANK_MAX."""
    from star.worked_examples import validate_row
    out, refused = [], 0
    for row in rows:
        candidate = bank_row(row)
        try:
            validate_row(candidate)
        except ValueError:
            refused += 1            # e.g. a request over the app's 1,500-character limit
            continue
        if len(out) < BANK_MAX:
            out.append(candidate)
    return out, refused


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--examples", type=Path, nargs="+", required=True)
    ap.add_argument("--failures", type=Path, nargs="*", default=[])
    ap.add_argument("--private-examples", type=Path, nargs="*", default=[])
    ap.add_argument("--gold", type=Path, nargs="*", default=[], help="licence-clean verified bank (export format)")
    ap.add_argument("--gold-weight", type=int, default=2)
    ap.add_argument("--suites", type=Path, default=ROOT / "evals" / "roblox")
    ap.add_argument("--embed-url", default="")
    ap.add_argument("--cosine", type=float, default=0.75)
    ap.add_argument("--ledger-share", type=float, default=0.35)
    ap.add_argument("--max-fail-per-task", type=int, default=3)
    ap.add_argument("--public", action="store_true", help="drop private (Paintball/River) rows from every output")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    embed = http_embedder(args.embed_url) if args.embed_url else None
    result = build(args.examples, args.failures, args.private_examples, args.suites, embed=embed,
                   cosine=args.cosine, public=args.public, ledger_share=args.ledger_share,
                   max_fail_per_task=args.max_fail_per_task, gold_files=args.gold, gold_weight=args.gold_weight)
    for kind in ("sft", "kto"):         # sft/ is train_qlora.py's --data layout (train.jsonl, val.jsonl)
        (args.out / kind).mkdir(parents=True, exist_ok=True)
    for split in ("train", "val"):
        write_jsonl(args.out / "sft" / f"{split}.jsonl", [sft_row(r) for r in result["sft"][split]])
        write_jsonl(args.out / "kto" / f"{split}.jsonl", result["kto"][split])
    write_jsonl(args.out / "bank.jsonl", result["bank"])
    manifest = {k: result[k] for k in ("counts", "families", "contaminated", "max_suite_cosine", "suite_digest")}
    manifest.update(system_prompt=SYSTEM, public=args.public, embed=bool(embed), cosine=args.cosine,
                    sources={str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in [*args.examples, *args.failures, *args.private_examples, *args.gold]})
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps(result["counts"]))
    print(json.dumps(result["families"]))


if __name__ == "__main__":
    main()
