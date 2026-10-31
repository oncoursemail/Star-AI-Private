"""LocalIntelligence opt-in integration for the operational self-audit.

No network, GPU, Roblox Studio, account credentials, or model is used.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import asyncio
import json
import unittest

from star.agent import execute
from star.intelligence import LocalIntelligence


def make_hub(home: Path, *, enabled: bool) -> LocalIntelligence:
    return LocalIntelligence(
        home=home, skills_enabled=False, graphify_enabled=False,
        roblox_research_enabled=False, design_enabled=True, map_plans_enabled=True,
        studio_lab_enabled=False, asset_forge_enabled=False,
        awareness_enabled=enabled,
    )


class IntegrationTests(unittest.TestCase):
    def test_adapter_is_off_without_opt_in(self):
        with TemporaryDirectory() as tmp:
            hub = make_hub(Path(tmp), enabled=False)
            names = [t["name"] for t in hub.definitions("What are your capabilities?")]
            self.assertNotIn("star_self_capabilities", names)
            self.assertFalse(hub.status()["operational_awareness"]["enabled"])
            hub.close()

    def test_adapter_attaches_only_for_relevant_prompt(self):
        with TemporaryDirectory() as tmp:
            hub = make_hub(Path(tmp), enabled=True)
            self.assertFalse(any(t["name"].startswith("star_self") for t in hub.definitions("Hi")))
            names = [t["name"] for t in hub.definitions("What are your capabilities?")]
            self.assertIn("star_self_capabilities", names)
            names_for_game = [t["name"] for t in hub.definitions(
                "Create a beautiful 3v3 animal shooter game with physics")]
            self.assertIn("star_self_capabilities",names_for_game)
            self.assertIn("star_self_improvement_plan", names)
            hub.close()

    def test_live_intelligence_dispatch_is_read_only_and_honest(self):
        with TemporaryDirectory() as tmp:
            hub = make_hub(Path(tmp), enabled=True)
            prompt = "How can you improve at making a parkour game?"
            allowed = {t["name"] for t in hub.definitions(prompt)}
            self.assertIn("star_self_capabilities", allowed)
            audit = hub.call("star_self_capabilities",{"goal":"make a parkour game"},enabled=allowed)
            self.assertEqual(audit["identity"],"STAR operational self-model (not consciousness)")
            self.assertFalse(audit["self_authorized_permissions"])
            self.assertFalse(audit["work_performed"])
            self.assertGreaterEqual(len(audit["dimensions"]), 7)
            plan = hub.call("star_self_improvement_plan",
                            {"goal":"make a parkour game","limit":3},enabled=allowed)
            self.assertEqual(len(plan["experiments"]),3)
            self.assertTrue(plan["all_actions_proposed_only"])
            self.assertEqual(plan["started"], [])
            self.assertFalse((Path(tmp)/"resource_atlas.sqlite3").exists())
            hub.close()

    def test_missing_schema_authorization_is_refused_even_when_adapter_on(self):
        with TemporaryDirectory() as tmp:
            hub = make_hub(Path(tmp), enabled=True)
            with self.assertRaises(PermissionError):
                hub.call("star_self_capabilities",{"goal":"make a parkour game"},
                         enabled=set())
            hub.close()

    def test_adapter_cannot_be_forced_by_model_if_disabled(self):
        with TemporaryDirectory() as tmp:
            hub = make_hub(Path(tmp), enabled=False)
            with self.assertRaises(PermissionError):
                hub.call("star_self_capabilities",{"goal":"make a parkour game"},
                         enabled={"star_self_capabilities"})
            hub.close()

    def test_closed_adapter_rejects_calls(self):
        with TemporaryDirectory() as tmp:
            hub = make_hub(Path(tmp), enabled=True)
            hub.close()
            with self.assertRaises(PermissionError):
                hub.call("star_self_capabilities",{"goal":"make a parkour game"},
                         enabled={"star_self_capabilities"})

    def test_schema_rejects_extra_mutation_arguments(self):
        with TemporaryDirectory() as tmp:
            hub = make_hub(Path(tmp), enabled=True)
            allowed = {"star_self_capabilities"}
            with self.assertRaises(Exception):
                hub.call("star_self_capabilities",
                         {"goal":"make a parkour game", "execute": True}, enabled=allowed)
            hub.close()

    def test_actual_agent_dispatch_reads_audit_without_running_a_job(self):
        class Answers:
            def __init__(self):
                self.requests = []
            async def create(self, **kwargs):
                self.requests.append(kwargs)
                if len(self.requests) == 1:
                    msg = SimpleNamespace(content="", tool_calls=[
                        SimpleNamespace(id="audit-1", function=SimpleNamespace(
                            name="star_self_capabilities",
                            arguments=json.dumps({"goal": "make a parkour game"})))])
                else:
                    msg = SimpleNamespace(content="I still need to test my Studio workflow.",tool_calls=None)
                return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

        async def run():
            with TemporaryDirectory() as tmp:
                host = make_hub(Path(tmp), enabled=True)
                model = Answers()
                client = SimpleNamespace(chat=SimpleNamespace(
                    completions=model))
                answer, messages, archived = await execute(
                    client=client, model="local", prompt="What can you build? Make a parkour game",
                    image_paths=[], intelligence=host, now="", stream_tokens=False)
                self.assertIn("test", answer)
                functions = {t["function"]["name"] for t in model.requests[0]["tools"]}
                self.assertIn("star_self_capabilities",functions)
                # The actual model request gets a bounded self-audit reference
                # without having to ask for or run this tool first.
                first_request = json.dumps(model.requests[0]["messages"], ensure_ascii=False)
                self.assertIn("STAR capability preflight",first_request)
                self.assertIn("Tool availability is not competence",first_request)
                self.assertIn("cannot change permissions",first_request)
                receipts = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
                self.assertEqual(len(receipts),1)
                self.assertFalse(receipts[0]["isError"])
                inner = json.loads(receipts[0]["output"])
                self.assertEqual(inner["identity"],"STAR operational self-model (not consciousness)")
                self.assertFalse(inner["work_performed"])
                self.assertEqual(archived,[])
                host.close()
        asyncio.run(run())

    def test_model_cannot_invoke_undeclared_self_audit(self):
        class Answers:
            def __init__(self):
                self.calls = 0
            async def create(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    msg = SimpleNamespace(content="",tool_calls=[
                        SimpleNamespace(id="audit-2",function=SimpleNamespace(
                            name="star_self_capabilities",
                            arguments=json.dumps({"goal":"make a parkour game"})))])
                else:
                    msg = SimpleNamespace(content="Not enabled.",tool_calls=None)
                return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

        async def run():
            with TemporaryDirectory() as tmp:
                host = make_hub(Path(tmp),enabled=False)
                model = Answers()
                client = SimpleNamespace(chat=SimpleNamespace(completions=model))
                answer, messages, _ = await execute(
                    client=client, model="local",prompt="Make a parkour game",
                    image_paths=[], intelligence=host, now="", stream_tokens=False)
                receipts = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
                self.assertEqual(len(receipts),1)
                self.assertTrue(receipts[0]["isError"])
                self.assertIn("rejected",receipts[0]["output"].lower())
                host.close()
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
