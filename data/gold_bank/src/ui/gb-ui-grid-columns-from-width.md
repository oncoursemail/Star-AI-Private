---
id: gb-ui-grid-columns-from-width
category: ui-layout
topics: UIGridLayout, CellSize, responsive grid, AbsoluteSize, inventory
source: original
---
# Request
My inventory uses a UIGridLayout with a fixed CellSize of 100x100. On wide screens there's a big empty strip on the right, and on phones only two cells fit. I want as many columns as fit, with cells stretching to use the full width. How do I compute that?

# Answer
Pick the column count from the container's real width, a minimum cell size and the gap, then divide the remaining width evenly. Keep the math in a pure function and re-run it when the container's AbsoluteSize changes.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.ResponsiveGrid
local ResponsiveGrid = {}

export type Fit = { columns: number, cell: number }

function ResponsiveGrid.fit(width: number, minCell: number, gap: number, maxColumns: number?): Fit
	assert(minCell > 0 and gap >= 0, "invalid grid sizes")
	local columns = math.max(1, math.floor((width + gap) / (minCell + gap)))
	if maxColumns then
		columns = math.min(columns, maxColumns)
	end
	local cell = math.floor((width - gap * (columns - 1)) / columns)
	return { columns = columns, cell = math.max(cell, 0) }
end

function ResponsiveGrid.attach(container: GuiObject, grid: UIGridLayout, minCell: number, gap: number): RBXScriptConnection
	grid.CellPadding = UDim2.fromOffset(gap, gap)
	grid.FillDirectionMaxCells = 0
	local function update()
		local width: number = container.AbsoluteSize.X
		local fit = ResponsiveGrid.fit(width, minCell, gap)
		grid.CellSize = UDim2.fromOffset(fit.cell, fit.cell)
	end
	update()
	return container:GetPropertyChangedSignal("AbsoluteSize"):Connect(update)
end

return ResponsiveGrid
```

- `(width + gap) / (minCell + gap)` counts one gap fewer than cells, which is how the layout actually places them.
- Flooring the cell size avoids half-pixel cells that blur borders and icons.
- If the container is a ScrollingFrame with a vertical scrollbar, subtract `ScrollBarThickness` from the width first.
- Return value is the connection so the caller can disconnect it when the menu is destroyed.

# Test
```lua
local fit = item.fit(400, 80, 8)
check("columns that fit", fit.columns == 4)
check("cells stretch to fill", fit.cell == 94)
check("narrow container still gets one column", item.fit(50, 80, 8).columns == 1)
check("column cap", item.fit(2000, 80, 8, 6).columns == 6)
local frame = Instance.new("Frame")
frame.AbsoluteSize = Vector2.new(400, 300)
local grid = Instance.new("UIGridLayout")
grid.Parent = frame
local conn = item.attach(frame, grid, 80, 8)
check("applied on attach", grid.CellSize.X.Offset == 94)
frame.AbsoluteSize = Vector2.new(800, 300)
check("recomputed on resize", grid.CellSize.X.Offset == math.floor((800 - 8 * 8) / 9))
conn:Disconnect()
```
