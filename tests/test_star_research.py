"""Trust-boundary regression tests for the research-upgraded STAR scaffold."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import pytest

from star.knowledge import KnowledgeStore
from star.orchestration import Task, TaskPlan, overlaps
from star.evals import load_catalog, summarize_verdicts


def test_knowledge_isolation_review_and_evidence():
    with TemporaryDirectory() as temp:
        store = KnowledgeStore(Path(temp))
        one = store.add_note(project="VALEN", kind="decision", text="Green trees with layered boughs", source="reviewer:1")
        two = store.add_note(project="BOOBOUND", kind="decision", text="Warm parchment shop", source="reviewer:2")
        assert store.find("VALEN", "trees") == []  # unreviewed AI notes never silently trusted
        assert store.find("VALEN", "trees", reviewed_only=False)[0].id == one
        with pytest.raises(ValueError):
            store.review_note(project="BOOBOUND", note_id=one, evidence="test")
        store.review_note(project="VALEN", note_id=one, evidence="Screenshot 10 verified")
        assert store.find("VALEN", "trees")[0].reviewed is True
        assert store.find("BOOBOUND", "trees", reviewed_only=False) == []
        assert store.find("VALEN", "parchment", reviewed_only=False) == []
        store.close()


def test_knowledge_artifacts_are_immutable_and_scoped():
    with TemporaryDirectory() as temp:
        root = Path(temp)
        reference = root / "ref.png"
        reference.write_bytes(b"very small bytes of fake fixture")
        store = KnowledgeStore(root / "data")
        sha, original = store.ingest_artifact(project="A", path=reference, origin="upload:1", media_type="image/png")
        assert original.read_bytes() == reference.read_bytes()
        reference.write_bytes(b"different future version")
        assert store.artifact("A", sha).read_bytes() == b"very small bytes of fake fixture"
        with pytest.raises(ValueError):
            store.artifact("B", sha)
        with pytest.raises(ValueError):
            store.artifact("A", "../../secrets")
        store.close()


def test_knowledge_bad_inputs():
    with TemporaryDirectory() as temp:
        store = KnowledgeStore(Path(temp))
        with pytest.raises(ValueError):
            store.add_note(project="A/../B", kind="decision", text="good", source="author")
        with pytest.raises(ValueError):
            store.add_note(project="A", kind="imaginary", text="good", source="author")
        with pytest.raises(ValueError):
            store.add_note(project="A", kind="decision", text="good", source="")
        store.close()


def test_dependency_and_ownership():
    tasks = [
        Task("inspect", "research", "Read source", reads=("star/ui",)),
        Task("edit_ui", "ui", "Edit GUI", dependencies=("inspect",), writes=("star/ui",)),
        Task("edit_other", "luau", "Edit economy", writes=("star/economy",)),
        Task("review", "review", "Check GUI", dependencies=("edit_ui",), reads=("star/ui",)),
    ]
    plan = TaskPlan(tasks, max_parallel=2)
    assert [t.id for t in plan.ready(set())] == ["inspect", "edit_other"]
    assert [t.id for t in plan.ready({"inspect"}, {"edit_other"})] == ["edit_ui"]
    assert [t.id for t in plan.ready({"inspect","edit_ui","edit_other"})] == ["review"]
    assert overlaps("star/ui", "star/ui/menu")
    assert not overlaps("star/ui", "star/uiverse")


def test_scheduler_refuses_write_vs_read_collision():
    tasks = [Task("observer", "review", "Read", reads=("shared",)),
             Task("writer", "ui", "Write", writes=("shared/file",))]
    plan = TaskPlan(tasks, max_parallel=2)
    assert [t.id for t in plan.ready(set())] == ["observer"]
    assert plan.ready(set(), {"observer"}) == []
    with pytest.raises(ValueError):
        TaskPlan([Task("a", "ui", "task", dependencies=("b",)),Task("b", "ui", "task", dependencies=("a",))])
    with pytest.raises(ValueError):
        Task("a", "ui", "task", writes=("../../secret",))


def test_eval_catalog_is_not_claimed_as_executed():
    catalog = load_catalog(Path(__file__).resolve().parents[1]/"evals"/"roblox_cases.json")
    assert len(catalog) >= 20
    results = summarize_verdicts(catalog, {catalog[0].id: "passed", catalog[1].id: "blocked"})
    assert results["counts"]["passed"] == 1
    assert results["counts"]["not_run"] == len(catalog) - 2
    with pytest.raises(ValueError):
        summarize_verdicts(catalog, {"fabricated": "passed"})


def test_selfbuilder_cannot_modify_skill_init():
    from star.selfbuild import skill_path
    assert not skill_path("star/skills/__init__.py")


def test_artifact_corruption_detected():
    with TemporaryDirectory() as temp:
        root = Path(temp)
        p = root / "ref.png"
        p.write_bytes(b"original")
        memory = KnowledgeStore(root / "store")
        digest, immutable = memory.ingest_artifact(project="A", path=p, origin="upload:1", media_type="image/png")
        immutable.write_bytes(b"tampered")
        with pytest.raises(ValueError, match="checksum"):
            memory.artifact("A", digest)
        memory.close()


def test_knowledge_like_wildcards_are_not_injections():
    with TemporaryDirectory() as temp:
        store = KnowledgeStore(Path(temp))
        store.add_note(project="A", kind="decision", text="hello world", source="approved ref")
        assert store.find("A", "hello_world", reviewed_only=False) == []
        assert store.find("A", "hello", reviewed_only=False)
        store.close()


def test_task_rejects_invalid_scope_and_missing_dependencies():
    with pytest.raises(ValueError):
        Task("weird/path", "ui", "Goal")
    with pytest.raises(ValueError):
        Task("id", "not_a_role", "Goal")
    with pytest.raises(ValueError):
        TaskPlan([Task("a", "ui", "Goal", dependencies=("nope",))])
    with pytest.raises(ValueError):
        TaskPlan([Task("a", "ui", "Goal")], max_parallel=0)


def test_github_token_restricted_to_one_private_repo(monkeypatch):
    import asyncio
    from star.github_app import GitHubApp
    from star.repository_roles import SOURCE_REPO, RELEASE_REPO
    from star import github_app as gh
    from datetime import datetime, timezone, timedelta

    recorded = {}
    class FakeResponse:
        def raise_for_status(self): pass
        def json(self):
            return {"token":"short-lived-test-token", "expires_at":(datetime.now(timezone.utc)+timedelta(minutes=59)).isoformat()}
    class FakeClient:
        def __init__(self, *, timeout, trust_env, follow_redirects):
            recorded["client_settings"] = {"timeout":timeout,"trust_env":trust_env,"follow_redirects":follow_redirects}
        async def __aenter__(self): return self
        async def __aexit__(self,*args): return False
        async def post(self, url, *, headers, json):
            recorded.update({"url":url,"json":json})
            return FakeResponse()

    monkeypatch.setattr(gh.jwt, "encode", lambda *a, **k: "signed-jwt-fixture")
    monkeypatch.setattr(gh.httpx, "AsyncClient", FakeClient)
    with TemporaryDirectory() as temp:
        key = Path(temp) / "test.pem"
        key.write_text("fixture, never a real secret",encoding="utf8")
        bot = GitHubApp("123", "456", key, SOURCE_REPO)
        assert asyncio.run(bot._install_token()) == "short-lived-test-token"
        assert recorded["json"] == {"repositories":["Star-AI-Private"],
                                     "permissions":{"contents":"write","pull_requests":"write"}}
        assert recorded["client_settings"] == {"timeout":30,"trust_env":False,"follow_redirects":False}
        recorded.clear()
        public = GitHubApp("123", "456", key, RELEASE_REPO)
        with pytest.raises(PermissionError):
            asyncio.run(public._install_token())
        assert recorded == {}  # No private developer token is minted for public distribution.


def test_selfbuilder_protects_security_and_research_documents():
    from star.selfbuild import skill_path
    assert not skill_path("docs/SECURITY_AND_AUTONOMY.md")
    assert not skill_path("docs/GITHUB_APP_SETUP.md")
    assert not skill_path("docs/FRONTIER_RESEARCH_VOL2.md")
    assert skill_path("docs/skills/approved_skill_guide.md")


def test_github_app_source_writes_restricted_to_canonical_repo(tmp_path):
    """An agent cannot accidentally write a development branch in another repo."""
    import asyncio
    from star.github_app import GitHubApp
    key=tmp_path/"test.pem"
    key.write_text("non-secret test fixture")
    app=GitHubApp("123", "456", key, "someone/other-repo")
    with pytest.raises(PermissionError):
        asyncio.run(app.create_branch("star/demo"))
    with pytest.raises(PermissionError):
        asyncio.run(app.write_branch_file("star/demo", "README.md", b"fixture", "test"))
    with pytest.raises(PermissionError):
        asyncio.run(app.open_pr("main", "star/demo", "test", "test"))
