from star.harness_routing import (
    FailureKind,
    RouteCandidate,
    classify_failure,
    next_fallback,
)


def test_rate_limit_allows_fallback():
    d = classify_failure("HTTP 429 rate limit exceeded")
    assert d.kind is FailureKind.RATE_LIMIT
    assert d.may_fallback
    assert not d.may_retry_same


def test_context_failure_fails_closed():
    d = classify_failure("maximum context length exceeded")
    assert d.kind is FailureKind.CONTEXT
    assert not d.may_fallback
    assert not d.may_retry_same


def test_auth_failure_fails_closed():
    d = classify_failure("401 unauthorized: invalid API key")
    assert d.kind is FailureKind.AUTH
    assert not d.may_fallback


def test_fallback_stays_inside_trust_boundary_by_default():
    local_a = RouteCandidate("local", "fast-a", "local")
    cloud = RouteCandidate("groq", "cloud-a", "cloud")
    local_b = RouteCandidate("local", "fast-b", "local")
    decision = classify_failure("503 overloaded")

    assert next_fallback(local_a, [local_a, cloud, local_b], decision=decision) == local_b


def test_trust_boundary_change_requires_explicit_permission():
    local = RouteCandidate("local", "fast-a", "local")
    cloud = RouteCandidate("groq", "cloud-a", "cloud")
    decision = classify_failure("503 overloaded")

    assert next_fallback(local, [local, cloud], decision=decision) is None
    assert next_fallback(
        local,
        [local, cloud],
        decision=decision,
        allow_trust_changes=True,
    ) == cloud
