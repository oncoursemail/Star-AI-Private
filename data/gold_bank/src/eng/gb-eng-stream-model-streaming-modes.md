---
id: gb-eng-stream-model-streaming-modes
category: performance-streaming
topics: ModelStreamingMode, Atomic, Persistent, PersistentPerPlayer, StreamingEnabled
source: original
---
# Request
With streaming on, players sometimes see half a car (wheels missing) and my client scripts that expect `Car.Body.Seat` crash. Also my lobby scoreboard model must always be present on every client. What are the ModelStreamingMode options and how do I apply them consistently across many models?

# Answer
`Atomic` streams a model in and out as a whole, so its descendants arrive together (no half cars). `Persistent` keeps a model on every client for the whole session. `PersistentPerPlayer` keeps it only for players you add with `Model:AddPersistentPlayer`. Use them sparingly, since persistent models cost memory everywhere. Tag models by role and let one server script set the mode.

```lua
--!strict
-- Script: ServerScriptService.StreamingModes
local CollectionService = game:GetService("CollectionService")
local Players = game:GetService("Players")

local MODES: { [string]: Enum.ModelStreamingMode } = {
	StreamAtomic = Enum.ModelStreamingMode.Atomic, -- vehicles, doors, anything scripts read as a unit
	StreamPersistent = Enum.ModelStreamingMode.Persistent, -- lobby board, map markers needed everywhere
	StreamOwner = Enum.ModelStreamingMode.PersistentPerPlayer, -- a player's own plot or base
}

local function apply(model: Instance, mode: Enum.ModelStreamingMode)
	if not model:IsA("Model") then
		return
	end
	model.ModelStreamingMode = mode
	if mode == Enum.ModelStreamingMode.PersistentPerPlayer then
		local ownerId = model:GetAttribute("OwnerId")
		local owner = if type(ownerId) == "number" then Players:GetPlayerByUserId(ownerId) else nil
		if owner then
			model:AddPersistentPlayer(owner)
		end
	end
end

for tag, mode in MODES do
	for _, model in CollectionService:GetTagged(tag) do
		apply(model, mode)
	end
	CollectionService:GetInstanceAddedSignal(tag):Connect(function(model: Instance)
		apply(model, mode)
	end)
end
```

- Atomic models still stream out as a unit, so clients must still handle the whole car being absent: wait for it with `WaitForChild` and a timeout, then read its children without further waits.
- Persistent models are sent to everyone when they join and never leave; a few key models are fine, but marking whole buildings persistent defeats streaming.
- Set the mode on the server (or in Studio on the model); the client only reads it.

# Test
```lua
local car = Instance.new("Model")
car.Parent = workspace
car:AddTag("StreamAtomic")
local owner = __makePlayer(7, "Owner")
local plot = Instance.new("Model")
plot:SetAttribute("OwnerId", 7)
local added = {}
plot.AddPersistentPlayer = function(_, p)
	table.insert(added, p)
end
plot.Parent = workspace
plotModel, plotOwners, plotOwner = plot, added, owner
```
```lua
local cs = game:GetService("CollectionService")
local car = cs:GetTagged("StreamAtomic")[1]
check("existing tagged model set atomic", car.ModelStreamingMode == Enum.ModelStreamingMode.Atomic)
local board = Instance.new("Model")
board.Parent = workspace
board:AddTag("StreamPersistent")
check("model tagged later set persistent", board.ModelStreamingMode == Enum.ModelStreamingMode.Persistent)
local plot = plotModel
plot:AddTag("StreamOwner")
check("per-player model adds its owner", plot.ModelStreamingMode == Enum.ModelStreamingMode.PersistentPerPlayer and plotOwners[1] == plotOwner)
local folder = Instance.new("Folder")
folder.Parent = workspace
folder:AddTag("StreamAtomic")
check("non-model ignored", folder.ModelStreamingMode == nil)
```
