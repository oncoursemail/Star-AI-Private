"""providers.open_client: the STAR_PRIORITY class goes to the owner's own STAR server as X-Star-Priority, never to a
cloud provider."""
from __future__ import annotations

from star import providers
from star.desktop_core import Settings


def _client(monkeypatch, provider, value):
    if value is None:
        monkeypatch.delenv("STAR_PRIORITY", raising=False)
    else:
        monkeypatch.setenv("STAR_PRIORITY", value)
    monkeypatch.setattr(providers, "connection_for", lambda settings: ("http://127.0.0.1:8080/v1", "k"))
    monkeypatch.setattr(providers, "provider_kind", lambda settings: provider)
    return providers.open_client(Settings(provider="star_server", server_endpoint="http://127.0.0.1:8080/v1"))


def test_header_sent_to_the_star_server(monkeypatch):
    assert _client(monkeypatch, "lan", "p3").default_headers.get("X-Star-Priority") == "P3"


def test_no_header_without_a_class_or_for_a_cloud_provider(monkeypatch):
    assert "X-Star-Priority" not in _client(monkeypatch, "lan", None).default_headers
    assert "X-Star-Priority" not in _client(monkeypatch, "lan", "urgent").default_headers
    assert "X-Star-Priority" not in _client(monkeypatch, "cloud", "P3").default_headers
