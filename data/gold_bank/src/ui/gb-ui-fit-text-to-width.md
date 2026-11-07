---
id: gb-ui-fit-text-to-width
category: ui-text
topics: TextService, GetTextSize, fit text, never overflow, binary search
source: original
---
# Request
My item name labels have a fixed width and must never overflow or wrap, but TextScaled makes short names giant. I want: use the normal size if it fits, otherwise shrink step by step down to a minimum, and only then cut with "...". How?

# Answer
Measure the text at a candidate size with `TextService:GetTextSize` and binary-search the largest integer size between min and max that fits the label's width. If even the minimum does not fit, set the minimum and turn on truncation. The measuring function is injectable so the fitting logic can be tested on its own.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.FitText
local TextService = game:GetService("TextService")

local FitText = {}

export type Measure = (text: string, size: number) -> number

function FitText.largestSize(text: string, width: number, minSize: number, maxSize: number, measure: Measure): number?
	if measure(text, minSize) > width then
		return nil
	end
	local lo, hi = minSize, maxSize
	while lo < hi do
		local mid = (lo + hi + 1) // 2
		if measure(text, mid) <= width then
			lo = mid
		else
			hi = mid - 1
		end
	end
	return lo
end

function FitText.apply(label: TextLabel, minSize: number, maxSize: number, measure: Measure?)
	local width: number = label.AbsoluteSize.X
	local font = label.Font
	local measureWith: Measure = measure or function(text: string, size: number): number
		local bounds: Vector2 = TextService:GetTextSize(text, size, font, Vector2.new(math.huge, math.huge))
		return bounds.X
	end
	local size = FitText.largestSize(label.Text, width, minSize, maxSize, measureWith)
	label.TextScaled = false
	label.TextWrapped = false
	label.TextSize = size or minSize
	label.TextTruncate = if size then Enum.TextTruncate.None else Enum.TextTruncate.AtEnd
end

return FitText
```

- Binary search needs only about four measurements for a 10 to 24 range, so it is cheap enough to run when the text changes.
- Re-run `apply` when the label's AbsoluteSize changes, since the width is what decides the size.
- Rich text and FontFace-only fonts measure differently; for those use `TextService:GetTextBoundsAsync` with GetTextBoundsParams in the measure function.

# Test
```lua
local function measure(text, size)
	return #text * size * 0.5
end
check("normal size kept when it fits", item.largestSize("Axe", 200, 10, 24, measure) == 24)
check("shrinks to the largest fitting size", item.largestSize("Purchase", 70, 10, 24, measure) == 17)
check("nil when even the minimum overflows", item.largestSize("A very long legendary item name", 60, 10, 24, measure) == nil)
local label = Instance.new("TextLabel")
label.AbsoluteSize = Vector2.new(70, 20)
label.Text = "Purchase"
item.apply(label, 10, 24, measure)
check("applied size fits without truncation", label.TextSize == 17 and label.TextTruncate == Enum.TextTruncate.None)
label.Text = "A very long legendary item name"
item.apply(label, 10, 24, measure)
check("falls back to minimum plus ellipsis", label.TextSize == 10 and label.TextTruncate == Enum.TextTruncate.AtEnd)
check("scaling and wrapping off", label.TextScaled == false and label.TextWrapped == false)
```
