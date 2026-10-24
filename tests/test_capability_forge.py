from star.api_intelligence import ApiCandidate, OpenApiSummary
from star.capability_forge import (
    CapabilityConstraints,
    CapabilityForge,
    CapabilityIndex,
    CapabilityOption,
    CapabilityStore,
    capability_set_fingerprint,
    compile_adapter_manifest,
    mcp_option,
    rest_option,
)


def _rest(name, description, host, *, verified=True, operations=("GET /data",), auth="No", official=False):
    candidate = ApiCandidate(
        name=name,
        url=f"https://{host}/docs",
        description=description,
        category="Development",
        auth=auth,
        https=True,
        cors="yes",
        source="test-catalog",
    )
    summary = OpenApiSummary(
        title=name,
        version="3.2.1",
        servers=(f"https://{host}",),
        operations=tuple(operations),
        auth_schemes=(),
        write_operations=tuple(op for op in operations if op.startswith(("POST ", "PUT ", "PATCH ", "DELETE "))),
        warnings=(),
    )
    return rest_option(
        candidate,
        openapi=summary,
        spec_fingerprint=("spec-" + name.lower()) if verified else "",
        verified_at=1_000.0 if verified else None,
        official=official,
    )


def test_inverted_index_finds_relevant_capability_without_scanning_every_option():
    options = [_rest("Weather", "forecast temperature rain", "weather.test")]
    options += [_rest(f"Other {i}", f"unrelated catalog item {i}", f"other{i}.test") for i in range(200)]
    index = CapabilityIndex(options)
    results = index.search("rain forecast")
    assert results[0][0].name == "Weather"
    assert len(results) == 1


def test_index_query_cache_returns_same_ranked_result():
    index = CapabilityIndex([
        _rest("Weather A", "weather forecast", "a.test"),
        _rest("Weather B", "weather forecast archive", "b.test"),
    ])
    first = index.search("weather forecast", limit=2)
    second = index.search("weather forecast", limit=2)
    assert first == second


def test_verified_official_capability_wins_close_tournament():
    unofficial = _rest("Weather Basic", "weather forecast", "basic.test", verified=False)
    official = _rest("Weather Official", "weather forecast", "official.test", verified=True, official=True)
    result = CapabilityForge([unofficial, official]).select("weather forecast", now=2_000.0)
    assert result.winner is not None
    assert result.winner.option.name == "Weather Official"
    assert any("verified" in reason for reason in result.winner.reasons)


def test_health_memory_promotes_reliable_fast_provider(tmp_path):
    a = _rest("Weather Alpha", "weather forecast", "alpha.test")
    b = _rest("Weather Beta", "weather forecast", "beta.test")
    store = CapabilityStore(tmp_path / "forge.sqlite3")
    try:
        for n in range(5):
            store.record_result(a.key, success=True, latency_ms=80, now=2_000 + n)
            store.record_result(b.key, success=(n == 0), latency_ms=1_200, now=2_000 + n)
        result = CapabilityForge([a, b], store=store).select(
            "weather forecast", constraints=CapabilityConstraints(cache_ttl_seconds=0), now=3_000
        )
        assert result.winner is not None
        assert result.winner.option.key == a.key
        assert any("observed success" in reason for reason in result.winner.reasons)
    finally:
        store.close()


def test_three_consecutive_failures_open_circuit_and_use_fallback(tmp_path):
    primary = _rest("Primary Weather", "weather forecast", "primary.test", official=True)
    fallback = _rest("Fallback Weather", "weather forecast", "fallback.test")
    store = CapabilityStore(tmp_path / "forge.sqlite3")
    try:
        for offset in range(3):
            evidence = store.record_result(primary.key, success=False, latency_ms=200, now=2_000 + offset)
        assert evidence.circuit_open_until and evidence.circuit_open_until > 2_100
        result = CapabilityForge([primary, fallback], store=store).select(
            "weather forecast", constraints=CapabilityConstraints(cache_ttl_seconds=0), now=2_100
        )
        assert result.winner is not None
        assert result.winner.option.key == fallback.key
    finally:
        store.close()


def test_hot_selection_cache_skips_full_tournament(tmp_path):
    option = _rest("Weather", "forecast rain", "weather.test", official=True)
    store = CapabilityStore(tmp_path / "forge.sqlite3")
    try:
        forge = CapabilityForge([option], store=store)
        first = forge.select("rain forecast", now=2_000)
        second = forge.select("rain forecast", now=2_001)
        assert first.from_cache is False
        assert second.from_cache is True
        assert second.candidates_considered == 1
        assert second.winner and second.winner.option.key == option.key
    finally:
        store.close()


def test_catalog_fingerprint_invalidates_cached_winner(tmp_path):
    first = _rest("Weather", "forecast rain", "weather.test", official=True)
    store = CapabilityStore(tmp_path / "forge.sqlite3")
    try:
        old = CapabilityForge([first], store=store)
        chosen = old.select("rain forecast", now=2_000)
        assert chosen.winner
        changed = CapabilityOption(
            **{**first.__dict__, "spec_fingerprint": "different-spec"}
        )
        new = CapabilityForge([changed], store=store)
        again = new.select("rain forecast", now=2_001)
        assert old.fingerprint != new.fingerprint
        assert again.from_cache is False
    finally:
        store.close()


def test_read_only_selection_rejects_write_only_rest_capability():
    write_only = _rest(
        "Dangerous", "project management tasks", "write.test",
        operations=("POST /projects", "DELETE /projects/{id}"),
    )
    result = CapabilityForge([write_only]).select("project management")
    assert result.winner is None


def test_adapter_manifest_is_inert_and_strips_writes():
    option = _rest(
        "Mixed", "items catalog", "mixed.test",
        operations=("GET /items", "POST /items", "DELETE /items/{id}"),
        official=True,
    )
    manifest = compile_adapter_manifest(option, read_only=True)
    assert manifest["allowed_hosts"] == ["mixed.test"]
    assert manifest["allowed_operations"] == ["GET /items"]
    assert manifest["executable"] is False
    assert manifest["requires_owner_enable"] is True


def test_adapter_manifest_refuses_unverified_or_credentialed_endpoint():
    unverified = _rest("Unverified", "weather forecast", "u.test", verified=False)
    try:
        compile_adapter_manifest(unverified)
    except ValueError as exc:
        assert "verified" in str(exc)
    else:
        raise AssertionError("unverified capability should be refused")

    verified = _rest("Verified", "weather forecast", "v.test")
    bad = CapabilityOption(**{**verified.__dict__, "endpoint": "https://user:pass@v.test"})
    try:
        compile_adapter_manifest(bad)
    except ValueError as exc:
        assert "HTTPS" in str(exc)
    else:
        raise AssertionError("credential-bearing endpoint should be refused")


def test_mcp_option_uses_same_fast_router_but_remains_inert():
    mcp = mcp_option(
        name="com.example/weather",
        description="weather forecast tools",
        source="official-mcp-registry",
        repository_url="https://github.com/example/weather",
        tools=("forecast", "historical_weather"),
        version_fingerprint="v1.2.3",
        verified_at=2_000,
        official=True,
    )
    result = CapabilityForge([mcp]).select("weather forecast", now=2_100)
    assert result.winner and result.winner.option.kind == "mcp"
    manifest = compile_adapter_manifest(mcp)
    assert manifest["allowed_tools"] == ["forecast", "historical_weather"]
    assert manifest["executable"] is False


def test_capability_set_fingerprint_is_order_independent():
    a = _rest("A", "weather", "a.test")
    b = _rest("B", "weather", "b.test")
    assert capability_set_fingerprint([a, b]) == capability_set_fingerprint([b, a])
