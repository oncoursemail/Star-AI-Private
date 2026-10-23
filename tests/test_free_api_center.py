"""Free API control center (#407 slice 1): fake providers only, no network, zero spend without opt-in."""
from star import free_api_center as fac
from star.providers import PROVIDERS


def test_catalog_is_source_linked_and_never_promises_unlimited_access():
    for pid, info in fac.CATALOG.items():
        assert info.source.startswith("https://")
        assert info.free in fac.FREE_KINDS and info.privacy in fac.PRIVACY_LABELS
        assert "unlimited" not in info.notes.lower()
    assert set(PROVIDERS) <= set(fac.CATALOG)   # every provider STAR can call has a catalog row


def test_rate_headers_groq_openai_style():
    r = fac.parse_rate_headers({"x-ratelimit-limit-requests": "14400", "x-ratelimit-remaining-requests": "14399",
                                "x-ratelimit-reset-requests": "2m59.56s", "x-ratelimit-limit-tokens": "18000",
                                "x-ratelimit-remaining-tokens": "17997", "x-ratelimit-reset-tokens": "7.66s"})
    assert (r.limit_requests, r.remaining_requests) == (14400, 14399)
    assert r.reset_requests_s == 179.56 and r.reset_tokens_s == 7.66
    assert (r.limit_tokens, r.remaining_tokens) == (18000, 17997)


def test_rate_headers_openrouter_epoch_ms_and_retry_after():
    r = fac.parse_rate_headers({"X-RateLimit-Limit": "20", "X-RateLimit-Remaining": "0",
                                "X-RateLimit-Reset": "1760950000000", "Retry-After": "30"}, now=1760949970.0)
    assert (r.limit_requests, r.remaining_requests) == (20, 0)
    assert r.reset_requests_s == 30.0 and r.retry_after_s == 30.0


def test_rate_headers_missing_or_garbage_are_none():
    r = fac.parse_rate_headers({"x-ratelimit-remaining-requests": "many", "retry-after": "soon"})
    assert r.remaining_requests is None and r.retry_after_s is None
    assert fac.parse_rate_headers({}) == fac.RateInfo()


def test_429_backs_off_then_recovers_and_never_cycles_accounts():
    q = fac.QuotaBook()
    q.note_response("groq", 429, {"retry-after": "12"}, now=100.0)
    ok, why = q.available("groq", now=105.0)
    assert not ok and "429" in why and "7" in why
    assert q.available("groq", now=113.0)[0]
    q.note_response("groq", 200, {}, now=150.0)          # a success ends the episode
    q.note_response("groq", 429, {}, now=200.0)          # no header: exponential backoff from 2 s
    q.note_response("groq", 429, {}, now=201.0)
    assert q.state("groq")["blocked_until"] == 205.0 and q.state("groq")["consecutive_429"] == 2
    q.note_response("groq", 200, {"x-ratelimit-remaining-requests": "5"}, now=300.0)
    assert q.state("groq")["consecutive_429"] == 0 and q.available("groq", now=300.0)[0]


def test_quota_exhaustion_fails_closed_until_reset():
    q = fac.QuotaBook()
    q.note_response("gemini", 200, {"x-ratelimit-remaining-requests": "0",
                                    "x-ratelimit-reset-requests": "45s"}, now=10.0)
    ok, why = q.available("gemini", now=20.0)
    assert not ok and "exhausted" in why
    assert q.available("gemini", now=56.0)[0]


def test_outage_status_is_shown_and_blocks_briefly():
    q = fac.QuotaBook()
    q.note_response("openrouter", 503, {}, now=0.0)
    assert q.state("openrouter")["last_status"] == 503 and not q.available("openrouter", now=1.0)[0]


def test_routing_is_local_by_default_and_never_falls_back_to_another_cloud():
    q = fac.QuotaBook()
    assert fac.route(opted_in=set(), quotas=q).provider == "local"
    d = fac.route(opted_in={"groq"}, quotas=q, keys={"groq": True})
    assert d.provider == "groq" and d.spend == "free_tier"
    q.note_response("groq", 429, {"retry-after": "60"}, now=0.0)
    d = fac.route(opted_in={"groq"}, quotas=q, keys={"groq": True, "openrouter": True}, now=1.0)
    assert d.provider == "local" and "groq" in d.reason     # openrouter was not opted in: no silent fallback
    assert fac.route(opted_in={"groq"}, quotas=fac.QuotaBook(), keys={}).provider == "local"   # no key: local


def test_private_work_and_paid_providers_stay_local_without_explicit_opt_in():
    q = fac.QuotaBook()
    assert fac.route(opted_in={"groq"}, quotas=q, keys={"groq": True}, private=True).provider == "local"
    d = fac.route(opted_in={"cerebras"}, quotas=q, keys={"cerebras": True})
    assert d.provider == "local" and "spend" in d.reason
    d = fac.route(opted_in={"cerebras"}, quotas=q, keys={"cerebras": True}, allow_spend={"cerebras"})
    assert d.provider == "cerebras" and d.spend == "may_bill"


def test_withdrawn_offer_fails_closed(monkeypatch):
    info = fac.CATALOG["groq"]
    monkeypatch.setitem(fac.CATALOG, "groq", fac.ProviderInfo(**{**info.__dict__, "withdrawn": True}))
    d = fac.route(opted_in={"groq"}, quotas=fac.QuotaBook(), keys={"groq": True})
    assert d.provider == "local" and "withdrawn" in d.reason


def test_status_rows_never_contain_key_material():
    q = fac.QuotaBook()
    q.note_response("groq", 429, {"retry-after": "5"}, now=0.0)
    rows = fac.status(opted_in={"groq"}, quotas=q, keys={"groq": True}, now=1.0)
    row = next(r for r in rows if r["provider"] == "groq")
    assert row["configured"] is True and row["opted_in"] is True and row["available"] is False
    assert row["privacy"] == fac.CATALOG["groq"].privacy and row["source"].startswith("https://")
    assert not any(isinstance(v, str) and "gsk_" in v for r in rows for v in r.values())


def test_redaction_of_keys_in_errors():
    text = "401 for Bearer gsk_abcdefghijklmnopqrstuvwxyz0123 and key=AIzaSyA-123456789012345678901234567 sk-or-v1-abcdef0123456789abcdef0123456789"  # star:allow (made-up key shapes for the redaction test)
    out = fac.redact(text)
    assert "gsk_" not in out and "AIza" not in out and "sk-or-v1-abcdef" not in out
    assert out.count("[redacted]") == 3
