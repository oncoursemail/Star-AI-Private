#!/usr/bin/env python3
"""Build a llama.cpp static n-gram lookup cache (`--spec-type ngram-cache --lookup-cache-static FILE`) from STAR's
verified Luau: worked examples, eval reference answers, Roblox creator-docs code samples and the Roblox API dump.

What llama-lookup-create writes, without building it: every 2-token n-gram of the corpus (LLAMA_NGRAM_STATIC = 2)
with the counts of the token that followed it, saved as common/ngram-cache.cpp common_ngram_cache_save does:
per n-gram 4 x int32 tokens (unused = -1), int32 number of entries, then (int32 token, int32 count) pairs.
Tokens come from the model's own tokenizer through a llama-server /tokenize endpoint (same vocabulary).

  python3 build_cache.py --server http://127.0.0.1:8099 --out luau-static.lcs \
      --jsonl /opt/star/learning/data/examples.jsonl --jsonl /opt/star/learning/outbox/worked-examples.jsonl \
      --reference-dir evals/roblox/reference --docs /opt/star/knowledge/sources/creator-docs \
      --api data/roblox_api/roblox_api.json --holdout holdout.json

`--holdout` (JSON list of {"id", "prompt"} and optional "answer") keeps the measured prompts out of the corpus: their
reference answers and any example whose prompt shares a 60-character run with them are dropped. With answers given,
it also prints the share of their tokens the static cache alone would draft correctly (a proxy for acceptance).
Stdlib only; runs on the brain.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import struct
import urllib.request

NGRAM_MAX = 4          # LLAMA_NGRAM_MAX
NGRAM_STATIC = 2       # LLAMA_NGRAM_STATIC
TOKEN_NULL = -1        # LLAMA_TOKEN_NULL
MIN_SAMPLES, MIN_PERCENT = 2, 50   # draft_min_sample_size_lax / draft_min_percent_lax for 2-grams
CODE = re.compile(r"^```[ \t]*(?:lua|luau)\b[^\n]*\n(.*?)^```", re.M | re.S | re.I)


def code_blocks(text: str) -> list[str]:
    return [m.group(1) for m in CODE.finditer(text)]


def api_lines(dump: dict) -> list[str]:
    lines = []
    for cls in dump.get("Classes", []):
        name = cls["Name"]
        if "Service" in cls.get("Tags", []) or name.endswith("Service"):
            lines.append(f'local {name} = game:GetService("{name}")')
        for member in cls.get("Members", []):
            kind, field = member.get("MemberType"), member.get("Name")
            if kind == "Function":
                params = ", ".join(p.get("Name", "") for p in member.get("Parameters", []))
                lines.append(f"{name}:{field}({params})")
            elif kind == "Event":
                lines.append(f"{name}.{field}:Connect(function()")
            elif kind == "Property":
                lines.append(f"{name}.{field}")
    for enum in dump.get("Enums", []):
        for item in enum.get("Items", []):
            lines.append(f"Enum.{enum['Name']}.{item['Name']}")
    return lines


def overlaps(prompt: str, holdout: list[str], run: int = 60) -> bool:
    for other in holdout:
        for start in range(0, max(1, len(other) - run + 1), run // 2):
            piece = other[start:start + run]
            if len(piece) == run and piece in prompt:
                return True
    return False


def collect(args, holdout: list[dict]) -> tuple[list[str], Counter]:
    held_prompts = [h["prompt"] for h in holdout]
    held_ids = {h["id"] for h in holdout}
    docs, kinds, seen = [], Counter(), set()

    def add(kind: str, text: str) -> None:
        text = text.strip("\n")
        if len(text) >= 40 and text not in seen:
            seen.add(text)
            docs.append(text)
            kinds[kind] += 1

    for path in args.jsonl:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            prompt = row.get("prompt") or row.get("instruction") or ""
            if overlaps(prompt, held_prompts):
                kinds["dropped_overlap"] += 1
                continue
            for block in code_blocks(row.get("answer") or row.get("response") or ""):
                add("examples", block)
    if args.reference_dir:
        for file in sorted(Path(args.reference_dir).glob("*.md")):
            task = file.name.split(".")[0]
            if ".bad." in file.name or task in held_ids:
                continue
            for block in code_blocks(file.read_text(encoding="utf-8")):
                add("references", block)
    if args.docs:
        for file in sorted(Path(args.docs).rglob("*.md")):
            for block in code_blocks(file.read_text(encoding="utf-8", errors="replace")):
                add("creator_docs", block)
    if args.api:
        add("api_dump", "\n".join(api_lines(json.loads(Path(args.api).read_text(encoding="utf-8")))))
    return docs, kinds


def tokenize(server: str, text: str) -> list[int]:
    body = json.dumps({"content": text, "add_special": False}).encode("utf-8")
    request = urllib.request.Request(server + "/tokenize", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read())["tokens"]


def count(sequences: list[list[int]]) -> dict[tuple[int, int], Counter]:
    cache: dict[tuple[int, int], Counter] = defaultdict(Counter)
    for tokens in sequences:
        for i in range(NGRAM_STATIC, len(tokens)):
            cache[(tokens[i - 2], tokens[i - 1])][tokens[i]] += 1
    return cache


def save(cache: dict[tuple[int, int], Counter], path: Path) -> None:
    with path.open("wb") as out:
        for (a, b), part in cache.items():
            out.write(struct.pack("<4i", a, b, TOKEN_NULL, TOKEN_NULL))
            out.write(struct.pack("<i", len(part)))
            for token, n in part.items():
                out.write(struct.pack("<ii", token, n))


def load(path: Path) -> dict[tuple[int, int], Counter]:
    data, cache, at = path.read_bytes(), {}, 0
    while at < len(data):
        a, b, c, d = struct.unpack_from("<4i", data, at)
        (n,) = struct.unpack_from("<i", data, at + 16)
        at += 20
        part = Counter()
        for _ in range(n):
            token, k = struct.unpack_from("<ii", data, at)
            part[token] = k
            at += 8
        cache[(a, b)] = part
    return cache


def static_draft(part: Counter) -> int | None:
    """common/ngram-cache.cpp try_draft(nc_static, ngram) for a 2-gram."""
    if not part:
        return None
    token, best = part.most_common(1)[0]
    total = sum(part.values())
    if total < MIN_SAMPLES or 100 * best < MIN_PERCENT * total:
        return None
    return token


def proxy(cache, sequences: list[list[int]]) -> dict:
    drafted = right = total = 0
    for tokens in sequences:
        for i in range(NGRAM_STATIC, len(tokens)):
            total += 1
            guess = static_draft(cache.get((tokens[i - 2], tokens[i - 1]), Counter()))
            if guess is not None:
                drafted += 1
                right += guess == tokens[i]
    return {"tokens": total, "drafted": drafted, "right": right,
            "draft_share": round(drafted / total, 3) if total else None,
            "right_of_drafted": round(right / drafted, 3) if drafted else None}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--jsonl", action="append", default=[])
    parser.add_argument("--reference-dir", default="")
    parser.add_argument("--docs", default="")
    parser.add_argument("--api", default="")
    parser.add_argument("--holdout", default="")
    args = parser.parse_args(argv)
    holdout = json.loads(Path(args.holdout).read_text(encoding="utf-8")) if args.holdout else []
    docs, kinds = collect(args, holdout)
    sequences = [tokenize(args.server, doc) for doc in docs]
    cache = count(sequences)
    save(cache, args.out)
    assert load(args.out) == cache, "the written file does not read back"
    report = {"documents": dict(kinds), "corpus_tokens": sum(map(len, sequences)), "ngrams": len(cache),
              "bytes": args.out.stat().st_size,
              "self_proxy": proxy(cache, sequences)}
    answers = [h["answer"] for h in holdout if h.get("answer")]
    if answers:
        report["holdout_proxy"] = proxy(cache, [tokenize(args.server, a) for a in answers])
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
