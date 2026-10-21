---
id: gb-world-build-maze-generator
category: building-layout
topics: maze generation, backtracker, Random seed, procedural walls, parts
source: original
---
# Request
I want a new maze every round. Can you write a maze generator that is seeded (so all servers in a tournament can get the same maze), always solvable, and then builds the walls as parts? My recursive version crashes with stack overflow on big mazes.

# Answer
Use the depth-first "backtracker" with an explicit stack instead of recursion, so maze size is limited only by memory. It produces a perfect maze (exactly one path between any two cells), which guarantees it is solvable. The generator returns plain data; a separate builder turns closed edges into wall parts.

```lua
--!strict
-- ModuleScript: ServerScriptService.MazeGenerator
export type Maze = {
	width: number,
	height: number,
	openEast: { { boolean } },
	openSouth: { { boolean } },
}

local MazeGenerator = {}

function MazeGenerator.generate(width: number, height: number, seed: number): Maze
	local random = Random.new(seed)
	local openEast: { { boolean } } = {}
	local openSouth: { { boolean } } = {}
	local visited: { { boolean } } = {}
	for x = 1, width do
		openEast[x], openSouth[x], visited[x] = {}, {}, {}
		for y = 1, height do
			openEast[x][y], openSouth[x][y], visited[x][y] = false, false, false
		end
	end

	local stack: { { number } } = { { 1, 1 } }
	visited[1][1] = true
	while #stack > 0 do
		local cell = stack[#stack]
		local x, y = cell[1], cell[2]
		local options: { { number } } = {}
		for _, step in { { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 } } do
			local nx, ny = x + step[1], y + step[2]
			if nx >= 1 and nx <= width and ny >= 1 and ny <= height and not visited[nx][ny] then
				table.insert(options, { nx, ny })
			end
		end
		if #options == 0 then
			table.remove(stack)
		else
			local nextCell = options[random:NextInteger(1, #options)]
			local nx, ny = nextCell[1], nextCell[2]
			-- Open the shared edge; it is stored on the west/north cell of the pair.
			if nx ~= x then
				openEast[math.min(x, nx)][y] = true
			else
				openSouth[x][math.min(y, ny)] = true
			end
			visited[nx][ny] = true
			table.insert(stack, nextCell)
		end
	end
	return { width = width, height = height, openEast = openEast, openSouth = openSouth }
end

function MazeGenerator.build(maze: Maze, origin: CFrame, cellSize: number, wallHeight: number, parent: Instance): Model
	local model = Instance.new("Model")
	model.Name = "Maze"
	local thickness = 1
	local function wall(centerX: number, centerZ: number, sizeX: number, sizeZ: number)
		local part = Instance.new("Part")
		part.Anchored = true
		part.Size = Vector3.new(sizeX, wallHeight, sizeZ)
		part.CFrame = origin:ToWorldSpace(CFrame.new(centerX, wallHeight / 2, centerZ))
		part.Parent = model
	end
	for x = 1, maze.width do
		wall((x - 0.5) * cellSize, 0, cellSize + thickness, thickness)
		for y = 1, maze.height do
			if x == 1 then
				wall(0, (y - 0.5) * cellSize, thickness, cellSize + thickness)
			end
			if not maze.openEast[x][y] then
				wall(x * cellSize, (y - 0.5) * cellSize, thickness, cellSize + thickness)
			end
			if not maze.openSouth[x][y] then
				wall((x - 0.5) * cellSize, y * cellSize, cellSize + thickness, thickness)
			end
		end
	end
	model.Parent = parent
	return model
end

return MazeGenerator
```

- `Random.new(seed)` gives the same sequence everywhere, so one seed shared through MessagingService or a reserved server's data reproduces the exact maze.
- A perfect maze on W x H cells always has exactly W*H - 1 open passages, which is an easy invariant to assert in tests.
- One part per wall segment is simple; for very large mazes merge runs of consecutive walls into one long part to cut the part count.

# Test
```lua
local maze = item.generate(12, 9, 42)
local open = 0
for x = 1, 12 do
	for y = 1, 9 do
		if maze.openEast[x][y] then open += 1 end
		if maze.openSouth[x][y] then open += 1 end
	end
end
check("perfect maze has cells - 1 passages", open == 12 * 9 - 1)

local seen, queue, reached = { ["1,1"] = true }, { { 1, 1 } }, 1
while #queue > 0 do
	local c = table.remove(queue, 1)
	local x, y = c[1], c[2]
	local moves = {}
	if x < 12 and maze.openEast[x][y] then table.insert(moves, { x + 1, y }) end
	if x > 1 and maze.openEast[x - 1][y] then table.insert(moves, { x - 1, y }) end
	if y < 9 and maze.openSouth[x][y] then table.insert(moves, { x, y + 1 }) end
	if y > 1 and maze.openSouth[x][y - 1] then table.insert(moves, { x, y - 1 }) end
	for _, m in moves do
		local key = m[1] .. "," .. m[2]
		if not seen[key] then
			seen[key] = true
			reached += 1
			table.insert(queue, m)
		end
	end
end
check("every cell is reachable", reached == 12 * 9)
check("border edges stay closed", not maze.openEast[12][5] and not maze.openSouth[3][9])

local again = item.generate(12, 9, 42)
local same = true
for x = 1, 12 do
	for y = 1, 9 do
		if again.openEast[x][y] ~= maze.openEast[x][y] or again.openSouth[x][y] ~= maze.openSouth[x][y] then same = false end
	end
end
check("same seed gives the same maze", same)

local small = item.generate(5, 4, 7)
local built = item.build(small, CFrame.new(), 8, 6, workspace)
check("one wall per closed edge plus the outer border", #built:GetChildren() == (4 * 4 + 5 * 3) - 19 + 2 * 5 + 2 * 4)
check("big maze does not overflow the stack", #item.generate(120, 120, 1).openEast == 120)
```
