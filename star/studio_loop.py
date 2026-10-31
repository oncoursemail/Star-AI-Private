"""The Studio build loop on the official Studio MCP connector, with the sandbox rule enforced in code.

    connect -> which place is this? -> read tree and scripts -> screenshot -> edit scripts and
    instances -> playtest -> read output -> screenshot -> fix -> report what changed, with undo

Nothing here invents a connector method: the tool list is read from the connector at runtime
(star/studio.py) and sorted by star/policy.py. Three things are STAR's own, as fixed text that a
model cannot change: the question "which place is open" (IDENTITY_PROBE), the wrapper around a
sandbox Luau edit (wrap_edit), bound script updates and guarded native history undo.

The sandbox rule. STAR edits a place only when the owner switched Studio edits on AND the place is
  * a blank, unsaved place (never published: PlaceId 0; no scripts, or marked by an earlier STAR edit), or
  * a place owned by STAR's own Roblox account, and the owner also allowed those.
Every other place, and always the places on the deny-list, is read-only whatever the settings say.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import asyncio
import json
import re
import secrets

from ._lazy import lazy_module
anyio = lazy_module("anyio")  # loaded on first use, not when the desktop starts

from .edit_match import EditMismatch, apply_edit
from .policy import BLOCKED_TOOLS, PLAYTEST_TOOLS, READ_TOOLS, WRITE_TOOLS, classify
from .roblox_cloud import DENIED_PLACE_IDS, DENIED_UNIVERSE_IDS

PLACE_MARK, EDIT_MARK = "STAR_PLACE ", "STAR_EDIT "
PLAY_MARK = "STAR_PLAY "
PLAY_OWNER_MARK, PLAY_STOP_MARK = "STAR_PLAY_OWNER ", "STAR_STOP "
PLAY_START_SECONDS, PLAY_STOP_SECONDS, PLAY_POLL_SECONDS = 15.0, 10.0, 0.05
SANDBOX_ATTRIBUTE = "StarSandbox"
_SERVICES = ('"Workspace", "ReplicatedFirst", "ReplicatedStorage", "ServerScriptService", "ServerStorage", '
             '"StarterGui", "StarterPack", "StarterPlayer", "Lighting"')

# Reads only. API names checked against the official reference (DataModel.PlaceId, GameId,
# CreatorId, CreatorType; Instance:GetAttribute; HttpService:JSONEncode).
IDENTITY_PROBE = f"""-- STAR:identity (reads only)
local HttpService = game:GetService("HttpService")
local scripts = 0
for _, name in ipairs({{ {_SERVICES} }}) do
	local ok, service = pcall(function()
		return game:GetService(name)
	end)
	if ok and service then
		for _, item in ipairs(service:GetDescendants()) do
			if item:IsA("LuaSourceContainer") then
				scripts += 1
			end
		end
	end
end
return "{PLACE_MARK}" .. HttpService:JSONEncode({{
	placeId = game.PlaceId,
	gameId = game.GameId,
	creatorId = game.CreatorId,
	creatorType = game.CreatorType.Name,
	name = game.Name,
	scripts = scripts,
	marker = workspace:GetAttribute("{SANDBOX_ATTRIBUTE}") == true,
	session = game:GetDebugId(32) .. ":" .. workspace:GetDebugId(32),
}})
"""

# Marks an unsaved place as STAR's sandbox, so a later session may continue in it.
MARK_SNIPPET = f'-- STAR:mark\nworkspace:SetAttribute("{SANDBOX_ATTRIBUTE}", true)\nreturn "marked"\n'

_SCRIPT_PATH = re.compile(r"(?:game\.)?[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_][A-Za-z0-9_ \-]{0,79})+")
_TAG = re.compile(r"StarEdit_[0-9a-f]{8}")


def wrap_edit(code: str, tag: str | None = None) -> tuple[str, str]:
    """Record sandbox Luau as one Studio history step and list what it added.

    The model's first line stays on this wrapper's first line; the enclosing
    DataModel guard adds its own lines to the code sent to the connector.
    """
    tag = tag or "StarEdit_" + secrets.token_hex(4)
    if not _TAG.fullmatch(tag):
        raise ValueError("Invalid edit tag")
    head = ('local __s = {added = {}, removed = 0, c = game:GetService("ChangeHistoryService")}; '
            '__s.connectorRecorded = __s.c:IsRecordingInProgress(); '
            f'if not __s.connectorRecorded then __s.rec = __s.c:TryBeginRecording("{tag}", "{tag}") end; '
            'if not __s.rec and not __s.connectorRecorded then error("STAR could not begin an undo recording") end; '
            '__s.a = game.DescendantAdded:Connect(function(i) table.insert(__s.added, i) end); '
            '__s.r = game.DescendantRemoving:Connect(function() __s.removed += 1 end); '
            'local __ok, __res = pcall(function() ')
    tail = f"""
end)
task.wait()
__s.a:Disconnect()
__s.r:Disconnect()
local __paths, __count = {{}}, 0
local __tags = game:GetService("CollectionService")
for _, item in ipairs(__s.added) do
	local alive, path = pcall(function()
		return item:GetFullName()
	end)
	if alive and item:IsDescendantOf(game) then
		__count += 1
		local parent = item.Parent
		if not (parent and table.find(__s.added, parent)) then
			pcall(function()
				__tags:AddTag(item, "{tag}")
			end)
			if #__paths < 60 then
				table.insert(__paths, item.ClassName .. " " .. path)
			end
		end
	end
end
pcall(function()
	workspace:SetAttribute("{SANDBOX_ATTRIBUTE}", true)
end)
if __s.rec then
	__s.c:FinishRecording(__s.rec, Enum.FinishRecordingOperation.Commit)
end
return "{EDIT_MARK}" .. game:GetService("HttpService"):JSONEncode({{
	tag = "{tag}", ok = __ok, recorded = __s.rec ~= nil, connectorRecorded = __s.connectorRecorded,
    added = __paths, addedCount = __count,
	removed = __s.removed, result = if __res == nil then nil else string.sub(tostring(__res), 1, 2000),
}})
"""
    return head + code + tail, tag


# --------------------------------------------------------------------------- which place is open

@dataclass(frozen=True)
class PlaceIdentity:
    place_id: int
    game_id: int
    creator_id: int
    creator_type: str
    name: str
    scripts: int
    marker: bool
    session: str = ""


@dataclass(frozen=True)
class Verdict:
    editable: bool
    kind: str          # blank | own | denied | published | not_blank | unknown | changed
    reason: str
    identity: PlaceIdentity | None = None

    def public(self) -> dict:
        shown = {"editable": self.editable, "kind": self.kind, "reason": self.reason}
        if self.identity:
            shown["place"] = {"place_id": self.identity.place_id, "name": self.identity.name[:80],
                              "scripts": self.identity.scripts}
        return shown


def result_text(result) -> str:
    """All text of an MCP tool result, whether it is an SDK object or a plain dict."""
    data = result.model_dump(by_alias=True, exclude_none=True) if hasattr(result, "model_dump") else result
    parts = data.get("content") if isinstance(data, dict) else None
    return "\n".join(str(part.get("text", "")) for part in parts or () if isinstance(part, dict)
                     and part.get("type") == "text")


def result_failed(result) -> bool:
    data = result.model_dump(by_alias=True, exclude_none=True) if hasattr(result, "model_dump") else result
    return bool(isinstance(data, dict) and data.get("isError"))


def _marked_json(text: str, mark: str) -> dict | None:
    """The JSON object STAR's own snippet printed after `mark`, however the connector quoted it."""
    position = text.find(mark)
    if position < 0:
        return None
    rest = text[position + len(mark):]
    for candidate in (rest, rest.replace(chr(92) + '"', '"').replace(chr(92) * 2, chr(92))):
        try:
            value, _end = json.JSONDecoder().raw_decode(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def studios(result) -> list[dict]:
    """[{id, name}] from list_roblox_studios."""
    try:
        data = json.loads(result_text(result))
    except ValueError:
        return []
    items = data.get("studios") if isinstance(data, dict) else None
    return [{"id": str(item.get("id", "")), "name": str(item.get("name", ""))[:200]}
            for item in items or () if isinstance(item, dict) and item.get("id")]


def name_is_denied(name: str) -> bool:
    """A deny-listed place or experience id in the instance's display name: no question is asked of that place."""
    denied = DENIED_PLACE_IDS | DENIED_UNIVERSE_IDS
    return any(int(number) in denied for number in re.findall(r"\d{6,19}", str(name)))


async def identify(session, studio_id: str, *, tools: set[str], studio_name: str = "") -> PlaceIdentity | None:
    """Ask the open place what it is. None when that cannot be found out (then nothing is edited)."""
    if name_is_denied(studio_name) or "execute_luau" not in tools:
        return None
    result = await _call(session, "execute_luau", {
        "studio_id": studio_id, "datamodel_type": "Edit", "code": IDENTITY_PROBE})
    found = None if result_failed(result) else _marked_json(result_text(result), PLACE_MARK)
    if not found:
        return None
    try:
        return PlaceIdentity(int(found["placeId"]), int(found["gameId"]), int(found["creatorId"]),
                             str(found.get("creatorType", "")), str(found.get("name", ""))[:120],
                             int(found["scripts"]), found.get("marker") is True,
                             str(found.get("session", ""))[:160])
    except (KeyError, TypeError, ValueError):
        return None


def judge(identity: PlaceIdentity | None, *, opted_in: bool, own_places: bool = False,
          own_account_id: int | None = None, studio_name: str = "") -> Verdict:
    """The sandbox rule. Pure: the same facts always give the same answer."""
    if name_is_denied(studio_name) or (identity and (identity.place_id in DENIED_PLACE_IDS
                                                     or identity.game_id in DENIED_UNIVERSE_IDS)):
        return Verdict(False, "denied", "This place is on STAR's deny-list. STAR never edits it. Open a new "
                                         "Baseplate for STAR to build in.", identity)
    if identity is None:
        return Verdict(False, "unknown", "STAR could not find out which place is open, so it only reads.")
    if identity.place_id == 0 and identity.game_id == 0:
        if identity.scripts and not identity.marker:
            return Verdict(False, "not_blank", "This unsaved place already has scripts that STAR did not "
                           "make. Open a new Baseplate for STAR to build in.", identity)
        if not opted_in:
            return Verdict(False, "blank", "A blank place is open. Switch on Studio edits to let STAR build in it.",
                           identity)
        return Verdict(True, "blank", "A blank, unpublished place: STAR may build here.", identity)
    if (identity.creator_type == "User" and own_account_id and identity.creator_id == own_account_id):
        if opted_in and own_places:
            return Verdict(True, "own", "A place of STAR's own Roblox account: STAR may build here.", identity)
        return Verdict(False, "own", "This place belongs to STAR's own Roblox account. Allow 'places of "
                       "STAR's own account' in Settings to let STAR edit it.", identity)
    return Verdict(False, "published", "This is a published place that does not belong to STAR's own "
                   "account. STAR only reads it. Open a new Baseplate for STAR to build in.", identity)


# --------------------------------------------------------------------------- journal and undo

@dataclass
class ChangeJournal:
    """What STAR changed in this session, in order, with what is needed to take it back."""
    entries: list[dict] = field(default_factory=list)

    def report(self) -> dict:
        changes = []
        for entry in self.entries:
            if entry["kind"] == "script":
                changes.append({"what": ("created script " if entry["created"] else "edited script ") + entry["path"],
                                "undo": ("Guarded Studio history undo" if entry["created"] else "Guarded reverse source edit")
                                        if entry["restorable"] and entry.get("known") and entry.get("ok")
                                        else "Manual Studio history (connector recording)" if entry.get("known") and entry.get("ok") and entry.get("connector_recorded")
                                        else "Inspect the unconfirmed edit in Studio"})
            elif entry["kind"] == "luau":
                added = entry.get("added_count", 0)
                changes.append({"what": f"ran an edit: {added} instance(s) added, {entry.get('removed', 0)} removed"
                                        + ("" if entry.get("ok", True) else " (the edit stopped with an error)"),
                                "added": entry.get("added", [])[:20],
                                "undo": "Guarded Studio history undo" if entry.get("known") and entry.get("recorded")
                                        else "Manual Studio history (connector recording)" if entry.get("known") and entry.get("ok") and entry.get("connector_recorded")
                                        else "Inspect the unconfirmed edit in Studio"})
            elif entry["kind"] == "playtest":
                changes.append({"what": ("started a playtest" if entry["start"] else "stopped the playtest")
                                if entry.get("confirmed") else "playtest " + ("start" if entry["start"] else "stop") + " unconfirmed",
                                "undo": "nothing to undo", **({"detail": entry["detail"]} if entry.get("detail") else {})})
            if entry["kind"] in {"script", "luau"} and not entry.get("ok"):
                changes[-1]["what"] += " (failed or outcome unconfirmed)"
            if entry.get("diagnostic"):
                changes[-1]["diagnostic"] = entry["diagnostic"]
        steps = sum(1 for entry in self.entries if entry["kind"] in ("script", "luau"))
        # Track inspection coverage separately from successful changes. Unscoped
        # execute_luau edits cannot claim their touched scene objects were inspected.
        inspections = {"existing_scripts_inspected": sum(
            1 for e in self.entries if e["kind"] == "script" and not e["created"]
            and e.get("target_inspected") is True),
            "new_script_paths": sum(1 for e in self.entries
                                    if e["kind"] == "script" and e["created"]),
            "unscoped_luau_edits": sum(1 for e in self.entries if e["kind"] == "luau")}
        return {"changes": changes, "edits": steps, "inspection": inspections,
                "undo": {"available": steps > 0,
                         # Only what exists: the journal lives for this session, so a later turn
                         # cannot take these edits back by itself; Studio's own undo can.
                         "how": "Inspect unconfirmed operations before recovery. Studio Ctrl+Z handles DataModel history; "
                                "script source uses Script Editor history or a guarded reverse source edit." if steps else ""}}

    def text(self) -> str:
        report = self.report()
        if not report["edits"]:
            return ""
        lines = [f"Studio changes in this turn ({report['edits']}):"]
        for change in report["changes"]:
            if change["undo"] != "nothing to undo":
                lines.append(f"- {change['what']}" + ("".join(f"\n    {item}" for item in change.get("added", [])[:8])))
        lines.append("Undo: " + report["undo"]["how"])
        return "\n".join(lines)


def _plain_source(text: str) -> str:
    """script_read numbers its lines (number, U+2192 arrow, code); give back the code."""
    return "\n".join(re.sub(r"^\s*\d+\u2192", "", line) for line in text.split("\n"))


class _Refused:
    def __init__(self, text: str):
        self._data = {"isError": True, "content": [{"type": "text", "text": text}]}

    def model_dump(self, **_):
        return self._data


async def _call(session, name: str, arguments: dict):
    """Transport errors are failed/uncertain results; cancellation still cancels the caller."""
    try:
        return await session.call_tool(name, arguments=arguments)
    except Exception as exc:
        return _Refused(f"Studio {name} call failed ({type(exc).__name__}); outcome unconfirmed")


def _diagnostic(result, receipt: dict | None = None) -> str:
    """Bounded host-facing engine failure detail; never expose connection/environment text."""
    from .lessons import redact
    problem = receipt.get("problem") if isinstance(receipt, dict) else None
    detail = problem if isinstance(problem, str) else result_text(result) if result_failed(result) else "No valid STAR operation receipt was returned"
    detail = re.sub(r"(?:https?://|[A-Za-z]:[\\/]|\\\\)[^\s\"'<>]+", "[location removed]", detail)
    detail = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b", "[address removed]", detail)
    return redact(detail, limit=500)


def _play_state(result) -> str | None:
    """Only the explicitly tested connector state shape is supported; unknown means unconfirmed."""
    if result_failed(result):
        return None
    try:
        facts = json.loads(result_text(result))
    except ValueError:
        facts = None
    if isinstance(facts, dict):
        return facts.get("playState") if facts.get("playState") in {"Edit", "Playing"} else None
    modes = re.findall(r"(?m)^- Current Studio Mode: ([^\r\n]+)\r?$", result_text(result))
    if len(modes) != 1 or modes[0] not in {"Edit", "Play", "Playing"}:
        return None
    return "Edit" if modes[0] == "Edit" else "Playing"


def _lua_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _bound_code(identity: PlaceIdentity, code: str) -> str:
    """Check the actual DataModel in the same engine call as the mutation.

    Debug IDs distinguish two unsaved Baseplates in one Studio window. A missing
    native identity is a refusal, not permission to reuse only PlaceId zero.
    The header also gives offline connector stand-ins an explicit test contract.
    """
    if not identity.session:
        raise ValueError("Studio did not supply a DataModel session identity")
    pin = {"placeId": identity.place_id, "gameId": identity.game_id,
           "creatorId": identity.creator_id, "creatorType": identity.creator_type,
           "session": identity.session}
    encoded = json.dumps(pin, separators=(",", ":"), ensure_ascii=False)
    return ("-- STAR:bound " + encoded + "\n"
            "local __star_game = game\n"
            "local __star_pin = game:GetService(\"HttpService\"):JSONDecode(" + _lua_string(encoded) + ")\n"
            "local function __star_check()\n"
            "  if game ~= __star_game or game.PlaceId ~= __star_pin.placeId or game.GameId ~= __star_pin.gameId\n"
            "    or game.CreatorId ~= __star_pin.creatorId or game.CreatorType.Name ~= __star_pin.creatorType\n"
            "    or game:GetDebugId(32) .. \":\" .. workspace:GetDebugId(32) ~= __star_pin.session then\n"
            "    error(\"STAR target changed; no mutation accepted\")\n"
            "  end\n"
            "end\n__star_check()\n" + code)


SCRIPT_CAS = """-- STAR:script-cas
local HttpService = game:GetService("HttpService")
local request = HttpService:JSONDecode(%(payload)s)
local parts = string.split(request.path, ".")
local parent = __star_game
for index = 1, #parts - 1 do
  parent = parent and parent:FindFirstChild(parts[index])
end
if not parent then error("STAR script parent is missing") end
local target = parent:FindFirstChild(parts[#parts])
local created = target == nil
if created and request.before ~= nil then error("STAR script was removed") end
if not created and (not target:IsA("LuaSourceContainer") or request.before == nil) then
  error("STAR script changed or already exists")
end
local editor = game:GetService("ScriptEditorService")
if not created and editor:GetEditorSource(target) ~= request.before then
  error("STAR script conflict; owner changes preserved")
end
local history = game:GetService("ChangeHistoryService")
local connectorRecorded = history:IsRecordingInProgress()
local recording = nil
if not connectorRecorded then recording = history:TryBeginRecording(request.tag, request.tag) end
if not recording and not connectorRecorded then error("STAR could not begin an undo recording") end
local ok, problem = pcall(function()
  __star_check()
  if created then
    target = Instance.new(request.className)
    target.Name = parts[#parts]
    target.Parent = parent
  end
  editor:UpdateSourceAsync(target, function(current)
    __star_check()
    if parent:FindFirstChild(parts[#parts]) ~= target or not target:IsDescendantOf(__star_game)
      or current ~= (if created then "" else request.before) then
      error("STAR script conflict; owner changes preserved")
    end
    return request.after
  end)
  __star_check()
  if editor:GetEditorSource(target) ~= request.after then error("STAR script update not confirmed") end
  workspace:SetAttribute("StarSandbox", true)
end)
if recording then history:FinishRecording(recording, Enum.FinishRecordingOperation.Commit) end
local undoCan, undoName = history:GetCanUndo()
return "STAR_EDIT " .. HttpService:JSONEncode({
  tag = request.tag, ok = ok, created = created, recorded = recording ~= nil, connectorRecorded = connectorRecorded,
  instanceId = target and target:GetDebugId(32) or nil,
  undoCan = undoCan, undoName = undoName,
  problem = if ok then nil else tostring(problem),
})
"""


SCRIPT_UNDO_CAS = """-- STAR:script-undo-cas
local HttpService = game:GetService("HttpService")
local request = HttpService:JSONDecode(%(payload)s)
local function resolve()
  local current = __star_game
  for _, name in ipairs(string.split(request.path, ".")) do
    current = current and current:FindFirstChild(name)
  end
  return current
end
local target = resolve()
if not target or not target:IsA("LuaSourceContainer") or target:GetDebugId(32) ~= request.instanceId then
  error("STAR undo conflict; script identity changed")
end
local editor = game:GetService("ScriptEditorService")
if editor:GetEditorSource(target) ~= request.after then error("STAR undo conflict; owner changes preserved") end
local history = __star_game:GetService("ChangeHistoryService")
local canUndo, name = history:GetCanUndo()
if request.created then
  if not canUndo or name ~= request.tag then error("STAR undo conflict; a newer edit must be undone first") end
  __star_check()
  history:Undo()
  __star_check()
  if resolve() ~= nil or target:IsDescendantOf(__star_game) then error("STAR creation undo not confirmed") end
else
  -- DataModel history intentionally excludes Source. Restore source by exact
  -- reverse CAS, never by claiming ChangeHistoryService restored it.
  local function sourceCheck()
    __star_check()
    local currentCan, currentName = history:GetCanUndo()
    if not request.connectorRecorded and (currentCan ~= request.undoCan or currentName ~= request.undoName) then
      error("STAR undo conflict; newer DataModel history must be reviewed first")
    end
    if resolve() ~= target or target:GetDebugId(32) ~= request.instanceId
      or not target:IsDescendantOf(__star_game) then error("STAR undo conflict; script identity changed") end
  end
  sourceCheck()
  editor:UpdateSourceAsync(target, function(current)
    sourceCheck()
    if current ~= request.after then error("STAR undo conflict; owner changes preserved") end
    return request.before
  end)
  sourceCheck()
  if resolve() ~= target or target:GetDebugId(32) ~= request.instanceId
    or editor:GetEditorSource(target) ~= request.before then error("STAR script undo not confirmed") end
end
return "STAR_EDIT " .. HttpService:JSONEncode({ undone = request.tag, ok = true })
"""


NATIVE_UNDO = """-- STAR:recording-undo %(tag)s
local history = game:GetService("ChangeHistoryService")
local canUndo, name = history:GetCanUndo()
if not canUndo or name ~= "%(tag)s" then error("STAR undo conflict; a newer edit must be undone first") end
__star_check()
history:Undo()
__star_check()
local canRedo, undoneName = history:GetCanRedo()
if not canRedo or undoneName ~= "%(tag)s" then error("STAR recording undo not confirmed") end
return "STAR_EDIT " .. game:GetService("HttpService"):JSONEncode({ undone = "%(tag)s", ok = true })
"""


PLAY_BOUND = """-- STAR:play-bound
local tests = __star_game:GetService("StudioTestService")
local job = { status = "queued" }
task.spawn(function()
  local ok, problem = pcall(function()
    __star_check()
    if not tests.EditModeActive then error("STAR cannot start over an existing playtest") end
    job.status = "starting"
    tests:ExecutePlayModeAsync({ starSession = __star_pin.session, starRequest = "%(tag)s" })
    job.status = "completed"
  end)
  if not ok then job.status = "failed"; job.problem = tostring(problem) end
end)
return "STAR_PLAY " .. __star_game:GetService("HttpService"):JSONEncode({
  request = "%(tag)s", requested = job.status == "starting", status = job.status, problem = job.problem,
})
"""


def _play_stop_code(identity: PlaceIdentity, request: str, *, stop: bool) -> str:
    """Fixed host code: Server test arguments bind its clone to the original Edit session."""
    if not identity.session or not re.fullmatch(r"StarEdit_[0-9a-f]{8}", request):
        raise ValueError("the original native play request is unavailable")
    payload = {"placeId": identity.place_id, "gameId": identity.game_id,
               "creatorId": identity.creator_id, "creatorType": identity.creator_type,
               "session": identity.session, "request": request}
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    code = ("-- STAR:play-stop-" + ("bound " if stop else "probe ") + encoded + "\n"
            "local HttpService = game:GetService(\"HttpService\")\n"
            "local expected = HttpService:JSONDecode(" + _lua_string(encoded) + ")\n"
            "local tests = game:GetService(\"StudioTestService\")\n"
            "if not game:GetService(\"RunService\"):IsServer() then error(\"STAR stop requires the Server context\") end\n"
            "local args = tests:GetTestArgs()\n"
            "if game.PlaceId ~= expected.placeId or game.GameId ~= expected.gameId\n"
            "  or game.CreatorId ~= expected.creatorId or game.CreatorType.Name ~= expected.creatorType then\n"
            "  error(\"STAR stop target changed; no stop accepted\")\nend\n"
            "if type(args) ~= \"table\" or args.starSession ~= expected.session\n"
            "  or args.starRequest ~= expected.request then\n"
            "  error(\"STAR stop request changed; no stop accepted\")\nend\n")
    if stop:
        code += ("tests:EndTest({ starStopped = expected.request, starSession = expected.session })\n"
                 "return \"STAR_STOP \" .. HttpService:JSONEncode({ request = expected.request,\n"
                 "  session = expected.session, requested = true })\n")
    else:
        code += ("return \"STAR_PLAY_OWNER \" .. HttpService:JSONEncode({ request = expected.request,\n"
                 "  session = expected.session, matched = true })\n")
    return code


def _server_not_ready(result) -> bool:
    """Only captured native readiness errors permit repeating the fixed read-only probe."""
    text = result_text(result).strip()
    return result_failed(result) and (text in {
        "Target is not reachable",
        "Target is not reachable (createExecuteLuauBridge_loadCodeAsync, Server)",
    } or ("Target is not reachable (ExecuteLuau.loadCode, DMN_ID_PLAYSERVER)" in text
             and "No OnInvoke handler responded" in text))  # wording of the Studio build seen 2026-10-29


class GuardedStudio:
    """What the agent loop talks to instead of the raw connector session.

    Reads STAR knows pass through. An edit is refused unless the verdict allows it and it targets
    the instance that was judged; allowed edits are written to the journal, and a sandbox Luau edit
    is wrapped so it is one undo step and its additions are known. A tool this class has no rule
    for (one a later connector adds, whatever it is called) is refused, never passed on.
    """

    def __init__(self, session, *, studio_id: str, verdict: Verdict, tools: set[str],
                 journal: ChangeJournal | None = None, rule: dict | None = None,
                 uncertainty_store=None, route: str | None = None):
        self.session, self.studio_id, self.verdict, self.tools = session, studio_id, verdict, set(tools)
        self.journal = journal if journal is not None else ChangeJournal()
        self._marked = bool(verdict.identity and verdict.identity.marker)
        # The owner's switches the verdict was made with (judge's keyword arguments), kept so the
        # same rule can be applied again before each change.
        self.rule = dict(rule) if rule is not None else None
        self._play_pending = False
        self._cleanup_task = None
        self._play_identity = self._play_request = self._play_entry = None
        self._play_stop_attempted = False
        self._uncertainty_store, self._uncertainty_scope = uncertainty_store, None
        if uncertainty_store is not None:
            try:
                from .studio_connections import validate_target
                from .studio_uncertainty import StudioScope
                identity = verdict.identity
                self._uncertainty_scope = StudioScope(
                    route=validate_target(route), session=identity.session,
                    place_id=identity.place_id, universe_id=identity.game_id,
                    creator_id=identity.creator_id, creator_type=identity.creator_type)
            except Exception:
                # Reads/explicit stop stay available even with an invalid binding.
                self._uncertainty_scope = None

    def _durable_check(self) -> str | None:
        if self._uncertainty_store is None:
            return None  # Explicit legacy/offline caller; desktop always supplies a store.
        if self._uncertainty_scope is None:
            return "the durable Studio target binding is unavailable; writes are refused"
        try:
            if self._uncertainty_store.pending(self._uncertainty_scope):
                return "an earlier native operation is unresolved; host inspection and explicit acknowledgement are required"
        except Exception:
            return "the durable Studio operation ledger is unavailable; writes are refused"
        return None

    def _durable_begin(self, kind: str, entry: dict) -> str | None:
        if self._uncertainty_store is None:
            return None
        problem = self._durable_check()
        if problem:
            return problem
        try:
            token = self._uncertainty_store.begin(self._uncertainty_scope, kind)
            if not isinstance(token, str) or not token:
                raise ValueError("invalid operation token")
            entry["_pending_token"] = token
        except Exception:
            return "a pending native operation could not be safely recorded; writes are refused"
        return None

    def _durable_confirm(self, entry: dict) -> bool:
        if self._uncertainty_store is None:
            return True
        known = entry.get("confirmed") if entry["kind"] == "playtest" else entry.get("known")
        ok = entry.get("confirmed") if entry["kind"] == "playtest" else entry.get("ok")
        try:
            if self._uncertainty_store.confirm(self._uncertainty_scope, entry.get("_pending_token"),
                                               known=known, ok=ok) is True:
                return True
        except Exception:
            pass
        entry["known"], entry["ok"] = False, False
        if entry["kind"] == "playtest":
            entry["confirmed"] = False
        entry["diagnostic"] = "The native operation succeeded but its durable confirmation could not be recorded; host inspection is required"
        return False

    async def _confirm(self) -> str | None:
        """Just before a change: is the place that was judged still the one that is open?

        A turn can last minutes, and another place can be opened in the same Studio window while
        it runs. So the place is asked again and the sandbox rule applied again. None means go
        ahead. Otherwise nothing is changed: another place than the one judged, or one the rule no
        longer allows, makes the rest of the session read-only; a place that could not be asked
        at this moment refuses only this one change.
        """
        if self.rule is None:
            return "the sandbox rule of this session is not known"
        now = await _look(self.session, self.tools, self.studio_id, self.rule)
        if now.identity is None and now.kind == "unknown":
            return "STAR could not confirm which place is open right now, so nothing was changed"
        judged = self.verdict.identity
        same = judged is not None and now.identity is not None and bool(judged.session) and (
            (judged.place_id, judged.game_id, judged.creator_id, judged.creator_type, judged.session)
            == (now.identity.place_id, now.identity.game_id, now.identity.creator_id,
                now.identity.creator_type, now.identity.session))
        if now.editable and same:
            return None
        self.verdict = now if not now.editable else Verdict(
            False, "changed", "Another place is open in this Studio window than the one STAR checked when "
            "the turn began. STAR only reads it now; ask again to continue there.", now.identity)
        return self.verdict.reason

    async def call_tool(self, name: str, arguments: dict | None = None):
        arguments = dict(arguments or {})
        if name in BLOCKED_TOOLS:
            return _Refused("STAR does not use this Studio tool")
        if name in READ_TOOLS:
            return await _call(self.session, name, arguments)
        if name in PLAYTEST_TOOLS:
            return _Refused("Playtest input is temporarily unavailable: the native connector cannot atomically bind input to STAR's exact play request")
        if name not in WRITE_TOOLS:
            return _Refused("STAR does not know this Studio tool, so it does not use it")
        if arguments.get("studio_id") != self.studio_id:
            return _Refused("Edit refused: that is not the Studio instance STAR checked")
        # Cleanup must remain available after a place switch makes the turn read-only.
        if name == "start_stop_play" and arguments.get("is_start") is False:
            return await self._stop_play()
        problem = self._durable_check()
        if problem:
            return _Refused("Edit refused: " + problem)
        if any((entry["kind"] in {"script", "luau"} and not (entry.get("known") and entry.get("ok")))
               or (entry["kind"] == "playtest" and not entry.get("confirmed"))
               for entry in self.journal.entries):
            return _Refused("Edit refused: an earlier operation is unconfirmed; host inspection and acknowledgement are required")
        if not self.verdict.editable:
            return _Refused("Edit refused: " + self.verdict.reason)
        if name in {"execute_luau", "multi_edit"} and arguments.get("datamodel_type") != "Edit":
            return _Refused("Edit refused: Luau runs in the Edit DataModel only")
        # Persistent changes and native launch recheck the Edit identity. Stop has
        # its own Server request binding above, because Edit is unavailable in Play.
        if name in ("multi_edit", "execute_luau") or (name == "start_stop_play" and arguments.get("is_start") is not False):
            problem = await self._confirm()
            if problem:
                return _Refused("Edit refused: " + problem)
        if name == "multi_edit":
            return await self._edit_script(arguments)
        if name == "execute_luau":
            wrapped, tag = wrap_edit(str(arguments.get("code", "")))
            try:
                wrapped = _bound_code(self.verdict.identity, wrapped)
            except ValueError as exc:
                return _Refused("Edit refused: " + str(exc))
            entry = {"kind": "luau", "tag": tag, "known": False, "ok": False, "recorded": False,
                     "connector_recorded": False, "added": [], "added_count": 0, "removed": 0}
            problem = self._durable_begin("luau", entry)
            if problem:
                return _Refused("Edit refused: " + problem)
            self.journal.entries.append(entry)  # A cancelled/lost reply may follow an applied edit.
            result = await _call(self.session, name, {**arguments, "code": wrapped})
            seen = _marked_json(result_text(result), EDIT_MARK)
            seen = seen if seen and not result_failed(result) and seen.get("tag") == tag \
                and type(seen.get("ok")) is bool and type(seen.get("recorded")) is bool \
                and type(seen.get("connectorRecorded")) is bool and seen["recorded"] != seen["connectorRecorded"] \
                and type(seen.get("addedCount")) is int and seen["addedCount"] >= 0 \
                and type(seen.get("removed")) is int and seen["removed"] >= 0 \
                and isinstance(seen.get("added"), list) else None
            self._marked = self._marked or bool(seen)
            entry.update({"known": bool(seen), "ok": bool(seen.get("ok")) if seen else False,
                "recorded": bool(seen and seen.get("recorded")),
                "connector_recorded": bool(seen and seen.get("connectorRecorded")),
                "added": [str(item)[:160] for item in (seen or {}).get("added", [])][:60],
                "added_count": int((seen or {}).get("addedCount", 0) or 0), "removed": int((seen or {}).get("removed", 0) or 0)})
            if not entry["ok"]:
                entry["diagnostic"] = _diagnostic(result, seen)
            elif not self._durable_confirm(entry):
                return _Refused(entry["diagnostic"])
            return result if seen and seen.get("ok") else _Refused(
                "Studio edit failed or its outcome could not be confirmed; inspect Studio before retrying")
        if name == "start_stop_play" and arguments.get("is_start") is True:
            return await self._start_play()
        return await _call(self.session, name, arguments)

    async def _read(self, path: str) -> str | None:
        if "script_read" not in self.tools:
            return None
        result = await _call(self.session, "script_read", {"studio_id": self.studio_id, "target_file": path,
                                                         "should_read_entire_file": True})
        return None if result_failed(result) else _plain_source(result_text(result))

    async def _edit_script(self, arguments: dict):
        path = str(arguments.get("file_path", ""))
        edits = arguments.get("edits") or []
        if not _SCRIPT_PATH.fullmatch(path) or not isinstance(edits, list) or not 1 <= len(edits) <= 100:
            return _Refused("Edit refused: unsupported script path or edit list")
        before = await self._read(path)
        created = before is None
        # OpenGameEval-style inspect-before-edit: reading a script's text is not
        # the same as verifying the object, its class and its current Studio path.
        # This is a host tool read, never a model assertion. If it fails, no write
        # or durable operation is dispatched. New scripts have no target to inspect.
        inspected = False
        if not created:
            if "inspect_instance" not in self.tools:
                return _Refused("Edit refused: Studio cannot inspect the existing script instance")
            observation = await _call(self.session, "inspect_instance", {
                "studio_id": self.studio_id, "path": path})
            observed_text = result_text(observation).strip()
            if result_failed(observation) or not observed_text or observed_text.lower() == "not found":
                return _Refused("Edit refused: existing Studio script inspection failed")
            try:
                facts = json.loads(observed_text)
            except (ValueError, TypeError):
                facts = None  # Some Studio versions return an unstructured description.
            if isinstance(facts, dict):
                observed_path = facts.get("path", facts.get("fullPath"))
                if observed_path is not None and (
                    type(observed_path) is not str or
                    observed_path.removeprefix("game.") != path.removeprefix("game.")
                ):
                    return _Refused("Edit refused: Studio inspected a different script path")
                kind = facts.get("className")
                if kind is not None and kind not in {"Script", "LocalScript", "ModuleScript"}:
                    return _Refused("Edit refused: inspected object is not a script")
            inspected = True
        class_name = arguments.get("className")
        remaining = edits
        if created:
            if class_name not in {"Script", "LocalScript", "ModuleScript"} or not isinstance(edits[0], dict) \
                    or edits[0].get("old_string") != "" or not isinstance(edits[0].get("new_string"), str):
                return _Refused("Edit refused: creating a script needs a supported class and initial source")
            after, remaining = edits[0]["new_string"], edits[1:]
        else:
            after = before
        for edit in remaining:
            if before == "" and after == "" and isinstance(edit, dict) and edit.get("old_string") == "" \
                    and isinstance(edit.get("new_string"), str):
                after = edit["new_string"]
                continue
            if not isinstance(edit, dict) or not isinstance(edit.get("old_string"), str) \
                    or not isinstance(edit.get("new_string"), str):
                return _Refused("Edit refused: old_string must match the script exactly")
            try:
                # Tolerates indentation/trailing-space slips; refuses anything ambiguous (star/edit_match.py).
                after = apply_edit(after, edit["old_string"], edit["new_string"],
                                   replace_all=bool(edit.get("replace_all"))).text
            except EditMismatch as exc:
                return _Refused("Edit refused: " + str(exc))
        if len(after) > 100_000 or (before is not None and len(before) > 100_000):
            return _Refused("Edit refused: script exceeds the bounded source size")
        if "execute_luau" not in self.tools or self.verdict.identity is None:
            return _Refused("Edit refused: the connector cannot bind a script mutation to its DataModel")
        tag = "StarEdit_" + secrets.token_hex(4)
        payload = {"path": path.removeprefix("game."), "before": before, "after": after,
                   "className": class_name, "tag": tag}
        code = SCRIPT_CAS % {"payload": _lua_string(json.dumps(payload, ensure_ascii=False))}
        try:
            code = _bound_code(self.verdict.identity, code)
        except ValueError as exc:
            return _Refused("Edit refused: " + str(exc))
        entry = {"kind": "script", "path": path, "created": created,
                 "target_inspected": inspected, "before": before,
                 "after": after, "tag": tag, "instance_id": None, "restorable": False,
                 "known": False, "ok": False, "undo_can": None, "undo_name": None,
                 "recorded": False, "connector_recorded": False}
        problem = self._durable_begin("script", entry)
        if problem:
            return _Refused("Edit refused: " + problem)
        self.journal.entries.append(entry)
        result = await _call(self.session, "execute_luau", {
            "studio_id": self.studio_id, "datamodel_type": "Edit", "code": code})
        seen = _marked_json(result_text(result), EDIT_MARK)
        known = bool(seen and not result_failed(result) and seen.get("tag") == tag and type(seen.get("ok")) is bool
                     and type(seen.get("recorded")) is bool and type(seen.get("connectorRecorded")) is bool
                     and seen["recorded"] != seen["connectorRecorded"] and seen.get("created") is created
                     and isinstance(seen.get("instanceId"), str) and 0 < len(seen["instanceId"]) <= 160
                     and type(seen.get("undoCan")) is bool
                     and ((seen["undoCan"] and isinstance(seen.get("undoName"), str) and 0 < len(seen["undoName"]) <= 160)
                          or (not seen["undoCan"] and seen.get("undoName") is None)))
        # A lost response can follow an applied write. Preserve an uncertain journal
        # entry, but never authorize path-only undo or replay that write automatically.
        entry.update({
                                     "instance_id": seen.get("instanceId") if known else None,
                                     "restorable": bool(known and seen.get("ok") and (not created or seen.get("recorded"))),
                                     "known": known, "ok": bool(known and seen.get("ok")),
                                     "undo_can": seen.get("undoCan") if known else None,
                                     "undo_name": seen.get("undoName") if known else None,
                                     "recorded": bool(known and seen.get("recorded")),
                                     "connector_recorded": bool(known and seen.get("connectorRecorded"))})
        self._marked = self._marked or bool(known and seen.get("ok"))
        if not entry["ok"]:
            entry["diagnostic"] = _diagnostic(result, seen)
        elif not self._durable_confirm(entry):
            entry["restorable"] = False
            return _Refused(entry["diagnostic"])
        return result if known and seen.get("ok") and not result_failed(result) else _Refused(
            "Studio script edit failed or its outcome could not be confirmed; inspect Studio before retrying. "
            + entry["diagnostic"])

    async def _start_play(self):
        """Launch through the bound engine service, then confirm actual play state."""
        if self.verdict.identity is None:
            return _Refused("Playtest refused: no bound DataModel")
        try:
            tag = "StarEdit_" + secrets.token_hex(4)
            code = _bound_code(self.verdict.identity, PLAY_BOUND % {"tag": tag})
        except ValueError as exc:
            return _Refused("Playtest refused: " + str(exc))
        if not {"execute_luau", "get_studio_state"} <= self.tools:
            return _Refused("Playtest refused: bound launch, state and stop tools are required")
        entry = {"kind": "playtest", "start": True, "confirmed": False, "request": tag}
        problem = self._durable_begin("play_start", entry)
        if problem:
            return _Refused("Playtest refused: " + problem)
        self.journal.entries.append(entry)
        self._play_pending, self._cleanup_task = True, None
        self._play_identity, self._play_request, self._play_entry = self.verdict.identity, tag, entry
        self._play_stop_attempted = False
        try:
            async with asyncio.timeout(PLAY_START_SECONDS):
                requested = await _call(self.session, "execute_luau", {
                    "studio_id": self.studio_id, "datamodel_type": "Edit", "code": code})
                seen = _marked_json(result_text(requested), PLAY_MARK)
                if result_failed(requested) or not seen or seen.get("request") != tag \
                        or seen.get("requested") is not True or seen.get("status") != "starting":
                    entry["detail"] = "Playtest request failed or its outcome could not be confirmed"
                    entry["diagnostic"] = _diagnostic(requested, seen)
                    await self._stop_cleanup()
                    return _Refused(entry["detail"])
                while True:
                    state = await _call(self.session, "get_studio_state", {"studio_id": self.studio_id})
                    mode = _play_state(state)
                    if mode == "Playing":
                        owner = await _call(self.session, "execute_luau", {
                            "studio_id": self.studio_id, "datamodel_type": "Server",
                            "code": _play_stop_code(self._play_identity, tag, stop=False)})
                        ownership = _marked_json(result_text(owner), PLAY_OWNER_MARK)
                        if _server_not_ready(owner):
                            await asyncio.sleep(PLAY_POLL_SECONDS)
                            continue
                        if result_failed(owner) or not ownership or ownership.get("request") != tag \
                                or ownership.get("session") != self._play_identity.session or ownership.get("matched") is not True:
                            entry["detail"] = "Playing state does not confirm this native play request"
                            entry["diagnostic"] = _diagnostic(owner, ownership)
                            await self._stop_cleanup()
                            return _Refused(entry["detail"])
                        entry["confirmed"] = True
                        if not self._durable_confirm(entry):
                            await self._stop_cleanup()
                            return _Refused(entry["diagnostic"])
                        return requested
                    if mode != "Edit":
                        entry["detail"] = "Playtest state could not be read in the supported format"
                        await self._stop_cleanup()
                        return _Refused(entry["detail"])
                    await asyncio.sleep(PLAY_POLL_SECONDS)
        except asyncio.CancelledError:
            entry["detail"] = "Playtest start cancelled; launch outcome unconfirmed"
            await self._stop_cleanup()
            raise
        except TimeoutError:
            entry["detail"] = "Playtest did not reach a confirmed Playing state within its deadline"
            await self._stop_cleanup()
            return _Refused(entry["detail"])

    async def _stop_play(self):
        """End only this guard's native request; never stop an unrelated Studio playtest."""
        entry = {"kind": "playtest", "start": False, "confirmed": False}
        self.journal.entries.append(entry)
        identity = self._play_identity or self.verdict.identity
        request = self._play_request

        def refuse(detail):
            entry["detail"] = detail
            return _Refused(detail)

        async def original_edit():
            current = await identify(self.session, self.studio_id, tools=self.tools)
            return bool(identity and identity.session and current and
                        (current.place_id, current.game_id, current.creator_id, current.creator_type, current.session)
                        == (identity.place_id, identity.game_id, identity.creator_id, identity.creator_type, identity.session))

        try:
            async with asyncio.timeout(PLAY_STOP_SECONDS):
                if self._play_stop_attempted:
                    return refuse("An earlier native stop was already dispatched; host inspection is required before retrying")
                while True:
                    state = await _call(self.session, "get_studio_state", {"studio_id": self.studio_id})
                    mode = _play_state(state)
                    if mode == "Edit":
                        if not await original_edit():
                            return refuse("Playtest cleanup refused: the original Edit DataModel is no longer open")
                        entry["confirmed"], self._play_pending = True, False
                        return {"content": [{"type": "text", "text": "The original native session is already in Edit mode"}], "isError": False}
                    if mode != "Playing":
                        return refuse("Playtest stop state could not be confirmed")
                    if identity is None or not request:
                        return refuse("Playtest cleanup refused: this guard has no original native play request")
                    probe = await _call(self.session, "execute_luau", {"studio_id": self.studio_id,
                        "datamodel_type": "Server", "code": _play_stop_code(identity, request, stop=False)})
                    seen = _marked_json(result_text(probe), PLAY_OWNER_MARK)
                    if result_failed(probe):
                        # Server bridge readiness can lag behind the Playing state. Only this
                        # known read-only readiness failure is polled; EndTest is never retried.
                        if _server_not_ready(probe):
                            await asyncio.sleep(PLAY_POLL_SECONDS)
                            continue
                        entry["diagnostic"] = _diagnostic(probe, seen)
                        return refuse("Playtest cleanup refused: the original Server test could not be verified")
                    if not seen or seen.get("request") != request or seen.get("session") != identity.session or seen.get("matched") is not True:
                        return refuse("Playtest cleanup refused: the Server test does not match the original native request")
                    break

                # A lost start remains unresolved even when this same guard safely ends it.
                # Confirmed starts get a separate durable stop operation before dispatch.
                if self._uncertainty_store is not None:
                    if self._uncertainty_scope is None:
                        return refuse("Playtest cleanup refused: the durable native binding is unavailable")
                    try:
                        pending = self._uncertainty_store.pending(self._uncertainty_scope)
                    except Exception:
                        pending = None
                        entry["diagnostic"] = "The operation ledger is unavailable; bound cleanup does not restore permission to write"
                    if pending:
                        start_token = (self._play_entry or {}).get("_pending_token")
                        if len(pending) != 1 or pending[0].get("token") != start_token or pending[0].get("kind") != "play_start":
                            return refuse("Playtest cleanup refused: an unrelated native operation remains unresolved")
                        entry["retains_start_uncertainty"] = True
                    elif pending == []:
                        problem = self._durable_begin("play_stop", entry)
                        if problem:
                            return refuse("Playtest cleanup refused: " + problem)
                self._play_stop_attempted = True
                stopped = await _call(self.session, "execute_luau", {"studio_id": self.studio_id,
                    "datamodel_type": "Server", "code": _play_stop_code(identity, request, stop=True)})
                seen = _marked_json(result_text(stopped), PLAY_STOP_MARK)
                if result_failed(stopped) or not seen or seen.get("request") != request or seen.get("session") != identity.session or seen.get("requested") is not True:
                    entry["diagnostic"] = _diagnostic(stopped, seen)
                    return refuse("Playtest stop was refused or its outcome could not be confirmed; no stop will be replayed")
                while True:
                    state = await _call(self.session, "get_studio_state", {"studio_id": self.studio_id})
                    mode = _play_state(state)
                    if mode == "Edit":
                        if not await original_edit():
                            return refuse("Playtest stop returned to a different Edit DataModel; cleanup is unconfirmed")
                        entry["confirmed"], self._play_pending = True, False
                        if entry.get("_pending_token") and not self._durable_confirm(entry):
                            return refuse(entry["diagnostic"])
                        return stopped
                    if mode != "Playing":
                        return refuse("Playtest stop state could not be confirmed")
                    await asyncio.sleep(PLAY_POLL_SECONDS)
        except TimeoutError:
            return refuse("Playtest did not reach a verified original Edit state within its stop deadline")
        except asyncio.CancelledError:
            entry["detail"] = "Native stop cancelled; its outcome remains unresolved and will not be replayed"
            raise

    async def _stop_cleanup(self):
        # The local MCP handler runs in AnyIO level-triggered cancel scopes;
        # asyncio.shield alone does not protect subsequent checkpoints there.
        with anyio.CancelScope(shield=True):
            if self._cleanup_task is None:
                self._cleanup_task = asyncio.create_task(self._stop_play())
            return await asyncio.shield(self._cleanup_task)

    async def undo(self) -> dict:
        """Take back this session's edits, newest first, as far as STAR can do it exactly."""
        done, left = [], []
        problem = self._durable_check()
        if problem:
            return {"undone": done, "left": ["Undo refused: " + problem]}
        if not self.verdict.editable:
            return {"undone": done, "left": ["Undo refused: " + self.verdict.reason]}
        problem = await self._confirm()        # the undo removes and rewrites things: same check
        if problem:
            return {"undone": done, "left": ["Undo refused: " + problem]}
        completed = set()
        blocked = False
        for index in range(len(self.journal.entries) - 1, -1, -1):
            entry = self.journal.entries[index]
            if entry["kind"] not in {"luau", "script"}:
                continue
            label = entry.get("path") or "a Luau edit"
            if blocked or not entry.get("known") or "execute_luau" not in self.tools:
                left.append("use Ctrl+Z in Studio for: " + label)
                blocked = True
                continue
            if entry["kind"] == "script" and entry.get("restorable"):
                payload = {"path": entry["path"].removeprefix("game."), "created": entry["created"],
                           "before": entry["before"], "after": entry["after"], "tag": entry["tag"],
                           "instanceId": entry["instance_id"], "undoCan": entry["undo_can"], "undoName": entry["undo_name"],
                           "connectorRecorded": entry["connector_recorded"]}
                code = SCRIPT_UNDO_CAS % {"payload": _lua_string(json.dumps(payload, ensure_ascii=False))}
            elif entry["kind"] == "luau" and entry.get("recorded"):
                code = NATIVE_UNDO % {"tag": entry["tag"]}
            else:
                left.append("use Ctrl+Z in Studio for: " + label)
                blocked = True
                continue
            try:
                code = _bound_code(self.verdict.identity, code)
            except ValueError:
                left.append("undo refused; no bound DataModel for: " + label)
                blocked = True
                continue
            problem = self._durable_begin("undo", entry)
            if problem:
                left.append("undo refused; " + problem)
                blocked = True
                continue
            entry["known"], entry["ok"] = False, False
            result = await _call(self.session, "execute_luau", {
                "studio_id": self.studio_id, "datamodel_type": "Edit", "code": code})
            seen = _marked_json(result_text(result), EDIT_MARK)
            if result_failed(result) or not seen or seen.get("undone") != entry["tag"] or seen.get("ok") is not True:
                entry["diagnostic"] = _diagnostic(result, seen)
                left.append("undo not confirmed; owner changes preserved for: " + label)
                blocked = True
                continue
            entry["known"], entry["ok"] = True, True
            if not self._durable_confirm(entry):
                left.append("undo completed but its durable confirmation is unresolved for: " + label)
                blocked = True
                continue
            completed.add(index)
            done.append(("removed script " if entry["created"] else "restored script ") + entry["path"]
                        if entry["kind"] == "script" else "undid recorded Luau edit")
        self.journal.entries = [entry for index, entry in enumerate(self.journal.entries) if index not in completed]
        return {"undone": done, "left": left}


async def _look(session, tools: set[str], studio_id: str, rule: dict) -> Verdict:
    """Find the instance, ask the open place what it is, apply the sandbox rule. Reads only."""
    name = ""
    if "list_roblox_studios" in tools:
        listing = await _call(session, "list_roblox_studios", {})
        if result_failed(listing):
            return Verdict(False, "unknown", "The Studio instance list could not be read.")
        listed = studios(listing)
        name = next((item["name"] for item in listed if item["id"] == studio_id), "")
        if listed and not any(item["id"] == studio_id for item in listed):
            return Verdict(False, "unknown", "The chosen Studio instance is not open any more.")
    identity = await identify(session, studio_id, tools=tools, studio_name=name)
    return judge(identity, studio_name=name, **rule)


async def open_guarded(session, discovered: list[dict], *, studio_id: str, opted_in: bool,
                       own_places: bool = False, own_account_id: int | None = None,
                       uncertainty_store=None, route: str | None = None) -> GuardedStudio:
    """Connect step of the loop: find the instance, ask what it is, apply the sandbox rule.

    The same look is repeated before every change (GuardedStudio._confirm)."""
    tools = {tool.get("name", "") for tool in discovered}
    rule = {"opted_in": opted_in, "own_places": own_places, "own_account_id": own_account_id}
    verdict = await _look(session, tools, studio_id, rule)
    return GuardedStudio(session, studio_id=studio_id, verdict=verdict, tools=tools, rule=rule,
                         uncertainty_store=uncertainty_store, route=route)


def own_account_id(home) -> int | None:
    """STAR's own Roblox account: the account of the connected API key, as its last test showed it."""
    from .roblox_cloud import RobloxCloud
    try:
        last = RobloxCloud(home=home).status().get("last_check") or {}
    except Exception:
        return None
    account = (last.get("account") or {}).get("user_id") if last.get("state") in ("valid", "missing_permission") else None
    return account if type(account) is int and account > 0 else None


def with_report(outcome, studio: GuardedStudio):
    """Append what was changed in Studio, and how to undo it, to the answer of a turn. Written by
    code from the journal, so it is there whether or not the model mentions its edits."""
    text = studio.journal.text()
    if not text or not isinstance(outcome, tuple) or not outcome or not isinstance(outcome[0], str):
        return outcome
    return (outcome[0].rstrip() + "\n\n" + text, *outcome[1:])


# --------------------------------------------------------------------------- the loop, step by step

ERROR_LINE = re.compile(r"(?i)\b(error|exception|attempt to|is not a valid member|stack begin|infinite yield)\b")


def console_errors(text: str) -> list[str]:
    return [line.strip()[:400] for line in text.splitlines() if ERROR_LINE.search(line)][:40]


async def run_build_loop(studio: GuardedStudio, *, scripts: list[dict], luau_edits: list[str] = (),
                         fix=None, settle=None, undo_at_end: bool = False) -> dict:
    """One full pass of the loop without a model, for the fake connector and for the live check.

    `scripts`: [{path, class_name, source}] to create or replace. `luau_edits`: sandbox Luau that
    builds instances. `fix(errors)` returns the same kind of script list to repair what the
    playtest printed. `settle()` is awaited while the playtest runs.
    """
    session, sid, tools = studio.session, studio.studio_id, studio.tools
    steps: list[dict] = []
    report = {"verdict": studio.verdict.public(), "tools": classify([{"name": name} for name in tools]),
              "steps": steps, "ok": False}

    async def read(name, **arguments):
        result = await _call(session, name, {"studio_id": sid, **arguments})
        return result, result_text(result)

    async def shot(label):
        if "screen_capture" not in tools:
            return steps.append({"step": "screenshot " + label, "ok": False, "detail": "the connector has no screen_capture"})
        result = await _call(session, "screen_capture", {"studio_id": sid, "capture_id": label})
        data = result.model_dump(by_alias=True, exclude_none=True) if hasattr(result, "model_dump") else result
        images = [part for part in (data.get("content", []) if isinstance(data, dict) else [])
                  if isinstance(part, dict) and part.get("type") == "image" and part.get("data")]
        steps.append({"step": "screenshot " + label, "ok": bool(images) and not result_failed(result),
                      "bytes": sum(len(str(part.get("data", ""))) for part in images)})

    async def write(items):
        for item in items:
            existing = await studio._read(item["path"])
            edit = ({"old_string": existing, "new_string": item["source"]} if existing is not None
                    else {"old_string": "", "new_string": item["source"]})
            if existing == item["source"]:
                continue
            result = await studio.call_tool("multi_edit", {
                "studio_id": sid, "datamodel_type": "Edit", "file_path": item["path"], "edits": [edit],
                **({} if existing is not None else {"className": item.get("class_name", "Script")})})
            steps.append({"step": "write " + item["path"], "ok": not result_failed(result),
                          "detail": result_text(result)[:200] if result_failed(result) else ""})
            if result_failed(result):
                return False
        return True

    async def playtest(label):
        step = {"step": "playtest " + label, "ok": False, "errors": None}
        steps.append(step)
        try:
            started = await studio.call_tool("start_stop_play", {"studio_id": sid, "is_start": True})
            if result_failed(started):
                step["detail"] = result_text(started)[:200]
                return None
            if settle is not None:
                await settle()
            result, output = await read("get_console_output")
            step["console_ok"] = not result_failed(result)
            if result_failed(result):
                step["detail"] = "Console output could not be read; no clean-playtest claim is possible"
                return None
            step.update(errors=console_errors(output), output_chars=len(output))
        except Exception as exc:
            step["detail"] = f"Playtest failed ({type(exc).__name__})"
            return None
        finally:
            if studio._play_pending:
                stopped = await studio._stop_cleanup()
                step["stop_ok"] = not result_failed(stopped)
                if result_failed(stopped):
                    step["detail"] = result_text(stopped)[:200]
            else:
                step["stop_ok"] = True
            step["ok"] = step.get("console_ok") is True and step["stop_ok"] and step["errors"] is not None
        return step["errors"] if step["ok"] else None

    try:
        result, state = await read("get_studio_state")
        steps.append({"step": "connect", "ok": _play_state(result) is not None, "state": state[:300]})
        result, tree = await read("search_game_tree", datamodel_type="Edit", max_depth=2)
        steps.append({"step": "read tree", "ok": not result_failed(result) and bool(tree), "chars": len(tree)})
        result, found = await read("script_grep", query="function")
        steps.append({"step": "read scripts", "ok": not result_failed(result), "chars": len(found)})
        await shot("before")
        if not studio.verdict.editable:
            report["stopped"] = "read only: " + studio.verdict.reason
            return report
        if not all(step["ok"] for step in steps):
            report["stopped"] = "required Studio read or screenshot failed"
            return report
        if not await write(scripts):
            report["stopped"] = "script edit failed or unconfirmed"
            return report
        for code in luau_edits:
            result = await studio.call_tool("execute_luau", {"studio_id": sid, "datamodel_type": "Edit", "code": code})
            ok = not result_failed(result) and bool(studio.journal.entries and studio.journal.entries[-1].get("ok"))
            steps.append({"step": "build instances", "ok": ok})
            if not ok:
                report["stopped"] = "Luau edit failed or unconfirmed"
                return report
        errors = await playtest("first")
        if errors is None:
            report["stopped"] = "playtest failed or unconfirmed"
            return report
        await shot("after first playtest")
        if errors and fix is not None:
            if not await write(fix(errors)):
                report["stopped"] = "repair edit failed or unconfirmed"
                return report
            errors = await playtest("after the fix")
            if errors is None:
                report["stopped"] = "repair playtest failed or unconfirmed"
                return report
            await shot("after the fix")
        report["ok"] = errors == [] and all(step["ok"] for step in steps)
        return report
    except asyncio.CancelledError:
        report["stopped"] = "cancelled; inspect any unconfirmed edits"
        raise
    except Exception as exc:
        report["stopped"] = f"Studio build loop failed ({type(exc).__name__})"
        return report
    finally:
        if studio._play_pending:
            stopped = await studio._stop_cleanup()
            if result_failed(stopped):
                report["ok"] = False
                report["cleanup"] = result_text(stopped)[:200]
        report["changes"] = studio.journal.report()
        if undo_at_end:
            report["undo"] = await studio.undo()
            if report["undo"]["left"]:
                report["ok"] = False
