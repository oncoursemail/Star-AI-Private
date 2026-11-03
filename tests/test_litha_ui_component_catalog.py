"""Source-owned Litha UI catalog integrity checks.

The catalog is advisory documentation; passing tests never authorizes a tool.
"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "docs" / "design" / "LITHA_UI_COMPONENT_CATALOG.json"


def _in_repo(path: str) -> Path:
    candidate = Path(path)
    assert not candidate.is_absolute(), f"Catalog path must be relative: {path}"
    assert ".." not in candidate.parts, f"Catalog must not escape repository: {path}"
    return ROOT / candidate


def test_component_catalog_is_valid_and_sources_exist() -> None:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["trust"].startswith("Documentation")
    components = data["components"]
    assert isinstance(components, list) and components
    names = [item["id"] for item in components]
    assert len(names) == len(set(names)), "Stable component identifiers must be unique"
    for item in components:
        assert item["status"] in {"implemented", "planned"}
        assert isinstance(item["purpose"], str) and item["purpose"].strip()
        if item["status"] == "implemented":
            assert _in_repo(item["source"]).is_file(), item["id"]
            for test in item["tests"]:
                assert _in_repo(test).is_file(), (item["id"], test)
            assert item.get("tokens"), item["id"]
            for token in item["tokens"]:
                assert token.startswith("--star-"), (item["id"], token)
        else:
            assert "source" not in item, f"Unshipped component {item['id']} must not pretend to have source"
            assert item.get("requires"), item["id"]


def test_catalog_does_not_claim_pro_or_unbuilt_runtime_components_are_shipped() -> None:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    by_id = {entry["id"]: entry for entry in data["components"]}
    for name in ("agent.tool-receipt", "agent.source-trail", "agent.conductor-inspector", "agent.run-replay"):
        assert by_id[name]["status"] == "planned"
    assert by_id["chat.run-aura"]["source"] == "frontend/src/RunAura.tsx"
    assert all("boardui" not in item.get("source", "").lower() for item in data["components"])
