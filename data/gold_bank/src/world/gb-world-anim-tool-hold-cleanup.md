---
id: gb-world-anim-tool-hold-cleanup
category: animation
topics: Tool, Equipped, Unequipped, Died, looping animation, cleanup
source: original
---
# Request
My gun has a looping hold animation. If I unequip it fast or die while holding it, sometimes the pose stays stuck on my character. Here's what I have:

```lua
tool.Equipped:Connect(function()
	local hum = tool.Parent:FindFirstChild("Humanoid")
	hum:LoadAnimation(script.Hold):Play()
end)
```

# Answer
The track is never stored, so nothing can stop it, and every equip loads another one. Keep the current track, stop it on Unequipped, on Humanoid.Died and when the tool is destroyed, and load through the Animator. Per-equip connections (the Died hook) are released together with the track.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.ToolHoldPose
local ToolHoldPose = {}

function ToolHoldPose.bind(tool: Tool, holdAnimation: Animation): () -> ()
	local track: AnimationTrack? = nil
	local diedConnection: RBXScriptConnection? = nil

	local function release()
		if diedConnection then
			diedConnection:Disconnect()
			diedConnection = nil
		end
		if track then
			track:Stop(0.15)
			track:Destroy()
			track = nil
		end
	end

	local function onEquipped()
		release()
		local character = tool.Parent
		local humanoid = if character then character:FindFirstChildOfClass("Humanoid") else nil
		if humanoid == nil or humanoid.Health <= 0 then
			return
		end
		local animator = humanoid:FindFirstChildOfClass("Animator")
		if animator == nil then
			return
		end
		local newTrack = animator:LoadAnimation(holdAnimation)
		newTrack.Priority = Enum.AnimationPriority.Action
		newTrack.Looped = true
		newTrack:Play(0.15)
		track = newTrack
		diedConnection = humanoid.Died:Connect(release)
	end

	local connections = {
		tool.Equipped:Connect(onEquipped),
		tool.Unequipped:Connect(release),
		tool.Destroying:Connect(release),
	}

	return function()
		release()
		for _, connection in connections do
			connection:Disconnect()
		end
	end
end

return ToolHoldPose
```

In the tool's LocalScript: `ToolHoldPose.bind(script.Parent, script:WaitForChild("Hold"))`.

- `Humanoid:LoadAnimation` is deprecated; load through the Animator under the Humanoid. Tracks the local player plays on their own character this way still replicate to everyone.
- `Looped = true` in code means the pose keeps holding even if the animation asset was exported without looping.
- Destroying the track on release keeps re-equips from piling up tracks on the Animator.
- Action priority overrides idle and walk on the joints the hold animation keys, so leave the legs unkeyed if you want walking to show.

# Test
```lua
local player = __makePlayer(4, "Gunner")
local character = __makeCharacter(player)
local animator = character.Humanoid.Animator
local tool = Instance.new("Tool")
local hold = Instance.new("Animation")
local unbind = item.bind(tool, hold)

tool.Parent = character
tool.Equipped:Fire()
check("hold pose plays on equip", #animator:GetPlayingAnimationTracks() == 1)
tool.Unequipped:Fire()
check("pose stops on unequip", #animator:GetPlayingAnimationTracks() == 0)
tool.Equipped:Fire()
tool.Equipped:Fire()
check("re-equip keeps a single playing track", #animator:GetPlayingAnimationTracks() == 1)
character.Humanoid.Health = 0
check("pose stops on death", #animator:GetPlayingAnimationTracks() == 0)
tool.Equipped:Fire()
check("no pose while dead", #animator:GetPlayingAnimationTracks() == 0)
unbind()
character.Humanoid.Health = 100
tool.Equipped:Fire()
check("unbind disconnects everything", #animator:GetPlayingAnimationTracks() == 0)
```
