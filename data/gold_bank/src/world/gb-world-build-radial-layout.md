---
id: gb-world-build-radial-layout
category: building-layout
topics: CFrame layout, ring, spiral staircase, procedural placement, PivotTo
source: original
---
# Request
I need to place things in circles a lot: pillars around an arena all facing the centre, seats around a campfire, and a spiral staircase around a tower. Can you write a reusable module that gives me the CFrames, so I'm not doing trig by hand every time?

# Answer
Work in the layout's local space: rotate around Y by the item's angle, then step out along -Z by the radius. That one composition gives a ring; adding a height per step gives a spiral. Converting to world space happens once, through the centre CFrame, so the whole layout can be tilted or moved by changing that single CFrame.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.RadialLayout
local RadialLayout = {}

function RadialLayout.ring(center: CFrame, radius: number, count: number, faceCenter: boolean): { CFrame }
	local result: { CFrame } = {}
	for index = 0, count - 1 do
		local angle = index / count * 2 * math.pi
		local localFrame = CFrame.Angles(0, angle, 0) * CFrame.new(0, 0, -radius)
		if faceCenter then
			localFrame *= CFrame.Angles(0, math.pi, 0)
		end
		result[index + 1] = center:ToWorldSpace(localFrame)
	end
	return result
end

function RadialLayout.spiral(base: CFrame, steps: number, radius: number, rise: number, degreesPerStep: number): { CFrame }
	local result: { CFrame } = {}
	for index = 0, steps - 1 do
		local localFrame = CFrame.new(0, index * rise, 0)
			* CFrame.Angles(0, math.rad(index * degreesPerStep), 0)
			* CFrame.new(0, 0, -radius / 2)
		result[index + 1] = base:ToWorldSpace(localFrame)
	end
	return result
end

function RadialLayout.place(frames: { CFrame }, template: Model, parent: Instance): { Model }
	local placed: { Model } = {}
	for index, frame in frames do
		local copy = template:Clone()
		copy:PivotTo(frame)
		copy.Parent = parent
		placed[index] = copy
	end
	return placed
end

return RadialLayout
```

Usage: `RadialLayout.place(RadialLayout.ring(arena:GetPivot(), 60, 12, true), pillarTemplate, arena)`.

- The spiral offsets each step by half the radius so a step whose length equals the radius runs from the central column to the outer edge.
- Set `faceCenter` to false for things that should look outward, such as turrets on a wall.
- Pivot the template at its base (Model `WorldPivot`) so pieces sit on the ground instead of half-buried.

# Test
```lua
local frames = item.ring(CFrame.new(0, 0, 0), 10, 4, true)
check("four positions on the circle", #frames == 4 and (frames[1].Position - Vector3.new(0, 0, -10)).Magnitude < 1e-9)
check("second item is a quarter turn round", (frames[2].Position - Vector3.new(-10, 0, 0)).Magnitude < 1e-9)
local allFace = true
for _, f in frames do
	if (f.LookVector - (Vector3.zero - f.Position).Unit).Magnitude > 1e-9 then
		allFace = false
	end
end
check("every item faces the centre", allFace)

local moved = item.ring(CFrame.new(100, 5, 0), 10, 4, false)
check("layout follows the centre CFrame and faces out", (moved[1].Position - Vector3.new(100, 5, -10)).Magnitude < 1e-9 and moved[1].LookVector.Z < -0.99)

local steps = item.spiral(CFrame.new(0, 0, 0), 8, 6, 1, 45)
check("spiral rises one step at a time", math.abs(steps[8].Position.Y - 7) < 1e-9)
check("spiral steps stay at half radius", math.abs(Vector3.new(steps[5].Position.X, 0, steps[5].Position.Z).Magnitude - 3) < 1e-9)

local template = Instance.new("Model")
local p = Instance.new("Part")
p.Parent = template
template.PrimaryPart = p
local placed = item.place(frames, template, workspace)
check("place clones and pivots each copy", #placed == 4 and (placed[3]:FindFirstChildWhichIsA("BasePart").Position - frames[3].Position).Magnitude < 1e-9)
```
