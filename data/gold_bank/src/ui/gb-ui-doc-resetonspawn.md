---
id: gb-ui-doc-resetonspawn
category: docs-question
topics: ScreenGui, ResetOnSpawn, PlayerGui, respawn, StarterGui
source: original
---
# Request
Why does my shop menu close and lose everything the player typed every time their character dies? The LocalScript inside it also seems to run again from the top after each respawn.

# Answer
Every ScreenGui has `ResetOnSpawn`, true by default. When the character respawns, Roblox deletes those ScreenGuis from PlayerGui and copies fresh ones from StarterGui, so their state and the LocalScripts inside them start over. Set it to false for UI that should outlive a death, or create that UI from a LocalScript in StarterPlayerScripts, which does not rerun on respawn.

```lua
--!strict
-- LocalScript: StarterPlayerScripts.ShopBootstrap
local Players = game:GetService("Players")

local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui")

local shopGui = Instance.new("ScreenGui")
shopGui.Name = "Shop"
shopGui.ResetOnSpawn = false
shopGui.ZIndexBehavior = Enum.ZIndexBehavior.Sibling

local window = Instance.new("Frame")
window.Name = "Window"
window.AnchorPoint = Vector2.new(0.5, 0.5)
window.Position = UDim2.fromScale(0.5, 0.5)
window.Size = UDim2.fromScale(0.5, 0.6)
window.Visible = false
window.Parent = shopGui

shopGui.Parent = playerGui
```

- Keep `ResetOnSpawn = true` for things tied to one life, such as a health bar wired to the old Humanoid; they then rebind to the new character for free.
- With `ResetOnSpawn = false`, anything that references the character must listen to `player.CharacterAdded`, because the old Humanoid is gone after a respawn.
- Setting the property on the StarterGui copy in Studio works too; the copy in PlayerGui inherits it.

# Test
```lua
__setClient(true)
__makePlayer(1, "Shopper")
```
```lua
local player = game:GetService("Players").LocalPlayer
local gui = player.PlayerGui:FindFirstChild("Shop")
check("ScreenGui created in PlayerGui", gui ~= nil)
check("survives respawn", gui ~= nil and gui.ResetOnSpawn == false)
check("window starts hidden and centred", gui ~= nil and gui.Window.Visible == false and gui.Window.AnchorPoint.X == 0.5)
```
