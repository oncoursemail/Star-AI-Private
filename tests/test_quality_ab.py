"""Arms of the quality A/B (docs/agents/quality-ab-20261020.md): `--set` on the eval runner and the opt-in slop repair
(slop_check=repair). The model is scripted: no network, no real brain."""
import argparse
import asyncio
import contextlib
from time import monotonic
from types import SimpleNamespace

import pytest

from star import slop
from star.desktop_core import Settings
from star.doc_grounding import Grounding, GroundingPlan, finalize

INVENTED = ("Here:\n\n```luau\nlocal Lighting = game:GetService(\"Lighting\")\nlocal atmo = Instance.new(\"Atmosphere\")\n"
            "atmo.SunInfluence = 0.5\natmo.Parent = Lighting\n```\n")
FIXED = INVENTED.replace("atmo.SunInfluence = 0.5", "atmo.Density = 0.5")


class ScriptedModel:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.replies.pop(0)))])


def run(answer, mode, model, events=None):
    found = Grounding(status="off", plan=GroundingPlan(retrieve="none", passages=0, max_chars=0, check_luau=False),
                      client=None, passages=[])
    route = SimpleNamespace(quick=False, task_timeout=600, model="star-fast", response_tokens=1600)
    messages = [{"role": "assistant", "content": answer}]
    return asyncio.run(finalize(found, route, (answer, messages, []), model_client=model, prompt="Add fog",
                                started=monotonic(), on_event=events.append if events is not None else None,
                                settings=SimpleNamespace(slop_check=mode)))


def test_repair_names_the_exact_finding_and_the_real_members_and_keeps_a_better_revision():
    model, events = ScriptedModel(FIXED), []
    answer, messages, archive = run(INVENTED, "repair", model, events)
    assert len(model.calls) == 1
    request = model.calls[0]["messages"][1]["content"]
    assert "line 6: possible unknown member SunInfluence of Atmosphere (C08.unknown_member)" in request
    assert "Atmosphere: " in request and "Density" in request
    assert answer == FIXED and messages[-1]["content"] == FIXED
    assert archive[-1]["star_slop"]["repair"]["accepted"] is True and archive[-1]["star_slop"]["score"] == 0
    assert {"event": "slop_repair", "accepted": True} in events


@pytest.mark.parametrize("reply, why", [(INVENTED, "not better"), ("Use Density.", "lost a code block"),
                                        ("```luau\nlocal atmo = 1\n", "cut off")])
def test_a_revision_that_is_not_strictly_better_or_loses_code_is_dropped(reply, why):
    answer, _, archive = run(INVENTED, "repair", ScriptedModel(reply))
    assert answer.startswith(INVENTED.rstrip()) and archive[-1]["star_slop"]["repair"]["accepted"] is False
    assert why.split()[-1] in archive[-1]["star_slop"]["repair"]["rejected"]


def test_no_repair_call_for_a_clean_answer_or_outside_repair_mode():
    for answer, mode in ((FIXED, "repair"), (INVENTED, "flag"), (INVENTED, "off")):
        model = ScriptedModel()
        run(answer, mode, model)
        assert model.calls == []


def test_a_failed_repair_call_keeps_the_answer():
    class Broken(ScriptedModel):
        async def create(self, **kwargs):
            raise OSError("server down")
    answer, _, archive = run(INVENTED, "repair", Broken())
    assert answer.startswith(INVENTED.rstrip()) and archive[-1]["star_slop"]["repair"]["error"] == "OSError"


def test_repair_is_a_valid_setting_and_the_note_is_never_scored_as_the_models_text():
    Settings(slop_check="repair").validate()
    noted = FIXED.rstrip() + slop.NOTE_MARKER + " the answer claims the code was tested; STAR did not run it.\n"
    assert slop.score_answer(noted).score == 0


def test_eval_runner_set_records_the_arm_and_passes_it_to_the_task(monkeypatch, tmp_path):
    from star import desktop_core, doc_knowledge, eval_runner
    assert eval_runner.parse_sets(["api_hints_enabled=true", "slop_check=repair", "luau_retry_ladder=False"]) == {
        "api_hints_enabled": True, "slop_check": "repair", "luau_retry_ladder": False}
    for bad in ("model=x", "server_endpoint=http://x", "api_hints_enabled"):
        with pytest.raises(SystemExit):
            eval_runner.parse_sets([bad])
    seen = {}
    monkeypatch.setattr(eval_runner, "read_key", lambda path: "test-key")
    monkeypatch.setattr(eval_runner, "served_models", lambda server, key: ["star-fast"])
    monkeypatch.setattr(eval_runner, "git_state", lambda: {})
    monkeypatch.setattr(doc_knowledge, "client_for", lambda settings: object())
    monkeypatch.setattr(desktop_core, "run_task", lambda settings, prompt, **kw: seen.setdefault("s", settings) and "ok")
    monkeypatch.setattr(eval_runner, "isolated_appdata", lambda: contextlib.nullcontext())
    monkeypatch.setenv("STAR_BACKGROUND_WORK", "0")
    infos = []
    for sets in ([], ["api_hints_enabled=true"]):
        seen.clear()
        args = argparse.Namespace(key_file=str(tmp_path / "k"), packs="off", server="http://127.0.0.1:8080/v1",
                                  ssh="", model="star-fast", mode="auto", pin_model=False, set=sets, _suite=None)
        run_info, ask, *_ = eval_runner.build_real(args)
        ask({"id": "LUA-01", "prompt": "hi"})
        assert seen["s"].api_hints_enabled is bool(sets)
        infos.append(run_info)
    assert "settings" not in infos[0] and infos[1]["settings"] == {"api_hints_enabled": True}
    assert infos[0]["fingerprint"] != infos[1]["fingerprint"]
    with pytest.raises(ValueError, match="Slop check"):
        eval_runner.build_real(argparse.Namespace(**{**vars(args), "set": ["slop_check=loud"]}))
