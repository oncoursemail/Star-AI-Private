"""Host-only, read-only Roblox Studio probe for pre-edit inspection receipts.

The owner-authorized host, not a language model, invokes the fixed Luau probe
through an already-authenticated official Studio MCP session. The probe reads
only a bounded object's public structural/property snapshot. The host validates
its response, hashes that snapshot, signs a receipt without sending its HMAC
key into Studio, and offers it to StudioInspectionCoverageGate.

This does NOT enumerate an edit's dependencies, establish a global scene
revision, authorize an edit, or prove that a remote Studio plugin is honest.
Scripts are deliberately unsupported: a structure-only probe cannot qualify
as a complete source inspection. No probe output should be sent to the model.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Callable

from .studio_inspection_coverage import (
    EditFootprint, StudioInspectionCoverageGate, StudioReadReceipt,
)
from .studio_loop import result_failed, result_text

MARK = "STAR_INSPECT "
MAX_RESPONSE_BYTES = 14_000
MAX_CHILDREN = 64
MAX_ANCESTOR_CHILDREN = 2048
# Exact property profiles: unsupported classes/failed properties fail closed.
# Never read script source, arbitrary attributes, or viewer/chat information.
PROFILES: dict[str, tuple[str, ...]] = {
    "Part": ("Anchored", "CanCollide", "Size", "CFrame", "Transparency", "Material", "Color"),
    "MeshPart": ("Anchored", "CanCollide", "Size", "CFrame", "Transparency", "Material", "Color", "MeshId", "TextureID"),
    "SpawnLocation": ("Anchored", "CanCollide", "Size", "CFrame", "Transparency", "Material", "Color", "Enabled", "Neutral"),
    "Model": ("PrimaryPart", "WorldPivot"),
    "Folder": ("Name",),
}
_TEXT = re.compile(r"[\x20-\x7e\u00a0-\uffff]{1,160}\Z")


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _result(result: object) -> dict | None:
    """Require exactly one bounded marked return value, no prefixed logs."""
    if result_failed(result):
        return None
    try:
        raw = result_text(result).strip()
        if len(raw.encode("utf-8")) > MAX_RESPONSE_BYTES:
            return None
        # The connector may JSON-quote its returned Luau string.
        if raw.startswith('"'):
            raw = json.loads(raw)
        if type(raw) is not str or not raw.startswith(MARK) or raw.count(MARK) != 1:
            return None
        data = json.loads(raw[len(MARK):])
        return data if type(data) is dict else None
    except (UnicodeError, ValueError, TypeError, RecursionError):
        return None


def _validated_snapshot(data: dict, *, token: str, session: str,
                        path: tuple[str, ...]) -> dict | None:
    """Whitelist the exact shape; never trust a claimed 'complete' alone."""
    if set(data) != {"ok", "challenge", "session", "path", "class_name",
                     "object_id", "fields", "children"}:
        return None
    if (data["ok"] is not True or data["challenge"] != token
            or data["session"] != session or data["path"] != list(path)):
        return None
    cls = data["class_name"]
    if type(cls) is not str or cls not in PROFILES:
        return None
    obj_id = data["object_id"]
    if type(obj_id) is not str or not _TEXT.fullmatch(obj_id):
        return None
    fields = data["fields"]
    if (type(fields) is not dict or set(fields) != set(PROFILES[cls])
            or any(type(v) is not str or len(v) > 160
                   or any(ord(ch) < 32 or ord(ch) == 127 for ch in v)
                   for v in fields.values())):
        return None
    children = data["children"]
    if type(children) is not list or len(children) > MAX_CHILDREN:
        return None
    for pair in children:
        if (type(pair) is not list or len(pair) != 2
                or any(type(x) is not str or not _TEXT.fullmatch(x) or len(x) > 80
                       for x in pair)):
            return None
    # The response is bounded and has a stable fingerprint irrespective of
    # GetChildren's unspecified engine enumeration order.
    if children != sorted(children):
        return None
    return {"class_name": cls, "object_id": obj_id,
            "fields": fields, "children": children}


def build_readonly_probe(footprint: EditFootprint, path: tuple[str, ...], *,
                         challenge: str) -> str:
    """Create fixed Luau; all inputs are encoded as data, never executable text."""
    if not isinstance(footprint, EditFootprint):
        raise TypeError("expected validated edit footprint")
    if type(path) is not tuple or path not in footprint.targets + footprint.dependencies:
        raise ValueError("path must be declared by the trusted edit footprint")
    if type(challenge) is not str or not re.fullmatch("[0-9a-f]{32}", challenge):
        raise ValueError("invalid per-call challenge")
    payload = _json({"challenge": challenge, "session": footprint.studio_session, "path": path})
    profiles = _json(PROFILES)
    return (
        "-- STAR:inspection-readonly (fixed host code; no writes or source reads)\n"
        "local HttpService = game:GetService(\"HttpService\")\n"
        "local req = HttpService:JSONDecode(" + _json(payload) + ")\n"
        "local profiles = HttpService:JSONDecode(" + _json(profiles) + ")\n"
        "local function fail() return \"" + MARK + "\" .. HttpService:JSONEncode({ok = false}) end\n"
        "local ok, data = pcall(function()\n"
        "  local actualSession = game:GetDebugId(32) .. \":\" .. workspace:GetDebugId(32)\n"
        "  if actualSession ~= req.session then return nil end\n"
        "  local obj = game:GetService(req.path[1])\n"
        "  for index = 2, #req.path do\n"
        "    local items = obj:GetChildren()\n"
        "    if #items > " + str(MAX_ANCESTOR_CHILDREN) + " then return nil end\n"
        "    local found, count = nil, 0\n"
        "    for _, child in ipairs(items) do\n"
        "      if child.Name == req.path[index] then found = child; count += 1 end\n"
        "    end\n"
        "    if count ~= 1 then return nil end\n"
        "    obj = found\n"
        "  end\n"
        "  local names = profiles[obj.ClassName]\n"
        "  if names == nil then return nil end\n"
        "  local children = obj:GetChildren()\n"
        "  if #children > " + str(MAX_CHILDREN) + " then return nil end\n"
        "  local observed = {}\n"
        "  for _, name in ipairs(names) do\n"
        "    local value = tostring(obj[name])\n"
        "    if #value > 160 then return nil end\n"
        "    observed[name] = value\n"
        "  end\n"
        "  local childInfo = {}\n"
        "  for _, child in ipairs(children) do\n"
        "    if #child.Name > 80 or #child.ClassName > 80 then return nil end\n"
        "    table.insert(childInfo, {child.Name, child.ClassName})\n"
        "  end\n"
        "  table.sort(childInfo, function(a,b)\n"
        "    if a[1] == b[1] then return a[2] < b[2] end\n"
        "    return a[1] < b[1]\n"
        "  end)\n"
        "  return {ok = true, challenge = req.challenge, session = actualSession,\n"
        "    path = req.path, class_name = obj.ClassName, object_id = obj:GetDebugId(32),\n"
        "    fields = observed, children = childInfo}\n"
        "end)\n"
        "if not ok or not data then return fail() end\n"
        "return \"" + MARK + "\" .. HttpService:JSONEncode(data)\n"
    )


class StudioInspectionReadHost:
    """Trusted adapter; probe output and host key never become model context.

    The gate and caller must come from the authorized local host. The host must
    maintain scene_revision, independently select dependencies, and invalidate
    plans on any native mutation/reconnect; this adapter cannot detect those.
    """

    def __init__(self, *, gate: StudioInspectionCoverageGate, host_key: bytes,
                 footprint: EditFootprint, plan_nonce: str, studio_id: str,
                 owner_approved: bool = False,
                 clock_ms: Callable[[], int] | None = None):
        if not isinstance(gate, StudioInspectionCoverageGate):
            raise TypeError("expected inspection gate")
        if type(host_key) is not bytes or len(host_key) < 32:
            raise ValueError("host key must contain 32+ bytes")
        if not isinstance(footprint, EditFootprint):
            raise TypeError("expected edit footprint")
        if type(plan_nonce) is not str or not re.fullmatch("[0-9a-f]{32}", plan_nonce):
            raise ValueError("invalid gate plan nonce")
        if (type(studio_id) is not str or not re.fullmatch("[A-Za-z0-9_.:-]{1,80}", studio_id)):
            raise ValueError("invalid Studio ID")
        if clock_ms is not None and not callable(clock_ms):
            raise TypeError("clock_ms must be callable")
        self._gate, self._key = gate, host_key
        self._footprint, self._nonce = footprint, plan_nonce
        self._studio_id = studio_id
        self._approved = owner_approved is True
        self._clock = clock_ms or (lambda: time.monotonic_ns() // 1_000_000)

    async def inspect(self, session: object, path: tuple[str, ...]) -> bool:
        """One fixed read-only Studio MCP call and one authenticated gate receipt."""
        if not self._approved:
            return False
        challenge = secrets.token_hex(16)
        code = build_readonly_probe(self._footprint, path, challenge=challenge)
        try:
            result = await session.call_tool("execute_luau", arguments={
                "studio_id": self._studio_id, "datamodel_type": "Edit", "code": code,
            })
            data = _result(result)
            if data is None:
                return False
            snapshot = _validated_snapshot(data, token=challenge,
                                           session=self._footprint.studio_session, path=path)
            if snapshot is None:
                return False
            now_ms = self._clock()
            observed = hashlib.sha256(_json(snapshot).encode("utf-8")).hexdigest()
            receipt = StudioReadReceipt(
                plan_nonce=self._nonce, project_id=self._footprint.project_id,
                studio_session=self._footprint.studio_session,
                scene_revision=self._footprint.scene_revision, path=path,
                class_name=snapshot["class_name"], observation_sha256=observed,
                captured_ms=now_ms, complete=True, unique_path=True, mac="0" * 64,
            )
            receipt = replace(receipt, mac=hmac.new(
                self._key, receipt.signed_bytes(), hashlib.sha256).hexdigest())
            return self._gate.accept(receipt, now_ms=now_ms)
        except Exception:
            # Missing transport, malformed Studio data, time rollback, and host
            # errors never qualify as a completed inspection.
            return False
