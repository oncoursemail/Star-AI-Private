---
id: gb-data-remote-settings-table-schema
category: remote-security
topics: RemoteEvent, table argument, schema validation, settings, keybinds
source: original
---
# Request
My settings menu sends the whole settings table to the server to save: `SaveSettings:FireServer(settings)`. It has volumes, a hints toggle and keybinds. The server just stores what it gets. What could go wrong and how should I validate a table argument?

# Answer
A client-sent table can hold anything: extra keys, huge strings, nested tables thousands deep, NaN volumes, or Instances that break your save. Build a fresh table on the server from a schema: copy only known keys, check each value's type and range, and fall back to the current value for anything invalid. Unknown keys are dropped, never copied.

```lua
--!strict
-- ModuleScript: ServerScriptService.SettingsSchema
export type Settings = {
	music: number,
	sfx: number,
	showHints: boolean,
	keybinds: { [string]: string },
}

local ACTIONS: { [string]: boolean } = { Dash = true, Interact = true, Inventory = true }
local KEYS: { [string]: boolean } = { Q = true, E = true, F = true, R = true, Tab = true, LeftShift = true, One = true, Two = true }

local SettingsSchema = {}

SettingsSchema.DEFAULTS = table.freeze({
	music = 0.5,
	sfx = 0.8,
	showHints = true,
	keybinds = table.freeze({ Dash = "Q", Interact = "E", Inventory = "Tab" }),
})

local function volume(value: unknown, fallback: number): number
	if type(value) == "number" and value == value and value >= 0 and value <= 1 then
		return value
	end
	return fallback
end

local function keybinds(value: unknown, current: { [string]: string }): { [string]: string }
	local out: { [string]: string } = {}
	for action, key in current do
		out[action] = key
	end
	if type(value) ~= "table" then
		return out
	end
	for action in ACTIONS do
		local key = (value :: { [any]: any })[action]
		if type(key) == "string" and KEYS[key] then
			out[action] = key
		end
	end
	return out
end

-- Builds a new settings table from untrusted input; never returns anything from `raw` itself.
function SettingsSchema.sanitize(raw: unknown, current: Settings): Settings
	local input: { [any]: any } = if type(raw) == "table" then raw :: any else {}
	return {
		music = volume(input.music, current.music),
		sfx = volume(input.sfx, current.sfx),
		showHints = if type(input.showHints) == "boolean" then input.showHints else current.showHints,
		keybinds = keybinds(input.keybinds, current.keybinds),
	}
end

return SettingsSchema
```

Handler: `settings[player] = SettingsSchema.sanitize(raw, settings[player] or SettingsSchema.DEFAULTS)`, behind a cooldown of a few seconds, then mark the profile dirty for the next save.

- Iterating your own `ACTIONS` table (not the client's table) means a table with a million keys costs the same as a normal one.
- Two actions bound to the same key is a UI problem, not a security one; reject it in the menu, or check for duplicates here if it would break your input code.
- Nothing from the client table is stored by reference, so later changes to it (or metatables on it) cannot leak into server data.

# Test
```lua
local defaults = item.DEFAULTS
local good = item.sanitize({ music = 0.2, sfx = 1, showHints = false, keybinds = { Dash = "F" } }, defaults)
check("valid values are copied", good.music == 0.2 and good.sfx == 1 and good.showHints == false and good.keybinds.Dash == "F")
check("unchanged keybinds keep their current value", good.keybinds.Interact == "E")

local evil = item.sanitize({ music = 0 / 0, sfx = 5, showHints = "yes", admin = true,
	keybinds = { Dash = "Escape", Fly = "Q", Interact = string.rep("E", 1000) } }, good)
check("NaN and out-of-range volumes fall back", evil.music == 0.2 and evil.sfx == 1)
check("wrong types fall back", evil.showHints == false)
check("unknown keys are dropped", (evil :: any).admin == nil and evil.keybinds.Fly == nil)
check("invalid keybinds fall back", evil.keybinds.Dash == "F" and evil.keybinds.Interact == "E")

local fromJunk = item.sanitize("not a table", defaults)
check("non-table input returns the current settings", fromJunk.music == 0.5 and fromJunk.keybinds.Inventory == "Tab")
check("result is a new table, not the defaults", fromJunk ~= defaults and fromJunk.keybinds ~= defaults.keybinds)
```
