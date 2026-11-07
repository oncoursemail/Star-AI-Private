---
id: gb-ui-health-bar-damage-trail
category: ui-style
topics: health bar, HealthChanged, damage trail, TweenService, colour thresholds
source: original
---
# Request
I want a health bar like in fighting games: the green fill drops instantly when you take damage, and a lighter "damage" bar behind it catches up a moment later so you can see how much you lost. It should also turn red when low. Can you build it hooked to the Humanoid?

# Answer
Use two bars in a track: the fill snaps to the new fraction, the trail tweens to it after a short delay. Healing moves both up at once, so only losses leave a trail. Colour comes from the fraction through fixed thresholds, and the whole thing listens to `Humanoid.HealthChanged`.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.HealthBar
local TweenService = game:GetService("TweenService")

local HealthBar = {}

local TRAIL_INFO = TweenInfo.new(0.35, Enum.EasingStyle.Quad, Enum.EasingDirection.Out, 0, false, 0.25)

function HealthBar.colorFor(fraction: number): Color3
	if fraction <= 0.25 then
		return Color3.fromRGB(214, 60, 60)
	elseif fraction <= 0.5 then
		return Color3.fromRGB(230, 170, 50)
	end
	return Color3.fromRGB(70, 190, 100)
end

function HealthBar.build(): (Frame, Frame, Frame)
	local track = Instance.new("Frame")
	track.Name = "HealthBar"
	track.Size = UDim2.fromOffset(240, 18)
	track.BackgroundColor3 = Color3.fromRGB(30, 32, 38)

	local trail = Instance.new("Frame")
	trail.Name = "Trail"
	trail.Size = UDim2.fromScale(1, 1)
	trail.BackgroundColor3 = Color3.fromRGB(240, 230, 220)
	trail.BorderSizePixel = 0
	trail.Parent = track

	local fill = Instance.new("Frame")
	fill.Name = "Fill"
	fill.Size = UDim2.fromScale(1, 1)
	fill.BorderSizePixel = 0
	fill.ZIndex = 2
	fill.Parent = track

	return track, fill, trail
end

function HealthBar.bind(humanoid: Humanoid, fill: Frame, trail: Frame): RBXScriptConnection
	local trailTween: Tween? = nil

	local function update(health: number)
		local maxHealth: number = humanoid.MaxHealth
		local fraction = if maxHealth > 0 then math.clamp(health / maxHealth, 0, 1) else 0
		local previous: number = fill.Size.X.Scale
		fill.Size = UDim2.fromScale(fraction, 1)
		fill.BackgroundColor3 = HealthBar.colorFor(fraction)
		if trailTween then
			trailTween:Cancel()
			trailTween = nil
		end
		if fraction >= previous then
			trail.Size = UDim2.fromScale(fraction, 1)
		else
			local tween = TweenService:Create(trail, TRAIL_INFO, { Size = UDim2.fromScale(fraction, 1) })
			trailTween = tween
			tween:Play()
		end
	end

	update(humanoid.Health)
	return humanoid.HealthChanged:Connect(update)
end

return HealthBar
```

- The trail tween has a 0.25 s delay, so quick successive hits extend one visible chunk instead of jittering.
- `MaxHealth` is read on every update, so the next health change after a buff shows the right fraction; also connect `humanoid:GetPropertyChangedSignal("MaxHealth")` if buffs can change it without a health change.
- Pair the colour with a number (e.g. "45 / 100") somewhere on the HUD so low health is not signalled by colour alone.

# Test
```lua
local player = __makePlayer(1, "Fighter")
local character = __makeCharacter(player)
local humanoid = character.Humanoid
local track, fill, trail = item.build()
local conn = item.bind(humanoid, fill, trail)
check("starts full and green", fill.Size.X.Scale == 1 and fill.BackgroundColor3 == item.colorFor(1))
humanoid:TakeDamage(60)
check("fill drops instantly", math.abs(fill.Size.X.Scale - 0.4) < 1e-9)
check("trail still shows the loss", trail.Size.X.Scale == 1)
__advance(1)
check("trail catches up", math.abs(trail.Size.X.Scale - 0.4) < 1e-9)
check("amber at 40 percent", fill.BackgroundColor3 == Color3.fromRGB(230, 170, 50))
humanoid.Health = 90
check("healing moves both bars at once", math.abs(trail.Size.X.Scale - 0.9) < 1e-9 and math.abs(fill.Size.X.Scale - 0.9) < 1e-9)
check("red when low", item.colorFor(0.2) == Color3.fromRGB(214, 60, 60))
conn:Disconnect()
check("track holds both bars", track.Fill == fill and track.Trail == trail)
```
