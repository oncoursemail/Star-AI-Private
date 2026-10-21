---
id: gb-world-anim-run-speed-sync
category: animation
topics: Humanoid.Running, AdjustSpeed, foot sliding, run animation, WalkSpeed
source: original
---
# Request
I replaced the default run with my own animation and gave sprinting a WalkSpeed of 28, but now the feet slide on the ground when sprinting and moonwalk when moving slowly on a gamepad. How do I make the animation speed follow how fast the character actually moves?

# Answer
Scale the track's playback speed by actual speed divided by the speed the animation was authored for, using `Humanoid.Running` (it reports the real horizontal speed). Clamp the ratio so extreme values do not look broken, and stop the track when the character is basically standing.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.RunSpeedSync
local STOP_BELOW = 0.75

local RunSpeedSync = {}

function RunSpeedSync.playbackRate(speed: number, authoredSpeed: number): number
	return math.clamp(speed / authoredSpeed, 0.4, 2)
end

function RunSpeedSync.attach(humanoid: Humanoid, runTrack: AnimationTrack, authoredSpeed: number): RBXScriptConnection
	assert(authoredSpeed > 0, "authoredSpeed is the studs per second the run cycle was animated at")
	runTrack.Looped = true
	runTrack.Priority = Enum.AnimationPriority.Movement

	return humanoid.Running:Connect(function(speed: number)
		if speed < STOP_BELOW then
			if runTrack.IsPlaying then
				runTrack:Stop(0.2)
			end
			return
		end
		local rate = RunSpeedSync.playbackRate(speed, authoredSpeed)
		if runTrack.IsPlaying then
			runTrack:AdjustSpeed(rate)
		else
			runTrack:Play(0.2, 1, rate)
		end
	end)
end

return RunSpeedSync
```

- Measure `authoredSpeed` once: play the animation in place and count how many studs a foot travels per second of animation; that number is what makes the feet plant.
- `Running` fires on speed changes, not every frame, so this costs nothing while the character runs at a steady speed.
- If you keep the default Animate script, remove its run entry (or disable the script) so two run tracks are not fighting at the same priority.

# Test
```lua
local rig = __buildRig()
local humanoid = rig.Humanoid
local track = humanoid.Animator:LoadAnimation(Instance.new("Animation"))
local connection = item.attach(humanoid, track, 16)

humanoid.Running:Fire(16)
check("authored speed plays at rate 1", track.IsPlaying and track.Speed == 1)
humanoid.Running:Fire(28)
check("sprinting speeds the cycle up", math.abs(track.Speed - 1.75) < 1e-9 and track.__plays == 1)
humanoid.Running:Fire(100)
check("rate is clamped", track.Speed == 2)
humanoid.Running:Fire(0.2)
check("standing stops the run", not track.IsPlaying)
check("bad authored speed is rejected", not pcall(item.attach, humanoid, track, 0))
connection:Disconnect()
```
