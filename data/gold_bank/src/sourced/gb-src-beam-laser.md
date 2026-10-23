---
id: gb-src-beam-laser
category: vfx-beam-trail
topics: Beam, Attachment, ColorSequence, NumberSequence, LightEmission, laser effect
source: adapted
source_id: creator-docs
source_path: content/en-us/reference/engine/classes/Beam.yaml
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
I want a laser between two emitter parts: red at the source fading to purple, solid in the middle and transparent at both ends, glowing, and it should turn off when I disable it. How do I build that Beam from a script?

# Answer
A Beam renders between two Attachments. Create an attachment on each part, set `Color` with a `ColorSequence` and `Transparency` with a `NumberSequence` (keypoints from 0 to 1 along the beam), and toggle `Enabled` to switch it.

```lua
--!strict
local Laser = {}

local COLOR = ColorSequence.new({
	ColorSequenceKeypoint.new(0, Color3.fromRGB(255, 0, 0)),
	ColorSequenceKeypoint.new(1, Color3.fromRGB(196, 0, 255)),
})

local TRANSPARENCY = NumberSequence.new({
	NumberSequenceKeypoint.new(0, 1),
	NumberSequenceKeypoint.new(0.15, 0),
	NumberSequenceKeypoint.new(0.85, 0),
	NumberSequenceKeypoint.new(1, 1),
})

function Laser.create(source: BasePart, target: BasePart, width: number): Beam
	local a0 = Instance.new("Attachment")
	a0.Name = "LaserStart"
	a0.Parent = source
	local a1 = Instance.new("Attachment")
	a1.Name = "LaserEnd"
	a1.Parent = target

	local beam = Instance.new("Beam")
	beam.Attachment0 = a0
	beam.Attachment1 = a1
	beam.Color = COLOR
	beam.Transparency = TRANSPARENCY
	beam.Width0 = width
	beam.Width1 = width
	beam.LightEmission = 1
	beam.FaceCamera = true
	beam.Segments = 1
	beam.Parent = source
	return beam
end

function Laser.setEnabled(beam: Beam, enabled: boolean)
	beam.Enabled = enabled
end

return Laser
```

- `NumberSequence` keypoints must start at time 0 and end at time 1; values in between shape the fade.
- `LightEmission = 1` blends the beam additively so it glows, and `FaceCamera` keeps a flat beam visible from every angle.
- A straight laser needs only one segment; raise `Segments` only when using `CurveSize0`/`CurveSize1`.

# Test
```lua
local a = Instance.new("Part")
a.Parent = workspace
local b = Instance.new("Part")
b.Position = Vector3.new(0, 0, -30)
b.Parent = workspace
local beam = item.create(a, b, 0.4)
check("beam connects both parts", beam.Attachment0.Parent == a and beam.Attachment1.Parent == b)
check("width and glow set", beam.Width0 == 0.4 and beam.Width1 == 0.4 and beam.LightEmission == 1)
check("transparent ends", beam.Transparency.Keypoints[1].Value == 1 and beam.Transparency.Keypoints[4].Value == 1)
item.setEnabled(beam, false)
check("can be switched off", beam.Enabled == false)
```
