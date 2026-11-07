---
id: gb-eng-literal-union-states
category: luau-typing
topics: string literal types, union, exhaustiveness, never type, door states
source: original
---
# Request
My door script stores its state as a string ("open", "closed", "locked", "opening") and I've had bugs from typos like `"Opened"`. How can strict mode catch invalid state strings, and warn me when I add a new state but forget to handle it somewhere?

# Answer
Make the state a union of string literals; assignments of any other string fail to type-check. For exhaustiveness, end the `if` chain with a branch that assigns the remaining value to `never`: once every state is handled the branch type-checks, and a forgotten state turns it into an error.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.DoorLogic
export type DoorState = "Closed" | "Opening" | "Open" | "Locked"
export type DoorInput = "Use" | "Unlock" | "Lock" | "Finished"

local DoorLogic = {}

function DoorLogic.next(state: DoorState, input: DoorInput, hasKey: boolean): DoorState
	if state == "Closed" then
		if input == "Use" then
			return "Opening"
		elseif input == "Lock" and hasKey then
			return "Locked"
		end
		return "Closed"
	elseif state == "Opening" then
		return if input == "Finished" then "Open" else "Opening"
	elseif state == "Open" then
		return if input == "Use" then "Closed" else "Open"
	elseif state == "Locked" then
		return if input == "Unlock" and hasKey then "Closed" else "Locked"
	else
		local unhandled: never = state
		error(`unhandled door state {unhandled}`)
	end
end

function DoorLogic.isPassable(state: DoorState): boolean
	return state == "Open"
end

return DoorLogic
```

- `DoorLogic.next("Opened", "Use", false)` is rejected: `"Opened"` is not part of `DoorState`.
- Add `"Broken"` to `DoorState` without a branch and `local unhandled: never = state` fails with a type error that names the missing case.
- Keeping transitions in one pure function makes the door easy to test and reuse; the door Script only stores the state and plays tweens when it changes.

# Test
```lua
check("use opens", item.next("Closed", "Use", false) == "Opening")
check("opening finishes", item.next("Opening", "Finished", false) == "Open")
check("open use closes", item.next("Open", "Use", false) == "Closed")
check("lock needs key", item.next("Closed", "Lock", false) == "Closed" and item.next("Closed", "Lock", true) == "Locked")
check("locked ignores use", item.next("Locked", "Use", true) == "Locked")
check("unlock with key", item.next("Locked", "Unlock", true) == "Closed")
check("passable only when open", item.isPassable("Open") and not item.isPassable("Opening"))
check("runtime guard on bad state", not pcall(item.next, "Opened", "Use", false))
```
