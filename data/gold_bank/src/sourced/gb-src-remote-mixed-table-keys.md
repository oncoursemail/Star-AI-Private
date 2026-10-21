---
id: gb-src-remote-mixed-table-keys
category: engineering-debugging
topics: RemoteEvent, argument serialization, mixed tables, instance keys, function arguments
source: adapted
source_id: creator-docs
source_path: content/en-us/scripting/events/remote.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
I send my loadout to the client with `remote:FireClient(player, { [workspace.Baseplate] = true, [1] = "Sword", CharClass = "Rogue" })`. On the client the Baseplate key turns into a string, and in another remote I pass a callback function that arrives as nil. Why, and how should I structure the data?

# Answer
Remote arguments are serialized, not shared. Instance keys are converted to strings, functions become nil, and mixed tables (array part plus string keys) lose part of their data. Send plain data: arrays of values, or dictionaries with string keys, and put instances in values, not keys.

```lua
--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local loadoutEvent = ReplicatedStorage:WaitForChild("LoadoutEvent") :: RemoteEvent

export type LoadoutPayload = {
	items: { string },
	charClass: string,
	spawnPart: BasePart?,
}

local function buildPayload(items: { string }, charClass: string, spawnPart: BasePart?): LoadoutPayload
	return {
		items = table.clone(items),
		charClass = charClass,
		spawnPart = spawnPart,
	}
end

local function sendLoadout(player: Player, payload: LoadoutPayload)
	loadoutEvent:FireClient(player, payload)
end

local function onPlayerAdded(player: Player)
	local spawnPart = workspace:FindFirstChild("SpawnLocation")
	local spawnBase: BasePart? = nil
	if spawnPart and spawnPart:IsA("BasePart") then
		spawnBase = spawnPart
	end
	sendLoadout(player, buildPayload({ "Sword", "Bow" }, "Rogue", spawnBase))
end

Players.PlayerAdded:Connect(onPlayerAdded)
for _, player in Players:GetPlayers() do
	onPlayerAdded(player)
end

return { buildPayload = buildPayload }
```

- The array of items and the string-keyed fields live in separate tables, so nothing is dropped as a mixed table.
- An instance as a value arrives as the same instance on the client (if it is replicated to that client); as a key it would become a string.
- Never send functions: the client receives nil. Send an action name and look up the function on the receiving side.

# Test
```lua
local remote = Instance.new("RemoteEvent")
remote.Name = "LoadoutEvent"
remote.Parent = game:GetService("ReplicatedStorage")
```

```lua
local remote = game:GetService("ReplicatedStorage").LoadoutEvent
local source = { "Sword" }
local payload = item.buildPayload(source, "Rogue", nil)
table.insert(source, "Shield")
check("items copied, not shared", #payload.items == 1)
check("string keys only at top level", payload.charClass == "Rogue" and payload[1] == nil)
local p = __makePlayer(5, "Diva")
check("loadout sent on join", #remote.__sent == 1 and remote.__sent[1][1] == p)
check("payload has array of items", remote.__sent[1][2].items[2] == "Bow")
```
