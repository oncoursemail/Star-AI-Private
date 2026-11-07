from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from starkb.corpus_manifest import CorpusError, read_manifest, verify_snapshot
from corpus_fixture import git, save, snapshot


def test_shipped_catalogue_has_no_usable_pins_or_live_activation():
    root = Path(__file__).resolve().parents[1]
    catalog = read_manifest(root / "corpus-candidates.json")
    assert len(catalog["sources"]) == 9
    assert all(s["revision"] is None for s in catalog["sources"])
    assert all(s["permission"] != "reviewed-copy" for s in catalog["sources"])
    live = (root / "corpora.json").read_text()
    assert '"creator-docs"' in live and '"luau-site"' in live
    # knowledge school (2026-10-18): the live catalogue lists further open-licensed sources, each with its licence
    import json as _json
    assert all(src.get("licence") and src.get("attribution") for src in _json.loads(live)["sources"])


@pytest.mark.parametrize("change", [
    {"revision": "main"}, {"prose_licence": "unknown"}, {"repo": "https://github.com/other/docs.git"},
    {"paths": ["../outside.md"]}, {"paths": ["src/content/docs/*.md"]},
    {"paths": ["src/content/docs/a.md", "src/content/docs/a.md"]},
    {"paths": [".env"]}, {"permission": "automatically-approved"},
    {"paths": [{"path": "src/content/docs/a.md"}]}, {"limits": None},
    {"licence_files": [{"path": ".env", "id": "MIT", "sha256": None}]},
    {"limits": {"files": True, "file_bytes": 100, "total_bytes": 100, "chunks": 10}},
])
def test_invalid_manifest_is_rejected(tmp_path, change):
    _, manifest, source = snapshot(tmp_path)
    source.update(change)
    save(manifest, [source])
    with pytest.raises(CorpusError):
        read_manifest(manifest)


def test_clean_snapshot_checks_exact_revision_origin_and_licence(tmp_path):
    repo, _, source = snapshot(tmp_path)
    result = verify_snapshot(source, repo.parent)
    assert result["commit"] == git(repo, "rev-parse", "HEAD")
    assert result["verification"] == "clean-local-snapshot; upstream-origin-is-declared"
    git(repo, "remote", "set-url", "origin", "https://github.com/not-official/docs.git")
    with pytest.raises(CorpusError, match="origin"):
        verify_snapshot(source, repo.parent)


@pytest.mark.parametrize("dirty", ["tracked", "untracked"])
def test_dirty_snapshot_cannot_be_called_pinned(tmp_path, dirty):
    repo, _, source = snapshot(tmp_path)
    target = repo / (source["paths"][0] if dirty == "tracked" else "extra.md")
    target.write_text("changed")
    with pytest.raises(CorpusError, match="dirty"):
        verify_snapshot(source, repo.parent)


def test_license_change_requires_review_even_when_snapshot_is_clean(tmp_path):
    repo, _, source = snapshot(tmp_path)
    (repo / "LICENSE.md").write_text("All rights reserved; no retrieval licence.")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "changed licence")
    source["revision"] = git(repo, "rev-parse", "HEAD")
    with pytest.raises(CorpusError, match="licence changed"):
        verify_snapshot(source, repo.parent)


def test_checkout_that_moved_from_pin_is_unavailable(tmp_path):
    repo, _, source = snapshot(tmp_path)
    git(repo, "commit", "--allow-empty", "-qm", "new revision")
    with pytest.raises(CorpusError, match="pinned revision"):
        verify_snapshot(source, repo.parent)


def test_unity_cannot_be_made_buildable(tmp_path):
    manifest = tmp_path / "manifest.json"
    save(manifest, [{"name": "unity-links", "permission": "reviewed-copy", "revision": "a" * 40}])
    with pytest.raises(CorpusError, match="Unity"):
        read_manifest(manifest)


@pytest.mark.parametrize("path", [
    "src/content/docs/bad\x01.md", "src/content/docs/bad\t.md", "src/content/docs/bad\x0b.md",
    "src/content/docs/bad\x1f.md", "src/content/docs/bad\x7f.md",
    "src/content//docs/a.md", "src/content/docs/a.md/", "src/content/docs/./a.md",
    "src/content/docs. /a.md", "src/content/docs/a.md ",
])
def test_manifest_rejects_control_characters_and_normalization_aliases(tmp_path, path):
    _, manifest, source = snapshot(tmp_path)
    source["paths"] = [path]
    save(manifest, [source])
    with pytest.raises(CorpusError):
        read_manifest(manifest)
