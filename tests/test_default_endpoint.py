"""The default local inference endpoint must be the one STAR's own engine serves.

Before this fix Python's Settings defaulted to port 1234 (LM Studio's port)
while the managed STAR Brain / model router, the legacy launcher and the React
defaults all use port 8080, so a fresh install showed and probed an endpoint
nothing listened on until the user clicked "Start Brain".
"""
from pathlib import Path
import inspect
import json
import re

import pytest

from star.desktop_core import Settings
from star.local_runtime import Runtime

ROOT = Path(__file__).resolve().parents[1]


def _default_port(function) -> int:
    return inspect.signature(function).parameters["port"].default


def test_default_endpoint_is_valid_loopback_and_matches_managed_engine_port():
    settings = Settings()
    settings.validate()
    ports = {
        _default_port(Runtime.arguments),
        _default_port(Runtime.router_arguments),
        _default_port(Runtime.start),
    }
    assert len(ports) == 1, "managed engine entry points must agree on one default port"
    assert settings.endpoint == f"http://127.0.0.1:{ports.pop()}/v1"


def test_fresh_profile_loads_the_managed_engine_endpoint(tmp_path):
    assert Settings.load(tmp_path / "settings.json").endpoint == Settings().endpoint


def test_saved_endpoint_is_never_rewritten_by_the_new_default(tmp_path):
    """Existing profiles keep exactly what they saved (for example LM Studio on 1234)."""
    file = tmp_path / "settings.json"
    file.write_text(json.dumps({"endpoint": "http://127.0.0.1:1234/v1", "model": "lm-studio-model"}),
                    encoding="utf-8")
    loaded = Settings.load(file)
    assert loaded.endpoint == "http://127.0.0.1:1234/v1"
    loaded.validate()
    # A profile that predates the endpoint field gets the managed default, not a stale one.
    file.write_text(json.dumps({"model": "m"}), encoding="utf-8")
    assert Settings.load(file).endpoint == Settings().endpoint


def test_react_default_endpoint_literals_match_python_default():
    """Cross-language guard: every hard-coded default endpoint in the UI equals Python's."""
    pattern = re.compile(r"""\bendpoint\s*:\s*['"](http://127\.0\.0\.1:\d+/v1)['"]""")
    found = {}
    for source in sorted((ROOT / "frontend" / "src").rglob("*.ts*")):
        if ".test." in source.name:
            continue
        for match in pattern.findall(source.read_text(encoding="utf-8")):
            found[f"{source.name}"] = match
    # The UI hard-codes no default endpoint today (Python is the only source), so this is vacuous; if one is
    # added again it must equal Python's.
    assert set(found.values()) <= {Settings().endpoint}, found
