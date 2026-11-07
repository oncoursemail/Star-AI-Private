---
id: gb-ui-screeninsets-notch
category: ui-layout
topics: ScreenGui, ScreenInsets, safe area, notch, DeviceSafeInsets, full-bleed background
source: original
---
# Request
On iPhones with a notch, my left-side buttons are partly hidden behind it, but my full-screen background image also shouldn't have a black strip. How do I keep controls safe while letting the background cover everything?

# Answer
Split them into two ScreenGuis. The controls gui uses `ScreenInsets = CoreUISafeInsets` (stays clear of the notch, rounded corners and the Roblox top bar); the background gui uses `ScreenInsets = None` so it spans the whole physical screen. Each element then just positions itself inside its own gui.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.SafeScreens
local SafeScreens = {}

export type Screens = {
	background: ScreenGui,
	controls: ScreenGui,
}

function SafeScreens.create(playerGui: Instance): Screens
	local background = Instance.new("ScreenGui")
	background.Name = "Background"
	background.ScreenInsets = Enum.ScreenInsets.None
	background.DisplayOrder = 0
	background.ResetOnSpawn = false

	local controls = Instance.new("ScreenGui")
	controls.Name = "Controls"
	controls.ScreenInsets = Enum.ScreenInsets.CoreUISafeInsets
	controls.DisplayOrder = 10
	controls.ResetOnSpawn = false

	local art = Instance.new("ImageLabel")
	art.Name = "Art"
	art.Size = UDim2.fromScale(1, 1)
	art.ScaleType = Enum.ScaleType.Crop
	art.BackgroundColor3 = Color3.fromRGB(16, 18, 22)
	art.Parent = background

	background.Parent = playerGui
	controls.Parent = playerGui
	return { background = background, controls = controls }
end

return SafeScreens
```

- `DeviceSafeInsets` avoids only the hardware cut-outs; choose it for a gui that should be allowed under the Roblox top bar.
- Crop scaling fills the full screen without distortion; keep important parts of the art near the centre.
- `DisplayOrder` keeps controls above the background no matter which gui is created first.

# Test
```lua
local playerGui = Instance.new("Folder")
local screens = item.create(playerGui)
check("background spans the full screen", screens.background.ScreenInsets == Enum.ScreenInsets.None)
check("controls avoid notch and top bar", screens.controls.ScreenInsets == Enum.ScreenInsets.CoreUISafeInsets)
check("controls draw above background", screens.controls.DisplayOrder > screens.background.DisplayOrder)
check("art fills its gui", screens.background.Art.Size.X.Scale == 1 and screens.background.Art.ScaleType == Enum.ScaleType.Crop)
check("both parented and persistent", screens.controls.Parent == playerGui and screens.background.ResetOnSpawn == false)
```
