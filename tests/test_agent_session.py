"""Typed agent-session contract: usage/tier/billing are unknown unless a provider API measured them."""
import pytest

from star.agent_session import UNMEASURED, SessionEvent, SessionProbe, UsageReport


def test_unmeasured_usage_cannot_claim_anything():
    assert UNMEASURED.tier == "unknown" and UNMEASURED.billing == "unknown" and UNMEASURED.models == ()
    for claim in (dict(tier="free"), dict(billing="zero_spend"), dict(models=("gemini-2.5-flash",)),
                  dict(quota_remaining=100), dict(endpoint="models.list"), dict(measured_at=1.0)):
        with pytest.raises(ValueError):
            UsageReport(**claim)


def test_provider_measurement_needs_endpoint_and_time():
    with pytest.raises(ValueError):
        UsageReport(source="provider_api", tier="free")
    with pytest.raises(ValueError):
        UsageReport(source="provider_api", endpoint="models.list", measured_at=float("nan"))
    got = UsageReport(source="provider_api", models=("m1",), tier="free", billing="zero_spend",
                      quota_remaining=5, measured_at=1_800_000_000.0, endpoint="models.list")
    assert got.tier == "free" and got.models == ("m1",)


def test_states_and_values_are_checked():
    with pytest.raises(ValueError):
        UsageReport(source="guessed")
    with pytest.raises(ValueError):
        UsageReport(source="provider_api", tier="premium", measured_at=1.0, endpoint="x")
    with pytest.raises(ValueError):
        UsageReport(source="provider_api", quota_remaining=-1, measured_at=1.0, endpoint="x")
    with pytest.raises(ValueError):
        UsageReport(source="provider_api", models=["m"], measured_at=1.0, endpoint="x")


def test_probe_and_event_defaults_are_unknown():
    p = SessionProbe("a", installed=False, enabled=False, state="idle")
    assert p.auth == "unknown" and p.usage is UNMEASURED
    assert SessionEvent("end").data == dict()
