"""Offline adversarial tests for the host-only Studio inspection read adapter."""
import hashlib
import itertools
import json

import pytest

from star.studio_inspection_coverage import EditFootprint, StudioInspectionCoverageGate
from star import studio_inspection_read_host as host

KEY = b"r" * 32
TARGET = ("Workspace", "Arena", "Checkpoint")
DEPENDENCY = ("Workspace", "Arena", "Effects")
TICKET = "f" * 32
CHALLENGE = "a" * 32


def footprint():
    return EditFootprint(project_id="example", studio_session="studio-a",
                         scene_revision=7,
                         change_sha256=hashlib.sha256(b"exact-edit").hexdigest(),
                         targets=(TARGET,), dependencies=(DEPENDENCY,))


def scene(path=TARGET, *, cls="Part", children=None):
    return {
        "ok": True, "challenge": CHALLENGE, "session": "studio-a",
        "path": list(path), "class_name": cls, "object_id": "obj_0001",
        "fields": {name: "value" for name in host.PROFILES.get(cls, ())},
        "children": children if children is not None else [],
    }


def emitted(payload, *, quoted=False, fail=False):
    text = host.MARK + json.dumps(payload)
    if quoted:
        text = json.dumps(text)
    return {"isError": fail, "content": [{"type": "text", "text": text}]}


class FakeSession:
    def __init__(self, payload, *, quoted=False, fail=False, error=False):
        self.payload = payload
        self.quoted = quoted
        self.fail = fail
        self.error = error
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self.error:
            raise ConnectionError("Studio is offline; secrets must not be exposed")
        return emitted(self.payload, quoted=self.quoted, fail=self.fail)


def opened(*, approved=True, now=1010):
    gate = StudioInspectionCoverageGate(host_key=KEY)
    gate.enable(owner_approved=True)
    nonce = gate.register(footprint(), now_ms=1000, host_approved=True)
    ticks = itertools.count(now, 5)
    adapter = host.StudioInspectionReadHost(
        gate=gate, host_key=KEY, footprint=footprint(), plan_nonce=nonce,
        studio_id="studio-1", owner_approved=approved, clock_ms=lambda: next(ticks),
    )
    return gate, adapter


@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture(autouse=True)
def fixed_challenge(monkeypatch):
    monkeypatch.setattr(host.secrets, "token_hex", lambda _: CHALLENGE)


@pytest.mark.anyio
async def test_real_fixed_host_read_reaches_coverage_gate():
    gate, adapter = opened()
    session = FakeSession(scene(), quoted=True)
    assert await adapter.inspect(session, TARGET) is True
    assert gate.review(now_ms=1012).missing_paths == (DEPENDENCY,)
    name, args = session.calls[0]
    assert name == "execute_luau"
    assert args["studio_id"] == "studio-1" and args["datamodel_type"] == "Edit"
    code = args["code"]
    assert "count ~= 1" in code and "GetChildren()" in code
    assert "GetDebugId(32)" in code and "obj.ClassName" in code
    assert "SetAttribute" not in code and "UpdateSourceAsync" not in code
    assert "ScriptEditorService" not in code and "GetEditorSource" not in code
    assert "ChangeHistoryService" not in code and KEY.decode("ascii") not in code
    assert await adapter.inspect(FakeSession(scene(DEPENDENCY, cls="Folder")), DEPENDENCY)
    review = gate.review(now_ms=1016)
    assert review.status == "ready_for_review"
    assert review.authorized_to_mutate is False


@pytest.mark.anyio
async def test_disable_means_no_call_and_stale_plan_does_not_qualify():
    gate, adapter = opened(approved=False)
    conn = FakeSession(scene())
    assert not await adapter.inspect(conn, TARGET)
    assert conn.calls == []
    gate2, adapter2 = opened()
    gate2.invalidate_revision(now_ms=1009)
    assert not await adapter2.inspect(FakeSession(scene()), TARGET)
    assert gate2.review(now_ms=1011).status == "unplanned"


@pytest.mark.anyio
@pytest.mark.parametrize("bad", [
    {"challenge": "b" * 32},
    {"session": "studio-b"},
    {"path": ["Workspace", "Other", "Checkpoint"]},
    {"ok": False},
    {"class_name": "Script", "fields": {}},
    {"class_name": "Part", "fields": {"Anchored": "true"}},
    {"object_id": ""},
    {"children": [["Missing", "Part"]] * 65},
    {"children": [["z", "Part"], ["a", "Part"]]},
    {"children": [["A", "Part", "extra"]]},
    {"extra": "untrusted"},
])
async def test_wrong_or_partial_probes_are_rejected(bad):
    gate, adapter = opened()
    data = {**scene(), **bad}
    assert not await adapter.inspect(FakeSession(data), TARGET)
    assert gate.review(now_ms=1011).status == "incomplete"


@pytest.mark.anyio
async def test_transport_failure_markup_spoof_and_response_budget_fail():
    gate, adapter = opened()
    assert not await adapter.inspect(FakeSession(scene(), error=True), TARGET)
    assert not await adapter.inspect(FakeSession(scene(), fail=True), TARGET)
    class Injected:
        async def call_tool(self, _name, arguments):
            return {"content": [{"type": "text", "text": "prefix " + host.MARK + json.dumps(scene())}]}
    assert not await adapter.inspect(Injected(), TARGET)
    class Huge:
        async def call_tool(self, _name, arguments):
            return {"content": [{"type": "text", "text": host.MARK + ("0" * host.MAX_RESPONSE_BYTES)}]}
    assert not await adapter.inspect(Huge(), TARGET)
    assert gate.review(now_ms=1011).status == "incomplete"


@pytest.mark.anyio
async def test_replay_and_unrequested_scope_fail_closed():
    gate, adapter = opened()
    first = FakeSession(scene())
    assert await adapter.inspect(first, TARGET)
    assert not await adapter.inspect(first, TARGET)  # duplicate receipt path
    with pytest.raises(ValueError):
        await adapter.inspect(first, ("Workspace", "Other"))
    assert gate.review(now_ms=1016).inspected == 1


@pytest.mark.anyio
async def test_timestamps_and_wrong_signing_key_fail():
    gate, adapter = opened(now=2000)
    assert await adapter.inspect(FakeSession(scene()), TARGET)
    assert await adapter.inspect(FakeSession(scene(DEPENDENCY, cls="Folder")), DEPENDENCY)
    assert gate.review(now_ms=32_006).status == "stale"
    gate2 = StudioInspectionCoverageGate(host_key=KEY)
    gate2.enable(owner_approved=True)
    nonce = gate2.register(footprint(), now_ms=1000, host_approved=True)
    wrong = host.StudioInspectionReadHost(
        gate=gate2, host_key=b"x" * 32, footprint=footprint(), plan_nonce=nonce,
        studio_id="studio-1", owner_approved=True, clock_ms=lambda: 1010,
    )
    assert not await wrong.inspect(FakeSession(scene()), TARGET)
    assert gate2.review(now_ms=1011).inspected == 0


def test_probe_contract_rejects_unplanned_or_malformed_paths():
    with pytest.raises(ValueError):
        host.build_readonly_probe(footprint(), ("Workspace", "Other"),
                                  challenge=CHALLENGE)
    with pytest.raises(ValueError):
        host.build_readonly_probe(footprint(), TARGET, challenge="../injection")
    with pytest.raises(ValueError):
        host.StudioInspectionReadHost(
            gate=StudioInspectionCoverageGate(host_key=KEY), host_key=KEY,
            footprint=footprint(), plan_nonce=TICKET, studio_id="../bad",
        )
    code = host.build_readonly_probe(footprint(), TARGET, challenge=CHALLENGE)
    # All dynamic values are JSON-decoded data; none are source interpolated.
    assert "HttpService:JSONDecode" in code
    assert code.count("JSONDecode") == 2
