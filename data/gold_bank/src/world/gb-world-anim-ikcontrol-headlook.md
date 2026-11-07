---
id: gb-world-anim-ikcontrol-headlook
category: animation
topics: IKControl, LookAt, head tracking, NPC, angle falloff
source: original
---
# Request
I'd like my shopkeeper NPC to turn its head toward the nearest player using IKControl, but when the player walks behind it the head spins around like an owl. How do I set up the IKControl and stop it from over-rotating?

# Answer
Use a `LookAt` IKControl from the UpperTorso to the Head, and scale its `Weight` by how far the target is off the NPC's forward direction: full weight inside a comfortable cone, fading to zero past the limit. `SmoothTime` takes care of easing between targets.

```lua
--!strict
-- ModuleScript: ServerScriptService.HeadLook
export type HeadLook = {
	setTarget: (target: BasePart?) -> (),
	weight: () -> number,
}

local HeadLook = {}

-- 1 inside (maxAngle - fade), 0 beyond maxAngle, linear in between. Angles in degrees.
function HeadLook.weightForAngle(angle: number, maxAngle: number, fade: number): number
	if angle >= maxAngle then
		return 0
	end
	return math.clamp((maxAngle - angle) / math.max(fade, 1e-3), 0, 1)
end

function HeadLook.new(character: Model, maxAngle: number?, fade: number?): HeadLook
	local humanoid = character:FindFirstChildOfClass("Humanoid")
	local root = character:FindFirstChild("HumanoidRootPart")
	local torso = character:FindFirstChild("UpperTorso")
	local head = character:FindFirstChild("Head")
	assert(humanoid and root and torso and head, "R15 character with UpperTorso and Head expected")
	local limit = maxAngle or 70
	local fadeRange = fade or 20

	local ik = Instance.new("IKControl")
	ik.Type = Enum.IKControlType.LookAt
	ik.ChainRoot = torso
	ik.EndEffector = head
	ik.SmoothTime = 0.15
	ik.Weight = 0
	ik.Parent = humanoid

	local function setTarget(target: BasePart?)
		if target == nil then
			ik.Target = nil
			ik.Weight = 0
			return
		end
		-- Offset in the root's space: -Z is straight ahead.
		local offset = root.CFrame:PointToObjectSpace(target.Position)
		local angle = math.deg(math.acos(math.clamp(-offset.Unit.Z, -1, 1)))
		ik.Target = target
		ik.Weight = HeadLook.weightForAngle(angle, limit, fadeRange)
	end

	return {
		setTarget = setTarget,
		weight = function(): number
			return ik.Weight
		end,
	}
end

return HeadLook
```

- Pick the target (nearest player within range) a few times per second and call `setTarget`; the IKControl itself interpolates every frame, so updating more often adds nothing.
- The fade band lowers the weight gradually as the player walks behind the NPC, so the head eases back to its animated pose instead of snapping.
- For R6 rigs use the Torso as `ChainRoot`; the angle maths is the same.

# Test
```lua
local rig = __buildRig(Vector3.new(0, 3, 0))
local torso = Instance.new("Part")
torso.Name = "UpperTorso"
torso.Parent = rig
rig.Parent = workspace
local look = item.new(rig)
local ik = rig.Humanoid:FindFirstChildOfClass("IKControl")
check("IKControl created as LookAt", ik ~= nil and ik.Type == Enum.IKControlType.LookAt and ik.EndEffector == rig.Head)

local front = Instance.new("Part")
front.Position = Vector3.new(0, 3, -10)
look.setTarget(front)
check("target straight ahead gets full weight", math.abs(look.weight() - 1) < 1e-6 and ik.Target == front)

local behind = Instance.new("Part")
behind.Position = Vector3.new(0, 3, 10)
look.setTarget(behind)
check("target behind gets zero weight", look.weight() == 0)

look.setTarget(nil)
check("clearing the target resets weight", look.weight() == 0 and ik.Target == nil)
check("fade zone is linear", math.abs(item.weightForAngle(60, 70, 20) - 0.5) < 1e-6)
check("past the limit is zero", item.weightForAngle(95, 70, 20) == 0)
```
