"""UI contracts through real workspace files, the dispatcher and the agent loop."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from types import SimpleNamespace

from PIL import Image, ImageDraw
import pytest

from star.starry_eye_quality import MAX_JSON_BYTES, audit
from star.workspace import Workspace


@pytest.fixture(autouse=True)
def default_off(monkeypatch):
    monkeypatch.delenv("STAR_UI_EVIDENCE", raising=False)


def _save(root, name, value):
    path = root / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(root, *, events=False):
    source = root / "app.ts"
    source.write_text("export const label = 'Play';\n", encoding="utf-8")
    image = Image.new("RGB", (400, 300), "#111111")
    ImageDraw.Draw(image).rectangle((12, 18, 92, 62), fill="#333333")
    image.save(root / "menu.png")
    source_hashes = {"app.ts": hashlib.sha256(source.read_bytes()).hexdigest()}
    capture_hash = hashlib.sha256((root / "menu.png").read_bytes()).hexdigest()
    case = {"id": "desktop", "screen": "menu", "state": "default",
            "viewport": {"width": 400, "height": 300, "unit": "css_px"},
            "input": "keyboard" if events else "pointer", "motion": "default", "elements": ["Play"]}
    observation = {"case": "desktop", "view": "menu", "pixel_ratio": 1,
                   "sources_sha256": source_hashes, "capture_sha256": capture_hash,
                   **{k: copy.deepcopy(case[k]) for k in ("screen", "state", "viewport", "input", "motion")}}
    manifest = {"project": "SyntheticUiTest", "artifact": "menu", "source": "app.ts",
                "views": {"menu": {"file": "menu.png", "width": 400, "height": 300}},
                "layout": {"menu": [{"id": "Play", "rect": [12, 18, 80, 44], "interactive": True,
                                      "foreground": "#FFFFFF", "background": "#111111"}]},
                "ui_observations": [observation]}
    if events:
        case["events"] = ["open", "activate"]
        trace = {"engine": "web", "run_finished": True, "sources_sha256": source_hashes,
                 "events": [{"name": name, "t_ms": time, "case_id": "desktop", "capture_sha256": capture_hash}
                            for name, time in (("open", 0), ("activate", 500))]}
        observation["trace_sha256"] = _save(root, "trace.json", trace)
        manifest["trace_file"] = "trace.json"
    contract = {"version": 1, "target": "web", "cases": [case]}
    _save(root, "contract.json", contract)
    _save(root, "quality.json", manifest)
    return Workspace(root), manifest, contract


def _call(work):
    return work.call("workspace_starry_eye_audit", {"path": "quality.json", "ui_contract_path": "contract.json"})


def test_optional_contract_is_off_by_default_and_never_silently_ignored(tmp_path, monkeypatch):
    work, _, _ = _fixture(tmp_path)
    legacy = audit(work, "quality.json")
    assert legacy["status"] == "automated_checks_passed" and "ui_coverage" not in legacy
    with pytest.raises(ValueError, match="STAR_UI_EVIDENCE=on"):
        _call(work)
    monkeypatch.setenv("STAR_UI_EVIDENCE", "on")
    assert audit(work, "quality.json") == legacy


def test_complete_contract_uses_existing_read_only_dispatch(tmp_path, monkeypatch):
    work, _, _ = _fixture(tmp_path, events=True)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    monkeypatch.setenv("STAR_UI_EVIDENCE", "on")
    result = _call(work)
    assert result["status"] == "automated_checks_passed"
    coverage = result["ui_coverage"]
    assert coverage["status"] == "declared_coverage_complete" and coverage["complete_count"] == 1
    for key in ("runtime_executed_by_this_tool", "capture_authenticity_proven", "owner_approved",
                "accessibility_conformance_proven", "motion_preference_honored_proven"):
        assert coverage[key] is False
    assert len(result["ui_contract_sha256"]) == len(result["ui_audit_key"]) == 64
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_missing_required_reduced_motion_case_prevents_overall_pass(tmp_path, monkeypatch):
    work, _, contract = _fixture(tmp_path)
    reduced = copy.deepcopy(contract["cases"][0])
    reduced.update(id="reduced", motion="reduced")
    contract["cases"].append(reduced)
    _save(tmp_path, "contract.json", contract)
    monkeypatch.setenv("STAR_UI_EVIDENCE", "on")
    result = _call(work)
    assert result["status"] == "insufficient_evidence"
    assert result["unverified_count"] == 1 and result["failed_count"] == 0
    assert any(f["code"] == "ui_case_unverified" and f["case"] == "reduced" for f in result["findings"])


@pytest.mark.parametrize("changed", ["source", "capture", "trace"])
def test_changed_real_bytes_invalidate_supplied_bindings(tmp_path, monkeypatch, changed):
    work, _, _ = _fixture(tmp_path, events=True)
    if changed == "source":
        (tmp_path / "app.ts").write_text("export const label = 'Different';\n", encoding="utf-8")
    elif changed == "capture":
        Image.new("RGB", (400, 300), "#222222").save(tmp_path / "menu.png")
    else:
        trace = json.loads((tmp_path / "trace.json").read_text())
        trace["events"].pop()
        _save(tmp_path, "trace.json", trace)
    monkeypatch.setenv("STAR_UI_EVIDENCE", "on")
    result = _call(work)
    assert result["status"] == "automated_checks_failed"
    expected = {"source": "ui_sources_stale", "capture": "ui_capture_stale", "trace": "ui_trace_stale"}[changed]
    assert any(f["code"] == expected for f in result["findings"])


def test_audit_identity_includes_requirements_and_observations(tmp_path, monkeypatch):
    work, manifest, contract = _fixture(tmp_path)
    monkeypatch.setenv("STAR_UI_EVIDENCE", "on")
    first = _call(work)
    contract["cases"][0]["elements"].append("Help")
    _save(tmp_path, "contract.json", contract)
    second = _call(work)
    assert first["evidence_key"] == second["evidence_key"]
    assert first["ui_audit_key"] != second["ui_audit_key"]
    assert second["status"] == "insufficient_evidence"
    manifest["ui_observations"][0]["state"] = "error"
    _save(tmp_path, "quality.json", manifest)
    third = _call(work)
    assert second["ui_audit_key"] != third["ui_audit_key"]
    assert third["status"] == "automated_checks_failed"


@pytest.mark.parametrize("filename,key", [("contract.json", "version"), ("quality.json", "source"),
                                           ("trace.json", "run_finished")])
def test_duplicate_json_fields_cannot_rewrite_ui_evidence(tmp_path, monkeypatch, filename, key):
    work, _, _ = _fixture(tmp_path, events=True)
    path = tmp_path / filename
    value = json.loads(path.read_text())
    path.write_text("{" + json.dumps(key) + ":" + json.dumps(value[key]) + "," + json.dumps(value)[1:])
    monkeypatch.setenv("STAR_UI_EVIDENCE", "on")
    with pytest.raises(ValueError, match="Malformed JSON evidence"):
        _call(work)


@pytest.mark.parametrize("path", ["../outside.json", "/tmp/outside.json", ".env.json", ".git/contract.json"])
def test_contract_obeys_existing_workspace_boundaries(tmp_path, monkeypatch, path):
    work, _, _ = _fixture(tmp_path)
    monkeypatch.setenv("STAR_UI_EVIDENCE", "on")
    with pytest.raises((PermissionError, FileNotFoundError)):
        work.call("workspace_starry_eye_audit", {"path": "quality.json", "ui_contract_path": path})


def test_contract_cannot_be_a_symlink_or_oversized(tmp_path, monkeypatch):
    work, _, _ = _fixture(tmp_path)
    monkeypatch.setenv("STAR_UI_EVIDENCE", "on")
    try:
        (tmp_path / "alias.json").symlink_to(tmp_path / "contract.json")
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable")
    with pytest.raises(ValueError, match="regular"):
        work.call("workspace_starry_eye_audit", {"path": "quality.json", "ui_contract_path": "alias.json"})
    (tmp_path / "contract.json").write_text(" " * (MAX_JSON_BYTES + 1))
    with pytest.raises(ValueError, match="small"):
        _call(work)


@pytest.mark.parametrize("bad", [None, True, {}, "", "x" * 501])
def test_optional_argument_is_schema_validated(tmp_path, bad):
    work = Workspace(tmp_path)
    with pytest.raises(ValueError, match="Invalid workspace tool arguments"):
        work.call("workspace_starry_eye_audit", {"path": "quality.json", "ui_contract_path": bad})


def test_revocation_during_schema_validation_refuses_before_reading(tmp_path, monkeypatch):
    import jsonschema
    monkeypatch.setenv("STAR_UI_EVIDENCE", "on")
    original = jsonschema.validate

    def revoke(*args, **kwargs):
        original(*args, **kwargs)
        monkeypatch.delenv("STAR_UI_EVIDENCE")

    monkeypatch.setattr(jsonschema, "validate", revoke)
    with pytest.raises(ValueError, match="STAR_UI_EVIDENCE=on"):
        _call(Workspace(tmp_path))


def test_findings_cap_preserves_failure_count(tmp_path):
    work, manifest, _ = _fixture(tmp_path)
    manifest["layout"]["menu"] = [{"id": f"Button{i}", "rect": [20, 20, 40, 40], "interactive": True}
                                     for i in range(20)]
    _save(tmp_path, "quality.json", manifest)
    result = audit(work, "quality.json")
    assert result["status"] == "automated_checks_failed"
    assert result["failed_count"] == 190
    assert len(result["findings"]) == 100 and result["findings_omitted"] == 90


@pytest.mark.parametrize("field,bad", [("engine", []), ("engine", {}), ("timestamp", 10**400)])
def test_malformed_trace_is_a_bounded_validation_error(tmp_path, monkeypatch, field, bad):
    work, _, _ = _fixture(tmp_path, events=True)
    trace = json.loads((tmp_path / "trace.json").read_text())
    if field == "timestamp":
        trace["events"][0]["t_ms"] = bad
    else:
        trace[field] = bad
    _save(tmp_path, "trace.json", trace)
    monkeypatch.setenv("STAR_UI_EVIDENCE", "on")
    with pytest.raises(ValueError):
        _call(work)


@pytest.mark.parametrize("field", ["from", "to", "expected"])
def test_malformed_motion_labels_are_validation_errors(tmp_path, monkeypatch, field):
    work, manifest, _ = _fixture(tmp_path)
    manifest["motion"] = [{"from": "menu", "to": "menu", "expected": "static", field: []}]
    _save(tmp_path, "quality.json", manifest)
    monkeypatch.setenv("STAR_UI_EVIDENCE", "on")
    with pytest.raises(ValueError):
        _call(work)


def test_actual_agent_loop_offers_and_dispatches_contract_without_write_access(tmp_path, monkeypatch):
    from star.agent import execute
    work, _, _ = _fixture(tmp_path)
    monkeypatch.setenv("STAR_UI_EVIDENCE", "on")

    class Client:
        def __init__(self):
            self.requests = []
            self.chat = SimpleNamespace(completions=self)

        async def create(self, **kwargs):
            self.requests.append(copy.deepcopy(kwargs))
            calls = []
            if len(self.requests) == 1:
                calls = [SimpleNamespace(id="ui-1", function=SimpleNamespace(
                    name="workspace_starry_eye_audit",
                    arguments=json.dumps({"path": "quality.json", "ui_contract_path": "contract.json"}))) ]
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content="" if calls else "Reviewed.", tool_calls=calls), finish_reason="stop")])

    client = Client()
    asyncio.run(execute(client=client, model="offline-scripted", prompt="Audit the declared UI coverage.",
                        image_paths=[], workspace=work, context_chars=100_000, complete_code_answers=False, now=""))
    offered = {t["function"]["name"]: t["function"] for t in client.requests[0]["tools"]}
    assert "ui_contract_path" in offered["workspace_starry_eye_audit"]["parameters"]["properties"]
    assert "workspace_write" not in offered
    receipt = json.loads(next(m for m in client.requests[1]["messages"] if m["role"] == "tool")["content"])
    assert receipt["isError"] is False
    output = json.loads(receipt["output"])
    assert output["ui_coverage"]["status"] == "declared_coverage_complete"
