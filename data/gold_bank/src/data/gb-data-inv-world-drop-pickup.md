---
id: gb-data-inv-world-drop-pickup
category: server-authoritative-inventory
topics: dropped items, pickup, registry, distance check, despawn
source: original
---
# Request
Players can drop items on the ground and anyone can pick them up. I spawn a part with a StringValue holding the item name, and the client tells the server "I picked up this part". People are duping items by picking the same drop up twice and spawning drops from nothing. How should this work?

# Answer
Every drop gets a server-side registry entry keyed by a GUID: item, count and the world part. Dropping removes the item from the dropper's inventory first; picking up checks the id exists, the player is close, then deletes the registry entry before granting, so the second request finds nothing. Unclaimed drops despawn after a while.

```lua
--!strict
-- ModuleScript: ServerScriptService.WorldDrops
local HttpService = game:GetService("HttpService")

export type Bag = { [string]: number }
type Drop = { itemId: string, count: number, part: BasePart }

local PICKUP_RANGE = 10
local DESPAWN_SECONDS = 60

local drops: { [string]: Drop } = {}
local WorldDrops = {}

local function rootOf(player: Player): BasePart?
	local character = player.Character
	if character == nil then
		return nil
	end
	local root: BasePart? = character:FindFirstChild("HumanoidRootPart")
	return root
end

function WorldDrops.drop(player: Player, bag: Bag, itemId: unknown, countArg: unknown): string?
	local root = rootOf(player)
	if root == nil or type(itemId) ~= "string" or type(countArg) ~= "number" then
		return nil
	end
	local have = bag[itemId] or 0
	if countArg % 1 ~= 0 or countArg < 1 or countArg > have then
		return nil
	end
	bag[itemId] = if have - countArg > 0 then have - countArg else nil

	local id = HttpService:GenerateGUID(false)
	local part = Instance.new("Part")
	part.Name = "Drop"
	part.Size = Vector3.new(1, 1, 1)
	-- Unanchored, the part would be network-owned by the nearest client, which could move it into its range.
	part.Anchored = true
	part.Position = root.Position + root.CFrame.LookVector * 3
	part:SetAttribute("DropId", id)
	part:SetAttribute("ItemId", itemId)
	part.Parent = workspace
	drops[id] = { itemId = itemId, count = countArg, part = part }

	task.delay(DESPAWN_SECONDS, function()
		local entry = drops[id]
		if entry then
			drops[id] = nil
			entry.part:Destroy()
		end
	end)
	return id
end

function WorldDrops.pickup(player: Player, bag: Bag, dropId: unknown): boolean
	if type(dropId) ~= "string" then
		return false
	end
	local entry = drops[dropId]
	local root = rootOf(player)
	if entry == nil or root == nil then
		return false
	end
	if (root.Position - entry.part.Position).Magnitude > PICKUP_RANGE then
		return false
	end
	drops[dropId] = nil -- claim first: a second request for the same id now fails
	entry.part:Destroy()
	bag[entry.itemId] = (bag[entry.itemId] or 0) + entry.count
	return true
end

return WorldDrops
```

- The part only carries the id for the client to point at; what the drop contains is read from the registry, so editing the part's attributes changes nothing.
- Registry first, then destroy, then grant: the order makes double pickups impossible even if two requests arrive in the same frame.
- If your inventory has capacity limits, check room before claiming and leave the drop on the ground when it does not fit.

# Test
```lua
local dropper = __makePlayer(1, "Dropper")
local picker = __makePlayer(2, "Picker")
local far = __makePlayer(3, "Far")
__makeCharacter(dropper, Vector3.new(0, 3, 0))
__makeCharacter(picker, Vector3.new(2, 3, -3))
__makeCharacter(far, Vector3.new(500, 3, 0))
local bagA, bagB, bagC = { apple = 5 }, {}, {}

local id = item.drop(dropper, bagA, "apple", 3)
check("dropping removes items and returns a drop id", id ~= nil and bagA.apple == 2)
check("the drop part is anchored so no client controls its position", workspace:FindFirstChild("Drop").Anchored == true)
check("drops cannot be made from items you lack", item.drop(dropper, bagA, "apple", 10) == nil
	and item.drop(dropper, bagA, "diamond", 1) == nil and item.drop(dropper, bagA, "apple", 0 / 0) == nil)
check("players out of range cannot pick up", not item.pickup(far, bagC, id) and bagC.apple == nil)
check("a nearby player picks it up", item.pickup(picker, bagB, id) and bagB.apple == 3)
check("the same drop cannot be picked up twice", not item.pickup(picker, bagB, id) and bagB.apple == 3)
check("made-up drop ids do nothing", not item.pickup(picker, bagB, "fake-guid"))

local id2 = item.drop(dropper, bagA, "apple", 1)
__advance(61)
check("unclaimed drops despawn", not item.pickup(dropper, bagA, id2) and bagA.apple == 1)
```
