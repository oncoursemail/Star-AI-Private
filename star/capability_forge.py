"""STAR Capability Forge: fast, evidence-aware routing across verified capabilities.

This module does not execute APIs, install MCP servers, or grant permissions.  It is the
selection/memory layer between discovery and a separately authorized executor:

    catalog/spec metadata -> indexed options -> evidence-aware tournament -> adapter manifest

The hot path is deliberately deterministic and model-free.  A verified healthy winner can be
reused from a short cache; failures open a local circuit breaker so STAR stops wasting time on a
provider that is currently unhealthy.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time
from typing import Iterable, Literal
from urllib.parse import urlsplit

from .api_intelligence import ApiCandidate, OpenApiSummary


CapabilityKind = Literal["rest", "mcp", "local"]
_TOKEN = re.compile(r"[a-z0-9][a-z0-9+._/-]*", re.IGNORECASE)
_READ_HTTP = ("GET ", "HEAD ", "OPTIONS ")
_WRITE_HTTP = ("POST ", "PUT ", "PATCH ", "DELETE ")
MAX_INDEX_OPTIONS = 50_000
MAX_QUERY_CACHE = 256


@dataclass(frozen=True)
class CapabilityOption:
    key: str
    kind: CapabilityKind
    name: str
    summary: str
    source: str
    endpoint: str = ""
    auth: str = "unknown"
    operations: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    risk_flags: tuple[str, ...] = ()
    spec_fingerprint: str = ""
    verified_at: float | None = None
    official: bool = False

    @property
    def verified(self) -> bool:
        return bool(self.spec_fingerprint and self.verified_at is not None)


@dataclass(frozen=True)
class CapabilityConstraints:
    read_only: bool = True
    require_https: bool = True
    prefer_no_auth: bool = True
    prefer_official: bool = True
    max_results: int = 5
    cache_ttl_seconds: int = 600

    def normalized(self) -> "CapabilityConstraints":
        return CapabilityConstraints(
            read_only=bool(self.read_only),
            require_https=bool(self.require_https),
            prefer_no_auth=bool(self.prefer_no_auth),
            prefer_official=bool(self.prefer_official),
            max_results=max(1, min(int(self.max_results), 20)),
            cache_ttl_seconds=max(0, min(int(self.cache_ttl_seconds), 86_400)),
        )


@dataclass(frozen=True)
class HealthEvidence:
    successes: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    latency_ema_ms: float | None = None
    last_success_at: float | None = None
    last_failure_at: float | None = None
    circuit_open_until: float | None = None


@dataclass(frozen=True)
class ScoredCapability:
    option: CapabilityOption
    score: float
    lexical_score: float
    evidence_score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class SelectionResult:
    winner: ScoredCapability | None
    fallbacks: tuple[ScoredCapability, ...]
    from_cache: bool
    cache_key: str
    catalog_fingerprint: str
    candidates_considered: int


def _tokens(text: str) -> tuple[str, ...]:
    """Keep whole identifiers *and* word components for dotted/slashed MCP/API names.

    For example, `example/weather-forecast` is searchable as `weather`,
    `forecast`, and the original identifier.  Duplicates are removed to avoid
    overweighting punctuation-heavy provider names.
    """
    found: dict[str, None] = {}
    for match in _TOKEN.finditer(text):
        original = match.group(0).lower()
        if len(original) > 1:
            found[original] = None
        for part in re.split(r"[^a-z0-9]+", original):
            if len(part) > 1:
                found[part] = None
    return tuple(found)


def _safe_https_endpoint(url: str) -> bool:
    if not url:
        return True
    try:
        parsed = urlsplit(url)
        return bool(parsed.scheme == "https" and parsed.hostname and parsed.username is None and parsed.password is None)
    except ValueError:
        return False


def _auth_friction(auth: str) -> int:
    value = (auth or "unknown").strip().lower()
    if value in {"no", "none", "null", ""}:
        return 0
    if "apikey" in value or "api key" in value or "bearer" in value:
        return 1
    if "oauth" in value:
        return 2
    return 1


def _read_operations(option: CapabilityOption) -> tuple[str, ...]:
    if option.kind != "rest":
        return option.operations
    return tuple(op for op in option.operations if op.upper().startswith(_READ_HTTP))


def _write_operations(option: CapabilityOption) -> tuple[str, ...]:
    if option.kind != "rest":
        return ()
    return tuple(op for op in option.operations if op.upper().startswith(_WRITE_HTTP))


def capability_set_fingerprint(options: Iterable[CapabilityOption]) -> str:
    """Identity of the routable option set, used to invalidate stale winner caches."""
    canonical = []
    for option in sorted(options, key=lambda item: item.key):
        canonical.append({
            "key": option.key,
            "kind": option.kind,
            "endpoint": option.endpoint,
            "spec": option.spec_fingerprint,
            "operations": option.operations,
            "tags": option.tags,
            "official": option.official,
        })
    body = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def rest_option(
    candidate: ApiCandidate,
    *,
    openapi: OpenApiSummary | None = None,
    spec_fingerprint: str = "",
    verified_at: float | None = None,
    official: bool = False,
) -> CapabilityOption:
    """Convert verified REST metadata into the common capability shape."""
    endpoint = candidate.url
    operations: tuple[str, ...] = ()
    risk = list(candidate.warnings)
    if openapi is not None:
        operations = openapi.operations
        risk.extend(openapi.warnings)
        endpoint = next((server for server in openapi.servers if _safe_https_endpoint(server)),
                        openapi.servers[0] if openapi.servers else candidate.url)
    host = ""
    try:
        host = (urlsplit(endpoint).hostname or "").lower()
    except ValueError:
        pass
    key_material = f"rest\0{candidate.name}\0{host}\0{candidate.source}"
    key = "rest:" + hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:24]
    return CapabilityOption(
        key=key,
        kind="rest",
        name=candidate.name,
        summary=" ".join(part for part in (candidate.category, candidate.description) if part).strip(),
        source=candidate.source,
        endpoint=endpoint,
        auth=candidate.auth,
        operations=operations,
        tags=(candidate.category,) if candidate.category else (),
        risk_flags=tuple(dict.fromkeys(risk)),
        spec_fingerprint=spec_fingerprint,
        verified_at=verified_at,
        official=official,
    )


def mcp_option(
    *,
    name: str,
    description: str,
    source: str,
    repository_url: str = "",
    tools: Iterable[str] = (),
    version_fingerprint: str = "",
    verified_at: float | None = None,
    official: bool = False,
) -> CapabilityOption:
    """Create a discovery option for an MCP server without installing or connecting to it."""
    clean_name = str(name).strip()[:240]
    if not clean_name:
        raise ValueError("MCP capability needs a name")
    clean_tools = tuple(dict.fromkeys(str(tool).strip()[:160] for tool in tools if str(tool).strip()))
    key = "mcp:" + hashlib.sha256(clean_name.encode("utf-8")).hexdigest()[:24]
    return CapabilityOption(
        key=key,
        kind="mcp",
        name=clean_name,
        summary=str(description).strip()[:1000],
        source=source,
        endpoint=repository_url,
        auth="unknown",
        operations=clean_tools,
        tags=("mcp",),
        spec_fingerprint=version_fingerprint,
        verified_at=verified_at,
        official=official,
    )


class CapabilityIndex:
    """In-memory BM25-style inverted index with a small LRU query cache."""

    def __init__(self, options: Iterable[CapabilityOption]):
        deduped: dict[str, CapabilityOption] = {}
        for option in options:
            if not isinstance(option, CapabilityOption):
                raise TypeError("CapabilityIndex accepts CapabilityOption values")
            deduped[option.key] = option
            if len(deduped) > MAX_INDEX_OPTIONS:
                raise ValueError("Capability index exceeds the configured option limit")
        self.options = tuple(deduped.values())
        self.by_key = {option.key: option for option in self.options}
        self._weights: list[dict[str, float]] = []
        self._inverted: dict[str, set[int]] = {}
        self._doc_freq: dict[str, int] = {}
        self._cache: OrderedDict[tuple[str, int], tuple[tuple[int, float], ...]] = OrderedDict()

        for index, option in enumerate(self.options):
            weights: dict[str, float] = {}
            fields = (
                (option.name, 4.0),
                (option.summary, 1.0),
                (" ".join(option.operations), 1.7),
                (" ".join(option.tags), 3.0),
                (option.kind, 1.2),
            )
            for text, weight in fields:
                for token in _tokens(text):
                    weights[token] = max(weights.get(token, 0.0), weight)
            self._weights.append(weights)
            for token in weights:
                self._inverted.setdefault(token, set()).add(index)
        self._doc_freq = {token: len(indexes) for token, indexes in self._inverted.items()}

    def search(self, query: str, *, limit: int = 40) -> tuple[tuple[CapabilityOption, float], ...]:
        limit = max(1, min(int(limit), 200))
        normalized = " ".join(_tokens(query))
        if not normalized:
            return ()
        cache_key = (normalized, limit)
        cached = self._cache.get(cache_key)
        if cached is not None:
            self._cache.move_to_end(cache_key)
            return tuple((self.options[index], score) for index, score in cached)

        query_tokens = tuple(normalized.split())
        candidate_indexes: set[int] = set()
        for token in query_tokens:
            candidate_indexes.update(self._inverted.get(token, ()))
        if not candidate_indexes:
            return ()

        total = max(1, len(self.options))
        scored: list[tuple[int, float]] = []
        for index in candidate_indexes:
            weights = self._weights[index]
            score = 0.0
            matched = 0
            for token in query_tokens:
                weight = weights.get(token)
                if weight is None:
                    continue
                matched += 1
                df = self._doc_freq.get(token, 1)
                idf = math.log(1.0 + (total - df + 0.5) / (df + 0.5))
                score += idf * weight
            if matched:
                coverage = matched / len(query_tokens)
                score += coverage * 3.0
                if matched == len(query_tokens) and len(query_tokens) > 1:
                    score += 2.0
                option = self.options[index]
                phrase = " ".join(query_tokens)
                name_text = " ".join(_tokens(option.name))
                tag_text = " ".join(_tokens(" ".join(option.tags)))
                summary_text = " ".join(_tokens(option.summary))
                if phrase and phrase in name_text:
                    score += 5.0
                elif phrase and phrase in tag_text:
                    score += 4.0
                elif phrase and phrase in summary_text:
                    score += 2.0
                scored.append((index, score))
        scored.sort(key=lambda item: (-item[1], self.options[item[0]].name.lower(), self.options[item[0]].key))
        result = tuple(scored[:limit])
        self._cache[cache_key] = result
        self._cache.move_to_end(cache_key)
        while len(self._cache) > MAX_QUERY_CACHE:
            self._cache.popitem(last=False)
        return tuple((self.options[index], score) for index, score in result)


class CapabilityStore:
    """Small local health/selection memory. Stores public metadata and counters, never secrets."""

    def __init__(self, path: Path | str):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS capability_health (
            capability_key TEXT PRIMARY KEY,
            successes INTEGER NOT NULL DEFAULT 0,
            failures INTEGER NOT NULL DEFAULT 0,
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            latency_ema_ms REAL,
            last_success_at REAL,
            last_failure_at REAL,
            circuit_open_until REAL
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS capability_selection_cache (
            cache_key TEXT PRIMARY KEY,
            winner_key TEXT NOT NULL,
            catalog_fingerprint TEXT NOT NULL,
            expires_at REAL NOT NULL
        )""")
        self.db.commit()

    def health(self, key: str) -> HealthEvidence:
        row = self.db.execute(
            "SELECT * FROM capability_health WHERE capability_key=?", (key,)
        ).fetchone()
        if row is None:
            return HealthEvidence()
        return HealthEvidence(
            successes=row["successes"],
            failures=row["failures"],
            consecutive_failures=row["consecutive_failures"],
            latency_ema_ms=row["latency_ema_ms"],
            last_success_at=row["last_success_at"],
            last_failure_at=row["last_failure_at"],
            circuit_open_until=row["circuit_open_until"],
        )

    def record_result(
        self,
        key: str,
        *,
        success: bool,
        latency_ms: float | None = None,
        now: float | None = None,
        circuit_seconds: int = 300,
    ) -> HealthEvidence:
        if not isinstance(key, str) or not 3 <= len(key) <= 200:
            raise ValueError("Invalid capability key")
        if latency_ms is not None and (not math.isfinite(latency_ms) or latency_ms < 0 or latency_ms > 3_600_000):
            raise ValueError("Invalid capability latency")
        now = float(time.time() if now is None else now)
        old = self.health(key)
        successes = old.successes + (1 if success else 0)
        failures = old.failures + (0 if success else 1)
        consecutive = 0 if success else old.consecutive_failures + 1
        latency = old.latency_ema_ms
        if latency_ms is not None:
            latency = float(latency_ms) if latency is None else latency * 0.75 + float(latency_ms) * 0.25
        open_until = None
        if not success and consecutive >= 3:
            open_until = now + max(60, min(int(circuit_seconds), 3600))
        self.db.execute(
            """INSERT INTO capability_health(
                capability_key,successes,failures,consecutive_failures,latency_ema_ms,
                last_success_at,last_failure_at,circuit_open_until
            ) VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(capability_key) DO UPDATE SET
                successes=excluded.successes, failures=excluded.failures,
                consecutive_failures=excluded.consecutive_failures,
                latency_ema_ms=excluded.latency_ema_ms,
                last_success_at=excluded.last_success_at,
                last_failure_at=excluded.last_failure_at,
                circuit_open_until=excluded.circuit_open_until""",
            (
                key, successes, failures, consecutive, latency,
                now if success else old.last_success_at,
                old.last_failure_at if success else now,
                open_until,
            ),
        )
        # A failed call must invalidate hot winner choices immediately.  Otherwise
        # STAR could keep choosing a failing provider until TTL expiry even when
        # a healthier fallback was already known.
        if not success:
            self.db.execute(
                "DELETE FROM capability_selection_cache WHERE winner_key=?", (key,)
            )
        self.db.commit()
        return self.health(key)

    def remember_selection(
        self,
        cache_key: str,
        *,
        winner_key: str,
        catalog_fingerprint: str,
        expires_at: float,
    ) -> None:
        self.db.execute(
            """INSERT INTO capability_selection_cache(cache_key,winner_key,catalog_fingerprint,expires_at)
               VALUES(?,?,?,?)
               ON CONFLICT(cache_key) DO UPDATE SET winner_key=excluded.winner_key,
                 catalog_fingerprint=excluded.catalog_fingerprint, expires_at=excluded.expires_at""",
            (cache_key, winner_key, catalog_fingerprint, float(expires_at)),
        )
        self.db.commit()

    def cached_selection(
        self, cache_key: str, *, catalog_fingerprint: str, now: float
    ) -> str | None:
        row = self.db.execute(
            "SELECT winner_key,catalog_fingerprint,expires_at FROM capability_selection_cache WHERE cache_key=?",
            (cache_key,),
        ).fetchone()
        if row is None:
            return None
        if row["catalog_fingerprint"] != catalog_fingerprint or float(row["expires_at"]) <= now:
            self.db.execute("DELETE FROM capability_selection_cache WHERE cache_key=?", (cache_key,))
            self.db.commit()
            return None
        return str(row["winner_key"])

    def close(self) -> None:
        self.db.close()


def _cache_key(query: str, constraints: CapabilityConstraints) -> str:
    body = json.dumps(
        {"query": " ".join(_tokens(query)), "constraints": asdict(constraints.normalized())},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _eligible(option: CapabilityOption, constraints: CapabilityConstraints) -> bool:
    if constraints.require_https and option.endpoint and not _safe_https_endpoint(option.endpoint):
        return False
    if constraints.read_only and option.kind == "rest" and option.operations and not _read_operations(option):
        return False
    return True


def _evidence_adjustment(
    option: CapabilityOption,
    health: HealthEvidence,
    *,
    constraints: CapabilityConstraints,
    now: float,
) -> tuple[float, tuple[str, ...]]:
    score = 0.0
    reasons: list[str] = []
    verified_at = option.verified_at
    if option.spec_fingerprint and verified_at is not None:
        score += 4.0
        reasons.append("verified specification/version evidence")
        age_days = max(0.0, (now - verified_at) / 86_400)
        if age_days > 90:
            penalty = min(4.0, (age_days - 90) / 90)
            score -= penalty
            reasons.append("verification evidence is aging")
    if constraints.prefer_official and option.official:
        score += 2.0
        reasons.append("official provider/registry metadata")
    friction = _auth_friction(option.auth)
    if constraints.prefer_no_auth and friction == 0:
        score += 1.5
        reasons.append("no credential required")
    elif friction >= 2:
        score -= 0.75
        reasons.append("OAuth adds connection friction")
    if option.risk_flags:
        penalty = min(3.0, 0.4 * len(option.risk_flags))
        score -= penalty
        reasons.append(f"{len(option.risk_flags)} unresolved risk flag(s)")

    attempts = health.successes + health.failures
    if attempts:
        success_rate = (health.successes + 1.0) / (attempts + 2.0)
        reliability = (success_rate - 0.5) * 8.0
        score += reliability
        reasons.append(f"observed success {health.successes}/{attempts}")
    if health.latency_ema_ms is not None:
        latency_penalty = min(3.0, math.log1p(max(0.0, health.latency_ema_ms) / 250.0) * 0.8)
        score -= latency_penalty
        reasons.append(f"latency EMA {health.latency_ema_ms:.0f} ms")
    return score, tuple(reasons)


class CapabilityForge:
    """Select the best already-discovered option without spending a model call."""

    def __init__(self, options: Iterable[CapabilityOption], *, store: CapabilityStore | None = None):
        self.index = CapabilityIndex(options)
        self.store = store
        self.fingerprint = capability_set_fingerprint(self.index.options)

    def select(
        self,
        query: str,
        *,
        constraints: CapabilityConstraints = CapabilityConstraints(),
        now: float | None = None,
    ) -> SelectionResult:
        constraints = constraints.normalized()
        now = float(time.time() if now is None else now)
        key = _cache_key(query, constraints)

        cached_key = None
        if self.store is not None and constraints.cache_ttl_seconds > 0:
            cached_key = self.store.cached_selection(key, catalog_fingerprint=self.fingerprint, now=now)
        if cached_key:
            option = self.index.by_key.get(cached_key)
            if option is not None and _eligible(option, constraints):
                health = self.store.health(option.key) if self.store else HealthEvidence()
                if not health.circuit_open_until or health.circuit_open_until <= now:
                    evidence, reasons = _evidence_adjustment(
                        option, health, constraints=constraints, now=now
                    )
                    scored = ScoredCapability(option, evidence, 0.0, evidence, reasons + ("hot selection cache",))
                    return SelectionResult(
                        winner=scored,
                        fallbacks=(),
                        from_cache=True,
                        cache_key=key,
                        catalog_fingerprint=self.fingerprint,
                        candidates_considered=1,
                    )

        lexical = self.index.search(query, limit=max(40, constraints.max_results * 8))
        ranked: list[ScoredCapability] = []
        for option, lexical_score in lexical:
            if not _eligible(option, constraints):
                continue
            health = self.store.health(option.key) if self.store is not None else HealthEvidence()
            if health.circuit_open_until and health.circuit_open_until > now:
                continue
            evidence_score, reasons = _evidence_adjustment(
                option, health, constraints=constraints, now=now
            )
            total = lexical_score + evidence_score
            ranked.append(ScoredCapability(
                option=option,
                score=total,
                lexical_score=lexical_score,
                evidence_score=evidence_score,
                reasons=reasons,
            ))
        ranked.sort(key=lambda item: (-item.score, item.option.name.lower(), item.option.key))
        chosen = ranked[: constraints.max_results]
        winner = chosen[0] if chosen else None
        if winner is not None and self.store is not None and constraints.cache_ttl_seconds > 0:
            self.store.remember_selection(
                key,
                winner_key=winner.option.key,
                catalog_fingerprint=self.fingerprint,
                expires_at=now + constraints.cache_ttl_seconds,
            )
        return SelectionResult(
            winner=winner,
            fallbacks=tuple(chosen[1:]),
            from_cache=False,
            cache_key=key,
            catalog_fingerprint=self.fingerprint,
            candidates_considered=len(lexical),
        )


def compile_adapter_manifest(
    option: CapabilityOption,
    *,
    read_only: bool = True,
) -> dict:
    """Compile verified metadata into an inert manifest for later human-reviewed activation."""
    if not option.verified:
        raise ValueError("Capability must have verified specification/version evidence before compilation")
    if option.endpoint and not _safe_https_endpoint(option.endpoint):
        raise ValueError("Verified capability endpoint must use HTTPS without URL credentials")
    if option.kind == "rest":
        allowed_operations = _read_operations(option) if read_only else option.operations
        if not allowed_operations:
            raise ValueError("Capability has no operations allowed by this manifest")
        hosts = []
        if option.endpoint:
            host = urlsplit(option.endpoint).hostname
            if host:
                hosts.append(host.lower())
        return {
            "manifest_version": 1,
            "capability_key": option.key,
            "kind": option.kind,
            "name": option.name,
            "source": option.source,
            "allowed_hosts": hosts,
            "allowed_operations": list(allowed_operations),
            "auth_mode": option.auth,
            "spec_fingerprint": option.spec_fingerprint,
            "read_only": bool(read_only),
            "risk_flags": list(option.risk_flags),
            "executable": False,
            "requires_owner_enable": True,
        }
    return {
        "manifest_version": 1,
        "capability_key": option.key,
        "kind": option.kind,
        "name": option.name,
        "source": option.source,
        "allowed_tools": list(option.operations),
        "spec_fingerprint": option.spec_fingerprint,
        "read_only": bool(read_only),
        "risk_flags": list(option.risk_flags),
        "executable": False,
        "requires_owner_enable": True,
    }
