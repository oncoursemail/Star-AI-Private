"""Gold exemplar bank: verified, licence-recorded Roblox/Luau task pairs for retrieval (setting `gold_examples_enabled`).

The bank (`data/gold_bank/bank.jsonl`) is built by `star.gold_bank_verify` from the authoring files under
`data/gold_bank/src/`: only items that passed every check (Luau compile + strict analysis, STAR's linter, the API dump,
the slop checker, a runtime test in the Luau VM where the item has one, and the leakage check against the evaluation
suites) are written there, each with its source, SPDX licence id and commit (data/gold_bank/LICENSES.md).

Retrieval: the closest items by STAR's embedding model (star-embed-ft1, the skill-pack router's model), above a
similarity floor (0.50, set before any eval run: on five hand-written non-eval queries a paraphrase of an item scored
0.72, a same-topic request 0.54, unrelated requests 0.02-0.23); when embeddings are unavailable, the worked-example BM25 ranking (star.worked_examples.rank).
Read-only, no network of its own: the caller passes the async `embed(texts)` it already has.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re

from . import worked_examples

BANK = Path(__file__).resolve().parent.parent / "data" / "gold_bank" / "bank.jsonl"
HEADING = "VERIFIED GOLD EXAMPLES (reference patterns with recorded licences; the user's request comes first)"
EMBED_MODEL = "star-embed-ft1"
QUERY_PREFIX = "task: search result | query: "
MIN_SIMILARITY = 0.50
MAX_EXAMPLES = 3
MAX_EXAMPLE_CHARS = 2400
MAX_BLOCK_CHARS = 5200
QUERY_TIMEOUT = 3.0
BANK_TIMEOUT = 30.0
MAX_ROWS = 2000
CATEGORIES = (
    "luau-typing", "luau-syntax", "remote-security", "datastore-safety", "ui-layout", "ui-overflow", "ui-interaction",
    "ui-text", "ui-style", "server-authoritative-inventory", "economy-simulation", "npc-pathing", "gameplay-systems",
    "animation", "rig-prop-alignment", "tool-attachment", "vfx-particles", "vfx-beam-trail", "building-layout",
    "building-lighting", "physics", "combat-hitbox", "round-systems", "world-raycast", "world-collectionservice",
    "messaging", "performance", "performance-streaming", "engineering-algorithm", "engineering-debugging",
    "engineering-test-first", "docs-question",
)
_ID = re.compile(r"gb-[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_SPDX = re.compile(r"[A-Za-z0-9.+-]{2,64}\Z")


@dataclass(frozen=True)
class GoldExample:
    id: str
    category: str
    topics: tuple[str, ...]
    request: str
    answer: str
    spdx: str
    source_url: str


def validate_row(row: object) -> GoldExample:
    """A bank row as the verifier writes it; anything else is refused."""
    if type(row) is not dict:
        raise ValueError("gold row must be an object")
    ident, category, request, answer = row.get("id"), row.get("category"), row.get("request"), row.get("answer")
    source, topics = row.get("source"), row.get("topics")
    if type(ident) is not str or not _ID.fullmatch(ident) or len(ident) > 64:
        raise ValueError("invalid gold id")
    if category not in CATEGORIES:
        raise ValueError(f"{ident}: unknown category")
    if type(request) is not str or not request.strip() or len(request) > 2000:
        raise ValueError(f"{ident}: invalid request")
    if type(answer) is not str or not answer.strip() or len(answer) > 16000:
        raise ValueError(f"{ident}: invalid answer")
    if type(topics) is not list or not all(type(t) is str and 0 < len(t) <= 40 for t in topics) or len(topics) > 12:
        raise ValueError(f"{ident}: invalid topics")
    if (type(source) is not dict or source.get("kind") not in ("original", "adapted", "verbatim")
            or type(source.get("spdx")) is not str or not _SPDX.fullmatch(source["spdx"])
            or type(source.get("url", "")) is not str):
        raise ValueError(f"{ident}: invalid source record")
    if source["kind"] != "original" and not (source.get("url") and re.fullmatch(r"[0-9a-f]{40}", str(source.get("commit")))):
        raise ValueError(f"{ident}: third-party item without url and commit")
    if row.get("verified") is not True:
        raise ValueError(f"{ident}: not verified")
    return GoldExample(ident, category, tuple(topics), request, answer, source["spdx"], source.get("url", ""))


def parse_bank(raw: bytes) -> list[GoldExample]:
    """Validate the whole file; duplicate ids or a bad row refuse the file."""
    lines = [line for line in raw.decode("utf-8").splitlines() if line.strip()]
    if len(lines) > MAX_ROWS:
        raise ValueError("gold bank has too many rows")
    found, seen = [], set()
    for line in lines:
        item = validate_row(json.loads(line))
        if item.id in seen:
            raise ValueError(f"duplicate gold id {item.id}")
        seen.add(item.id)
        found.append(item)
    return found


_LOADED: dict[tuple[str, int, int], list[GoldExample]] = {}


def load(path: Path | None = None) -> list[GoldExample]:
    """The bank, cached per file version; [] when the file is missing."""
    path = Path(BANK if path is None else path)
    try:
        stat = path.stat()
    except OSError:
        return []
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key not in _LOADED:
        _LOADED.clear()
        _LOADED[key] = parse_bank(path.read_bytes())
    return _LOADED[key]


def document(item: GoldExample) -> str:
    """What an item is embedded as (EmbeddingGemma's document prompt): its request and topics."""
    return f"title: {', '.join(item.topics)} | text: {item.request}"


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def _vectors(reply, count: int) -> list[list[float]]:
    if not isinstance(reply, list) or len(reply) != count:
        raise ValueError("unexpected embedding reply")
    out = []
    for vector in reply:
        if not isinstance(vector, list) or not vector or not all(isinstance(x, (int, float)) for x in vector):
            raise ValueError("unexpected embedding vector")
        out.append([float(x) for x in vector])
    return out


# Item vectors per (model, bank content): computed once per process (the bank is a few hundred rows).
_VECTORS: dict[str, list[list[float]]] = {}


def _bank_key(items: list[GoldExample]) -> str:
    digest = hashlib.sha256(EMBED_MODEL.encode())
    for item in items:
        digest.update(document(item).encode("utf-8"))
    return digest.hexdigest()


async def rank_by_embedding(prompt: str, items: list[GoldExample], embed) -> list[tuple[float, GoldExample]]:
    """(similarity, item) best first. Raises on any embedding problem (the caller falls back to BM25)."""
    key = _bank_key(items)
    vectors = _VECTORS.get(key)
    if vectors is None:
        texts = [document(item) for item in items]
        vectors = []
        for start in range(0, len(texts), 64):
            batch = texts[start:start + 64]
            vectors.extend(_vectors(await asyncio.wait_for(embed(batch), BANK_TIMEOUT), len(batch)))
        _VECTORS.clear()
        _VECTORS[key] = vectors
    query = _vectors(await asyncio.wait_for(embed([QUERY_PREFIX + prompt[:2000]]), QUERY_TIMEOUT), 1)[0]
    scored = [(_cosine(query, vector), item) for vector, item in zip(vectors, items)]
    return sorted(scored, key=lambda pair: (-pair[0], pair[1].id))


def rank_by_words(prompt: str, items: list[GoldExample]) -> list[tuple[float, GoldExample]]:
    """The worked-example BM25 ranking (two distinctive shared words and 40 % coverage required); at most two."""
    by_id = {item.id: item for item in items}
    rows = [worked_examples.Example(item.id, item.id, item.category, item.request, item.answer) for item in items]
    return [(score, by_id[row.id]) for row, score in worked_examples.rank(prompt, rows, limit=2)]


def render(chosen: list[GoldExample], *, max_chars: int = MAX_BLOCK_CHARS) -> tuple[str, list[GoldExample]]:
    parts, used = [], []
    for item in chosen:
        text = (f"[gold example {len(used) + 1}: {item.category}; licence {item.spdx}"
                + (f"; source {item.source_url}" if item.source_url else "") + "]\n"
                f"Request: {item.request}\nAnswer:\n{item.answer}\n[end gold example]\n")
        if len(text) > MAX_EXAMPLE_CHARS or len(text) + sum(map(len, parts)) > max_chars:
            continue
        parts.append(text)
        used.append(item)
        if len(used) >= MAX_EXAMPLES:
            break
    return "".join(parts), used


async def select(prompt: str, embed=None, *, path: Path | None = None, max_chars: int = MAX_BLOCK_CHARS,
                 min_similarity: float = MIN_SIMILARITY, on_fallback=None) -> tuple[str, list[GoldExample]]:
    """(block, items) for this prompt; ('', []) when nothing is close enough or the bank is missing."""
    if type(prompt) is not str or not prompt.strip() or max_chars < 300:
        return "", []
    try:
        items = load(BANK if path is None else path)
    except (OSError, ValueError):
        items = []
    if not items:
        return "", []
    ranked: list[tuple[float, GoldExample]] = []
    if embed is not None:
        try:
            scored = await rank_by_embedding(prompt, items, embed)
            ranked = [pair for pair in scored if pair[0] >= min_similarity]
            embed = "used"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if on_fallback is not None:
                on_fallback(type(exc).__name__)
            embed = None
    if embed is None:
        ranked = rank_by_words(prompt, items)
    return render([item for _, item in ranked[:MAX_EXAMPLES * 2]], max_chars=max_chars)
