---
id: gb-data-remote-admin-allowlist
category: remote-security
topics: admin commands, UserId allowlist, RemoteEvent, command parsing, kick
source: original
---
# Request
I made an admin panel that fires `AdminCommand:FireServer("kick", targetName)`, and the server checks `if player.Name == "MyName"`. Is that safe? I'd like a proper admin command handler with kick and give-coins.

# Answer
Name checks break when you rename and are easy to get wrong; check the sender's UserId against a server-side allowlist instead, on every request, because anyone can fire the remote even if the panel is hidden. Then parse the command, look it up in a server table, validate every argument and log what was done.

```lua
--!strict
-- Script: ServerScriptService.AdminCommands
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

-- Real UserIds only; names can change.
local ADMIN_IDS: { [number]: boolean } = {}
-- In a group-owned experience game.CreatorId is the group's id, which could match some unrelated user.
if game.CreatorType == Enum.CreatorType.User then
	ADMIN_IDS[game.CreatorId] = true
end
local MAX_COINS = 100_000

local adminCommand = Instance.new("RemoteEvent")
adminCommand.Name = "AdminCommand"
adminCommand.Parent = ReplicatedStorage

local function findPlayer(name: unknown): Player?
	if type(name) ~= "string" or #name > 20 then
		return nil
	end
	local wanted = string.lower(name)
	for _, candidate in Players:GetPlayers() do
		if string.lower(candidate.Name) == wanted then
			return candidate
		end
	end
	return nil
end

type Command = (admin: Player, target: Player, arg: unknown) -> boolean

local COMMANDS: { [string]: Command } = {
	kick = function(_admin: Player, target: Player, _arg: unknown): boolean
		if ADMIN_IDS[target.UserId] then
			return false -- admins cannot kick each other from the panel
		end
		target:Kick("Removed by a moderator.")
		return true
	end,
	coins = function(_admin: Player, target: Player, arg: unknown): boolean
		if type(arg) ~= "number" or arg % 1 ~= 0 or arg < 1 or arg > MAX_COINS then
			return false
		end
		local stored: unknown = target:GetAttribute("Coins")
		local current = if type(stored) == "number" then stored else 0
		target:SetAttribute("Coins", current + arg)
		return true
	end,
}

local function onCommand(admin: Player, nameArg: unknown, targetArg: unknown, extra: unknown)
	if not ADMIN_IDS[admin.UserId] then
		print("[admin] refused command from non-admin", admin.UserId)
		return
	end
	if type(nameArg) ~= "string" then
		return
	end
	local command = COMMANDS[nameArg]
	local target = findPlayer(targetArg)
	if command == nil or target == nil then
		return
	end
	local done = command(admin, target, extra)
	local adminId: number, targetId: number = admin.UserId, target.UserId
	print(string.format("[admin] %d ran %s on %d: %s", adminId, nameArg, targetId, tostring(done)))
end

adminCommand.OnServerEvent:Connect(onCommand)
```

- Hide the panel for non-admins as a convenience only; the `ADMIN_IDS` check on the server is the actual protection.
- `COMMANDS[nameArg]` is a plain table lookup on a table with no metatable, so strings like "__index" find nothing.
- For group-owned games, swap the table check for `player:GetRankInGroup(game.CreatorId) >= rank` (in `pcall`, cached per player).

# Test
```lua
game.CreatorType = Enum.CreatorType.User
```
```lua
local remote = game:GetService("ReplicatedStorage"):WaitForChild("AdminCommand")
local owner = __makePlayer(1, "Owner")
local regular = __makePlayer(2, "Regular")
local target = __makePlayer(3, "Target")

remote.OnServerEvent:Fire(regular, "kick", "Target")
check("non-admins cannot run commands", target.__kicked == nil)

remote.OnServerEvent:Fire(owner, "coins", "target", 500)
check("admin can give coins (name match is case-insensitive)", target:GetAttribute("Coins") == 500)

remote.OnServerEvent:Fire(owner, "coins", "Target", 1e12)
remote.OnServerEvent:Fire(owner, "coins", "Target", 0 / 0)
remote.OnServerEvent:Fire(owner, "coins", "Target", -50)
check("out-of-range or NaN amounts are refused", target:GetAttribute("Coins") == 500)

remote.OnServerEvent:Fire(owner, "explode", "Target")
remote.OnServerEvent:Fire(owner, "__index", "Target")
check("unknown commands do nothing", target.__kicked == nil)

remote.OnServerEvent:Fire(owner, "kick", "Target")
check("admin can kick", target.__kicked ~= nil)
remote.OnServerEvent:Fire(owner, "kick", "Owner")
check("admins are not kickable from the panel", owner.__kicked == nil)
```
