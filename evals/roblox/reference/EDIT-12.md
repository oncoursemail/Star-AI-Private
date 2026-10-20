Reference fix.

```lua
-- PaintColor: team paint colours as {r, g, b} tables with channels 0..1 (shared by client and server).
local PaintColor = {}

PaintColor.TEAMS = {
	Red = { r = 0.9, g = 0.15, b = 0.15 },
	Blue = { r = 0.15, g = 0.35, b = 0.95 },
	Green = { r = 0.2, g = 0.8, b = 0.3 },
	Yellow = { r = 0.95, g = 0.85, b = 0.1 },
}

function PaintColor.new(r, g, b)
	return { r = r, g = g, b = b }
end

-- Blend from a to b; t = 0 gives a, t = 1 gives b.
function PaintColor.mix(a, b, t)
	t = math.clamp(t, 0, 1)
	return {
		r = a.r + (b.r - a.r) * t,
		g = a.g + (b.g - a.g) * t,
		b = a.b + (b.b - a.b) * t,
	}
end

function PaintColor.darken(c, amount)
	return PaintColor.new(c.r * (1 - amount), c.g * (1 - amount), c.b * (1 - amount))
end

local function channel(x)
	return string.format("%02x", math.clamp(math.floor(x * 255 + 0.5), 0, 255))
end

function PaintColor.toHex(c)
	return "#" .. channel(c.r) .. channel(c.g) .. channel(c.b)
end

function PaintColor.fromHex(hex)
	local r, g, b = string.match(hex, "^#?(%x%x)(%x%x)(%x%x)$")
	if r == nil then
		return nil
	end
	return PaintColor.new(tonumber(r, 16) / 255, tonumber(g, 16) / 255, tonumber(b, 16) / 255)
end

function PaintColor.equal(a, b)
	return math.abs(a.r - b.r) < 1e-3 and math.abs(a.g - b.g) < 1e-3 and math.abs(a.b - b.b) < 1e-3
end

function PaintColor.forTeam(name)
	return PaintColor.TEAMS[name] or PaintColor.new(1, 1, 1)
end

return PaintColor
```
