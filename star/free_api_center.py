"""Free API control center (#407, slice 1): source-linked provider catalog, live rate-limit headers, zero-spend routing.

Pure library, nothing here opens a connection, reads a key or changes a setting. The caller feeds every real HTTP
response into ``QuotaBook.note_response`` (status + headers) and asks ``route`` which provider may serve a request:

- local is the default and the only fallback: a blocked or exhausted cloud provider never silently hands the request to
  another cloud provider, only to the local brain;
- a provider is used only when the owner opted in to it, a key is configured, the catalog says its offer is a free tier
  (anything else needs an explicit ``allow_spend`` entry) and its live quota is not exhausted;
- 429 fails closed for ``Retry-After`` / reset time (exponential backoff when the server gives none); there is no key or
  account cycling;
- a catalog row marked ``withdrawn`` fails closed until a human updates the row from the linked source.

The catalog values are what the linked pages said when the row was written; they are not verified live by this code.
The live headers are the truth for quotas. Free tiers can change: never promise unlimited access.
"""
from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from email.utils import parsedate_to_datetime
from typing import Iterable, Mapping

FREE_KINDS = ("free_tier", "trial_credit", "paid", "unknown")
PRIVACY_LABELS = ("no_training_stated", "may_train_on_free", "used_to_improve", "unknown")
OUTAGE_BLOCK_S = 5.0
MAX_BACKOFF_S = 300.0


@dataclass(frozen=True)
class ProviderInfo:
    label: str
    source: str          # the page the row was written from
    free: str            # FREE_KINDS
    privacy: str         # PRIVACY_LABELS
    notes: str = ""
    withdrawn: bool = False


CATALOG: dict[str, ProviderInfo] = {
    "groq": ProviderInfo("GroqCloud", "https://console.groq.com/docs/rate-limits", "free_tier", "unknown",
                         "free tier with per-model RPM/RPD/TPM caps from the x-ratelimit headers; data-use terms: verify at source"),
    "openrouter": ProviderInfo("OpenRouter", "https://openrouter.ai/pricing", "free_tier", "may_train_on_free",
                               "only ':free' model variants are free, with a daily request cap; free-variant providers may log or train on prompts (check each model page)"),
    "gemini": ProviderInfo("Google Gemini", "https://ai.google.dev/gemini-api/docs/pricing", "free_tier", "used_to_improve",
                           "free tier per model with RPM/RPD caps; Google states free-tier content may be used to improve its products"),
    "cerebras": ProviderInfo("Cerebras", "https://inference-docs.cerebras.ai/support/rate-limits", "unknown", "unknown",
                             "offer not verified for this catalog: treated as may-bill until a human checks the source"),
    "cloudflare": ProviderInfo("Cloudflare Workers AI", "https://developers.cloudflare.com/workers-ai/platform/pricing/",
                               "free_tier", "unknown", "daily free allocation (neurons), then billed; not wired into STAR yet"),
    "hf": ProviderInfo("Hugging Face Inference Providers", "https://huggingface.co/docs/inference-providers/pricing",
                       "trial_credit", "unknown", "monthly credits, then billed; not wired into STAR yet"),
    "brave": ProviderInfo("Brave Search API", "https://brave.com/search/api/", "unknown", "unknown",
                          "search only; plan terms changed during 2025, verify before relying on a free quota"),
    "tavily": ProviderInfo("Tavily", "https://docs.tavily.com/", "free_tier", "unknown",
                           "search only; monthly free credits, then billed"),
}


@dataclass(frozen=True)
class RateInfo:
    limit_requests: int | None = None
    remaining_requests: int | None = None
    reset_requests_s: float | None = None
    limit_tokens: int | None = None
    remaining_tokens: int | None = None
    reset_tokens_s: float | None = None
    retry_after_s: float | None = None


_DURATION = re.compile(r"^(?:(\d+)h)?(?:(\d+)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+)ms)?$")


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None and value.strip() != "" else None
    except ValueError:
        return None


def _duration_s(value: str | None, now: float) -> float | None:
    """'2m59.56s', '7.66s', '500ms', plain seconds, an epoch in ms (OpenRouter) or an HTTP date -> seconds from now."""
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    m = _DURATION.match(v)
    if m and any(m.groups()):
        h, mi, s, ms = m.groups()
        return round(int(h or 0) * 3600 + int(mi or 0) * 60 + float(s or 0) + int(ms or 0) / 1000, 3)
    try:
        n = float(v)
    except ValueError:
        try:
            return round(max(0.0, parsedate_to_datetime(v).timestamp() - now), 3)
        except (TypeError, ValueError):
            return None
    if n > 1e11:          # epoch milliseconds
        return round(max(0.0, n / 1000 - now), 3)
    if n > 1e8:           # epoch seconds
        return round(max(0.0, n - now), 3)
    return n


def parse_rate_headers(headers: Mapping[str, str], now: float | None = None) -> RateInfo:
    """Groq/OpenAI-style x-ratelimit-*-requests/tokens, OpenRouter X-RateLimit-Limit/Remaining/Reset and Retry-After.
    Missing or unparsable values are None, never guessed."""
    now = time.time() if now is None else now
    h = {k.lower(): v for k, v in headers.items()}
    return RateInfo(
        limit_requests=_int(h.get("x-ratelimit-limit-requests", h.get("x-ratelimit-limit"))),
        remaining_requests=_int(h.get("x-ratelimit-remaining-requests", h.get("x-ratelimit-remaining"))),
        reset_requests_s=_duration_s(h.get("x-ratelimit-reset-requests", h.get("x-ratelimit-reset")), now),
        limit_tokens=_int(h.get("x-ratelimit-limit-tokens")),
        remaining_tokens=_int(h.get("x-ratelimit-remaining-tokens")),
        reset_tokens_s=_duration_s(h.get("x-ratelimit-reset-tokens"), now),
        retry_after_s=_duration_s(h.get("retry-after"), now),
    )


@dataclass
class _State:
    last_status: int | None = None
    blocked_until: float = 0.0
    exhausted_until: float = 0.0
    consecutive_429: int = 0
    rate: RateInfo = field(default_factory=RateInfo)
    updated: float = 0.0


class QuotaBook:
    """Per-provider live quota state built only from real responses. In memory; nothing is persisted."""

    def __init__(self) -> None:
        self._s: dict[str, _State] = {}

    def _get(self, provider: str) -> _State:
        return self._s.setdefault(provider, _State())

    def note_response(self, provider: str, status: int, headers: Mapping[str, str], now: float | None = None) -> None:
        now = time.time() if now is None else now
        st = self._get(provider)
        rate = parse_rate_headers(headers, now)
        st.last_status, st.rate, st.updated = status, rate, now
        if status == 429:
            st.consecutive_429 += 1
            wait = rate.retry_after_s or rate.reset_requests_s or rate.reset_tokens_s
            if wait is None:
                wait = min(2.0 ** st.consecutive_429, MAX_BACKOFF_S)
            st.blocked_until = now + wait
            return
        if status >= 500:
            st.blocked_until = now + OUTAGE_BLOCK_S
            return
        st.consecutive_429 = 0
        if rate.remaining_requests == 0:
            st.exhausted_until = now + (rate.reset_requests_s or 60.0)
        elif rate.remaining_tokens == 0:
            st.exhausted_until = now + (rate.reset_tokens_s or 60.0)

    def available(self, provider: str, now: float | None = None) -> tuple[bool, str]:
        now = time.time() if now is None else now
        st = self._get(provider)
        if now < st.blocked_until:
            return False, f"blocked after {st.last_status} for {st.blocked_until - now:.0f} s"
        if now < st.exhausted_until:
            return False, f"quota exhausted, reset in {st.exhausted_until - now:.0f} s"
        return True, "ok"

    def state(self, provider: str) -> dict:
        st = self._get(provider)
        return {**asdict(st), "rate": asdict(st.rate)}


@dataclass(frozen=True)
class Decision:
    provider: str      # "local" or a catalog id
    reason: str
    spend: str         # none | free_tier | may_bill


def route(*, opted_in: Iterable[str], quotas: QuotaBook, keys: Mapping[str, bool] | None = None,
          now: float | None = None, private: bool = False, allow_spend: Iterable[str] = (),
          preferred: str | None = None) -> Decision:
    """Which provider may serve this request. Local unless every condition holds for an opted-in provider."""
    if private:
        return Decision("local", "private work stays local", "none")
    keys = keys or {}
    wanted = set(opted_in)
    spend_ok = set(allow_spend)
    order = [p for p in ([preferred] if preferred else []) + list(CATALOG) if p in wanted]
    reasons: list[str] = []
    seen: set[str] = set()
    for pid in order:
        if pid in seen:
            continue
        seen.add(pid)
        info = CATALOG.get(pid)
        if info is None:
            reasons.append(f"{pid}: not in the catalog")
            continue
        if info.withdrawn:
            reasons.append(f"{pid}: offer withdrawn, update the catalog from {info.source}")
            continue
        if not keys.get(pid):
            reasons.append(f"{pid}: no key configured")
            continue
        if info.free != "free_tier" and pid not in spend_ok:
            reasons.append(f"{pid}: would spend ({info.free}), not allowed")
            continue
        ok, why = quotas.available(pid, now)
        if not ok:
            reasons.append(f"{pid}: {why}")
            continue
        return Decision(pid, "opted in, key configured, quota ok",
                        "free_tier" if info.free == "free_tier" else "may_bill")
    return Decision("local", "; ".join(reasons) or "no cloud provider opted in", "none")


def status(*, opted_in: Iterable[str], quotas: QuotaBook, keys: Mapping[str, bool] | None = None,
           now: float | None = None) -> list[dict]:
    """One row per catalog provider for a control-center view. Never includes key material, only whether a key exists."""
    keys = keys or {}
    wanted = set(opted_in)
    rows = []
    for pid, info in CATALOG.items():
        ok, why = quotas.available(pid, now)
        st = quotas.state(pid)
        rows.append({"provider": pid, "label": info.label, "configured": bool(keys.get(pid)), "opted_in": pid in wanted,
                     "available": ok and not info.withdrawn, "reason": "withdrawn" if info.withdrawn else why,
                     "free": info.free, "privacy": info.privacy, "source": info.source, "notes": info.notes,
                     "last_status": st["last_status"], "rate": st["rate"]})
    return rows


_KEY = re.compile(r"(?:Bearer\s+)?(?:gsk_|AIza|sk-|hf_|csk-|tvly-|BSA)[A-Za-z0-9._-]{10,}|Bearer\s+[A-Za-z0-9._~+/-]{16,}")


def redact(text: str) -> str:
    """Known key shapes (Groq, Google, OpenAI/OpenRouter, HF, Cerebras, Tavily, Brave) and bearer tokens -> [redacted]."""
    return _KEY.sub("[redacted]", text)
