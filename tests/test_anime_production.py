"""Structural validator for examples/anime_production (and its `star anime-check` command)."""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
from pathlib import Path

import pytest

from star import cli
from star.anime_production import check_file, main, validate_benchmark, validate_cues_csv, validate_pilot

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "anime_production"
PILOT = json.loads((EXAMPLES / "pilot.json").read_text(encoding="utf-8"))
BENCHMARK = json.loads((EXAMPLES / "benchmark_template.json").read_text(encoding="utf-8"))
CUES = (EXAMPLES / "pilot_cues.csv").read_text(encoding="utf-8")


def mutated(base, change):
    data = copy.deepcopy(base)
    change(data)
    return data


def test_shipped_examples_are_valid_and_the_csv_matches_the_plan():
    assert validate_pilot(PILOT) == []
    assert validate_benchmark(BENCHMARK) == []
    assert validate_cues_csv(CUES, PILOT) == []


@pytest.mark.parametrize(("change", "expected"), [
    (lambda d: d["shots"][3].update(start_frame=500), "gap or overlap"),
    (lambda d: d.update(total_frames=2000), "total_frames"),
    (lambda d: d["shots"][0].update(visible_cast=["miko", "nobody"]), "unknown: nobody"),
    (lambda d: d["shots"][1].update(cut_id="c01"), "duplicate cut_id"),
    (lambda d: d["dialogue_cues"][0].update(character_id="nobody"), "unknown character"),
    (lambda d: d["dialogue_cues"][0].update(target_end_frame_exclusive=400), "outside cut"),
    (lambda d: d["dialogue_cues"][2].update(target_start_frame=200), "speaks over themselves"),
    (lambda d: d["dialogue_cues"][0].update(audio_sha256="abc"), "SHA-256"),
    (lambda d: d["dialogue_cues"][0].update(selected_take_id="take-1"), "must not name a selected take"),
    (lambda d: d.update(generated_media=["x.mp4"]), "no generated_media"),
    (lambda d: d["timebase"].update(frame_range_convention="closed"), "half_open"),
    (lambda d: d.update(schema_version=True), "schema_version"),
])
def test_pilot_problems_are_reported(change, expected):
    errors = validate_pilot(mutated(PILOT, change))
    assert any(expected in error for error in errors), errors


def test_cue_sheet_must_agree_with_the_plan():
    edited = CUES.replace("Tell me that's our platform.", "Tell me that is our platform.")
    assert any("text differs" in e for e in validate_cues_csv(edited, PILOT))
    assert any("missing from the cue sheet" in e for e in validate_cues_csv("\n".join(CUES.splitlines()[:-1]), PILOT))
    assert validate_cues_csv("cue_id,cut_id\nd01,c02\n") != []


@pytest.mark.parametrize(("change", "expected"), [
    (lambda d: d["runs"].append({"test_id": "dialogue_handoff"}), "no runs"),
    (lambda d: d.update(summary={"fastest": "route-a"}), "null summary"),
    (lambda d: d.update(initial_take_limit_per_route=9), "initial_take_limit_per_route"),
    (lambda d: d["screen_tests"].append(dict(d["screen_tests"][0])), "duplicate test_id"),
    (lambda d: d["measurement_fields"].pop("billing"), "measurement_fields"),
    (lambda d: d.update(human_review_required="yes"), "human_review_required"),
])
def test_benchmark_problems_are_reported(change, expected):
    errors = validate_benchmark(mutated(BENCHMARK, change))
    assert any(expected in error for error in errors), errors


def test_a_run_benchmark_may_hold_runs_for_known_tests_only():
    run = mutated(BENCHMARK, lambda d: d.update(status="run", runs=[{"test_id": "quiet_reaction"}]))
    assert validate_benchmark(run) == []
    bad = mutated(BENCHMARK, lambda d: d.update(status="run", runs=[{"test_id": "other"}]))
    assert validate_benchmark(bad) != []


def test_check_file_picks_the_validator_by_kind_and_exit_codes_follow(tmp_path, capsys):
    assert check_file(EXAMPLES / "pilot.json") == ("pilot", [])
    assert check_file(EXAMPLES / "benchmark_template.json") == ("benchmark", [])
    assert main([str(EXAMPLES / "pilot_cues.csv"), "--plan", str(EXAMPLES / "pilot.json")]) == 0
    broken = tmp_path / "pilot.json"
    broken.write_text(json.dumps(mutated(PILOT, lambda d: d.update(total_frames=1))), encoding="utf-8")
    assert main([str(broken)]) == 1
    assert main([str(tmp_path / "missing.json")]) == 2
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["error"].startswith("FileNotFoundError")


def test_star_anime_check_command(capsys, tmp_path, monkeypatch):
    seen, real_main = [], cli.main

    async def fake_main(args):
        seen.append(args)

    monkeypatch.setattr("sys.argv", ["star", "anime-check", str(EXAMPLES / "pilot_cues.csv"), "--plan", "p.json"])
    monkeypatch.setattr(cli, "setup", lambda: None)
    monkeypatch.setattr(cli, "main", fake_main)
    cli.cli()
    assert (seen[0].command, seen[0].plan) == ("anime-check", "p.json")
    ok = argparse.Namespace(command="anime-check", file=str(EXAMPLES / "pilot.json"), plan=None)
    asyncio.run(real_main(ok))
    assert json.loads(capsys.readouterr().out)["valid"] is True
    broken = tmp_path / "pilot.json"
    broken.write_text(json.dumps(mutated(PILOT, lambda d: d.update(total_frames=1))), encoding="utf-8")
    with pytest.raises(SystemExit) as stop:
        asyncio.run(real_main(argparse.Namespace(command="anime-check", file=str(broken), plan=None)))
    assert stop.value.code == 1
