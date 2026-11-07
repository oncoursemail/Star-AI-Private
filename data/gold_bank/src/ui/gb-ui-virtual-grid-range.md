---
id: gb-ui-virtual-grid-range
category: ui-overflow
topics: virtualised grid, inventory, visible range, rows and columns, index math
source: original
---
# Request
My pet inventory is a grid that can hold 3,000 pets. I want to only create cells for the rows that are on screen. Given the scroll position, how do I work out which pet indices are visible in a grid with several columns?

# Answer
Work in rows: the first visible row comes from the scroll offset divided by the row pitch (cell height plus gap), the number of rows from the viewport height, then convert rows to item indices with the column count. Add an overscan row on each side so fast scrolling does not show gaps, and clamp to the item count.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.GridWindow
local GridWindow = {}

export type Window = { first: number, last: number, canvasHeight: number }

function GridWindow.compute(scrollY: number, viewportHeight: number, cell: number, gap: number, columns: number,
	count: number, overscanRows: number?): Window
	assert(cell > 0 and columns >= 1, "invalid grid")
	local pitch = cell + gap
	local rows = math.ceil(count / columns)
	local canvasHeight = if rows > 0 then rows * pitch - gap else 0
	if count == 0 then
		return { first = 1, last = 0, canvasHeight = 0 }
	end
	local extra = overscanRows or 1
	local firstRow = math.max(0, math.floor(math.max(scrollY, 0) / pitch) - extra)
	local lastRow = math.min(rows - 1, math.floor((math.max(scrollY, 0) + viewportHeight) / pitch) + extra)
	return {
		first = firstRow * columns + 1,
		last = math.min(count, (lastRow + 1) * columns),
		canvasHeight = canvasHeight,
	}
end

-- Pixel position of item `index` (1-based) inside the canvas.
function GridWindow.cellPosition(index: number, cell: number, gap: number, columns: number): (number, number)
	local zero = index - 1
	local col = zero % columns
	local row = zero // columns
	return col * (cell + gap), row * (cell + gap)
end

return GridWindow
```

- The canvas height subtracts the last gap so the grid ends flush with its final row.
- Feed `first..last` to a pool of cells like a virtual list, positioning each with `cellPosition` instead of a UIGridLayout.
- Negative scroll values (elastic overscroll on touch) are clamped, so the window never starts before index 1.

# Test
```lua
local w = item.compute(0, 400, 90, 10, 5, 3000)
check("top of the grid", w.first == 1 and w.last == 30)
check("canvas fits all rows", w.canvasHeight == 600 * 100 - 10)
w = item.compute(1000, 400, 90, 10, 5, 3000)
check("scrolled window starts one row early", w.first == 9 * 5 + 1 and w.last == 16 * 5)
w = item.compute(59600, 400, 90, 10, 5, 3000)
check("clamped at the end", w.last == 3000)
check("empty grid", item.compute(0, 400, 90, 10, 5, 0).last == 0)
local x, y = item.cellPosition(7, 90, 10, 5)
check("cell position from index", x == 100 and y == 100)
check("elastic overscroll clamped", item.compute(-50, 400, 90, 10, 5, 3000).first == 1)
```
