---
id: gb-eng-easing-library
category: engineering-algorithm
topics: easing functions, interpolation, custom tween, camera, lerp
source: original
---
# Request
I animate a camera rig and some UI numbers manually every frame (TweenService doesn't fit because the target keeps moving). I need easing functions like quad/cubic in-out, back-out and elastic-out, plus a helper that maps elapsed time to an eased alpha. Can you write them?

# Answer
Each easing maps `t` in [0, 1] to an eased alpha with `f(0) = 0` and `f(1) = 1`. A small `progress` helper clamps elapsed/duration so callers never overshoot the end, and `lerp` applies the alpha to numbers.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Easing
export type EasingFn = (t: number) -> number

local Easing = {}

function Easing.linear(t: number): number
	return t
end

function Easing.quadInOut(t: number): number
	return if t < 0.5 then 2 * t * t else 1 - (-2 * t + 2) ^ 2 / 2
end

function Easing.cubicOut(t: number): number
	return 1 - (1 - t) ^ 3
end

function Easing.cubicInOut(t: number): number
	return if t < 0.5 then 4 * t * t * t else 1 - (-2 * t + 2) ^ 3 / 2
end

function Easing.backOut(t: number): number
	local c1 = 1.70158
	local c3 = c1 + 1
	return 1 + c3 * (t - 1) ^ 3 + c1 * (t - 1) ^ 2
end

function Easing.elasticOut(t: number): number
	if t <= 0 or t >= 1 then
		return math.clamp(t, 0, 1)
	end
	return 2 ^ (-10 * t) * math.sin((t * 10 - 0.75) * (2 * math.pi) / 3) + 1
end

function Easing.progress(elapsed: number, duration: number, ease: EasingFn): number
	if duration <= 0 then
		return 1
	end
	return ease(math.clamp(elapsed / duration, 0, 1))
end

function Easing.lerp(a: number, b: number, alpha: number): number
	return a + (b - a) * alpha
end

return Easing
```

- `backOut` and `elasticOut` overshoot past 1 mid-animation by design; that is fine for positions and scale, but clamp before using the alpha for transparency or a progress bar.
- For a moving target, store the start value and start time when the move begins and compute `Easing.lerp(start, target, Easing.progress(now - startTime, 0.4, Easing.cubicOut))` each frame; for CFrames use `start:Lerp(goal, alpha)`.
- `progress` with a zero duration returns 1, so an instant transition snaps to the end instead of dividing by zero.

# Test
```lua
local names = { "linear", "quadInOut", "cubicOut", "cubicInOut", "backOut", "elasticOut" }
local endpoints = true
for _, name in names do
	local f = item[name]
	if math.abs(f(0)) > 1e-9 or math.abs(f(1) - 1) > 1e-9 then
		endpoints = false
	end
end
check("all easings start at 0 and end at 1", endpoints)
check("in-out symmetric at half", math.abs(item.quadInOut(0.5) - 0.5) < 1e-9 and math.abs(item.cubicInOut(0.5) - 0.5) < 1e-9)
check("cubicOut is ahead of linear", item.cubicOut(0.3) > 0.3)
local overshoot = 0
for i = 1, 99 do
	overshoot = math.max(overshoot, item.backOut(i / 100))
end
check("backOut overshoots", overshoot > 1.05)
check("progress clamps", item.progress(5, 2, item.linear) == 1 and item.progress(-1, 2, item.linear) == 0)
check("zero duration snaps", item.progress(0, 0, item.cubicOut) == 1)
check("lerp", item.lerp(10, 20, item.progress(1, 4, item.linear)) == 12.5)
```
