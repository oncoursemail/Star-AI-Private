---
id: gb-ui-billboard-nameplate
category: ui-layout
topics: BillboardGui, nameplate, StudsOffset, MaxDistance, Humanoid DisplayDistanceType
source: original
---
# Request
I want custom nameplates above players' heads showing their display name in their team colour, replacing the default Roblox name. Mine are sized in pixels so they look huge when far away, and they stay visible through walls from across the map.

# Answer
Size the BillboardGui in Scale, which is measured in studs, so it shrinks with distance like a real object; keep `AlwaysOnTop` off so walls hide it, and set `MaxDistance` so far-away nameplates are not drawn. Hide the default name with the Humanoid's `DisplayDistanceType`, and parent the billboard to the head so it is cleaned up with the character.

```lua
--!strict
-- ModuleScript: ServerScriptService.Nameplates
local Players = game:GetService("Players")

local Nameplates = {}

function Nameplates.attach(character: Model, text: string, color: Color3): BillboardGui?
	local head = character:FindFirstChild("Head")
	local humanoid = character:FindFirstChildOfClass("Humanoid")
	if head == nil or humanoid == nil then
		return nil
	end
	humanoid.DisplayDistanceType = Enum.HumanoidDisplayDistanceType.None
	local old = head:FindFirstChild("Nameplate")
	if old then
		old:Destroy()
	end

	local gui = Instance.new("BillboardGui")
	gui.Name = "Nameplate"
	gui.Adornee = head
	gui.Size = UDim2.fromScale(5, 1.1)
	gui.StudsOffsetWorldSpace = Vector3.new(0, 2.2, 0)
	gui.MaxDistance = 80
	gui.AlwaysOnTop = false
	gui.LightInfluence = 0

	local label = Instance.new("TextLabel")
	label.Name = "DisplayName"
	label.BackgroundTransparency = 1
	label.Size = UDim2.fromScale(1, 1)
	label.TextScaled = true
	label.TextColor3 = color
	label.TextStrokeTransparency = 0.4
	label.TextStrokeColor3 = Color3.new(0, 0, 0)
	label.Text = text
	label.Parent = gui

	local cap = Instance.new("UITextSizeConstraint")
	cap.MaxTextSize = 28
	cap.Parent = label

	gui.Parent = head
	return gui
end

local function onPlayer(player: Player)
	local function onCharacter(character: Model)
		local color = Color3.new(1, 1, 1)
		if player.Team then
			color = player.TeamColor.Color
		end
		Nameplates.attach(character, player.DisplayName, color)
	end
	if player.Character then
		onCharacter(player.Character)
	end
	player.CharacterAdded:Connect(onCharacter)
end

function Nameplates.start()
	for _, player in Players:GetPlayers() do
		onPlayer(player)
	end
	Players.PlayerAdded:Connect(onPlayer)
end

return Nameplates
```

- The billboard is created on the server inside the character, so every client sees it without extra replication code.
- `LightInfluence = 0` keeps names readable at night and in dark interiors.
- `StudsOffsetWorldSpace` keeps the offset straight up even when the head tilts.
- Display names are already filtered by Roblox; any custom title text players type must be filtered before it goes on a nameplate.

# Test
```lua
local player = __makePlayer(7, "Builder")
local character = __makeCharacter(player)
local gui = item.attach(character, "Builder", Color3.new(1, 0, 0))
check("billboard on the head", gui ~= nil and gui.Parent == character.Head and gui.Adornee == character.Head)
check("sized in studs, not pixels", gui.Size.X.Scale == 5 and gui.Size.X.Offset == 0)
check("hidden by walls and distance", gui.AlwaysOnTop == false and gui.MaxDistance == 80)
check("default name hidden", character.Humanoid.DisplayDistanceType == Enum.HumanoidDisplayDistanceType.None)
local empty = Instance.new("Model")
check("missing head is handled", item.attach(empty, "x", Color3.new()) == nil)
item.start()
local late = __makePlayer(8, "Late")
local lateCharacter = __makeCharacter(late)
check("new players get nameplates", lateCharacter.Head:FindFirstChild("Nameplate") ~= nil)
local plates = 0
for _, c in character.Head:GetChildren() do
	if c:IsA("BillboardGui") then
		plates += 1
	end
end
check("attaching again replaces instead of stacking", plates == 1)
```
