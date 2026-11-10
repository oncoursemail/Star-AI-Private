"""Opt-in skill-pack routing by embedding similarity (setting `skill_pack_embeddings`).

The keyword router (`star.skill_packs.select`) needs the prompt to name a pack's topic in its trigger words. When
it finds nothing, this router embeds the prompt with STAR's own embedding model (star-embed-ft1 on STAR Server) and
picks the pack whose name and description are closest, above a similarity floor. The same context rules apply (a
Roblox, Godot or named-engine prompt, only enabled packs), so unrelated prompts stay unchanged. Pack vectors are
cached by model alias, pack text and a live canary fingerprint of the embedding space. A changed model behind the
same alias invalidates the cache; malformed vectors fall back to the keyword path.

Why keyword first: on the 197 held-out routing cases of the pack tests the embedding router alone was right 171
times at this floor and the keyword router 197; on 36 requests that describe a topic without its trigger words the
keyword router was right 16 times and keyword-then-embedding 25 (benchmarks/skill_pack_routing.py). MIN_SIMILARITY
was set before that measurement and not tuned on it.
Idea from jcode's embedding-matched skills (github.com/1jehuang/jcode, MIT); no code was copied.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
from pathlib import Path

from . import skill_packs
from .skill_packs import ENGINE_CONTEXTS, GODOT_PACKS, MAX_PACKS_PER_TURN, Pack

EMBED_MODEL = "star-embed-ft1"
QUERY_PREFIX = "task: search result | query: "      # EmbeddingGemma's retrieval-query prompt (as in starkb)
CACHE_FILE = "skill_pack_embeddings.json"
MIN_SIMILARITY = 0.45
QUERY_TIMEOUT = 3.0          # seconds for query + two tiny canary vectors
PACKS_TIMEOUT = 15.0         # seconds for the missing pack-document batch
MAX_QUERY_CHARS = 2000
CACHE_SCHEMA_VERSION = 2
MAX_CACHE_ENTRIES = 256
MAX_CACHE_BYTES = 2_000_000
MAX_VECTOR_DIMENSIONS = 8192
# A tiny, fixed query-side canary set fingerprints the live embedding space.
# These are embedded in the SAME request as the user's query, so a model reload
# helps detect when a new query vector must not reuse old cached document vectors.
FINGERPRINT_PROBES = (
    "A Roblox server validates remote event arguments before updating player data.",
    "A conversational agent waits for a speaker to finish before replying.",
)


def pack_document(pack: Pack) -> str:
    """What a pack is embedded as: its name and description (EmbeddingGemma's document prompt)."""
    return f"title: {pack.name.replace('-', ' ')} | text: {pack.description}"


def candidates(prompt: str, allowed) -> list[Pack]:
    """Packs the context rules allow for this prompt (the keyword router's gates, without its trigger words)."""
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20_000:
        return []
    roblox = bool(skill_packs._ROBLOX_CONTEXT.search(prompt))
    godot = bool(skill_packs._GODOT_CONTEXT.search(prompt))
    engines = {name for name, context in ENGINE_CONTEXTS.items() if context.search(prompt)} & set(allowed)
    if engines:
        # A named engine outranks Roblox packs, as in the keyword router.
        return [p for p in skill_packs.available() if p.name in engines]
    return [p for p in skill_packs.available() if p.name in allowed and p.name not in ENGINE_CONTEXTS
            and ((p.name in GODOT_PACKS and godot and not roblox) or (p.name not in GODOT_PACKS and roblox and not godot))]


def _cosine(a, b) -> float:
    if not a or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def _fingerprint(vectors: list[list[float]]) -> str:
    """Stable, privacy-safe canary digest for the embedding space actually answering now."""
    payload = {
        "schema": CACHE_SCHEMA_VERSION,
        "model": EMBED_MODEL,
        "probes": [[round(value, 5) for value in vector] for vector in vectors],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _key(document: str, fingerprint: str) -> str:
    material = f"{CACHE_SCHEMA_VERSION}\n{EMBED_MODEL}\n{fingerprint}\n{document}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _read_cache(path: Path | None) -> dict:
    if path is None:
        return {}
    try:
        if path.stat().st_size > MAX_CACHE_BYTES:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        valid = {}
        for key, vector in list(data.items())[-MAX_CACHE_ENTRIES:]:
            if (type(key) is not str or len(key) != 64 or type(vector) is not list
                    or not 1 <= len(vector) <= MAX_VECTOR_DIMENSIONS):
                continue
            try:
                if all(type(value) in (int, float) and math.isfinite(float(value)) for value in vector):
                    valid[key] = vector
            except (OverflowError, ValueError):
                continue
        return valid
    except (OSError, ValueError):
        return {}


def _write_cache(path: Path | None, cache: dict) -> None:
    if path is None:
        return
    try:
        from .atomic_io import atomic_write_text
        bounded = dict(list(cache.items())[-MAX_CACHE_ENTRIES:])
        atomic_write_text(path, json.dumps(bounded, separators=(",", ":"), allow_nan=False))
    except (OSError, TypeError, ValueError):
        pass       # a cache that cannot be written only costs the vectors again next time


def _vectors(reply, count: int) -> list[list[float]]:
    if not isinstance(reply, list) or len(reply) != count:
        raise ValueError("unexpected embedding reply")
    out: list[list[float]] = []
    dimension = None
    for vector in reply:
        if (type(vector) is not list or not vector
                or len(vector) > MAX_VECTOR_DIMENSIONS):
            raise ValueError("unexpected embedding vector")
        values = []
        for value in vector:
            if type(value) not in (int, float):
                raise ValueError("embedding values must be finite numbers")
            try:
                number = float(value)
            except (OverflowError, ValueError) as exc:
                raise ValueError("embedding values must be finite numbers") from exc
            if not math.isfinite(number):
                raise ValueError("embedding values must be finite numbers")
            values.append(number)
        if dimension is None:
            dimension = len(values)
        elif len(values) != dimension:
            raise ValueError("embedding vectors have inconsistent dimensions")
        out.append(values)
    return out


def _cached_vector(value: object, dimension: int) -> list[float] | None:
    if type(value) is not list or len(value) != dimension:
        return None
    try:
        if any(type(item) not in (int, float) or not math.isfinite(float(item)) for item in value):
            return None
        return [float(item) for item in value]
    except (OverflowError, ValueError):
        return None


async def rank(prompt: str, embed, *, allowed, cache_dir: Path | None = None) -> list[tuple[float, Pack]]:
    """(similarity, pack) for every candidate, best first.

    The query and two fixed canaries are embedded together. Their rounded,
    privacy-safe digest namespaces cached document vectors, so replacing model
    weights behind the same alias cannot silently mix embedding spaces. On a
    cache miss, a second canary pass verifies the model did not change while
    document vectors were being refreshed.
    """
    packs = candidates(prompt, allowed)
    if not packs:
        return []
    query_inputs = [
        QUERY_PREFIX + prompt[:MAX_QUERY_CHARS],
        *(QUERY_PREFIX + probe for probe in FINGERPRINT_PROBES),
    ]
    query_vectors = _vectors(
        await asyncio.wait_for(embed(query_inputs), QUERY_TIMEOUT), len(query_inputs)
    )
    query, fingerprint_vectors = query_vectors[0], query_vectors[1:]
    fingerprint = _fingerprint(fingerprint_vectors)
    path = Path(cache_dir) / CACHE_FILE if cache_dir is not None else None
    cache = _read_cache(path)
    documents = {p.name: pack_document(p) for p in packs}
    keys = {name: _key(document, fingerprint) for name, document in documents.items()}
    cached: dict[str, list[float]] = {}
    missing = []
    for pack in packs:
        vector = _cached_vector(cache.get(keys[pack.name]), len(query))
        if vector is None:
            missing.append(pack.name)
        else:
            cached[pack.name] = vector
    if missing:
        texts = [documents[name] for name in missing]
        fresh = _vectors(await asyncio.wait_for(embed(texts), PACKS_TIMEOUT), len(texts))
        if any(len(vector) != len(query) for vector in fresh):
            raise ValueError("query and document embedding dimensions differ")
        confirmation = _vectors(
            await asyncio.wait_for(
                embed([QUERY_PREFIX + probe for probe in FINGERPRINT_PROBES]), QUERY_TIMEOUT
            ),
            len(FINGERPRINT_PROBES),
        )
        if _fingerprint(confirmation) != fingerprint:
            raise RuntimeError("embedding model changed during skill-pack cache refresh")
        cache.update({keys[name]: vector for name, vector in zip(missing, fresh)})
        cached.update({name: vector for name, vector in zip(missing, fresh)})
        _write_cache(path, cache)
    scored = [(_cosine(query, cached[p.name]), p) for p in packs]
    return sorted(scored, key=lambda item: -item[0])


async def select(prompt: str, embed, *, enabled=None, limit: int = MAX_PACKS_PER_TURN, home=None,
                 min_similarity: float = MIN_SIMILARITY, on_fallback=None) -> list[Pack]:
    """The keyword router's packs; when it has none, the closest packs by embedding similarity."""
    allowed = skill_packs.enabled_names(home=home) if enabled is None else frozenset(enabled)
    if not allowed:
        return []
    keyword = skill_packs.select(prompt, enabled=allowed, limit=limit, home=home)
    if keyword:
        return keyword
    try:
        ranked = await rank(prompt, embed, allowed=allowed, cache_dir=home)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        if on_fallback is not None:
            on_fallback(type(exc).__name__)
        return []           # the keyword router already said: no pack
    return [pack for score, pack in ranked if score >= min_similarity][:max(0, limit)]