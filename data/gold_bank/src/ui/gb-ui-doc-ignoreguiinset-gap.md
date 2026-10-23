---
id: gb-ui-doc-ignoreguiinset-gap
category: docs-question
topics: IgnoreGuiInset, ScreenInsets, top bar gap, loading screen, full screen frame
source: original
---
# Request
My loading screen frame is `UDim2.fromScale(1, 1)` but there's a strip at the top where the game shows through, and everything is shifted down a bit. Why isn't Scale 1 the full screen?

# Answer
By default a ScreenGui's area starts below the Roblox top bar, so Scale 1 means "the screen minus the top bar" and is offset down by it. For full-screen covers set `IgnoreGuiInset = true` (and `ScreenInsets = None` so device safe areas such as a notch are covered too). Keep interactive controls in a separate gui that respects the insets.

```lua
--!strict
-- LocalScript: ReplicatedFirst.LoadingCover
local Players = game:GetService("Players")
local ReplicatedFirst = game:GetService("ReplicatedFirst")

local playerGui = Players.LocalPlayer:WaitForChild("PlayerGui")

local cover = Instance.new("ScreenGui")
cover.Name = "LoadingCover"
cover.IgnoreGuiInset = true
cover.ScreenInsets = Enum.ScreenInsets.None
cover.DisplayOrder = 1000
cover.ResetOnSpawn = false

local backdrop = Instance.new("Frame")
backdrop.Name = "Backdrop"
backdrop.Size = UDim2.fromScale(1, 1)
backdrop.BackgroundColor3 = Color3.fromRGB(14, 15, 18)
backdrop.BorderSizePixel = 0
backdrop.Parent = cover

local status = Instance.new("TextLabel")
status.Name = "Status"
status.AnchorPoint = Vector2.new(0.5, 0.5)
status.Position = UDim2.fromScale(0.5, 0.5)
status.Size = UDim2.fromOffset(300, 40)
status.BackgroundTransparency = 1
status.TextColor3 = Color3.fromRGB(220, 222, 228)
status.TextSize = 20
status.Text = "Loading"
status.Parent = backdrop

cover.Parent = playerGui
ReplicatedFirst:RemoveDefaultLoadingScreen()
```

- Running from ReplicatedFirst shows the cover before the rest of the game replicates; removing the default screen avoids two loading screens.
- The high DisplayOrder keeps it above HUD guis that load while it is up.
- Positions inside an inset-ignoring gui are measured from the very top of the screen, which matters for anything aligned with `Camera:WorldToViewportPoint`.

# Test
```lua
__setClient(true)
__makePlayer(1, "Neo")
local rf = game:GetService("ReplicatedFirst")
rf.RemoveDefaultLoadingScreen = function()
	rf.__removed = true
end
```
```lua
local cover = game:GetService("Players").LocalPlayer.PlayerGui:FindFirstChild("LoadingCover")
check("cover created", cover ~= nil)
check("ignores the top bar inset", cover ~= nil and cover.IgnoreGuiInset == true)
check("covers device safe areas too", cover ~= nil and cover.ScreenInsets == Enum.ScreenInsets.None)
check("default loading screen removed", game:GetService("ReplicatedFirst").__removed == true)
check("backdrop fills the screen", cover ~= nil and cover.Backdrop.Size.X.Scale == 1 and cover.Backdrop.Size.Y.Scale == 1)
```
