---
id: gb-src-filtered-display-name
category: ui-text
topics: TextService, FilterStringAsync, GetNonChatStringForBroadcastAsync, Humanoid.DisplayName, RemoteEvent validation
source: adapted
source_id: creator-docs
source_path: content/en-us/characters/name-health-display.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
Players can type a nickname in a TextBox that should appear above their head for everyone. Right now the client sends it with a RemoteEvent and the server sets `humanoid.DisplayName = newName` directly. What do I need to add so this is allowed and can't be abused?

# Answer
Any player-written text shown to others must go through `TextService:FilterStringAsync` and `GetNonChatStringForBroadcastAsync` on the server. Before filtering, validate the argument (type, length, empty), and rate-limit the remote, because filtering calls are throttled and can error.

```lua
--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TextService = game:GetService("TextService")

local MAX_LENGTH = 20
local COOLDOWN_SECONDS = 10

local changeName = ReplicatedStorage:WaitForChild("ChangeNameEvent") :: RemoteEvent
local lastChange: { [Player]: number } = {}

local function filterForEveryone(text: string, fromUserId: number): string?
	local ok, result = pcall(function()
		local filterResult = TextService:FilterStringAsync(text, fromUserId)
		return filterResult:GetNonChatStringForBroadcastAsync()
	end)
	if not ok then
		warn("Filtering failed:", result)
		return nil
	end
	return result
end

changeName.OnServerEvent:Connect(function(player: Player, newName: unknown)
	if type(newName) ~= "string" then
		return
	end
	local trimmed = string.gsub(newName, "^%s+", "")
	trimmed = string.gsub(trimmed, "%s+$", "")
	if trimmed == "" or utf8.len(trimmed) == nil or (utf8.len(trimmed) :: number) > MAX_LENGTH then
		return
	end
	local now = os.clock()
	if now - (lastChange[player] or -math.huge) < COOLDOWN_SECONDS then
		return
	end
	lastChange[player] = now

	local filtered = filterForEveryone(trimmed, player.UserId)
	local character = player.Character
	local humanoid = if character then character:FindFirstChildOfClass("Humanoid") else nil
	if filtered and humanoid then
		humanoid.DisplayName = filtered
	end
end)

Players.PlayerRemoving:Connect(function(player: Player)
	lastChange[player] = nil
end)
```

- `GetNonChatStringForBroadcastAsync` is the right variant for text every player sees; per-recipient filtering is for private text.
- If filtering fails, nothing is shown: never fall back to the unfiltered text.
- `utf8.len` both counts characters correctly for non-English names and rejects invalid UTF-8.

# Test
```lua
local remote = Instance.new("RemoteEvent")
remote.Name = "ChangeNameEvent"
remote.Parent = game:GetService("ReplicatedStorage")
```

```lua
local remote = game:GetService("ReplicatedStorage").ChangeNameEvent
local p = __makePlayer(1, "Namer")
local humanoid = __makeCharacter(p).Humanoid
humanoid.DisplayName = "Namer"
remote.OnServerEvent:Fire(p, 12345)
remote.OnServerEvent:Fire(p, "   ")
remote.OnServerEvent:Fire(p, string.rep("a", 30))
check("bad arguments ignored", humanoid.DisplayName == "Namer")
remote.OnServerEvent:Fire(p, "  Badword King ")
check("filtered and trimmed", humanoid.DisplayName == "####### King")
remote.OnServerEvent:Fire(p, "Second")
check("cooldown blocks rapid changes", humanoid.DisplayName == "####### King")
__advance(10.1)
remote.OnServerEvent:Fire(p, "Second")
check("allowed after cooldown", humanoid.DisplayName == "Second")
```
