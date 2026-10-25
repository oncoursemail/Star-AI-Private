from __future__ import annotations

import pytest

from star import general_knowledge_lab as lab
from star import intelligence


def test_physics_research_map_explains_tests_not_fake_retrieval():
    result = lab.plan("How do collisions and motion affect game physics?", max_domains=4)
    assert result["not_fetched"] is True
    assert result["model_parameters_updated"] is False
    assert result["status"] == "research_plan_only"
    assert {"physics", "gamedev"} <= {task["domain"] for task in result["tasks"]}
    for task in result["tasks"]:
        assert task["source_status"] == "suggested_not_retrieved"
        assert task["source_url"].startswith("https://")
        assert task["transfer_test"]
        assert len(task["checkpoints"]) >= 4


def test_broad_topic_spans_multiple_domains():
    result = lab.plan("Give me a comprehensive general knowledge curriculum", max_domains=8)
    assert result["domain_count"] == 8
    assert len({item["domain"] for item in result["tasks"]}) == 8
    assert result["not_fetched"]


def test_research_curriculum_is_prompt_gated_and_read_only(tmp_path):
    agent = intelligence.LocalIntelligence(
        home=tmp_path, skills_enabled=False, graphify_enabled=False,
        roblox_research_enabled=False,
    )
    try:
        names = {x["name"] for x in agent.definitions("Create a general knowledge curriculum")}
        assert "star_general_knowledge_curriculum" in names
        output = agent.call("star_general_knowledge_curriculum",
                            {"topic": "Learn mathematics and geometry",
                             "max_domains": 2}, enabled=names)
        assert output["domain_count"] <= 2
        assert output["not_fetched"]
        assert "star_general_knowledge_curriculum" not in {
            x["name"] for x in agent.definitions("Say hello")
        }
    finally:
        agent.close()


@pytest.mark.parametrize("topic,limit", [("", 3), ("a", 2), ("x" * 501, 2),
                                         ("Knowledge curriculum", 0), ("Learning", 9),
                                         ("Learning", True)])
def test_research_map_rejects_malformed_scope(topic, limit):
    with pytest.raises(ValueError):
        lab.plan(topic, max_domains=limit)
