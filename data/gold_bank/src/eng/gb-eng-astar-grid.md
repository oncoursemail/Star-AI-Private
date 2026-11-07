---
id: gb-eng-astar-grid
category: engineering-algorithm
topics: A*, pathfinding, grid, binary heap, tower defense
source: original
---
# Request
For my tower-defense map I need my own pathfinding on a 2D grid (PathfindingService doesn't respect the tiles players build on). Can you write A* for a grid of walkable/blocked cells with 4-way movement that returns the list of cells?

# Answer
A* with a Manhattan heuristic (admissible for 4-way moves), a small binary heap as the open set, and a closed flag per cell. Cells are packed into one integer key so lookups are flat table reads.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.GridAStar
export type Cell = { x: number, y: number }
export type Grid = { width: number, height: number, blocked: { [number]: boolean } }

local GridAStar = {}

local function key(grid: Grid, x: number, y: number): number
	return y * grid.width + x
end

local DIRECTIONS = { { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 } }

function GridAStar.findPath(grid: Grid, start: Cell, goal: Cell): { Cell }?
	local startKey, goalKey = key(grid, start.x, start.y), key(grid, goal.x, goal.y)
	if grid.blocked[startKey] or grid.blocked[goalKey] then
		return nil
	end
	local function h(x: number, y: number): number
		return math.abs(x - goal.x) + math.abs(y - goal.y)
	end

	-- open set: binary min-heap of keys ordered by f = g + h
	local heap: { number } = {}
	local f: { [number]: number } = {}
	local g: { [number]: number } = { [startKey] = 0 }
	local cameFrom: { [number]: number } = {}
	local closed: { [number]: boolean } = {}

	local function push(k: number)
		table.insert(heap, k)
		local i = #heap
		while i > 1 do
			local parent = i // 2
			if f[heap[parent]] <= f[heap[i]] then
				break
			end
			heap[parent], heap[i] = heap[i], heap[parent]
			i = parent
		end
	end

	local function pop(): number
		local top = heap[1]
		local last = heap[#heap]
		heap[#heap] = nil
		if #heap > 0 then
			heap[1] = last
			local i, n = 1, #heap
			while i * 2 <= n do
				local l, r, smallest = i * 2, i * 2 + 1, i
				if f[heap[l]] < f[heap[smallest]] then
					smallest = l
				end
				if r <= n and f[heap[r]] < f[heap[smallest]] then
					smallest = r
				end
				if smallest == i then
					break
				end
				heap[smallest], heap[i] = heap[i], heap[smallest]
				i = smallest
			end
		end
		return top
	end

	f[startKey] = h(start.x, start.y)
	push(startKey)
	while #heap > 0 do
		local current = pop()
		if current == goalKey then
			local path: { Cell } = {}
			local k: number? = current
			while k do
				table.insert(path, 1, { x = k % grid.width, y = k // grid.width })
				k = cameFrom[k]
			end
			return path
		end
		if closed[current] then
			continue -- stale heap entry from an earlier, worse g
		end
		closed[current] = true
		local cx, cy = current % grid.width, current // grid.width
		for _, d in DIRECTIONS do
			local nx, ny = cx + d[1], cy + d[2]
			if nx < 0 or ny < 0 or nx >= grid.width or ny >= grid.height then
				continue
			end
			local nk = key(grid, nx, ny)
			if grid.blocked[nk] or closed[nk] then
				continue
			end
			local tentative = g[current] + 1
			if g[nk] == nil or tentative < g[nk] then
				g[nk] = tentative
				f[nk] = tentative + h(nx, ny)
				cameFrom[nk] = current
				push(nk)
			end
		end
	end
	return nil
end

return GridAStar
```

- Re-pushing a cell when a shorter route is found and skipping already-closed cells on pop is simpler than a decrease-key heap and gives the same result.
- Manhattan distance never overestimates for 4-way movement, so the first time the goal is popped the path is shortest. For 8-way movement switch to octile distance.
- Re-run it only when a tower is placed or removed and cache the path; enemies then follow the cached cells. Before allowing a placement, run it with the new cell blocked and reject the tower if it returns nil.

# Test
```lua
local grid = { width = 5, height = 5, blocked = {} }
local function block(x, y)
	grid.blocked[y * 5 + x] = true
end
local open = item.findPath(grid, { x = 0, y = 0 }, { x = 4, y = 4 })
check("open grid shortest path", open ~= nil and #open == 9)
check("path endpoints", open[1].x == 0 and open[1].y == 0 and open[#open].x == 4 and open[#open].y == 4)
for y = 0, 3 do
	block(2, y)
end
local around = item.findPath(grid, { x = 0, y = 0 }, { x = 4, y = 0 })
check("detours around wall", around ~= nil and #around == 13)
local valid = true
for i = 2, #around do
	local dx, dy = math.abs(around[i].x - around[i - 1].x), math.abs(around[i].y - around[i - 1].y)
	if dx + dy ~= 1 or grid.blocked[around[i].y * 5 + around[i].x] then
		valid = false
	end
end
check("steps are adjacent and walkable", valid)
block(2, 4)
check("fully walled returns nil", item.findPath(grid, { x = 0, y = 0 }, { x = 4, y = 0 }) == nil)
check("blocked goal returns nil", item.findPath(grid, { x = 0, y = 0 }, { x = 2, y = 2 }) == nil)
```
