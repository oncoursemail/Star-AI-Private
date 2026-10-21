---
id: gb-ui-theme-runtime-switch
category: ui-style
topics: light dark theme, runtime theme switch, weak table, token binding, settings
source: original
---
# Request
I want a light/dark theme toggle in my settings. My UI is built in code across many modules. How can I switch every already-created element's colours when the player flips the toggle, without each module listening for it?

# Answer
Bind properties to token names instead of colours: `Theme.bind(frame, "BackgroundColor3", "surface")` applies the current theme now and remembers the binding. Switching the theme re-applies every binding. Bindings live in a table with weak keys, so destroyed UI does not stay in memory because of the theme.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.LiveTheme
local LiveTheme = {}

export type Palette = { [string]: Color3 }

local PALETTES: { [string]: Palette } = {
	dark = {
		surface = Color3.fromRGB(28, 30, 35),
		text = Color3.fromRGB(236, 237, 240),
		accent = Color3.fromRGB(70, 140, 235),
	},
	light = {
		surface = Color3.fromRGB(246, 247, 249),
		text = Color3.fromRGB(28, 30, 35),
		accent = Color3.fromRGB(30, 100, 200),
	},
}

local current = "dark"
local bindings: { [Instance]: { [string]: string } } = setmetatable({}, { __mode = "k" }) :: any

local function apply(instance: Instance, property: string, token: string)
	local target: any = instance
	target[property] = PALETTES[current][token]
end

function LiveTheme.bind(instance: Instance, property: string, token: string)
	assert(PALETTES[current][token] ~= nil, "unknown theme token " .. token)
	local props = bindings[instance]
	if props == nil then
		props = {}
		bindings[instance] = props
	end
	props[property] = token
	apply(instance, property, token)
end

function LiveTheme.set(name: string)
	assert(PALETTES[name] ~= nil, "unknown theme " .. name)
	current = name
	for instance, props in bindings do
		for property, token in props do
			apply(instance, property, token)
		end
	end
end

function LiveTheme.current(): string
	return current
end

return LiveTheme
```

- Unparented instances are recoloured too, so a menu built ahead of time already has the current theme when it is parented later.
- Weak keys let the garbage collector drop bindings for destroyed UI once nothing else references it.
- Store the choice in the player's saved settings and call `set` once at startup before building menus.

# Test
```lua
local gui = Instance.new("ScreenGui")
local panel = Instance.new("Frame")
panel.Parent = gui
local label = Instance.new("TextLabel")
label.Parent = panel
item.bind(panel, "BackgroundColor3", "surface")
item.bind(label, "TextColor3", "text")
check("dark applied on bind", panel.BackgroundColor3 == Color3.fromRGB(28, 30, 35))
item.set("light")
check("switch recolours existing UI", panel.BackgroundColor3 == Color3.fromRGB(246, 247, 249)
	and label.TextColor3 == Color3.fromRGB(28, 30, 35))
check("current theme reported", item.current() == "light")
local prebuilt = Instance.new("Frame")
item.bind(prebuilt, "BackgroundColor3", "surface")
item.set("dark")
check("unparented UI follows the switch", prebuilt.BackgroundColor3 == Color3.fromRGB(28, 30, 35))
check("unknown theme rejected", not pcall(item.set, "sepia"))
check("unknown token rejected", not pcall(item.bind, panel, "BorderColor3", "glow"))
```
