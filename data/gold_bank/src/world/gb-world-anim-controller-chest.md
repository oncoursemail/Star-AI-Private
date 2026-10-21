---
id: gb-world-anim-controller-chest
category: animation
topics: AnimationController, non-humanoid rig, Motor6D, AdjustSpeed, server animation
source: original
---
# Request
I rigged a treasure chest (the lid is attached with a Motor6D) and made an open animation, but there is no Humanoid so I don't know where to load it from. Also, when the open animation finishes the lid snaps shut again. How do I fix both?

# Answer
Non-humanoid rigs animate through an `AnimationController` with an `Animator` inside it. The snap happens because a finished track releases its pose; a marker on the last frame that sets the track speed to 0 holds the lid open until you stop it. The animation ids come from attributes on the model so nothing is hard-coded.

```lua
--!strict
-- ModuleScript: ServerScriptService.ChestAnimator
export type Chest = {
	openLid: () -> boolean,
	closeLid: () -> boolean,
	isOpen: () -> boolean,
}

local ChestAnimator = {}

local function ensureAnimator(model: Model): Animator
	local controller = model:FindFirstChildOfClass("AnimationController")
	if controller == nil then
		controller = Instance.new("AnimationController")
		controller.Parent = model
	end
	local animator = controller:FindFirstChildOfClass("Animator")
	if animator == nil then
		animator = Instance.new("Animator")
		animator.Parent = controller
	end
	return animator
end

local function loadFromAttribute(animator: Animator, model: Model, attribute: string): AnimationTrack
	local id = model:GetAttribute(attribute)
	assert(type(id) == "string" and id ~= "", string.format("set the %s attribute on the chest", attribute))
	local animation = Instance.new("Animation")
	animation.AnimationId = id
	return animator:LoadAnimation(animation)
end

function ChestAnimator.new(model: Model): Chest
	local animator = ensureAnimator(model)
	local openTrack = loadFromAttribute(animator, model, "OpenAnimationId")
	local closeTrack = loadFromAttribute(animator, model, "CloseAnimationId")
	local open = false

	-- "Hold" sits just before the open animation's last keyframe; freezing there keeps the lid up.
	openTrack:GetMarkerReachedSignal("Hold"):Connect(function()
		openTrack:AdjustSpeed(0)
	end)

	local function openLid(): boolean
		if open then
			return false
		end
		open = true
		closeTrack:Stop(0.1)
		openTrack:Play(0.1, 1, 1)
		model:SetAttribute("IsOpen", true)
		return true
	end

	local function closeLid(): boolean
		if not open then
			return false
		end
		open = false
		openTrack:Stop(0.1)
		closeTrack:Play(0.1, 1, 1)
		model:SetAttribute("IsOpen", false)
		return true
	end

	return {
		openLid = openLid,
		closeLid = closeLid,
		isOpen = function(): boolean
			return open
		end,
	}
end

return ChestAnimator
```

- The lid must be joined to the base with a Motor6D (not a WeldConstraint); the Animator can only move Motor6D and Bone joints.
- Playing the animation on the server replicates it to every client; for purely cosmetic props that many players open at once, fire a remote and play it on clients instead.
- `openLid`/`closeLid` return false when nothing changed, so a ProximityPrompt handler can skip the sound or reward on repeat triggers.
- Anchor only the chest base; an anchored lid cannot be moved by the animation.

# Test
```lua
local chest = Instance.new("Model")
local base = Instance.new("Part")
base.Parent = chest
chest:SetAttribute("OpenAnimationId", "rbxassetid://1")
chest:SetAttribute("CloseAnimationId", "rbxassetid://2")
chest.Parent = workspace
local animator = item.new(chest)
local tracks = chest.AnimationController.Animator.__tracks
local openTrack, closeTrack = tracks[1], tracks[2]

check("controller and animator created", chest:FindFirstChildOfClass("AnimationController") ~= nil and #tracks == 2)
check("first open succeeds", animator.openLid() == true and openTrack.IsPlaying)
check("second open is ignored", animator.openLid() == false and openTrack.__plays == 1)
openTrack:GetMarkerReachedSignal("Hold"):Fire()
check("hold marker freezes the pose", openTrack.Speed == 0)
check("close stops open and plays close", animator.closeLid() and not openTrack.IsPlaying and closeTrack.IsPlaying)
check("attribute mirrors the state", chest:GetAttribute("IsOpen") == false and not animator.isOpen())

local bare = Instance.new("Model")
check("missing animation id is reported", not pcall(item.new, bare))
```
