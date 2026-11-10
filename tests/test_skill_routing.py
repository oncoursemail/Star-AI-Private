"""Opt-in skill-pack routing by embedding similarity (star/skill_routing.py). The embedder is scripted."""
import asyncio
import json

import pytest

from star import skill_packs, skill_routing
from star.desktop_core import Settings

ALL = frozenset(p.name for p in skill_packs.available())
NO_TRIGGER = "Players in my Roblox game sometimes lose their progress when the server shuts down. How do I fix it?"


class Embedder:
    """Scripted vectors with a canary signature that changes when model weights change."""

    def __init__(self, near="roblox-datastore-safety", fail=None, revision="v1", switch_after=None):
        self.near, self.fail, self.revision, self.switch_after = near, fail, revision, switch_after
        self.calls = []

    async def __call__(self, texts):
        self.calls.append(list(texts))
        if self.fail:
            raise self.fail
        revision = self.revision
        if self.switch_after is not None and len(self.calls) > self.switch_after:
            revision = "v2"
        canaries = {skill_routing.QUERY_PREFIX + probe for probe in skill_routing.FINGERPRINT_PROBES}
        out = []
        for text in texts:
            if text in canaries:
                out.append([1.0, 0.0] if revision == "v1" else [0.0, 1.0])
            elif text.startswith(skill_routing.QUERY_PREFIX) or self.near.replace("-", " ") in text:
                out.append([1.0, 0.0])
            else:
                out.append([0.0, 1.0])
        return out


def run(coro):
    return asyncio.run(coro)


def test_off_by_default():
    assert Settings().skill_pack_embeddings is False


def test_a_prompt_without_trigger_words_gets_the_closest_pack(tmp_path):
    assert skill_packs.select(NO_TRIGGER, enabled=ALL) == []                     # the keyword router is silent
    embed = Embedder()
    chosen = run(skill_routing.select(NO_TRIGGER, embed, enabled=ALL, home=tmp_path))
    assert [p.name for p in chosen] == ["roblox-datastore-safety"]


def test_the_keyword_router_wins_when_it_has_an_answer(tmp_path):
    prompt = "Roblox: how do I validate RemoteEvent arguments on the server against exploiters?"
    keyword = skill_packs.select(prompt, enabled=ALL)
    assert keyword
    embed = Embedder()
    assert run(skill_routing.select(prompt, embed, enabled=ALL, home=tmp_path)) == keyword
    assert embed.calls == []                                                     # no server call at all


def test_prompts_outside_the_context_rules_never_reach_the_embedder(tmp_path):
    embed = Embedder()
    assert run(skill_routing.select("How do I bake bread?", embed, enabled=ALL, home=tmp_path)) == []
    assert run(skill_routing.select(NO_TRIGGER, embed, enabled=frozenset(), home=tmp_path)) == []
    assert embed.calls == []


def test_nothing_close_enough_means_no_pack(tmp_path):
    embed = Embedder(near="no-such-pack")
    assert run(skill_routing.select(NO_TRIGGER, embed, enabled=ALL, home=tmp_path)) == []


def test_server_problems_fall_back_to_the_keyword_answer_and_are_reported(tmp_path):
    reasons = []
    for failure in (ConnectionError("unreachable"), asyncio.TimeoutError()):
        embed = Embedder(fail=failure)
        assert run(skill_routing.select(NO_TRIGGER, embed, enabled=ALL, home=tmp_path,
                                        on_fallback=reasons.append)) == []
    assert reasons == ["ConnectionError", "TimeoutError"]

    async def odd(texts):
        return [[1.0]]                                                           # wrong count
    assert run(skill_routing.select(NO_TRIGGER, odd, enabled=ALL, home=tmp_path)) == []


def test_pack_vectors_are_cached_and_query_is_paired_with_fixed_canaries(tmp_path):
    first = Embedder()
    run(skill_routing.select(NO_TRIGGER, first, enabled=ALL, home=tmp_path))
    query_and_canaries = [
        skill_routing.QUERY_PREFIX + NO_TRIGGER,
        *(skill_routing.QUERY_PREFIX + probe for probe in skill_routing.FINGERPRINT_PROBES),
    ]
    canary_only = [skill_routing.QUERY_PREFIX + probe for probe in skill_routing.FINGERPRINT_PROBES]
    assert len(first.calls) == 3
    assert first.calls[0] == query_and_canaries
    assert len(first.calls[1]) > 1                                      # missing pack documents
    assert first.calls[2] == canary_only
    cache = json.loads((tmp_path / skill_routing.CACHE_FILE).read_text(encoding="utf-8"))
    assert len(cache) == len(first.calls[1])
    second = Embedder()
    run(skill_routing.select(NO_TRIGGER, second, enabled=ALL, home=tmp_path))
    assert second.calls == [query_and_canaries]                         # canary fingerprint hits cache


def test_cache_invalidates_when_weights_change_behind_the_same_model_alias(tmp_path):
    first = Embedder(revision="v1")
    run(skill_routing.select(NO_TRIGGER, first, enabled=ALL, home=tmp_path))
    second = Embedder(revision="v2")
    run(skill_routing.select(NO_TRIGGER, second, enabled=ALL, home=tmp_path))
    assert len(second.calls) == 3
    assert len(second.calls[1]) > 1                                     # old alias, new embedding space
    third = Embedder(revision="v2")
    run(skill_routing.select(NO_TRIGGER, third, enabled=ALL, home=tmp_path))
    assert len(third.calls) == 1


def test_invalid_cached_vectors_are_reembedded_and_bad_live_vectors_fall_back(tmp_path):
    first = Embedder()
    run(skill_routing.select(NO_TRIGGER, first, enabled=ALL, home=tmp_path))
    cache_path = tmp_path / skill_routing.CACHE_FILE
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    key = next(iter(cache))
    cache[key] = [float("nan"), 0.0]
    cache_path.write_text(json.dumps(cache), encoding="utf-8")
    second = Embedder()
    run(skill_routing.select(NO_TRIGGER, second, enabled=ALL, home=tmp_path))
    assert len(second.calls) == 3
    assert len(second.calls[1]) == 1                                     # only the corrupt entry is rebuilt

    async def nonfinite(texts):
        return [[float("nan"), 0.0] for _ in texts]
    assert run(skill_routing.select(NO_TRIGGER, nonfinite, enabled=ALL, home=tmp_path)) == []


def test_embedding_model_change_during_refresh_does_not_write_mixed_vectors(tmp_path):
    embed = Embedder(switch_after=2)
    with pytest.raises(RuntimeError, match="changed during"):
        run(skill_routing.rank(NO_TRIGGER, embed, allowed=ALL, cache_dir=tmp_path))
    assert not (tmp_path / skill_routing.CACHE_FILE).exists()


def test_embedding_vectors_reject_bool_nonfinite_and_mixed_dimensions():
    with pytest.raises(ValueError, match="finite"):
        skill_routing._vectors([[True, 0.0]], 1)
    with pytest.raises(ValueError, match="finite"):
        skill_routing._vectors([[float("inf"), 0.0]], 1)
    with pytest.raises(ValueError, match="inconsistent dimensions"):
        skill_routing._vectors([[1.0, 0.0], [1.0]], 2)
    assert skill_routing._cached_vector([1.0], 2) is None


@pytest.mark.parametrize("value", [None, "yes", 1])
def test_the_setting_is_a_strict_boolean_and_saved_by_the_desktop(value):
    with pytest.raises(ValueError):
        Settings(model="m", skill_pack_embeddings=value).validate()
    from star.react_shell import PERMITTED_SETTINGS
    assert "skill_pack_embeddings" in PERMITTED_SETTINGS


@pytest.mark.parametrize(("enabled", "provider", "embedded"), [
    (True, "star_server", True), (False, "star_server", False), (True, "local", False)])
def test_run_task_asks_star_server_for_embeddings_only_when_opted_in(tmp_path, monkeypatch, enabled, provider, embedded):
    from types import SimpleNamespace
    import star.desktop_core as core
    import star.doc_grounding as doc_grounding
    from tests.test_wave3_integration import FLEET, KEY, Models, reply
    from star import server_roles
    lan = "http://192.168." + "1.20:8080/v1"
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("STAR_SERVER_API_KEY", KEY)
    monkeypatch.setenv(skill_packs.ENV_VAR, "all")
    models, asked = Models(), []
    models.responses.append(reply("Done.", model="star-fast"))

    async def embeddings(*, model, **kwargs):
        inputs = kwargs["input"]
        asked.append((model, list(inputs)))
        vectors = [[1.0, 0.0] if t.startswith(skill_routing.QUERY_PREFIX) or "datastore safety" in t else [0.0, 1.0]
                   for t in inputs]
        return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=v) for i, v in enumerate(vectors)])

    class Client:
        def __init__(self):
            self.chat = SimpleNamespace(completions=models)
            self.embeddings = SimpleNamespace(create=embeddings)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False
    monkeypatch.setattr(core, "open_client", lambda settings, **_: Client())
    monkeypatch.setattr(doc_grounding, "client_for", lambda settings: None)
    fields = {"provider": "star_server", "server_endpoint": lan} if provider == "star_server" else {}
    if provider == "star_server":
        server_roles.remember_models(lan, FLEET)
    settings = Settings(model="star-fast", skill_pack_embeddings=enabled, **fields)
    events = []
    try:
        core.run_task(settings, NO_TRIGGER, mode="auto", on_event=events.append)
    finally:
        server_roles.forget()
    assert bool(asked) is embedded
    sent = json.dumps(models.requests[-1]["messages"][-1])
    assert ("Save Roblox player data" in sent or "DataStore" in sent) is embedded
    if embedded:
        assert asked[0][0] == skill_routing.EMBED_MODEL
        assert next(e for e in events if e["event"] == "skill_packs")["names"] == ["roblox-datastore-safety"]