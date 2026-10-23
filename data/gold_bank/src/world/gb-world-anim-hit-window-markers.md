---
id: gb-world-anim-hit-window-markers
category: animation
topics: GetMarkerReachedSignal, hit window, NPC attack, Heartbeat, animation events
source: original
---
# Request
My boss NPC damages players the moment its attack starts, long before the axe actually comes down. I added "HitStart" and "HitEnd" markers to the animation in the editor. How do I only check for hits between those two markers?

# Answer
Drive the damage window from the markers instead of from the moment you call `Play`. The module below plays the track, opens a per-frame hit check on "HitStart", closes it on "HitEnd" (or after a safety cap if a marker is missing), and returns a cancel function for when the boss is stunned mid-swing.

```lua
--!strict
-- ModuleScript: ServerScriptService.MarkerSwing
local RunService = game:GetService("RunService")

export type SwingOptions = {
	track: AnimationTrack,
	onActiveFrame: (dt: number) -> (),
	onFinished: (() -> ())?,
	maxActiveSeconds: number?,
}

local MarkerSwing = {}

function MarkerSwing.run(options: SwingOptions): () -> ()
	local track = options.track
	local maxActive = options.maxActiveSeconds or 0.6
	local connections: { RBXScriptConnection } = {}
	local window: RBXScriptConnection? = nil
	local finished = false

	local function closeWindow()
		if window then
			window:Disconnect()
			window = nil
		end
	end

	local function finish()
		if finished then
			return
		end
		finished = true
		closeWindow()
		for _, connection in connections do
			connection:Disconnect()
		end
		table.clear(connections)
		if track.IsPlaying then
			track:Stop(0.1)
		end
		if options.onFinished then
			options.onFinished()
		end
	end

	local function openWindow()
		if window or finished then
			return
		end
		local openedAt = os.clock()
		window = RunService.Heartbeat:Connect(function(dt: number)
			if os.clock() - openedAt > maxActive then
				closeWindow()
				return
			end
			options.onActiveFrame(dt)
		end)
	end

	connections = {
		track:GetMarkerReachedSignal("HitStart"):Connect(openWindow),
		track:GetMarkerReachedSignal("HitEnd"):Connect(closeWindow),
		track.Stopped:Connect(finish),
	}
	track:Play(0.05)
	return finish
end

return MarkerSwing
```

Wiring it to the boss, with the hitbox query of your choice inside `onActiveFrame`:

```lua
--!strict
local MarkerSwing = require(script.Parent.MarkerSwing)

local boss = workspace:WaitForChild("Boss")
local animator = boss:WaitForChild("Humanoid"):WaitForChild("Animator")
local slamTrack = animator:LoadAnimation(boss:WaitForChild("SlamAnimation"))

local function slam()
	local alreadyHit: { [Model]: boolean } = {}
	MarkerSwing.run({
		track = slamTrack,
		onActiveFrame = function()
			local pivot = boss:GetPivot()
			for _, part in workspace:GetPartBoundsInRadius(pivot.Position + pivot.LookVector * 6, 5) do
				local model = part:FindFirstAncestorOfClass("Model")
				local humanoid = if model then model:FindFirstChildOfClass("Humanoid") else nil
				if model and humanoid and model ~= boss and not alreadyHit[model] then
					alreadyHit[model] = true
					humanoid:TakeDamage(35)
				end
			end
		end,
	})
end

slam()
```

- Marker names are case-sensitive and must match the names typed in the Animation Editor exactly.
- The safety cap matters: if an animator renames a marker or the track is cut short, the window still closes instead of dealing damage forever.
- The returned `finish` is the stagger hook: call it when the boss is interrupted and both the window and the track stop together.
- Keep the per-target `alreadyHit` table per swing so one slam damages each player once.

# Test
```lua
local rig = __buildRig(Vector3.new(0, 3, 0))
rig.Parent = workspace
local anim = Instance.new("Animation")
local track = rig.Humanoid.Animator:LoadAnimation(anim)
local frames, done = 0, false
local cancel = item.run({
	track = track,
	onActiveFrame = function()
		frames += 1
	end,
	onFinished = function()
		done = true
	end,
})
__frames(5)
check("no hit frames before HitStart", frames == 0)
track:GetMarkerReachedSignal("HitStart"):Fire()
__frames(6)
check("hit frames run while the window is open", frames == 6)
track:GetMarkerReachedSignal("HitEnd"):Fire()
__frames(4)
check("window closes on HitEnd", frames == 6)
__advance(1)
check("finished when the track stops", done and not track.IsPlaying)

local track2 = rig.Humanoid.Animator:LoadAnimation(anim)
local frames2 = 0
local cancel2 = item.run({ track = track2, maxActiveSeconds = 0.1, onActiveFrame = function()
	frames2 += 1
end })
track2:GetMarkerReachedSignal("HitStart"):Fire()
__frames(30)
check("safety cap closes a window with no HitEnd", frames2 > 0 and frames2 <= 7)
cancel2()
check("cancel stops the track", not track2.IsPlaying)
cancel()
```
