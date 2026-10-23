"""Non-commercial sources are tagged so that no export can put them in a public bundle (store.check_licences)."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from starkb import store  # noqa: E402


def live_sources():
    return json.loads((ROOT / "corpora.json").read_text(encoding="utf-8"))["sources"]


def test_every_non_commercial_source_in_the_live_catalogue_is_kept_out_of_public_bundles():
    nc = {s["name"] for s in live_sources() if "-NC-" in s["licence"]}
    # Introduction to Business 2e: its book metadata says CC BY-NC-SA 4.0 (the repository LICENSE says CC BY 4.0)
    assert nc == {"openstax-business", "openstax-prealgebra", "openstax-calculus", "openstax-physics", "openstax-python"}
    assert all(s.get("public_bundle") is False for s in live_sources() if s["name"] in nc)
    store.check_licences({"sources": live_sources()})


@pytest.mark.parametrize("licence", ["CC-BY-NC-SA-4.0", "CC-BY-NC-4.0", "CC-BY-NC-ND-4.0"])
def test_a_non_commercial_source_without_the_tag_is_refused(licence):
    with pytest.raises(ValueError, match="public_bundle"):
        store.check_licences({"sources": [{"name": "book", "licence": licence}]})
    with pytest.raises(ValueError):
        store.check_licences({"sources": [{"name": "book", "licence": licence, "public_bundle": True}]})
    store.check_licences({"sources": [{"name": "book", "licence": licence, "public_bundle": False}]})


def test_other_licences_need_no_tag():
    store.check_licences({"sources": [{"name": n, "licence": lic} for n, lic in
                                      [("a", "CC-BY-4.0"), ("b", "CC-BY-SA-4.0"), ("c", "MIT"),
                                       ("d", "CC-BY-4.0 (prose), MIT (code samples)")]]})


def test_build_refuses_an_untagged_non_commercial_source_before_touching_the_index(tmp_path):
    manifest = tmp_path / "corpora.json"
    manifest.write_text(json.dumps({"sources": [{"name": "book", "licence": "CC-BY-NC-SA-4.0"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="public_bundle"):
        store.build(tmp_path / "kb.sqlite3", tmp_path / "sources", manifest)
    assert not (tmp_path / "kb.sqlite3").exists()
