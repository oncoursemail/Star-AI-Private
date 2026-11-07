---
id: gb-src-tagged-union-messages
category: luau-typing
topics: tagged unions, singleton types, refinement, type narrowing, never, exhaustive checks
source: adapted
source_id: luau-site
source_path: src/content/docs/types/unions-and-intersections.md
source_commit: 41db794d9ee6e56a17b399f8a4520b92301fee59
---
# Request
My client sends different action tables through one remote: `{kind = "equip", slot = 2}`, `{kind = "drop", itemId = "sword"}`, `{kind = "emote", name = "wave"}`. In strict mode I keep casting to `any`. How can I type this so the checker knows which fields exist in each branch?

# Answer
Model it as a tagged union: each variant has a `kind` field with a string singleton type. Checking `action.kind == "equip"` narrows the value to that variant. Ending with a `never` check makes the checker complain when you add a variant and forget to handle it. Because the data comes from a client, first validate the raw table into this type.

```lua
--!strict
export type Action =
	{ kind: "equip", slot: number }
	| { kind: "drop", itemId: string }
	| { kind: "emote", name: string }

local Actions = {}

local MAX_SLOT = 9
local EMOTES = { wave = true, dance = true, point = true }

function Actions.parse(raw: unknown): Action?
	if type(raw) ~= "table" then
		return nil
	end
	local data = raw :: { [any]: any }
	local kind = data.kind
	if kind == "equip" and type(data.slot) == "number" and data.slot % 1 == 0 and data.slot >= 1 and data.slot <= MAX_SLOT then
		return { kind = "equip", slot = data.slot }
	elseif kind == "drop" and type(data.itemId) == "string" and #data.itemId <= 32 then
		return { kind = "drop", itemId = data.itemId }
	elseif kind == "emote" and type(data.name) == "string" and EMOTES[data.name] then
		return { kind = "emote", name = data.name }
	end
	return nil
end

function Actions.describe(action: Action): string
	if action.kind == "equip" then
		return "equip slot " .. action.slot
	elseif action.kind == "drop" then
		return "drop " .. action.itemId
	elseif action.kind == "emote" then
		return "emote " .. action.name
	end
	local unhandled: never = action
	error("unhandled action " .. tostring(unhandled))
end

return Actions
```

- Inside `if action.kind == "equip"` only `slot` is accessible; `action.itemId` there is a type error.
- `parse` copies only the validated fields, so extra keys from an exploiter never reach game code.
- `slot % 1 == 0` rejects fractions, and the range check also rejects NaN because every comparison with NaN is false.

# Test
```lua
check("valid equip parsed", item.parse({ kind = "equip", slot = 2 }).slot == 2)
check("fractional and out of range slots rejected", item.parse({ kind = "equip", slot = 2.5 }) == nil and item.parse({ kind = "equip", slot = 0 / 0 }) == nil)
check("unknown emote rejected", item.parse({ kind = "emote", name = "explode" }) == nil)
check("non-table rejected", item.parse("equip") == nil and item.parse(nil) == nil)
local parsed = item.parse({ kind = "drop", itemId = "sword", extra = "hack" })
check("extra keys dropped", parsed ~= nil and parsed.extra == nil)
check("describe narrows each kind", item.describe({ kind = "emote", name = "wave" }) == "emote wave")
```
