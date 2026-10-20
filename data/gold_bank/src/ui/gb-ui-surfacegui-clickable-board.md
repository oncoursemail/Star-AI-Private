---
id: gb-ui-surfacegui-clickable-board
category: ui-layout
topics: SurfaceGui, Adornee, PlayerGui, PixelsPerStud, LocalScript in Workspace
source: original
---
# Request
I put a SurfaceGui with a "Buy" button on a board part in the Workspace, and a LocalScript inside the button to handle the click. The board shows, but clicking does nothing and a print at the top of the LocalScript never appears. Why?

# Answer
LocalScripts do not run in the Workspace (outside a character), so that script never starts. Build the SurfaceGui from a client script into PlayerGui and point its `Adornee` at the board: it renders on the part exactly the same, but now lives where client code runs. Use PixelsPerStud sizing so text stays sharp on any board size.

```lua
--!strict
-- ModuleScript: StarterPlayerScripts.ShopBoard
local ShopBoard = {}

function ShopBoard.mount(board: BasePart, playerGui: Instance, onBuy: () -> ()): SurfaceGui
	local gui = Instance.new("SurfaceGui")
	gui.Name = "ShopBoardGui"
	gui.Adornee = board
	gui.Face = Enum.NormalId.Front
	gui.SizingMode = Enum.SurfaceGuiSizingMode.PixelsPerStud
	gui.PixelsPerStud = 50
	gui.LightInfluence = 0
	gui.MaxDistance = 40
	gui.ResetOnSpawn = false

	local title = Instance.new("TextLabel")
	title.Name = "Title"
	title.BackgroundTransparency = 1
	title.Size = UDim2.fromScale(1, 0.35)
	title.TextScaled = true
	title.TextColor3 = Color3.fromRGB(240, 240, 240)
	title.Text = "Speed Coil"
	title.Parent = gui

	local buy = Instance.new("TextButton")
	buy.Name = "Buy"
	buy.AnchorPoint = Vector2.new(0.5, 1)
	buy.Position = UDim2.new(0.5, 0, 1, -20)
	buy.Size = UDim2.fromScale(0.5, 0.3)
	buy.BackgroundColor3 = Color3.fromRGB(46, 140, 80)
	buy.TextScaled = true
	buy.TextColor3 = Color3.fromRGB(255, 255, 255)
	buy.Text = "Buy"
	buy.Parent = gui

	buy.Activated:Connect(onBuy)
	gui.Parent = playerGui
	return gui
end

return ShopBoard
```

```lua
--!strict
-- LocalScript: StarterPlayerScripts.ShopBoardClient
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ShopBoard = require(script.Parent:WaitForChild("ShopBoard"))

local purchase = ReplicatedStorage:WaitForChild("RequestPurchase") :: RemoteEvent
local board = workspace:WaitForChild("ShopBoard") :: BasePart

ShopBoard.mount(board, Players.LocalPlayer:WaitForChild("PlayerGui"), function()
	purchase:FireServer("SpeedCoil")
end)
```

- `MaxDistance` hides the board (and its button) from far away, but that is only a client convenience: if buying should require standing near the board, check the distance on the server too.
- The client sends only an item id; the server looks up the price and checks the player's balance.
- `ResetOnSpawn = false` keeps the board from flickering out and back each time the player respawns.

# Test
```lua
local board = Instance.new("Part")
board.Name = "ShopBoard"
board.Parent = workspace
local playerGui = Instance.new("Folder")
local bought = 0
local gui = item.mount(board, playerGui, function()
	bought += 1
end)
check("lives in PlayerGui, drawn on the board", gui.Parent == playerGui and gui.Adornee == board)
check("pixel density sizing", gui.SizingMode == Enum.SurfaceGuiSizingMode.PixelsPerStud and gui.PixelsPerStud == 50)
check("readable in the dark", gui.LightInfluence == 0)
gui.Buy.Activated:Fire()
check("button click reaches the callback", bought == 1)
check("button anchored to the bottom centre", gui.Buy.AnchorPoint.X == 0.5 and gui.Buy.AnchorPoint.Y == 1)
```
