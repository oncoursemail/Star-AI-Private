"""Roblox architecture rules: deterministic checks for the semantic mistakes the strict judges failed gemma's answers for
(docs/agents/litha-rules-20261028.md has the mined failure families and each rule's measured false-positive rate).

    hits = check(answer_text, question="")        # [{"rule", "severity", "family", "message", "note", "line", ...}]

Each rule has an id, a severity ("error" = the feature does not work or is unsafe; "warning" = weaker), a message
written for the fix model (what is wrong and exactly how to fix it), a one-line kid-friendly note for the user, and
the official API names worth looking up in the docs index for the fix prompt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from . import scan
from .scan import Answer, Block


@dataclass(frozen=True)
class Rule:
    id: str
    severity: str
    family: str
    message: str
    note: str
    docs: tuple[str, ...]
    check: Callable[[Answer, str], list[dict]]


RULES: list[Rule] = []


def rule(rule_id, severity, family, message, note, docs=()):
    def deco(fn):
        RULES.append(Rule(rule_id, severity, family, message, note, tuple(docs), fn))
        return fn
    return deco


def hit(block: Block | None = None, pos: int | None = None, evidence: str = "") -> dict:
    out = {"evidence": evidence.strip()[:160]}
    if block is not None:
        out["block"] = block.index
        if pos is not None:
            out["line"] = scan.line_of(block.code, pos)
    return out


def _roblox(ans: Answer, question: str) -> bool:
    if any(b.luau and b.lang in ("lua", "luau") for b in ans.blocks):
        return True
    return bool(re.search(r"roblox|luau|\bstudio\b|leaderstats|RemoteEvent|LocalScript|ServerScriptService|"
                          r"game:GetService", question + "\n" + ans.text, re.I))


# ---- 1. script type vs location ---------------------------------------------------------------------------------------
@rule("localscript-never-runs", "error", "placement",
      "A LocalScript is placed where LocalScripts never run (Workspace parts, ProximityPrompts, ServerScriptService, "
      "ReplicatedStorage, ServerStorage). LocalScripts only run in StarterPlayerScripts, StarterCharacterScripts, "
      "StarterGui, StarterPack/a Tool, or ReplicatedFirst. Fix: if the work is world/server work (doors, "
      "ProximityPrompt.Triggered, Touched rewards, leaderstats), make it a server Script in the part or in "
      "ServerScriptService (ProximityPrompt.Triggered and Touched fire on the server and give you the player); if it "
      "is really client work (input, camera, GUI), put the LocalScript in StarterPlayerScripts and find the part with "
      "workspace:WaitForChild.",
      "LocalScripts only run in player places like StarterPlayerScripts, so I fixed where the script goes.",
      ("LocalScript", "ProximityPrompt.Triggered"))
def _localscript_never_runs(ans: Answer, q: str) -> list[dict]:
    out = []
    for b in ans.luau:
        local = b.kind == "local" or (b.kind == "either" and re.search(
            r"local ?script\s*(or|/)|script\s*(or|/)\s*(a\s+)?local ?script", b.label, re.I))
        if local and b.place in ("world", "sss", "storage") and \
                not re.search(r"ReplicatedFirst|StarterGui|StarterPlayer|StarterCharacter", b.label, re.I):
            out.append(hit(b, 0, b.label))
    if not out:
        pat = re.compile(r"\bLocalScript\b(?:(?!\bScript\b|,)[^.\n]){0,60}\b(in|inside|into|under)\b"
                         r"(?:(?!\bScript\b|,)[^.\n]){0,40}\b(Workspace|"
                         r"ServerScriptService|ServerStorage|the (door|part|brick|block|coin|pad|NPC|ProximityPrompt|"
                         r"prompt|lava|platform)|a (part|ProximityPrompt|brick)|your (door|part|brick|ProximityPrompt))\b",
                         re.I)
        for s in scan.sentences(ans.prose):
            m = pat.search(s)
            if m and not scan.NEGATION.search(s) and not re.search(r"StarterPlayer|StarterGui|StarterCharacter|"
                                                                   r"ReplicatedFirst|StarterPack|\bTool\b", s, re.I):
                out.append(hit(None, None, s))
                break
    return out


@rule("script-never-runs", "error", "placement",
      "A server Script is placed where server Scripts never run (StarterPlayerScripts, ReplicatedStorage, "
      "ReplicatedFirst, ServerStorage). Server Scripts run in Workspace (inside a part/model) and ServerScriptService. "
      "Fix: move it to ServerScriptService (or inside the part it controls), or make it a LocalScript if it is "
      "client work.",
      "Server Scripts only run in Workspace or ServerScriptService, so I moved it.",
      ("Script", "ServerScriptService"))
def _script_never_runs(ans: Answer, q: str) -> list[dict]:
    out = []
    for b in ans.luau:
        wrong = b.place == "storage" or (b.place == "client" and re.search(r"StarterPlayerScripts|ReplicatedFirst",
                                                                           b.label, re.I))
        if b.kind == "server" and wrong and not re.search(r"ServerScriptService|Workspace|StarterCharacterScripts",
                                                          b.label, re.I):
            out.append(hit(b, 0, b.label))
    return out


SERVER_ONLY = [
    (r"DataStoreService", "DataStoreService"),
    (r"GetService\(\s*[\"']ServerStorage[\"']\s*\)|(?<![\w.])ServerStorage\s*[:.]", "ServerStorage"),
    (r"GetService\(\s*[\"']ServerScriptService[\"']\s*\)", "ServerScriptService"),
    (r"\.OnServerEvent\b", "OnServerEvent"),
    (r"\.OnServerInvoke\b", "OnServerInvoke"),
    (r":FireClient\s*\(|:FireAllClients\s*\(", "FireClient/FireAllClients"),
    (r":InvokeClient\s*\(", "InvokeClient"),
    (r"MessagingService", "MessagingService"),
    (r":AwardBadge(Async)?\s*\(", "BadgeService:AwardBadge"),
    (r"\.ProcessReceipt\s*=", "MarketplaceService.ProcessReceipt"),
    (r":LoadCharacter\s*\(", "Player:LoadCharacter"),
    (r":BanAsync\s*\(", "Players:BanAsync"),
]
CLIENT_ONLY = [
    (r"(?<![\w])(game\.)?Players\.LocalPlayer|GetService\(\s*[\"']Players[\"']\s*\)\.LocalPlayer|"
     r"(?<![\w])\w*[Pp]layers\.LocalPlayer", "Players.LocalPlayer"),
    (r":FireServer\s*\(", "FireServer"),
    (r"\.OnClientEvent\b", "OnClientEvent"),
    (r":InvokeServer\s*\(", "InvokeServer"),
    (r"\.OnClientInvoke\b", "OnClientInvoke"),
    (r"UserInputService", "UserInputService"),
    (r"ContextActionService", "ContextActionService"),
    (r":GetMouse\s*\(", "Player:GetMouse"),
    (r"RenderStepped|:BindToRenderStep\s*\(", "RenderStepped/BindToRenderStep"),
    (r"CurrentCamera", "workspace.CurrentCamera"),
    (r"StarterGui\s*:\s*SetCore", "StarterGui:SetCore"),
    (r"\.(MessageReceived|OnIncomingMessage)\b", "TextChatService.MessageReceived"),
]


def _side(b: Block) -> str:
    if b.kind == "local":
        return "client"
    if b.kind == "server":
        return "server"
    if b.kind in ("module", "either"):
        return ""
    if b.place in ("sss", "world") and re.search(r"\bscript\b", b.label, re.I):
        return "server"
    if b.place == "client" and re.search(r"\bscript\b", b.label, re.I):
        return "client"
    return ""


@rule("server-api-in-localscript", "error", "client-server",
      "A LocalScript uses server-only things (DataStoreService, ServerStorage, OnServerEvent, FireClient, "
      "AwardBadge, LoadCharacter ...). These fail or do nothing on the client. Fix: move that part into a server "
      "Script in ServerScriptService; if the client must ask for it, the LocalScript fires a RemoteEvent "
      "(FireServer) and the server Script does the work in OnServerEvent after checking the request.",
      "That part only works on the server, so it now lives in a server Script.",
      ("RemoteEvent", "RemoteEvent.OnServerEvent"))
def _server_api_in_local(ans: Answer, q: str) -> list[dict]:
    out = []
    for b in ans.luau:
        if _side(b) != "client":
            continue
        for pat, name in SERVER_ONLY:
            m = re.search(pat, b.nocomment)
            if m:
                out.append(hit(b, m.start(), name))
                break
    return out


@rule("client-api-in-server-script", "error", "client-server",
      "A server Script uses client-only things (Players.LocalPlayer, FireServer, OnClientEvent, UserInputService, "
      "the camera, GetMouse, RenderStepped, TextChatService.MessageReceived). On the server LocalPlayer is nil and "
      "these never fire. Fix: put that code in a LocalScript in StarterPlayerScripts (or StarterGui for GUI), and "
      "use a RemoteEvent if the server must react; on the server get the player from the event (PlayerAdded, "
      "Touched -> Players:GetPlayerFromCharacter, ProximityPrompt.Triggered(player), OnServerEvent(player)).",
      "That part only works on the player's computer, so it now lives in a LocalScript.",
      ("Players.LocalPlayer", "RemoteEvent:FireServer"))
def _client_api_in_server(ans: Answer, q: str) -> list[dict]:
    out = []
    for b in ans.luau:
        if _side(b) != "server":
            continue
        for pat, name in CLIENT_ONLY:
            m = re.search(pat, b.nocomment)
            if m:
                out.append(hit(b, m.start(), name))
                break
    return out


@rule("fireserver-and-onserverevent-in-one-script", "error", "client-server",
      "One script both calls :FireServer and listens to .OnServerEvent: client and server code are mixed in one "
      "script, so half of it can never run. Fix: split it: a LocalScript (StarterPlayerScripts or the GUI) calls "
      "remote:FireServer(...), a server Script in ServerScriptService handles remote.OnServerEvent; say where each "
      "goes.",
      "Client and server code are now in two separate scripts, each in its right place.",
      ("RemoteEvent:FireServer", "RemoteEvent.OnServerEvent"))
def _mixed(ans: Answer, q: str) -> list[dict]:
    out = []
    for b in ans.luau:
        c = b.nocomment
        if re.search(r":FireServer\s*\(", c) and re.search(r"\.OnServerEvent\b", c) and b.kind != "either":
            out.append(hit(b, c.find(":FireServer"), "FireServer + OnServerEvent"))
    return out


PARENT_PART = re.compile(r"script\.Parent\s*(\.\s*(Touched|Triggered|ClickDetector|Position|CFrame|Anchored|"
                         r"Transparency|BrickColor|Color|Size|CanCollide|MouseButton1Click|Activated)\b|"
                         r":\s*WaitForChild\(\s*[\"'](ProximityPrompt|ClickDetector)[\"'])")


@rule("script-parent-is-a-service", "error", "placement",
      "The script is placed in ServerScriptService (or StarterPlayerScripts) but its code treats script.Parent as a "
      "part, prompt or button (script.Parent.Touched/.Triggered/.Position ...). There script.Parent is the service "
      "folder, so this errors. Fix: either put the Script inside the part (then script.Parent is the part), or keep "
      "it in ServerScriptService and get the part with workspace:WaitForChild(\"PartName\").",
      "The script now finds its part properly instead of guessing.",
      ("Instance:WaitForChild",))
def _parent_service(ans: Answer, q: str) -> list[dict]:
    out = []
    for b in ans.luau:
        in_sss = b.place == "sss" and not re.search(r"inside (the|your|a|this) (part|door|model|button|pad|brick)",
                                                    b.label, re.I)
        in_sps = b.kind == "local" and re.search(r"StarterPlayerScripts", b.label) and \
            not re.search(r"StarterGui|Tool|StarterCharacterScripts", b.label)
        if in_sss or in_sps:
            m = PARENT_PART.search(b.nocomment)
            if m:
                out.append(hit(b, m.start(), m.group(0)))
    return out


# ---- 2. client-server trust ---------------------------------------------------------------------------------------------
@rule("client-changes-currency", "error", "client-server",
      "A LocalScript changes leaderstats/currency values. Changes made on the client never reach the server, so "
      "nobody else sees them and they are not saved (and exploiters could set any number). Fix: the LocalScript "
      "only asks (remote:FireServer(\"what happened\")); a server Script checks the request and changes the "
      "leaderstats value.",
      "Coins are now changed by the server, so they really count and can't be faked.",
      ("RemoteEvent.OnServerEvent", "IntValue.Value"))
def _client_currency(ans: Answer, q: str) -> list[dict]:
    out = []
    for b in ans.luau:
        if _side(b) != "client":
            continue
        m = re.search(r"leaderstats[\w.:()\"' ]*\.Value\s*(=(?!=)|\+=|-=)|"
                      r"(coins?|cash|money|gold|points?|gems?|xp)\w*\.Value\s*(=(?!=)|\+=|-=)", b.clean, re.I)
        if m:
            out.append(hit(b, m.start(), b.code[m.start():m.end() + 30]))
    return out


AMOUNTISH = re.compile(r"amount|coins?|gold|cash|money|points?|xp|exp|gems?|score|damage|dmg|reward|price|cost|"
                       r"value|num|count|qty|quantity|kills?|level|health|speed|power|jump|bonus|gain|earn", re.I)
CURRENCY_TARGET = re.compile(r"(leaderstats|coins?|cash|money|gold|points?|gems?|xp|exp|score|kills?|wins?|level|"
                             r"stat)\w*[\w.:()\"' \[\]]*\.Value", re.I)


def _uses_param(line: str, p: str) -> bool:
    """`p` used as a value on this line (not only as a key into a server table: prices[p] is fine)."""
    stripped = re.sub(r"\[[^\]]*\]", "[]", line)
    return bool(re.search(rf"(?<![\w.:]){re.escape(p)}(?![\w])", stripped))


@rule("server-trusts-client-value", "error", "client-server",
      "The server's OnServerEvent handler uses a number or object the CLIENT sent (amount, price, damage, target, "
      "speed, position) to change stats/health/position. Exploiters can send anything, so a cap or 'amount > 0' "
      "check is not enough. Fix: the client only says WHAT happened (e.g. FireServer(\"ClaimDaily\") or the item "
      "name); the server decides the amount from its own table, checks the player can do it (distance with "
      "(a - b).Magnitude, cooldown with os.clock(), enough coins), then changes the value.",
      "The server now decides the numbers itself, so cheaters can't send fake ones.",
      ("RemoteEvent.OnServerEvent",))
def _trusts_client(ans: Answer, q: str) -> list[dict]:
    out = []
    for b in ans.luau:
        for params, body in scan.handlers(b.clean, "OnServerEvent"):
            found = None
            ranged = re.search(r"Magnitude|DistanceFromCharacter|:Distance|\bdistance\b|\brange\b", body, re.I)
            for p in params[1:]:
                if p == "...":
                    continue
                used = [ln for ln in body.split("\n")
                        if _uses_param(ln, p) and not re.search(r"^\s*(print|warn)\s*\(", ln)]
                if not used:
                    continue
                if STRONG_AMOUNT.search(p):
                    found = used[0]                      # the client picks a number the server then uses
                    break
                for ln in used:
                    money = re.search(r"\.Value\s*(=(?!=)|\+=|-=)", ln) and (AMOUNTISH.search(p) or
                                                                         CURRENCY_TARGET.search(ln))
                    dmg = re.search(rf":TakeDamage\s*\([^)]*\b{re.escape(p)}\b|\.Health\s*(=(?!=)|-=)", ln)
                    move = re.search(r"\.(WalkSpeed|JumpPower|JumpHeight|AssemblyLinearVelocity)\s*=", ln)
                    if (money or dmg or move) and not re.search(r"^\s*if\b", ln):
                        found = ln
                        break
                if found:
                    break
                # the client picks the target and the server damages it without a range check
                if re.search(r":TakeDamage\s*\(|\.Health\s*(=(?!=)|-=)", body) and not ranged:
                    found = used[0]
                    break
            if found:
                out.append(hit(b, b.clean.find(found.strip()) if found.strip() else None, found))
    return out


STRONG_AMOUNT = re.compile(r"^(\w*_)?(amount|coins?|gold|cash|money|points?|xp|exp|gems?|damage|dmg|reward|price|cost|"
                           r"power|speed|jump\w*|kills?|score|bonus|ammo\w*|health)$|"
                           r"(Amount|Coins?|Gold|Cash|Money|Points?|Xp|Damage|Reward|Price|Cost|Power|Speed|Kills?|"
                           r"Score|Bonus|Ammo|Health)$")
RATE_LIMIT = re.compile(r"os\.clock|tick\(\)|\btime\(\)|os\.time|cooldown|debounce|\blast\w*|\bcd\b|"
                        r"\bnextAllowed|\bthrottle|\brate", re.I)
SERVER_ACTION = re.compile(r"\.Value\s*(\+=|=[^=\n]*\+)|:TakeDamage\s*\(|\.Health\s*(-=|=[^=\n]*-)|"
                           r"Instance\.new\(\s*\"(BodyVelocity|LinearVelocity|VectorForce)\"|:ApplyImpulse\s*\(|"
                           r"AssemblyLinearVelocity\s*=")


@rule("remote-no-rate-limit", "error", "client-server",
      "The server's OnServerEvent handler gives coins / deals damage / applies a force every time the client fires, "
      "with no server-side cooldown, so an exploiter can fire it thousands of times a second. Fix: keep "
      "local last = {} on the server; if last[player] and os.clock() - last[player] < COOLDOWN then return end; "
      "last[player] = os.clock(); clear it on PlayerRemoving.",
      "The server now has its own cooldown, so spamming the button doesn't work.",
      ("RemoteEvent.OnServerEvent", "os.clock"))
def _remote_rate(ans: Answer, q: str) -> list[dict]:
    for b in ans.luau:
        for params, body in scan.handlers(b.clean, "OnServerEvent"):
            m = SERVER_ACTION.search(body)
            paid = re.search(r">=", body) and re.search(r"\.Value\s*(-=|=\s*0\b|=\s*[\w.]+\.Value\s*-)", body)
            if m and not paid and not RATE_LIMIT.search(body) and not RATE_LIMIT.search(b.clean[:b.clean.find("OnServerEvent")]):
                return [hit(b, b.clean.find("OnServerEvent"), m.group(0))]
    return []


# ---- 3. Touched without a debounce ------------------------------------------------------------------------------------
REWARD = re.compile(r"\.Value\s*(\+=|=[^=\n]*\+)|:TakeDamage\s*\(|\.Health\s*(-=|=[^=\n]*-)|:AwardBadge|"
                    r":Clone\s*\(\)[\s\S]{0,80}Backpack|Backpack|:PromptPurchase|:PromptGamePassPurchase|"
                    r":FireClient|:Teleport\w*\s*\(|:LoadCharacter")
# things that go wrong when the handler runs 20 times per touch: a wait-based toggle, new instances, random picks
TOUCH_ACTION = re.compile(r"(?<![\w.])task\.wait\s*\(|(?<![\w.])wait\s*\(|Instance\.new\s*\(|math\.random|"
                          r":FireServer\s*\(|:Play\s*\(")
GUARD = re.compile(r"debounce|cooldown|\bdb\b|\bbusy\b|\bcanTouch\b|\bisTouch|touched\w*\s*\[|\w+\s*\[\s*(player|plr|"
                   r"character|char|hit\.Parent|humanoid|userId|player\.UserId|plr\.UserId)\s*\]|\bused\b|\bclaimed\b|"
                   r"\bcollected\b|\bopen(ed)?\b|\bactive\b|\benabled\b|\bready\b|\bawarded\b|\bhasTouched|"
                   r"GetAttribute|SetAttribute|:Disconnect\s*\(|\.CanTouch\s*=\s*false|:Destroy\s*\(|\.Parent\s*=\s*nil|"
                   r"os\.clock|tick\(\)|time\(\)|lastTouch|last\w*\s*\[|\bprocessing\b|\bdone\b|\bisRunning\b",
                   re.I)


@rule("touched-no-debounce", "error", "logic",
      "A Touched handler gives a reward / deals damage / gives an item without a debounce. Touched fires many times "
      "per step (every body part, every frame of contact), and task.wait inside the handler does NOT stop the other "
      "calls. Fix: keep a per-player table (local touched = {}; if touched[player] then return end; touched[player] "
      "= true ... task.wait(cooldown); touched[player] = nil) or a boolean flag set BEFORE any wait.",
      "Touch events fire lots of times, so I added a cooldown so it only counts once.",
      ("BasePart.Touched",))
def _touched(ans: Answer, q: str) -> list[dict]:
    out = []
    for b in ans.luau:
        for params, body in scan.handlers(b.clean, "Touched"):
            raw_body = body
            act = REWARD.search(raw_body) or TOUCH_ACTION.search(raw_body)
            if act and not GUARD.search(raw_body) and not GUARD.search(b.clean[:b.clean.find(".Touched")]):
                out.append(hit(b, b.clean.find(".Touched"), "Touched handler: " + act.group(0)))
    return out


# ---- 4. DataStores ----------------------------------------------------------------------------------------------------
DS_CALL = re.compile(r":\s*(GetAsync|SetAsync|UpdateAsync|IncrementAsync|RemoveAsync|GetSortedAsync)\s*\(")


@rule("datastore-no-pcall", "error", "datastore",
      "DataStore calls (GetAsync/SetAsync/UpdateAsync/IncrementAsync/GetSortedAsync) are not wrapped in pcall. They "
      "are web requests and fail sometimes; an unprotected failure stops the script and can lose data. Fix: "
      "local ok, result = pcall(function() return store:GetAsync(key) end); only use result when ok; on a failed "
      "load do NOT save defaults over the real data later.",
      "Saving can fail sometimes, so the code now handles that safely.",
      ("DataStoreService", "GlobalDataStore:GetAsync", "GlobalDataStore:SetAsync"))
def _ds_pcall(ans: Answer, q: str) -> list[dict]:
    out = []
    for b in ans.luau:
        if "DataStore" not in b.code and "OrderedDataStore" not in b.code:
            continue
        spans = scan.protected_spans(b.clean)
        for m in DS_CALL.finditer(b.clean):
            if not any(s <= m.start() < e for s, e in spans):
                out.append(hit(b, m.start(), m.group(1)))
                break
    return out


ASYNC_CALL = re.compile(r":\s*(ComputeAsync|UserOwnsGamePassAsync|UserHasBadgeAsync|AwardBadge(Async)?|"
                        r"GetProductInfo|PlayerOwnsAsset|GetNameFromUserIdAsync|GetUserIdFromNameAsync|"
                        r"GetFriendsAsync|TeleportAsync|PublishAsync|SubscribeAsync|FilterStringAsync|"
                        r"GetUserThumbnailAsync)\s*\(")


@rule("web-call-no-pcall", "warning", "logic",
      "A Roblox web call (PathfindingService ComputeAsync, MarketplaceService/BadgeService checks, TeleportAsync, "
      "TextService filtering, MessagingService ...) is not inside pcall. These fail sometimes and then stop the "
      "script. Fix: local ok, err = pcall(function() ... end) and handle ok == false (retry later or skip).",
      "Online calls can fail sometimes, so the code now handles that safely.",
      ("PathfindingService", "MarketplaceService:UserOwnsGamePassAsync"))
def _web_pcall(ans: Answer, q: str) -> list[dict]:
    for b in ans.luau:
        spans = scan.protected_spans(b.clean)
        for m in ASYNC_CALL.finditer(b.clean):
            if not any(s <= m.start() < e for s, e in spans):
                return [hit(b, m.start(), m.group(1))]
    return []


@rule("datastore-save-on-character-removing", "error", "datastore",
      "Data is saved on CharacterRemoving/Humanoid.Died: that fires on every death, not when the player leaves. Fix: "
      "save in Players.PlayerRemoving, plus game:BindToClose for server shutdown (inside pcall).",
      "Progress now saves when you leave the game, not every time you fall over.",
      ("Players.PlayerRemoving", "DataModel:BindToClose"))
def _ds_char_removing(ans: Answer, q: str) -> list[dict]:
    out = []
    for b in ans.luau:
        for ev in ("CharacterRemoving", "Died"):
            for params, body in scan.handlers(b.clean, ev):
                m = re.search(r":\s*(SetAsync|UpdateAsync)\s*\(|\bsave\w*\s*\(", body, re.I)
                if m and re.search(r"DataStore", b.code):
                    out.append(hit(b, b.clean.find(ev), ev + " -> " + m.group(0)))
    return out


@rule("datastore-no-bindtoclose", "error", "datastore",
      "Player data is saved in PlayerRemoving but there is no game:BindToClose, so the last players' data can be lost "
      "when the server shuts down. Fix: add game:BindToClose(function() for each player save in pcall end).",
      "Data now also saves when the server closes.",
      ("DataModel:BindToClose",))
def _ds_bindtoclose(ans: Answer, q: str) -> list[dict]:
    code = ans.all_code
    if re.search(r"PlayerRemoving", code) and re.search(r":\s*(SetAsync|UpdateAsync)\s*\(", code) and \
            "BindToClose" not in code:
        b = next(b for b in ans.luau if "PlayerRemoving" in b.code)
        return [hit(b, b.code.find("PlayerRemoving"), "PlayerRemoving save without BindToClose")]
    return []


LOAD_GUARD = re.compile(r":Kick\s*\(|loaded|canSave|safeToSave|dataReady|loadFailed|failedLoad|"
                        r"\]\s*=\s*(success|ok|succeeded)\s*$|"
                        r"if\s+not\s+(success|ok|succeeded|s)\b[^\n]*\bthen\b[\s\S]{0,160}?\breturn\b", re.I | re.M)


@rule("datastore-failed-load-overwrites", "error", "datastore",
      "When GetAsync fails, the code falls back to default values and later SAVES them, overwriting the player's real "
      "data (data loss). Fix: remember whether the load worked: local loaded = {}; after the pcall set "
      "loaded[player] = success (true whenever pcall succeeded, EVEN when the data is nil for a brand-new player); "
      "in PlayerRemoving/BindToClose save only if loaded[player]; warn (or retry) when the load failed.",
      "If loading ever fails, the game now won't save over your real progress.",
      ("GlobalDataStore:GetAsync", "GlobalDataStore:SetAsync"))
def _ds_failed_load(ans: Answer, q: str) -> list[dict]:
    for b in ans.luau:
        if "DataStore" not in b.code or not re.search(r":\s*(SetAsync|UpdateAsync)\s*\(", b.clean):
            continue
        spans = scan.protected_spans(b.clean)
        m = re.search(r":\s*GetAsync\s*\(", b.clean)
        if m and any(s <= m.start() < e for s, e in spans) and not LOAD_GUARD.search(b.clean):
            return [hit(b, m.start(), "GetAsync failure -> defaults that get saved")]
    return []


NEW_PLAYER_FLAG = re.compile(r"(loaded|session\w*|canSave|dataReady)\w*\s*(\[[^\]\n]*\])?\s*=\s*(success|ok)\s+and\s+"
                             r"(data|result|value|saved\w*|stored\w*)\b|"
                             r"if\s+(success|ok)\s+and\s+(data|result|value|saved\w*)\s+then[^\n]*\n(?:[^\n]*\n){0,2}"
                             r"[^\n]*(loaded|session\w*|canSave|dataReady)\w*\s*(\[[^\]\n]*\])?\s*=\s*true", re.I)


@rule("datastore-new-player-never-saved", "error", "datastore",
      "The 'data loaded' flag is only set when GetAsync returned data, but for a brand-new player GetAsync succeeds "
      "with nil, so new players are never saved. Fix: set the flag from the pcall result alone (loaded[player] = "
      "success) and use defaults when data is nil.",
      "New players' progress now saves too.",
      ("GlobalDataStore:GetAsync",))
def _ds_new_player(ans: Answer, q: str) -> list[dict]:
    for b in ans.luau:
        m = NEW_PLAYER_FLAG.search(b.clean)
        if m and "GetAsync" in b.code:
            return [hit(b, m.start(), m.group(0))]
    return []


@rule("datastore-save-every-change", "warning", "datastore",
      "The code writes to the DataStore on every change (inside .Changed, Touched or a fast loop). DataStores have "
      "request limits and throttle; frequent SetAsync calls fail. Fix: keep the value in leaderstats/a table and "
      "save on PlayerRemoving + BindToClose (and optionally an autosave every 60+ seconds).",
      "Saving now happens at sensible times so Roblox doesn't block it.",
      ("DataStoreService",))
def _ds_every_change(ans: Answer, q: str) -> list[dict]:
    out = []
    for b in ans.luau:
        for ev in ("Changed", "Touched"):
            for params, body in scan.handlers(b.clean, ev):
                m = re.search(r":\s*(SetAsync|UpdateAsync|IncrementAsync)\s*\(", body)
                if m:
                    out.append(hit(b, b.clean.find("." + ev), ev + " -> " + m.group(1)))
        for m in re.finditer(r"GetPropertyChangedSignal\s*\([^)]*\)\s*:\s*Connect\s*\(\s*function\s*\([^)]*\)",
                             b.clean):
            body = b.clean[m.end():scan.body_end(b.clean, m.end())]
            if re.search(r":\s*(SetAsync|UpdateAsync|IncrementAsync)\s*\(", body):
                out.append(hit(b, m.start(), "GetPropertyChangedSignal -> save"))
    return out


@rule("datastore-stores-vector3", "error", "datastore",
      "The code saves a Vector3/CFrame/Color3 or an Instance straight into a DataStore. DataStores only store "
      "numbers, strings, booleans and tables of those, so the save fails. Fix: save {x = p.X, y = p.Y, z = p.Z} and "
      "rebuild with Vector3.new(t.x, t.y, t.z) when loading.",
      "Positions are now saved as plain numbers, which is what Roblox can store.",
      ("GlobalDataStore:SetAsync",))
def _ds_vector3(ans: Answer, q: str) -> list[dict]:
    out = []
    for b in ans.luau:
        m = re.search(r":\s*(SetAsync|UpdateAsync)\s*\([^,\n]+,\s*[\w.]*(\.Position|\.CFrame|Vector3\.new|CFrame\.new|"
                      r"\.Color)\s*\)", b.clean)
        if m:
            out.append(hit(b, m.start(), m.group(0)))
    return out


# ---- 5. loops, deprecated scheduling, remotes -------------------------------------------------------------------------
YIELD = re.compile(r"(?<![\w])(task\.)?wait\s*\(|:Wait\s*\(|coroutine\.yield|\bAsync\s*\(|\w+Async\s*\(|:Invoke\w*\(|"
                   r"(?<![\w])break\b|(?<![\w])return\b")


@rule("loop-without-yield", "error", "logic",
      "A `while true do` (or repeat ... until false) loop has no task.wait()/event :Wait() inside, so it freezes the "
      "game (Script timeout). Fix: put task.wait(seconds) inside the loop, or use RunService.Heartbeat:Connect for "
      "per-frame work.",
      "The loop now pauses each round so the game doesn't freeze.",
      ("task.wait", "RunService.Heartbeat"))
def _loop_yield(ans: Answer, q: str) -> list[dict]:
    out = []
    for b in ans.luau:
        for m in re.finditer(r"(?<![\w])while\s+(true|1)\s+do\b", b.clean):
            body = b.clean[m.end():scan.body_end(b.clean, m.end())]
            if not YIELD.search(body):
                out.append(hit(b, m.start(), m.group(0)))
        for m in re.finditer(r"(?<![\w])repeat\b", b.clean):
            e = scan.body_end(b.clean, m.end())
            if re.match(r"until\s+(false|nil)\b", b.clean[e:e + 12]) and not YIELD.search(b.clean[m.end():e]):
                out.append(hit(b, m.start(), "repeat ... until false"))
    return out


@rule("deprecated-scheduler", "warning", "deprecated",
      "Uses the old global wait()/spawn()/delay(). Fix: use task.wait(), task.spawn(), task.delay().",
      "I swapped old wait() for the newer task.wait().",
      ("task.wait", "task.spawn", "task.delay"))
def _deprecated_sched(ans: Answer, q: str) -> list[dict]:
    out = []
    for b in ans.luau:
        m = re.search(r"(?<![\w.:])(wait|spawn|delay)\s*\(", b.clean)
        if m:
            out.append(hit(b, m.start(), m.group(0)))
    return out


@rule("deprecated-body-mover", "error", "deprecated",
      "Creates a deprecated body mover (BodyVelocity, BodyPosition, BodyGyro, BodyForce, BodyAngularVelocity, "
      "BodyThrust). Fix: use LinearVelocity / AlignPosition / AlignOrientation / VectorForce / AngularVelocity with "
      "an Attachment (Attachment0), or BasePart:ApplyImpulse for a one-off push.",
      "I used the newer physics movers instead of old ones.",
      ("LinearVelocity", "AlignPosition", "BasePart:ApplyImpulse"))
def _body_mover(ans: Answer, q: str) -> list[dict]:
    out = []
    for b in ans.luau:
        m = re.search(r"Instance\.new\(\s*[\"'](BodyVelocity|BodyPosition|BodyGyro|BodyForce|BodyAngularVelocity|"
                      r"BodyThrust)[\"']", b.nocomment)
        if m:
            out.append(hit(b, m.start(), m.group(1)))
    return out


@rule("invokeclient-from-server", "warning", "client-server",
      "The server calls RemoteFunction:InvokeClient. If the client errors, leaves or an exploiter never returns, the "
      "server script hangs forever. Fix: use a RemoteEvent (FireClient) and, if an answer is needed, a second "
      "RemoteEvent back, or wrap InvokeClient in task.spawn with a timeout and never trust its result.",
      "The server no longer waits on a player's computer, so it can't get stuck.",
      ("RemoteFunction:InvokeClient", "RemoteEvent:FireClient"))
def _invokeclient(ans: Answer, q: str) -> list[dict]:
    for b in ans.luau:
        m = re.search(r":InvokeClient\s*\(", b.nocomment)
        if m and not re.search(r"hang|yield forever|never return|timeout|exploit", ans.prose, re.I):
            return [hit(b, m.start(), "InvokeClient")]
    return []


IMPERATIVE_REMOTE = re.compile(r"^\s*(?:\d+[.)]|[-*])?\s*(?:\*\*)?(?:In\s+\**\w+\**,?\s+)?(?:Insert|Add|Create|Put|"
                               r"Make|Place)\b[^\n]{0,80}\bRemote(Event|Function)\b", re.I | re.M)


@rule("remote-created-twice", "error", "remotes",
      "The prose tells the user to create the RemoteEvent/RemoteFunction by hand AND the server code also creates "
      "one with Instance.new: that makes two objects with the same name and the client may wait on the wrong one. "
      "Fix: pick one: create it in Studio (ReplicatedStorage, exact name) and use WaitForChild everywhere; remove "
      "the Instance.new from the code.",
      "There is now just one RemoteEvent, so both scripts talk to the same one.",
      ("RemoteEvent",))
def _remote_twice(ans: Answer, q: str) -> list[dict]:
    m = None
    for b in ans.luau:
        m = re.search(r"Instance\.new\(\s*[\"']Remote(Event|Function)[\"']", b.nocomment)
        if m:
            break
    if m and IMPERATIVE_REMOTE.search(ans.prose) and not re.search(r"FindFirstChild\(", b.clean):
        return [hit(b, m.start(), IMPERATIVE_REMOTE.search(ans.prose).group(0))]
    return []


@rule("remote-never-created", "error", "remotes",
      "The scripts WaitForChild a RemoteEvent/BindableEvent by name, but the answer never says to create it (and no "
      "code creates it), so WaitForChild waits forever. Fix: add one setup line: 'In ReplicatedStorage, insert a "
      "RemoteEvent named \"<Name>\"'.",
      "I added the setup step for the RemoteEvent so the scripts can find it.",
      ("RemoteEvent", "Instance:WaitForChild"))
def _remote_never_created(ans: Answer, q: str) -> list[dict]:
    code = "\n".join(b.nocomment for b in ans.luau)
    if re.search(r"Instance\.new\(\s*[\"'](Remote|Bindable)", code):
        return []
    for b in ans.luau:
        for m in re.finditer(r"local\s+(\w+)\s*=\s*[\w.:()\"' ]*WaitForChild\(\s*[\"']([\w ]+)[\"']\s*\)", b.nocomment):
            var, name = m.group(1), m.group(2)
            if re.search(rf"\b{var}\s*[.:]\s*(FireServer|OnServerEvent|FireClient|FireAllClients|OnClientEvent|"
                         rf"InvokeServer|OnServerInvoke|Fire|Event|Invoke|OnInvoke)\b", code) and \
                    name not in ans.prose and not re.search(rf"\b{re.escape(name)}\b", ans.prose):
                return [hit(b, m.start(), name)]
    return []


# ---- 6. physics constraints -------------------------------------------------------------------------------------------
ONE_ATT = "LinearVelocity|AngularVelocity|AlignPosition|AlignOrientation|VectorForce|Torque|LineForce"
TWO_ATT = "HingeConstraint|RopeConstraint|SpringConstraint|RodConstraint|PrismaticConstraint|BallSocketConstraint|" \
          "CylindricalConstraint"


@rule("constraint-without-attachment", "error", "physics",
      "A constraint/mover is created in code but its Attachment0 (and Attachment1 for two-part constraints) is never "
      "set, so it applies no force. Fix: create an Attachment in the part (Instance.new(\"Attachment\", part)), set "
      "mover.Attachment0 = attachment (AlignPosition/AlignOrientation: Mode = Enum.PositionAlignmentMode.OneAttachment "
      "or a second attachment), set MaxForce, then parent it.",
      "The physics mover is now attached to the part, so it actually pushes.",
      ("LinearVelocity", "Constraint.Attachment0", "Attachment"))
def _constraint(ans: Answer, q: str) -> list[dict]:
    out = []
    for b in ans.luau:
        for m in re.finditer(rf"local\s+(\w+)\s*=\s*Instance\.new\(\s*[\"']({ONE_ATT}|{TWO_ATT})[\"']", b.nocomment):
            var = m.group(1)
            if not re.search(rf"\b{var}\.Attachment0\s*=", b.nocomment):
                out.append(hit(b, m.start(), m.group(2)))
        m = re.search(rf"WaitForChild\(\s*[\"']({ONE_ATT})[\"']\s*\)", b.nocomment)
        if m and not out and not re.search(r"Attachment", ans.text):
            out.append(hit(b, m.start(), m.group(1) + " from the model, no Attachment set up anywhere"))
    return out


@rule("hinge-servo-not-set", "error", "physics",
      "The code sets a HingeConstraint's TargetAngle but never sets ActuatorType to Servo (and ServoMaxTorque, "
      "default 0), so the hinge does not move. Fix: hinge.ActuatorType = Enum.ActuatorType.Servo; "
      "hinge.ServoMaxTorque = 100000; then set TargetAngle (the hinge also needs Attachment0 and Attachment1).",
      "The door hinge now has power so it actually swings.",
      ("HingeConstraint.ActuatorType", "HingeConstraint.ServoMaxTorque"))
def _hinge(ans: Answer, q: str) -> list[dict]:
    code = ans.all_code
    if re.search(r"\.TargetAngle\s*=", code) and not re.search(r"ActuatorType", code) and \
            not re.search(r"^\s*(\d+[.)]|[-*])[^\n]*(Servo|ActuatorType)", ans.prose, re.M):
        b = next(b for b in ans.luau if "TargetAngle" in b.code)
        return [hit(b, b.code.find("TargetAngle"), "TargetAngle without ActuatorType")]
    return []


# ---- 7. incomplete answers --------------------------------------------------------------------------------------------
PLACEHOLDER = re.compile(r"--\s*(\.\.\.\s*$|TODO\b|(add|put|insert|write)\s+(your|the|more|any|some)?\s*"
                         r"[\w ]{0,30}(code|logic)\b|your (code|logic)\s+(goes\s+)?here|(code|logic) goes here|"
                         r"implement\s+[\w ]{0,30}here|rest of (your|the) code)", re.I)
TEMPLATE = re.compile(r"e\.g\.|\blike\b|such as|for example|\bor\b", re.I)


@rule("placeholder-code", "error", "incomplete",
      "The code leaves the important part as a placeholder comment (\"-- add your logic here\", \"-- ...\", TODO), so "
      "it does not do what was asked. Fix: write that part for real (short and simple is fine) or, if it really "
      "belongs to the user's own game, say exactly what to put there.",
      "I filled in the missing part so the script works on its own.",
      ())
def _placeholder(ans: Answer, q: str) -> list[dict]:
    for b in ans.luau:
        for m in re.finditer(r"--[^\n]*", b.code):
            if PLACEHOLDER.match(m.group(0)) and not TEMPLATE.search(m.group(0)):
                return [hit(b, m.start(), m.group(0))]
    return []


# ---- 8. claims in the prose -------------------------------------------------------------------------------------------
# Myths often sit in the "One common mistake is forgetting to ..." sentence, so the generic NEGATION filter (which
# skips "mistake" sentences) is wrong here: only real negations or "thinking/believing X" clear a myth sentence.
MYTH_NEG = re.compile(r"\b(not|never|no longer|cannot|isn't|aren't|doesn't|don't|won't|without needing|"
                      r"no need|thinking|believing|assuming|myth)\b|n't\b", re.I)


def _myth(ans: Answer, pattern: str, also: str | None = None, clear: str | None = None) -> list[dict]:
    for s in scan.sentences(ans.prose):
        if re.search(pattern, s, re.I) and (also is None or re.search(also, s, re.I)) and \
                not MYTH_NEG.search(s) and not (clear and re.search(clear, s, re.I)):
            return [hit(None, None, s)]
    return []


@rule("myth-allow-http-for-datastores", "error", "false-claim",
      "The answer says 'Allow HTTP Requests' is needed for DataStores. It is not: DataStores in Studio need 'Enable "
      "Studio Access to API Services' (Game Settings > Security) and a published place; HTTP Requests are only for "
      "HttpService. Fix that sentence.",
      "Small fix: DataStores need 'Studio Access to API Services', not HTTP Requests.",
      ("DataStoreService",))
def _myth_http(ans: Answer, q: str) -> list[dict]:
    if not re.search(r"DataStore|sav(e|ing)", q + "\n" + ans.text, re.I):
        return []
    return _myth(ans, r"(Allow )?HTTP Requests", clear=r"HttpService|only (for|if|when)")


@rule("myth-filteringenabled", "error", "false-claim",
      "The answer treats FilteringEnabled as a setting to turn on/off. It is always on in every Roblox game and "
      "cannot be disabled: client changes never replicate to the server. Remove that advice; use RemoteEvents.",
      "FilteringEnabled is always on in Roblox now, so I took that tip out.",
      ("RemoteEvent",))
def _myth_fe(ans: Answer, q: str) -> list[dict]:
    if re.search(r"FilteringEnabled\s*=", ans.all_code):
        return [hit(None, None, "FilteringEnabled =")]
    return _myth(ans, r"FilteringEnabled", also=r"\b(turn|switch|set|enable|disable|toggle|tick|check)\w*\b",
                 clear=r"always (on|enabled)|removed|deprecated|forced")


@rule("myth-respawntime-default", "error", "false-claim",
      "The answer gives a wrong default for Players.RespawnTime: the default is 5 seconds. Fix the number.",
      "Small fix: the normal respawn time is 5 seconds.",
      ("Players.RespawnTime",))
def _myth_respawn(ans: Answer, q: str) -> list[dict]:
    m = re.search(r"RespawnTime[^.\n]{0,60}default[^.\n\d]{0,20}(\d+(\.\d+)?)|default[^.\n]{0,40}RespawnTime[^.\n\d]{0,20}"
                  r"(\d+(\.\d+)?)", ans.text, re.I)
    if m:
        n = m.group(1) or m.group(3)
        if n and float(n) != 5:
            return [hit(None, None, m.group(0))]
    return []


@rule("myth-bindtoclose-on-crash", "error", "false-claim",
      "The answer says BindToClose saves data when the server crashes. It does not run on a crash (only on a normal "
      "shutdown, max ~30 s). Say PlayerRemoving is the main save and BindToClose covers shutdowns.",
      "Small fix: nothing can save during a crash; saving on leave is the main safety net.",
      ("DataModel:BindToClose",))
def _myth_btc(ans: Answer, q: str) -> list[dict]:
    return _myth(ans, r"BindToClose", also=r"crash", clear=r"except")


@rule("myth-third-party-sales", "error", "false-claim",
      "The answer says 'Allow Third Party Sales' is needed to sell your own game pass / developer product. It is not "
      "(that setting is only for selling OTHER creators' items in your game). Remove that step.",
      "Small fix: you don't need 'Third Party Sales' to sell your own game pass.",
      ("MarketplaceService:PromptGamePassPurchase",))
def _myth_tps(ans: Answer, q: str) -> list[dict]:
    return _myth(ans, r"Third[- ]Party Sales", clear=r"other (creators|people|developers)|only (if|for|when)")


@rule("myth-third-party-teleports", "error", "false-claim",
      "The answer says 'Allow Third Party Teleports' is needed to teleport between places of your own experience. It "
      "is only needed to teleport to OTHER creators' experiences. Remove that step (teleports also do not work in "
      "Studio play tests: test in the published game).",
      "Small fix: teleporting inside your own game doesn't need 'Third Party Teleports'.",
      ("TeleportService:TeleportAsync",))
def _myth_tpt(ans: Answer, q: str) -> list[dict]:
    if re.search(r"someone else|other (creator|people|player)'?s?|another (creator|developer)|friend'?s game", q, re.I):
        return []
    return _myth(ans, r"Third[- ]Party Teleports", clear=r"other (creators|people|developers)|only (if|for|when)|"
                                                          r"someone else")


@rule("myth-pcall-stops-hang", "error", "false-claim",
      "The answer says pcall stops InvokeServer/InvokeClient (or a web call) from hanging. pcall only catches errors; "
      "a call that never returns still waits forever. Fix the sentence (use a RemoteEvent, or a timeout with "
      "task.delay).",
      "Small fix: pcall catches errors but can't stop a call from waiting forever.",
      ("RemoteFunction:InvokeServer",))
def _myth_pcall(ans: Answer, q: str) -> list[dict]:
    return _myth(ans, r"pcall", also=r"\bhang|freez|forever|indefinitely|stuck", clear=r"only catches")


@rule("myth-local-animation-not-replicated", "error", "false-claim",
      "The answer says an animation played from a LocalScript on the player's own character is only seen by that "
      "player. That is false: animations a LocalScript plays on its own character through the Humanoid's Animator "
      "replicate to everyone. Play it from the LocalScript (Animator:LoadAnimation) and remove the needless "
      "RemoteEvent round trip.",
      "Small fix: animations you play on your own character are seen by everyone.",
      ("Animator:LoadAnimation",))
def _myth_anim(ans: Answer, q: str) -> list[dict]:
    if not re.search(r"animat", q + ans.prose, re.I):
        return []
    for s in scan.sentences(ans.prose):
        if re.search(r"animation", s, re.I) and re.search(r"LocalScript|client", s, re.I) and \
                re.search(r"only (you|the player|that player|they|your)\b[^.]{0,30}(see|seen)|other(s| players) "
                          r"(won't|can't|will not|cannot) see|(won't|doesn't|will not|does not) replicate", s, re.I) and \
                not re.search(r"NPC|another (player|character)|other players' characters|server-owned", s, re.I):
            return [hit(None, None, s)]
    return []


@rule("myth-random-needs-seed", "error", "false-claim",
      "The answer says math.random must be seeded (math.randomseed). In Luau math.random is seeded automatically; "
      "remove that advice (Random.new() is fine too).",
      "Small fix: Roblox already mixes up math.random for you.",
      ("math.random", "Random.new"))
def _myth_seed(ans: Answer, q: str) -> list[dict]:
    for s in scan.sentences(ans.prose):
        if re.search(r"without seed|need(s)? (to be )?seed|must seed|remember to seed|forget(ting)? to seed|"
                     r"randomseed", s, re.I) and not re.search(r"\b(not|no longer|isn't|automatic|don't)\b|n't\b",
                                                               s, re.I):
            return [hit(None, None, s)]
    return []


@rule("myth-module-shares-between-clients", "error", "false-claim",
      "The answer says a ModuleScript shares data between clients (or between the server and clients). Each client "
      "and the server get their OWN copy of a required module; changes in one are not seen by the others. Use "
      "RemoteEvents/attributes/values for shared state.",
      "Small fix: each player gets their own copy of a ModuleScript.",
      ("ModuleScript",))
def _myth_module(ans: Answer, q: str) -> list[dict]:
    for s in scan.sentences(ans.prose):
        if re.search(r"module", s, re.I) and re.search(r"share\w*[^.]{0,30}between (the )?(clients|players|"
                                                       r"different clients|all players|server and client)|"
                                                       r"between clients", s, re.I) and \
                not re.search(r"(do|does|will|can)( not|n't) share|own copy|separate cop", s, re.I):
            return [hit(None, None, s)]
    return []


@rule("claim-saves-without-saving", "error", "false-claim",
      "The prose says progress/coins are saved (between sessions, automatically, when you leave/rejoin), but the code "
      "never saves (no DataStore SetAsync/UpdateAsync). leaderstats alone only shows values; they reset when you "
      "leave. Fix: either add DataStore saving (pcall, PlayerRemoving + BindToClose) or say clearly that this does "
      "not save yet.",
      "Small fix: leaderstats only shows coins; saving needs a DataStore.",
      ("DataStoreService",))
def _claim_saves(ans: Answer, q: str) -> list[dict]:
    if re.search(r"SetAsync|UpdateAsync|IncrementAsync|ProfileService|ProfileStore|DataStore2", ans.all_code):
        return []
    for s in scan.sentences(ans.prose):
        if re.search(r"(saves?|saved|saving|persists?)\b[^.]{0,50}\b(automatically|between (sessions|games)|"
                     r"when (they|you|the player|players) (leave|rejoin|come back)|forever|next time)|"
                     r"(progress|data|coins|stats|work) (is|are|will be|gets?) (saved|stored|kept)", s, re.I) and \
                not MYTH_NEG.search(s) and not re.search(r"\b(if|need|would|could|want|next step|full version)\b|\?$",
                                                         s, re.I):
            return [hit(None, None, s)]
    return []


@rule("claim-no-script-needed", "warning", "false-claim",
      "The prose says no script is needed, but the answer then gives a script. Make the prose and the code agree.",
      "Small fix: the words and the code now match.",
      ())
def _claim_noscript(ans: Answer, q: str) -> list[dict]:
    if not ans.luau:
        return []
    for s in scan.sentences(ans.prose):
        if re.search(r"\bno (script|scripting|code)\b[^.]{0,20}\b(needed|required|necessary)|"
                     r"without (any|writing (any|a)) (script|code)", s, re.I) and \
                not re.search(r"\bbut\b|\bor\b|if you want", s, re.I):
            return [hit(None, None, s)]
    return []


# ---- public API -------------------------------------------------------------------------------------------------------
BY_ID = {r.id: r for r in RULES}


def check(text: str, question: str = "", only: set[str] | None = None, skip: set[str] | None = None) -> list[dict]:
    """All rule hits for one answer (Roblox answers only; anything else returns [])."""
    ans = scan.parse(text or "")
    if not _roblox(ans, question):
        return []
    out = []
    for r in RULES:
        if (only and r.id not in only) or (skip and r.id in skip):
            continue
        try:
            found = r.check(ans, question)
        except Exception as e:          # a rule must never break an answer
            found = []
            out.append({"rule": r.id, "severity": "info", "family": r.family, "message": f"rule crashed: {e!r}",
                        "note": "", "docs": [], "crash": True})
        for h in found[:1]:             # one hit per rule is enough for the fix prompt
            out.append({"rule": r.id, "severity": r.severity, "family": r.family, "message": r.message,
                        "note": r.note, "docs": list(r.docs), **h})
    return out


def errors(hits: list[dict]) -> list[dict]:
    return [h for h in hits if h["severity"] == "error"]
