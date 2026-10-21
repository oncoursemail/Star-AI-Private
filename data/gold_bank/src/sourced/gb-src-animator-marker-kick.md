---
id: gb-src-animator-marker-kick
category: animation
topics: Animator, LoadAnimation, AnimationTrack, GetMarkerReachedSignal, animation events, AnimationController
source: adapted
source_id: creator-docs
source_path: content/en-us/animation/using.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
I have a kick animation with an animation event marker called "KickImpact". I want to play it on the local player's character when they press F, and run some code exactly when the foot connects. I've seen `Humanoid:LoadAnimation` in old tutorials; what's the current way?

# Answer
Load the animation through the `Animator` inside the Humanoid (or inside an `AnimationController` for non-humanoid rigs), keep the track instead of reloading it each press, and connect to `GetMarkerReachedSignal("KickImpact")` for the hit moment. Take the animation id as a parameter.

```lua
--!strict
local KickController = {}

export type Kick = {
	tryPlay: () -> boolean,
	destroy: () -> (),
}

function KickController.new(character: Model, animationId: string, onImpact: (param: string) -> ()): Kick
	local humanoid = character:FindFirstChildOfClass("Humanoid")
	local animator = if humanoid then humanoid:FindFirstChildOfClass("Animator") else nil
	assert(animator, "character needs a Humanoid with an Animator")

	local animation = Instance.new("Animation")
	animation.AnimationId = animationId
	local track = animator:LoadAnimation(animation)
	track.Priority = Enum.AnimationPriority.Action

	local markerConnection = track:GetMarkerReachedSignal("KickImpact"):Connect(onImpact)

	local function tryPlay(): boolean
		if track.IsPlaying then
			return false
		end
		track:Play(0.1)
		return true
	end

	local function destroy()
		markerConnection:Disconnect()
		track:Stop(0)
		track:Destroy()
		animation:Destroy()
	end

	return { tryPlay = tryPlay, destroy = destroy }
end

return KickController
```

LocalScript usage:

```lua
--!strict
local ContextActionService = game:GetService("ContextActionService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local KickController = require(ReplicatedStorage:WaitForChild("KickController"))

local KICK_ANIMATION_ID = ReplicatedStorage:GetAttribute("KickAnimationId")

local player = Players.LocalPlayer

local function onCharacterAdded(character: Model)
	character:WaitForChild("Humanoid"):WaitForChild("Animator")
	local kick = KickController.new(character, KICK_ANIMATION_ID, function()
		ReplicatedStorage.KickHit:FireServer()
	end)
	ContextActionService:BindAction("Kick", function(_, state: Enum.UserInputState)
		if state == Enum.UserInputState.Begin then
			kick.tryPlay()
		end
		return Enum.ContextActionResult.Sink
	end, true, Enum.KeyCode.F)
	player.CharacterRemoving:Once(function()
		ContextActionService:UnbindAction("Kick")
		kick.destroy()
	end)
end

player.CharacterAdded:Connect(onCharacterAdded)
if player.Character then
	onCharacterAdded(player.Character)
end
```

- Animations played on the local player's character through its Animator replicate to other players automatically.
- The marker name must match the event name set in the Animation Editor exactly; the callback receives the event's parameter string.
- The binding and track are released in `CharacterRemoving`, so pressing F between death and respawn never touches a destroyed track.
- The server should treat `KickHit` as a request: check cooldown and distance before applying damage.

# Test
```lua
local p = __makePlayer(1, "Kicker")
local character = __makeCharacter(p)
local impacts = {}
local kick = item.new(character, "rbxassetid://1234", function(param)
	table.insert(impacts, param)
end)
check("first play starts", kick.tryPlay() == true)
check("no restart while playing", kick.tryPlay() == false)
local animator = character.Humanoid.Animator
local track = animator:GetPlayingAnimationTracks()[1]
check("track uses the given id", track ~= nil and track.Animation.AnimationId == "rbxassetid://1234")
track:GetMarkerReachedSignal("KickImpact"):Fire("right")
check("impact callback receives the marker parameter", impacts[1] == "right")
kick.destroy()
check("track stopped on destroy", track.IsPlaying == false)
```
