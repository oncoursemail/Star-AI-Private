---
id: gb-src-prompt-locked-door
category: gameplay-systems
topics: ProximityPrompt, ProximityPromptService, PromptTriggered, HoldDuration, attributes, door
source: adapted
source_id: creator-docs
source_path: content/en-us/ui/proximity-prompts.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
I have lots of doors tagged "KeyDoor", each with a ProximityPrompt. Players need a key (an attribute `HasKey`) to open one; opening should take a 1 second hold, and the door should stay open for 5 seconds. Do I need a script in every door?

# Answer
No: handle every prompt from one server script through `ProximityPromptService.PromptTriggered`, which passes the prompt and the player. Read the door from the prompt's parent, check the key on the server, and toggle the door with attributes so clients can animate it.

```lua
--!strict
local CollectionService = game:GetService("CollectionService")
local ProximityPromptService = game:GetService("ProximityPromptService")

local TAG = "KeyDoor"
local OPEN_SECONDS = 5

local function setOpen(door: BasePart, prompt: ProximityPrompt, open: boolean)
	door:SetAttribute("Open", open)
	door.CanCollide = not open
	door.Transparency = if open then 0.8 else 0
	prompt.Enabled = not open
end

local function configure(door: Instance)
	local prompt = door:FindFirstChildOfClass("ProximityPrompt")
	if prompt then
		prompt.ActionText = "Unlock"
		prompt.ObjectText = "Locked door"
		prompt.HoldDuration = 1
		prompt.RequiresLineOfSight = true
	end
end

local function onPromptTriggered(prompt: ProximityPrompt, player: Player)
	local door = prompt.Parent
	if not door or not door:IsA("BasePart") or not CollectionService:HasTag(door, TAG) then
		return
	end
	if door:GetAttribute("Open") or not player:GetAttribute("HasKey") then
		return
	end
	setOpen(door, prompt, true)
	task.delay(OPEN_SECONDS, function()
		if door.Parent then
			setOpen(door, prompt, false)
		end
	end)
end

for _, door in CollectionService:GetTagged(TAG) do
	configure(door)
end
CollectionService:GetInstanceAddedSignal(TAG):Connect(configure)
ProximityPromptService.PromptTriggered:Connect(onPromptTriggered)
```

- One connection serves every door, including doors added later through the tag signal.
- `PromptTriggered` runs on the server with the real player, so the key check cannot be skipped by the client.
- Disabling the prompt while the door is open stops repeated triggers.

# Test
```lua
local CollectionService = game:GetService("CollectionService")
local door = Instance.new("Part")
door.Name = "Door"
local prompt = Instance.new("ProximityPrompt")
prompt.Parent = door
door.Parent = workspace
CollectionService:AddTag(door, "KeyDoor")
```

```lua
local ProximityPromptService = game:GetService("ProximityPromptService")
local door = workspace.Door
local prompt = door.ProximityPrompt
check("prompt configured", prompt.HoldDuration == 1 and prompt.ActionText == "Unlock")
local noKey = __makePlayer(1, "NoKey")
ProximityPromptService.PromptTriggered:Fire(prompt, noKey)
check("no key, stays shut", door:GetAttribute("Open") ~= true and door.CanCollide == true)
local keyHolder = __makePlayer(2, "Keyed")
keyHolder:SetAttribute("HasKey", true)
ProximityPromptService.PromptTriggered:Fire(prompt, keyHolder)
check("opens with key", door:GetAttribute("Open") == true and door.CanCollide == false and prompt.Enabled == false)
__advance(5.1)
check("closes again after 5 s", door:GetAttribute("Open") == false and prompt.Enabled == true)
```
