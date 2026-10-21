---
id: gb-ui-device-layout-profiles
category: ui-layout
topics: PreferredInput, phone tablet console PC, breakpoints, ViewportSize, touch targets
source: original
---
# Request
I need my HUD to adapt: bigger buttons on phones, a roomier layout on tablets, large text for console players on a TV, and the compact version on PC. What's a sane way to decide which layout to use?

# Answer
Classify with two inputs: how the player is interacting (`UserInputService.PreferredInput`) and the viewport's short side. Map the class to a small table of metrics (text size, button height, margin) and rebuild or restyle when either input changes. Keep the classification pure so it is easy to test.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.LayoutProfile
local LayoutProfile = {}

export type Class = "phone" | "tablet" | "tv" | "desktop"
export type Metrics = { textSize: number, buttonHeight: number, margin: number }

local METRICS: { [Class]: Metrics } = {
	phone = { textSize = 16, buttonHeight = 52, margin = 12 },
	tablet = { textSize = 18, buttonHeight = 48, margin = 20 },
	tv = { textSize = 24, buttonHeight = 56, margin = 48 },
	desktop = { textSize = 16, buttonHeight = 36, margin = 16 },
}

function LayoutProfile.classify(preferred: Enum.PreferredInput, viewport: Vector2): Class
	if preferred == Enum.PreferredInput.Gamepad then
		return "tv"
	elseif preferred == Enum.PreferredInput.Touch then
		return if math.min(viewport.X, viewport.Y) < 500 then "phone" else "tablet"
	end
	return "desktop"
end

function LayoutProfile.metrics(class: Class): Metrics
	return METRICS[class]
end

-- Calls onChange(class) now and whenever the input method or the viewport changes class.
function LayoutProfile.watch(onChange: (class: Class) -> ()): () -> ()
	local UserInputService = game:GetService("UserInputService")
	local current: Class? = nil
	local function evaluate()
		local camera = workspace.CurrentCamera
		local viewport: Vector2 = if camera then camera.ViewportSize else Vector2.new(1280, 720)
		local class = LayoutProfile.classify(UserInputService.PreferredInput, viewport)
		if class ~= current then
			current = class
			onChange(class)
		end
	end
	local connections = {
		UserInputService:GetPropertyChangedSignal("PreferredInput"):Connect(evaluate),
		workspace.CurrentCamera:GetPropertyChangedSignal("ViewportSize"):Connect(evaluate),
	}
	evaluate()
	return function()
		for _, connection in connections do
			connection:Disconnect()
		end
	end
end

return LayoutProfile
```

- Touch targets of about 48 px or more are what thumbs hit reliably; desktop can be denser because a mouse is precise.
- TVs are viewed from a couch and may crop edges, hence the large text and wide margin.
- Notifying only when the class changes avoids rebuilding the HUD on every pixel of a window resize.

# Test
```lua
local UIS = game:GetService("UserInputService")
check("gamepad means tv", item.classify(Enum.PreferredInput.Gamepad, Vector2.new(1920, 1080)) == "tv")
check("small touch screen is a phone", item.classify(Enum.PreferredInput.Touch, Vector2.new(844, 390)) == "phone")
check("large touch screen is a tablet", item.classify(Enum.PreferredInput.Touch, Vector2.new(1024, 768)) == "tablet")
check("keyboard is desktop", item.classify(Enum.PreferredInput.KeyboardAndMouse, Vector2.new(844, 390)) == "desktop")
check("phone buttons are big enough to tap", item.metrics("phone").buttonHeight >= 48)
UIS.PreferredInput = Enum.PreferredInput.KeyboardAndMouse
local seen = {}
local stop = item.watch(function(class)
	table.insert(seen, class)
end)
UIS.PreferredInput = Enum.PreferredInput.Gamepad
workspace.CurrentCamera.ViewportSize = Vector2.new(1300, 720)
check("notifies on class changes only", #seen == 2 and seen[1] == "desktop" and seen[2] == "tv")
stop()
UIS.PreferredInput = Enum.PreferredInput.Touch
check("stopped watchers stay quiet", #seen == 2)
```
