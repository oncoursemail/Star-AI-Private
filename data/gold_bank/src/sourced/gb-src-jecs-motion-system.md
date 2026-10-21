---
id: gb-src-jecs-motion-system
category: performance
topics: jecs, ECS, components, tags, queries, without, systems, entity deletion
source: adapted
source_id: jecs
source_path: how_to/020_queries.luau
source_commit: 9bbb8bae4785138675ad8d131a0647b94dc01c18
---
# Request
I simulate thousands of cosmetic projectiles (sparks, shells) and I'm trying jecs. How do I write a system that moves every entity with Position and Velocity, removes entities whose Lifetime ran out, and skips entities tagged Frozen (paused by a time-stop ability)?

# Answer
Create the components and a `Frozen` tag on the world, then write the system as a function that queries `(Position, Velocity, Lifetime)` and excludes `Frozen` with `:without`. Collect expired entities during the loop and delete them after it, so the query is not modified while it iterates.

```lua
--!strict
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local jecs = require(ReplicatedStorage:WaitForChild("Packages"):WaitForChild("jecs"))

local world = jecs.world()
local Position = world:component()
local Velocity = world:component()
local Lifetime = world:component()
local Frozen = world:entity()

local function motionSystem(dt: number)
	local expired = {}
	for entity, position, velocity, lifetime in world:query(Position, Velocity, Lifetime):without(Frozen) do
		local remaining = lifetime - dt
		if remaining <= 0 then
			table.insert(expired, entity)
		else
			world:set(entity, Position, position + velocity * dt)
			world:set(entity, Lifetime, remaining)
		end
	end
	for _, entity in expired do
		world:delete(entity)
	end
end

local function spawnSpark(position: Vector3, velocity: Vector3, seconds: number)
	local spark = world:entity()
	world:set(spark, Position, position)
	world:set(spark, Velocity, velocity)
	world:set(spark, Lifetime, seconds)
	return spark
end

return {
	world = world,
	components = { Position = Position, Velocity = Velocity, Lifetime = Lifetime, Frozen = Frozen },
	motionSystem = motionSystem,
	spawnSpark = spawnSpark,
}
```

Run it from one loop: `RunService.Heartbeat:Connect(motionSystem)`, and freeze an entity with `world:add(spark, Frozen)`.

- Queries walk only archetypes that have all three components, so unrelated entities cost nothing here.
- `Frozen` is a tag (no data); `:without(Frozen)` skips paused entities with no `if` in the loop.
- Deleting after the loop avoids changing archetypes while the query is iterating them.
- In your own code, type components with `world:component() :: jecs.Id<Vector3>` so `world:set` checks the value type; draw the sparks in a separate render system that reads `Position`.
