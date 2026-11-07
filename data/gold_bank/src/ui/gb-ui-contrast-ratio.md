---
id: gb-ui-contrast-ratio
category: ui-style
topics: contrast ratio, accessibility, Color3, luminance, text colour
source: original
---
# Request
Players let us pick any team colour, and the team name is drawn on top of it. On yellow and light green the white text is unreadable. Can you write a function that measures contrast and picks black or white text for a background?

# Answer
Use the WCAG definition: convert each sRGB channel to linear light, compute relative luminance, and the contrast ratio is `(lighter + 0.05) / (darker + 0.05)`, from 1 (none) to 21 (black on white). Pick whichever text colour gives the higher ratio and expose the ratio so a style check can flag pairs under 4.5.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Contrast
local Contrast = {}

local function linear(channel: number): number
	if channel <= 0.04045 then
		return channel / 12.92
	end
	return ((channel + 0.055) / 1.055) ^ 2.4
end

function Contrast.luminance(color: Color3): number
	return 0.2126 * linear(color.R) + 0.7152 * linear(color.G) + 0.0722 * linear(color.B)
end

function Contrast.ratio(a: Color3, b: Color3): number
	local la, lb = Contrast.luminance(a), Contrast.luminance(b)
	local lighter, darker = math.max(la, lb), math.min(la, lb)
	return (lighter + 0.05) / (darker + 0.05)
end

local DARK = Color3.fromRGB(17, 17, 17)
local LIGHT = Color3.fromRGB(255, 255, 255)

function Contrast.textFor(background: Color3): Color3
	if Contrast.ratio(background, DARK) >= Contrast.ratio(background, LIGHT) then
		return DARK
	end
	return LIGHT
end

-- 4.5 is the WCAG AA minimum for body text; 3 is enough for large bold text.
function Contrast.meets(text: Color3, background: Color3, largeText: boolean?): boolean
	return Contrast.ratio(text, background) >= (if largeText then 3 else 4.5)
end

return Contrast
```

- Averaging R, G and B is not luminance: green looks far brighter than blue, which is why the weights differ.
- Near-black (17, 17, 17) reads softer than pure black and still passes on every light colour.
- Run `Contrast.meets` over your theme tokens in a test so a palette change cannot ship unreadable text.

# Test
```lua
local black, white = Color3.new(0, 0, 0), Color3.new(1, 1, 1)
check("black on white is 21:1", math.abs(item.ratio(black, white) - 21) < 1e-6)
check("a colour against itself is 1:1", math.abs(item.ratio(white, white) - 1) < 1e-9)
check("ratio is symmetric", item.ratio(black, white) == item.ratio(white, black))
local yellow = Color3.fromRGB(255, 221, 0)
check("dark text on yellow", item.textFor(yellow).R < 0.1)
check("white text on navy", item.textFor(Color3.fromRGB(20, 30, 90)).R == 1)
check("white on yellow fails AA", not item.meets(white, yellow))
local grey = Color3.fromRGB(140, 140, 140)
check("large text uses the lower bar", item.meets(grey, white, true) and not item.meets(grey, white))
```
