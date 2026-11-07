---
id: gb-data-inv-yield-race-dupe
category: server-authoritative-inventory
topics: duplication, race condition, yield, busy lock, RemoteEvent
source: original
---
# Request
My pet bank lets players move a pet from their team into a vault (a separate DataStore). Somehow people end up with the pet both in the vault and still on their team. The handler definitely checks ownership first:

```lua
VaultDeposit.OnServerEvent:Connect(function(plr, pet)
	local team = teams[plr]
	if team[pet] ~= true then
		return
	end
	writeVault(plr.UserId, pet) -- UpdateAsync inside
	team[pet] = nil
end)
```

# Answer
`writeVault` yields, and while it waits the same remote can fire again: the second call passes the ownership check because the pet is not removed yet, so the pet is stored twice. Remove (reserve) the item before any yield, put it back if the slow step fails, and allow only one request in flight per player.

```lua
--!strict
-- ModuleScript: ServerScriptService.PetStorage
export type Pets = { [string]: boolean }

local PetStorage = {}
local busy: { [Player]: boolean } = {}

-- save is the slow part (a DataStore write); it returns true on success.
function PetStorage.store(player: Player, pets: Pets, petId: unknown, save: (petId: string) -> boolean): boolean
	if type(petId) ~= "string" or busy[player] or not pets[petId] then
		return false
	end
	busy[player] = true
	pets[petId] = nil -- take it out before yielding: a second request can no longer see it
	local ok, saved = pcall(save, petId)
	if not (ok and saved) then
		pets[petId] = true -- the save failed, give the pet back
	end
	busy[player] = nil
	return ok and saved == true
end

return PetStorage
```

- The general rule: mutate server state before the first yield (DataStore, `task.wait`, `WaitForChild`, `InvokeClient`), never after; every yield is a window for a duplicate request.
- `busy` makes concurrent requests from one player fail fast instead of queueing; clear it on `PlayerRemoving` if your saves can outlive the player.
- `pcall(save, ...)` guarantees the `busy` flag is cleared and the pet restored even if the save throws.

# Test
```lua
local p = __makePlayer(1, "Duper")
local pets = { dragon = true }
local stored = {}
local function slowSave(petId)
	task.wait(1)
	table.insert(stored, petId)
	return true
end

local first, second = nil, nil
task.spawn(function()
	first = item.store(p, pets, "dragon", slowSave)
end)
task.spawn(function()
	second = item.store(p, pets, "dragon", slowSave)
end)
check("pet leaves the inventory before the save finishes", pets.dragon == nil)
__advance(2)
check("only the first request stores the pet", first == true and second == false and #stored == 1)

pets.cat = true
local failed = nil
task.spawn(function()
	failed = item.store(p, pets, "cat", function()
		error("DataStore down")
	end)
end)
__advance(1)
check("a failed save gives the pet back", failed == false and pets.cat == true)
check("the busy flag is cleared after a failure", item.store(p, pets, "cat", function()
	return true
end) and pets.cat == nil)
check("pets you do not own cannot be stored", item.store(p, pets, "unicorn", slowSave) == false)
```
