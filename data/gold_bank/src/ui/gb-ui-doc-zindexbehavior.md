---
id: gb-ui-doc-zindexbehavior
category: docs-question
topics: ZIndexBehavior, ZIndex, Sibling, Global, layering, ScreenGui
source: original
---
# Request
I gave my tooltip `ZIndex = 100`, but it still draws behind a panel that has `ZIndex = 2`. The tooltip is inside a small frame in the sidebar and the panel is elsewhere in the same ScreenGui. How does ZIndex actually work?

# Answer
It depends on the ScreenGui's `ZIndexBehavior`. With `Sibling` (the default for new ScreenGuis), ZIndex only orders an object against its siblings, and children always draw on top of their parent, so a tooltip deep inside the sidebar can never rise above a panel the sidebar is drawn under. With `Global`, every ZIndex in the gui is compared directly. The clean fix is structural: give overlays (tooltips, modals, dropdown lists) their own ScreenGui with a higher `DisplayOrder`.

```lua
--!strict
-- LocalScript: separate layer for overlays
local Players = game:GetService("Players")

local playerGui = Players.LocalPlayer:WaitForChild("PlayerGui")

local overlay = Instance.new("ScreenGui")
overlay.Name = "Overlay"
overlay.ZIndexBehavior = Enum.ZIndexBehavior.Sibling
overlay.DisplayOrder = 100
overlay.ResetOnSpawn = false

local tooltip = Instance.new("TextLabel")
tooltip.Name = "Tooltip"
tooltip.AutomaticSize = Enum.AutomaticSize.XY
tooltip.Visible = false
tooltip.Parent = overlay

overlay.Parent = playerGui
```

- Under Sibling, think of the tree: ZIndex sorts brothers and sisters; depth in the tree decides the rest.
- `DisplayOrder` sorts whole ScreenGuis, so the overlay gui wins over every HUD gui with a lower value regardless of their internal ZIndex.
- Switching an existing gui to Global often breaks other layering; moving the overlay out is safer.

# Test
```lua
__setClient(true)
__makePlayer(1, "Ivy")
```
```lua
local overlay = game:GetService("Players").LocalPlayer.PlayerGui:FindFirstChild("Overlay")
check("overlay gui exists", overlay ~= nil)
check("drawn above other guis", overlay ~= nil and overlay.DisplayOrder == 100)
check("sibling layering", overlay ~= nil and overlay.ZIndexBehavior == Enum.ZIndexBehavior.Sibling)
check("tooltip lives in the overlay", overlay ~= nil and overlay.Tooltip.Visible == false)
```
