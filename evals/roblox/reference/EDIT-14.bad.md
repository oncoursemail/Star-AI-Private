The original code, unchanged.

```lua
-- SettingsValidator: cleans the settings table a client sends with RemoteFunction SaveSettings.
-- Never trust the client: unknown keys are dropped and every value is checked.
local SettingsValidator = {}

local DEFAULTS = {
	fov = 70,
	volume = 0.8,
	invertY = false,
	crosshair = "dot",
}

local CROSSHAIRS = {
	dot = true,
	cross = true,
	circle = true,
}

local function number(value, default)
	if type(value) ~= "number" or value ~= value then
		return default
	end
	return value
end

function SettingsValidator.defaults()
	return table.clone(DEFAULTS)
end

function SettingsValidator.clean(raw)
	local out = SettingsValidator.defaults()
	if type(raw) ~= "table" then
		return out
	end
	local fov = number(raw.fov, DEFAULTS.fov)
	if fov < 60 or fov > 110 then
		fov = DEFAULTS.fov
	end
	out.fov = fov
	out.volume = math.clamp(number(raw.volume, DEFAULTS.volume), 0, 1)
	if type(raw.invertY) == "boolean" then
		out.invertY = raw.invertY
	end
	if type(raw.crosshair) == "string" and CROSSHAIRS[raw.crosshair] then
		out.crosshair = raw.crosshair
	end
	return out
end

function SettingsValidator.changed(old, new)
	local keys = {}
	for key, value in pairs(new) do
		if old[key] ~= value then
			table.insert(keys, key)
		end
	end
	table.sort(keys)
	return keys
end

return SettingsValidator
```
