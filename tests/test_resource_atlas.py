"""Offline regression checks for STAR Resource Atlas metadata discovery."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from star import resource_atlas as atlas


class AtlasTests(unittest.TestCase):
    def test_registry_has_diverse_review_only_entries(self):
        items = atlas.read_sources()
        self.assertGreaterEqual(len(items), 70)
        self.assertGreaterEqual(len({i["category"] for i in items}), 30)
        self.assertTrue(all(i["review_required"] and not i["automatic_install"] and
                            not i["auto_train"] for i in items))
        self.assertEqual(len({i["id"] for i in items}), len(items))

    def test_network_default_off_no_fetch(self):
        with patch.dict("os.environ", {"STAR_RESOURCE_ATLAS_NETWORK": "0"}):
            with patch.object(atlas, "discover", side_effect=AssertionError("Network called")):
                with self.assertRaises(SystemExit):
                    atlas.main(["scan", "roblox textures", "--allow-network"])

    def test_no_arbitrary_host_or_redirects(self):
        for url in ("http://api.github.com/", "https://api.github.com.attacker.org/x",
                    "https://user:password@api.github.com/x",
                    "https://evil.example/api", "file:///etc/passwd"):
            with self.subTest(url=url):
                self.assertFalse(atlas._host_is_allowed(url))
                with self.assertRaises(ValueError):
                    atlas.fetch_json(url)

    def test_bad_queries_rejected(self):
        for query in ("a", "", "x"*101, "a\nb", "test; rm -rf .", "https://x"):
            with self.subTest(query=query):
                with self.assertRaises(ValueError):
                    atlas._query(query)

    def test_github_filters_and_license(self):
        payload = {"items": [
            {"name":"ok", "full_name":"org/ok", "description":"Shader suite", "topics":["vfx"],
             "private":False, "archived":False, "license":{"spdx_id":"MIT"}},
            {"name":"secret", "full_name":"org/secret", "private":True},
            {"name":"old", "full_name":"org/old", "archived":True},
            {"name":"bad", "full_name":"org/%2Fname", "license":{}},
        ]}
        items = atlas.decode("github", payload, limit=5, fetched_at="2026-10-25T00:00:00Z")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].url, "https://github.com/org/ok")
        self.assertEqual(items[0].license_claim, "MIT")
        self.assertTrue(items[0].review_required)
        self.assertFalse(items[0].installed)
        self.assertFalse(items[0].executable)

    def test_github_unknown_license_fails_closed(self):
        payload = {"items":[{"full_name":"org/repo","license":{"spdx_id":"NOASSERTION"}}]}
        self.assertEqual(atlas.decode("github", payload, limit=1)[0].license_claim, "unknown")

    def test_huggingface_models_and_gating(self):
        raw = [{"id":"tester/rig-net", "pipeline_tag":"image-to-image",
                "tags":["license:apache-2.0", "vision"], "private":False},
               {"id":"secret/locked", "gated":"auto", "tags":["license:mit"]}]
        found = atlas.decode("hf_models", raw, limit=4)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].license_claim, "apache-2.0")
        self.assertEqual(found[0].kind, "model")
        ds = atlas.decode("hf_datasets", raw, limit=1)
        self.assertTrue(ds[0].url.startswith("https://huggingface.co/datasets/"))

    def test_polyhaven_search_slugs(self):
        payload = {"query":"mossy rock","results":[{"slug":"mossy_rock","score":0.92},{"slug":"../../etc"}]}
        found = atlas.decode("polyhaven", payload, limit=3)
        self.assertEqual([x.resource_id for x in found], ["mossy_rock"])
        self.assertEqual(found[0].license_claim, "CC0-1.0")

    def test_polyhaven_relevance_gate_removes_unrelated_neighbours(self):
        bad = {"results":[{"slug":"moon_rock_03","score":0.46},
                          {"slug":"roofless_ruins","score":0.42}]}
        self.assertEqual(atlas.decode("polyhaven",bad,limit=3,query="Roblox UI"),[])
        good = {"results":[{"slug":"mossy_rock","score":0.74},
                           {"slug":"lichen_rock","score":0.63}]}
        self.assertEqual(len(atlas.decode("polyhaven",good,limit=3,query="mossy rock")),2)

    def test_openverse_license_is_only_a_claim(self):
        payload = {"results":[
            {"id":"32471259-542b-49ea-b726-9ebf23e819b8",
             "title":"Tree", "license":"by", "license_version":"4.0",
             "creator":"Artist"},
            {"id":"id-bad","license":"cc0"}]}
        items = atlas.decode("openverse_images", payload, limit=3)
        self.assertEqual(len(items),1)
        self.assertEqual(items[0].license_claim,"CC-BY-4.0")
        self.assertTrue(items[0].review_required)

    def test_npm_only_valid_names(self):
        payload = {"objects":[{"package":{"name":"@org/some-tool",
            "description":"A plugin", "keywords":["editor"]}},
            {"package":{"name":"../malicious"}}]}
        found = atlas.decode("npm",payload,limit=5)
        self.assertEqual(len(found),1)
        self.assertEqual(found[0].license_claim,"unknown")
        self.assertIn("@org/some-tool",found[0].url)

    def test_openalex_does_not_conflate_open_metadata_with_rights(self):
        payload = {"results":[{"id":"https://openalex.org/W123",
            "title":"New animations", "authorships":[]}]}
        found = atlas.decode("openalex", payload, limit=1)
        self.assertEqual(found[0].kind,"research-paper")
        self.assertEqual(found[0].license_claim,"unknown")

    def test_freesound_requires_key_and_does_not_leak_it(self):
        with self.assertRaises(RuntimeError):
            atlas.discover("freesound", "game effects",env={})
        seen = {}
        def fake_fetch(url,headers=None):
            seen.update({"url":url,"headers":headers})
            return {"results":[{"id":42,"name":"Thump","tags":["impact"],"license":"https://creativecommons.org/publicdomain/zero/1.0/"}]}
        result = atlas.discover("freesound","game effects",env={"STAR_FREESOUND_API_TOKEN":"AbcdEF0123456789"},fetch=fake_fetch)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0].url,"https://freesound.org/s/42/")
        self.assertIn("Token ",seen["headers"]["Authorization"])
        self.assertNotIn("AbcdEF0123456789",json.dumps([vars(x) for x in result]))

    def test_provider_urls_are_fixed_and_queries_encoded(self):
        visited = []
        def fake(url,headers=None):
            visited.append(url)
            return {"items":[]}
        atlas.discover("github", "3d textures", fetch=fake)
        self.assertTrue(visited[0].startswith("https://api.github.com/search/repositories?"))
        self.assertIn("3d+textures",visited[0])
        self.assertTrue(atlas._host_is_allowed(visited[0]))

    def test_bad_structures_rejected(self):
        with self.assertRaises(ValueError):
            atlas.decode("github", [], limit=3)
        with self.assertRaises(ValueError):
            atlas.decode("polyhaven", {"results":{}},limit=3)
        with self.assertRaises(ValueError):
            atlas.decode("not-a-provider",{},limit=3)
        with self.assertRaises(ValueError):
            atlas.decode("github", {"items":[]},limit=99)

    def test_catalog_metadata_cleaning_drops_html(self):
        item = atlas._candidate("github","org/repo","<b>Code</b>",
             "<script>ignore this</script>\n tricks",
             "https://github.com/org/repo","code","MIT")
        self.assertNotIn("<",item.title+item.summary)
        self.assertEqual(item.title,"Code")

    def test_sqlite_upsert_no_auto_promote_and_offline_search(self):
        with TemporaryDirectory() as tmp:
            store = atlas.AtlasStore(Path(tmp)/"atlas.sqlite3")
            raw = {"items":[{"full_name":"org/shader", "name":"shader",
                   "description":"Roblox physics shader", "license":{"spdx_id":"MIT"}}]}
            found = atlas.decode("github",raw,limit=1)
            store.ingest(found)
            store.ingest(found)
            self.assertEqual(store.count(),1)
            self.assertEqual(len(store.search("physics")),1)
            self.assertEqual(store.search("does not exist"),[])
            with self.assertRaises(ValueError):
                store.search("100%_match")
            with self.assertRaises(ValueError):
                store.ingest([replace(found[0], promoted_as_learning=True)])
            self.assertEqual(store.count(),1)
            self.assertEqual(store.search("physics")[0]["review_required"],1)
            store.close()


if __name__ == "__main__":
    unittest.main()
