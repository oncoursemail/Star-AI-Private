---
id: gb-eng-perf-fidelity-audit
category: performance
topics: CollisionFidelity, RenderFidelity, MeshPart, CanQuery, physics cost
source: original
---
# Request
My map has ~3000 decorative MeshParts (rocks, plants, props) and physics/memory stats are high even though players can't touch most of them. Which collision and render settings should these use, and can I fix them all at once instead of clicking each one?

# Answer
Decorative meshes that nothing collides with should not be collidable, queryable or touchable, and need only the cheapest collision geometry: `CanCollide`, `CanQuery` and `CanTouch` false and `CollisionFidelity` `Box`. Background props that players never inspect up close can use `RenderFidelity` `Performance`. `CollisionFidelity` and `RenderFidelity` cannot be changed by game scripts at runtime, so run this once from the Studio command bar (or a plugin) on the folder of props, then save the place.

```lua
--!strict
-- ModuleScript: ServerStorage.Tools.PropOptimizer (run from the command bar in Studio:
--   require(game:GetService("ServerStorage").Tools.PropOptimizer).apply(workspace.Props, false))
export type Report = { scanned: number, changed: number, skippedCollidable: number }

local PropOptimizer = {}

function PropOptimizer.apply(root: Instance, dryRun: boolean): Report
	local report: Report = { scanned = 0, changed = 0, skippedCollidable = 0 }
	for _, part in root:GetDescendants() do
		if not part:IsA("MeshPart") then
			continue
		end
		report.scanned += 1
		if part:GetAttribute("KeepCollision") == true then
			report.skippedCollidable += 1
			continue -- props players stand on or that block bullets keep their settings
		end
		local needsChange = part.CanCollide or part.CanQuery or part.CanTouch
			or part.CollisionFidelity ~= Enum.CollisionFidelity.Box
			or part.RenderFidelity ~= Enum.RenderFidelity.Performance
		if needsChange then
			report.changed += 1
			if not dryRun then
				part.CanCollide = false
				part.CanQuery = false
				part.CanTouch = false
				part.CollisionFidelity = Enum.CollisionFidelity.Box
				part.RenderFidelity = Enum.RenderFidelity.Performance
			end
		end
	end
	return report
end

return PropOptimizer
```

- Run with `dryRun = true` first to see how many parts would change; mark exceptions (a rock players climb) with a `KeepCollision` attribute.
- `CanQuery = false` also removes the part from raycasts and spatial queries, which speeds up every gun and placement check in the game; leave it on for anything bullets should hit.
- `RenderFidelity.Performance` always renders the lowest-detail version of the mesh; keep `Automatic` (detail drops only with distance) on hero props players see up close, which you can also mark with the attribute.
- Anchor static props as well: unanchored decoration costs physics simulation even when it never moves.

# Test
```lua
local props = Instance.new("Folder")
props.Parent = workspace
local function mesh(keep)
	local m = Instance.new("MeshPart")
	m.CanCollide = true
	m.CanQuery = true
	m.CanTouch = true
	m.CollisionFidelity = Enum.CollisionFidelity.PreciseConvexDecomposition
	m.RenderFidelity = Enum.RenderFidelity.Precise
	if keep then
		m:SetAttribute("KeepCollision", true)
	end
	m.Parent = props
	return m
end
local rock = mesh(false)
local climbable = mesh(true)
local plain = Instance.new("Part")
plain.Parent = props
local dry = item.apply(props, true)
check("dry run counts without changing", dry.scanned == 2 and dry.changed == 1 and rock.CanCollide == true)
local real = item.apply(props, false)
check("decorative mesh optimised", rock.CanCollide == false and rock.CanQuery == false and rock.CollisionFidelity == Enum.CollisionFidelity.Box and rock.RenderFidelity == Enum.RenderFidelity.Performance)
check("marked prop untouched", climbable.CanCollide == true and real.skippedCollidable == 1)
check("second run finds nothing to change", item.apply(props, false).changed == 0)
```
