"""Structural validator for the anime production planning files in examples/anime_production.

Checks the pilot plan (pilot.json), its cue sheet (pilot_cues.csv) and the benchmark record
(benchmark_template.json) for the invariants docs/research/STAR_ANIME_PILOT_AND_BENCHMARK.md states:
contiguous half-open frame ranges, known characters, cue windows inside their cuts, CSV and JSON
agreeing, and no measured result recorded for a benchmark that was never run. Reads local files only;
it does not judge the creative content or inspect media.
"""
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import TypeGuard

MAX_BYTES = 2_000_000
CSV_FIELDS = ("cue_id", "cut_id", "character_id", "target_start_frame", "target_end_frame_exclusive",
              "text", "direction", "delivery_route", "review_status")
BENCHMARK_GROUPS = ("configuration", "evidence", "time", "billing", "quality")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _int(value: object) -> TypeGuard[int]:
    return type(value) is int and not isinstance(value, bool)


def _str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _frames(item: dict, start_key: str, end_key: str, where: str, errors: list[str]) -> bool:
    start, end = item.get(start_key), item.get(end_key)
    if not (_int(start) and _int(end) and 0 <= start < end):
        errors.append(f"{where}: {start_key}/{end_key} must be integers with 0 <= start < end")
        return False
    return True


def _unique_ids(items: list, key: str, where: str, errors: list[str]) -> dict:
    found: dict = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict) or not _str(item.get(key)):
            errors.append(f"{where}[{index}]: needs a non-empty {key}")
        elif item[key] in found:
            errors.append(f"{where}: duplicate {key} {item[key]!r}")
        else:
            found[item[key]] = item
    return found


def _list(data: dict, key: str, errors: list[str]) -> list:
    value = data.get(key)
    if not isinstance(value, list):
        errors.append(f"{key} must be a list")
        return []
    return value


def validate_pilot(data: object) -> list[str]:
    """Return the problems found in a pilot plan; an empty list means structurally valid."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["pilot plan must be a JSON object"]
    if data.get("schema_version") != 1 or type(data.get("schema_version")) is not int:
        errors.append("schema_version must be 1")
    if data.get("kind") != "anime_development_plan":
        errors.append("kind must be 'anime_development_plan'")
    timebase = data.get("timebase")
    rate = timebase if isinstance(timebase, dict) else {}
    numerator, denominator = rate.get("fps_numerator"), rate.get("fps_denominator")
    if not (_int(numerator) and numerator > 0 and _int(denominator) and denominator > 0
            and rate.get("frame_range_convention") == "half_open"):
        errors.append("timebase needs positive integer fps_numerator/fps_denominator and half_open ranges")
    total = data.get("total_frames")
    if not (_int(total) and total > 0):
        errors.append("total_frames must be a positive integer")
        total = None
    cast = _unique_ids(_list(data, "cast", errors), "character_id", "cast", errors)
    shots = _list(data, "shots", errors)
    cuts = _unique_ids(shots, "cut_id", "shots", errors)
    cursor = 0
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        where = f"shot {shot.get('cut_id')!r}"
        if _frames(shot, "start_frame", "end_frame_exclusive", where, errors):
            if shot["start_frame"] != cursor:
                errors.append(f"{where}: starts at {shot['start_frame']}, expected {cursor} (gap or overlap)")
            cursor = shot["end_frame_exclusive"]
        unknown = [name for name in shot.get("visible_cast", []) if name not in cast]
        if not isinstance(shot.get("visible_cast"), list) or unknown:
            errors.append(f"{where}: visible_cast must list known characters{' (unknown: ' + ', '.join(map(str, unknown)) + ')' if unknown else ''}")
    if shots and total is not None and cursor != total:
        errors.append(f"shots end at frame {cursor}, total_frames is {total}")
    cues = _list(data, "dialogue_cues", errors)
    _unique_ids(cues, "cue_id", "dialogue_cues", errors)
    spans: dict[str, list[tuple[int, int, str]]] = {}
    for cue in cues:
        if not isinstance(cue, dict):
            continue
        where = f"cue {cue.get('cue_id')!r}"
        if cue.get("character_id") not in cast:
            errors.append(f"{where}: unknown character {cue.get('character_id')!r}")
        cut = cuts.get(cue.get("cut_id"))
        if cut is None:
            errors.append(f"{where}: unknown cut {cue.get('cut_id')!r}")
        if _frames(cue, "target_start_frame", "target_end_frame_exclusive", where, errors):
            start, end = cue["target_start_frame"], cue["target_end_frame_exclusive"]
            if cut is not None and _int(cut.get("start_frame")) and _int(cut.get("end_frame_exclusive")) \
                    and not (cut["start_frame"] <= start and end <= cut["end_frame_exclusive"]):
                errors.append(f"{where}: window {start}-{end} is outside cut {cue['cut_id']}")
            spans.setdefault(str(cue.get("character_id")), []).append((start, end, str(cue.get("cue_id"))))
        if not _str(cue.get("text")):
            errors.append(f"{where}: text is empty")
        unknown = [name for name in cue.get("in_world_listeners", []) if name not in cast]
        if not isinstance(cue.get("in_world_listeners"), list) or unknown:
            errors.append(f"{where}: in_world_listeners must list known characters")
        if type(cue.get("mouth_visible")) is not bool:
            errors.append(f"{where}: mouth_visible must be true or false")
        digest = cue.get("audio_sha256")
        if digest is not None and not (isinstance(digest, str) and _SHA256.match(digest)):
            errors.append(f"{where}: audio_sha256 must be a lowercase SHA-256 or null")
        duration = cue.get("actual_duration_seconds")
        if duration is not None and (isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration <= 0):
            errors.append(f"{where}: actual_duration_seconds must be positive or null")
    for character, windows in spans.items():
        windows.sort()
        for (_, end, first), (start, _, second) in zip(windows, windows[1:]):
            if start < end:
                errors.append(f"cues {first} and {second}: {character} speaks over themselves")
    if data.get("status") == "proposal_unproduced":
        if data.get("generated_media") != [] or data.get("approved_assets") != [] or data.get("observed_metrics") is not None:
            errors.append("a proposal_unproduced plan must have no generated_media, approved_assets or observed_metrics")
        if any(isinstance(c, dict) and (c.get("selected_take_id") or c.get("audio_sha256")) for c in cues):
            errors.append("a proposal_unproduced plan must not name a selected take or audio hash")
    return errors


def validate_cues_csv(text: str, plan: object = None) -> list[str]:
    """Check the cue sheet's columns and, when the pilot plan is given, that every row matches it."""
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != CSV_FIELDS:
        return [f"cue sheet columns must be exactly: {','.join(CSV_FIELDS)}"]
    errors: list[str] = []
    rows = list(reader)
    if len({row["cue_id"] for row in rows}) != len(rows):
        errors.append("cue sheet has duplicate cue_id values")
    if isinstance(plan, dict) and isinstance(plan.get("dialogue_cues"), list):
        planned = {c.get("cue_id"): c for c in plan["dialogue_cues"] if isinstance(c, dict)}
        for row in rows:
            cue = planned.get(row["cue_id"])
            if cue is None:
                errors.append(f"cue sheet row {row['cue_id']!r} is not in the pilot plan")
                continue
            for field in CSV_FIELDS:
                if str(cue.get(field)) != row[field]:
                    errors.append(f"cue {row['cue_id']}: {field} differs from the pilot plan")
        for missing in sorted(str(cue_id) for cue_id in set(planned) - {row["cue_id"] for row in rows}):
            errors.append(f"pilot plan cue {missing!r} is missing from the cue sheet")
    return errors


def validate_benchmark(data: object) -> list[str]:
    """Check the benchmark record; a record that was not run may hold no runs or summary."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["benchmark record must be a JSON object"]
    if data.get("schema_version") != 1 or type(data.get("schema_version")) is not int:
        errors.append("schema_version must be 1")
    if data.get("kind") != "anime_benchmark_template":
        errors.append("kind must be 'anime_benchmark_template'")
    if not _str(data.get("protocol_version")):
        errors.append("protocol_version is required")
    for key, limit in (("initial_take_limit_per_route", 3), ("maximum_routes_per_test", 3)):
        if not (_int(data.get(key)) and 1 <= data[key] <= limit):
            errors.append(f"{key} must be an integer from 1 to {limit}")
    for key in ("baseline_required", "fixed_approved_audio_required", "human_review_required"):
        if type(data.get(key)) is not bool:
            errors.append(f"{key} must be true or false")
    tests = {}
    for index, test in enumerate(_list(data, "screen_tests", errors)):
        if not isinstance(test, dict) or not _str(test.get("test_id")):
            errors.append(f"screen_tests[{index}]: needs a test_id")
        elif test["test_id"] in tests:
            errors.append(f"screen_tests: duplicate test_id {test['test_id']!r}")
        elif isinstance(test.get("target_seconds"), bool) or not isinstance(test.get("target_seconds"), (int, float)) \
                or test["target_seconds"] <= 0:
            errors.append(f"screen test {test['test_id']!r}: target_seconds must be positive")
        else:
            tests[test["test_id"]] = test
    fields = data.get("measurement_fields")
    if not isinstance(fields, dict) or set(fields) != set(BENCHMARK_GROUPS):
        errors.append("measurement_fields must have exactly: " + ", ".join(BENCHMARK_GROUPS))
    else:
        for group, names in fields.items():
            if not (isinstance(names, list) and names and all(_str(n) for n in names) and len(set(names)) == len(names)):
                errors.append(f"measurement_fields.{group} must be a non-empty list of unique names")
    runs = _list(data, "runs", errors)
    if data.get("status") == "not_run":
        if runs or data.get("summary") is not None:
            errors.append("a not_run benchmark must have no runs and a null summary")
    else:
        for index, run in enumerate(runs):
            if not isinstance(run, dict) or run.get("test_id") not in tests:
                errors.append(f"runs[{index}]: test_id must be one of the screen tests")
    return errors


def check_file(path: Path, *, plan: Path | None = None) -> tuple[str, list[str]]:
    """Validate one file chosen by extension and kind; returns (kind, problems)."""
    if path.stat().st_size > MAX_BYTES:
        raise ValueError(f"{path.name} is larger than {MAX_BYTES} bytes")
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".csv":
        plan_data = json.loads(plan.read_text(encoding="utf-8")) if plan else None
        return "cue_sheet", validate_cues_csv(text, plan_data)
    data = json.loads(text)
    kind = data.get("kind") if isinstance(data, dict) else None
    if kind == "anime_benchmark_template":
        return "benchmark", validate_benchmark(data)
    return "pilot", validate_pilot(data)


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="pilot.json, benchmark_template.json or a cue sheet .csv")
    parser.add_argument("--plan", type=Path, help="for a .csv: the pilot.json it must match")
    args = parser.parse_args(argv)
    try:
        kind, errors = check_file(args.file, plan=args.plan)
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        return 2
    print(json.dumps({"file": args.file.name, "kind": kind, "valid": not errors, "errors": errors}, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
