---
id: gb-ui-derived-button-shades
category: ui-style
topics: Color3, HSV, hover colour, pressed colour, colour derivation
source: original
---
# Request
For every button colour in my game I hand-pick a hover and a pressed shade, and they're inconsistent: some hovers are much lighter than others, and on dark grey the hover is barely visible. Can I compute those shades from the base colour instead?

# Answer
Derive them in HSV: hover raises the value (brightness) a fixed step, pressed lowers it, and very dark bases get a larger hover step so the change stays visible. Clamping keeps white and black bases sensible. One pure function gives every button the same feel.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Shades
local Shades = {}

export type Set = { base: Color3, hover: Color3, pressed: Color3, disabled: Color3 }

local function shift(color: Color3, deltaValue: number, saturationScale: number?): Color3
	local h, s, v = color:ToHSV()
	return Color3.fromHSV(h, math.clamp(s * (saturationScale or 1), 0, 1), math.clamp(v + deltaValue, 0, 1))
end

function Shades.derive(base: Color3): Set
	local _, _, value = base:ToHSV()
	local hoverStep = if value < 0.3 then 0.12 else 0.07
	local hover = if value > 0.93 then shift(base, -0.06) else shift(base, hoverStep)
	return {
		base = base,
		hover = hover,
		pressed = shift(base, -0.1),
		disabled = shift(base, -0.15, 0.25),
	}
end

return Shades
```

- Changing value keeps the hue, so a blue button's hover is still the same blue, unlike lerping toward white.
- Near-white bases darken on hover instead, since they cannot get brighter.
- The disabled shade drops most of the saturation, so it reads as inactive for colour-blind players as well.

# Test
```lua
local blue = Color3.fromRGB(40, 110, 210)
local set = item.derive(blue)
local _, _, vBase = blue:ToHSV()
local hHover, _, vHover = set.hover:ToHSV()
local hBase = blue:ToHSV()
check("hover is brighter", vHover > vBase)
check("hue preserved", math.abs(hHover - hBase) < 1e-6)
local _, _, vPressed = set.pressed:ToHSV()
check("pressed is darker", vPressed < vBase)
local dark = item.derive(Color3.fromRGB(30, 30, 34))
local _, _, vd = dark.base:ToHSV()
local _, _, vdh = dark.hover:ToHSV()
check("dark bases get a bigger step", vdh - vd > 0.1)
local white = item.derive(Color3.new(1, 1, 1))
local _, _, vw = white.hover:ToHSV()
check("white hover darkens", vw < 1)
local _, sDisabled = set.disabled:ToHSV()
local _, sBase = blue:ToHSV()
check("disabled is desaturated", sDisabled < sBase)
```
