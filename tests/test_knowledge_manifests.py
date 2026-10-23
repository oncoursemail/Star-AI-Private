"""Prospective knowledge corpora: schemas, licence decisions and ingestion guardrails.

Local-only tests: no downloads, service, model, GPU or keyring.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

KNOWLEDGE = Path(__file__).resolve().parents[1] / "server" / "knowledge"
sys.path.insert(0, str(KNOWLEDGE))

from starkb.manifests import (  # noqa: E402
    IngestionNotAllowed, ManifestError, SOURCES_DIR, load_manifest, load_manifests,
    require_ingestion_rights, validate_manifest,
)

# One independently asserted licence decision for each proposed corpus.
CORPORA = [
    ("unity-manual", "link-only", "CC-BY-NC-ND-4.0", "Unity-Companion-License-1.4"),
    ("unity-scripting-api", "link-only", "CC-BY-NC-ND-4.0", "Unity-Scripting-Reference-Examples-Grant"),
    ("microsoft-dotnet", "ingest-allowed", "CC-BY-4.0", "MIT"),
    ("mdn-web", "ingest-allowed", "CC-BY-SA-2.5", "CC0-1.0-or-MIT"),
    ("python-stdlib", "ingest-allowed", "PSF-2.0", "PSF-2.0-OR-0BSD"),
    ("typescript-handbook", "ingest-allowed", "CC-BY-4.0", "MIT"),
    ("lua-5-4", "ingest-allowed", "MIT", "MIT"),
    ("luau", "ingest-allowed", "MIT", "MIT"),
    ("godot", "ingest-allowed", "CC-BY-3.0", "CC-BY-3.0-and-MIT"),
]


@pytest.mark.parametrize(("name", "mode", "text_licence", "sample_licence"), CORPORA)
def test_official_corpus_manifest_has_verified_rights_and_citations(name, mode, text_licence, sample_licence):
    doc = load_manifest(SOURCES_DIR / f"{name}.json")
    assert doc["schema_version"] == 1 and doc["name"] == name and doc["mode"] == mode
    assert doc["licence"]["text"]["id"] == text_licence
    assert doc["licence"]["code_samples"]["id"] == sample_licence
    assert doc["licence"]["text"]["redistribution_allowed"] == (mode == "ingest-allowed")
    assert doc["licence"]["code_samples"]["redistribution_allowed"] == (mode == "ingest-allowed" or name == "unity-scripting-api")
    assert doc["source"]["url"].startswith("https://") and doc["source"]["public_base"].startswith("https://")
    assert doc["include"] and doc["exclude"] and doc["expected_size"]["max"] >= doc["expected_size"]["min"]
    assert doc["update_cadence"]["frequency"] and doc["citation"]["example"].startswith(("Unity", "Microsoft", "MDN", "Python", "TypeScript", "Lua", "Luau", "Godot"))
    for part in ("text", "code_samples"):
        rights = doc["licence"][part]
        assert rights["url"].startswith("https://") and rights["evidence_url"].startswith("https://")
        assert rights["evidence_quote"] and rights["attribution"] and rights["conditions"]
    if mode == "link-only":
        with pytest.raises(IngestionNotAllowed, match="link-only"):
            load_manifest(SOURCES_DIR / f"{name}.json", for_ingestion=True)
    else:
        assert load_manifest(SOURCES_DIR / f"{name}.json", for_ingestion=True) == doc
        require_ingestion_rights(doc, include_code_samples=True)


def test_catalogue_is_metadata_only_and_contains_every_corpus():
    docs = load_manifests()
    assert {doc["name"] for doc in docs} == {name for name, *_ in CORPORA}
    assert [doc["name"] for doc in docs] == sorted(doc["name"] for doc in docs)
    with pytest.raises(IngestionNotAllowed, match="link-only"):
        load_manifests(for_ingestion=True)


def test_the_existing_roblox_index_has_not_been_extended():
    # The knowledge school added other corpora to the index (2026-10-18); the Roblox group, which Roblox questions
    # are answered from (search.auto_scope), is still exactly the two official sources.
    sources = json.loads((KNOWLEDGE / "corpora.json").read_text(encoding="utf-8"))["sources"]
    assert {item["name"] for item in sources if item.get("group", "roblox") == "roblox"} == {"creator-docs", "luau-site"}


@pytest.mark.parametrize("change", [
    lambda doc: doc.update(mode="unreviewed"),
    lambda doc: doc.update(mode=[]),
    lambda doc: doc.update(schema_version=True),
    lambda doc: doc["source"].update(url="http://example.org/docs"),
    lambda doc: doc["source"].update(kind=[]),
    lambda doc: doc["source"].update(url="https://example.org/unsafe" + chr(10)),
    lambda doc: doc["licence"]["text"].update(evidence_quote=""),
    lambda doc: doc["licence"]["text"].update(evidence_url="javascript:alert(1)"),
    lambda doc: doc["licence"]["text"].update(redistribution_allowed="yes"),
    lambda doc: doc["licence"]["text"].update(id="Unreviewed-Licence"),
    lambda doc: doc["expected_size"].update(min=0),
    lambda doc: doc["expected_size"].update(max=1),
    lambda doc: doc["update_cadence"].update(frequency=[]),
    lambda doc: doc["citation"].update(format="{title}"),
    lambda doc: doc["include"].append(doc["exclude"][0]),
    lambda doc: doc.update(unexpected=True),
])
def test_corrupt_or_misleading_manifest_is_rejected(change):
    doc = deepcopy(load_manifest(SOURCES_DIR / "microsoft-dotnet.json"))
    change(doc)
    with pytest.raises(ManifestError):
        validate_manifest(doc)


def test_unlicensed_text_cannot_be_reclassified_as_ingestable():
    doc = deepcopy(load_manifest(SOURCES_DIR / "unity-manual.json"))
    doc["mode"] = "ingest-allowed"
    with pytest.raises(ManifestError, match="text rights"):
        validate_manifest(doc)


def test_code_samples_are_checked_separately_from_prose():
    doc = deepcopy(load_manifest(SOURCES_DIR / "python-stdlib.json"))
    doc["licence"]["code_samples"]["redistribution_allowed"] = False
    validate_manifest(doc)
    require_ingestion_rights(doc)
    with pytest.raises(IngestionNotAllowed, match="code sample"):
        require_ingestion_rights(doc, include_code_samples=True)


def test_unreadable_invalid_and_misnamed_files_fail_closed(tmp_path):
    with pytest.raises(ManifestError, match="no manifest directory"):
        load_manifests(tmp_path / "missing")
    with pytest.raises(ManifestError, match="no corpus manifests"):
        load_manifests(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(ManifestError, match="cannot load manifest"):
        load_manifest(bad)
    bad.write_text((SOURCES_DIR / "microsoft-dotnet.json").read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ManifestError, match="mismatched corpus name"):
        load_manifests(tmp_path)
