---
id: gb-data-inv-server-item-definitions
category: server-authoritative-inventory
topics: item definitions, ServerStorage, ReplicatedStorage, table.freeze, client view
source: original
---
# Request
All my item stats (damage, sell value, drop chances) are in a ModuleScript in ReplicatedStorage so the UI can show them. Is it a problem that clients can read it, and how should I organize item definitions?

# Answer
Clients reading stats is fine for display, but anything the server relies on must come from a copy clients cannot edit, and some data (drop chances of secret items, internal flags) should not ship to clients at all. Keep the full definitions in ServerScriptService/ServerStorage, frozen, and publish a display-only view to ReplicatedStorage that the server builds from them.

```lua
--!strict
-- ModuleScript: ServerScriptService.ItemDefs
export type ItemDef = {
	name: string,
	rarity: "Common" | "Rare" | "Legendary",
	damage: number?,
	sellValue: number,
	dropWeight: number, -- server only
	hidden: boolean?,   -- server only: unreleased items are not shown to clients at all
}

local DEFS: { [string]: ItemDef } = {
	wood_sword = { name = "Wood Sword", rarity = "Common", damage = 8, sellValue = 5, dropWeight = 70 },
	ruby_blade = { name = "Ruby Blade", rarity = "Rare", damage = 20, sellValue = 60, dropWeight = 25 },
	void_edge = { name = "Void Edge", rarity = "Legendary", damage = 45, sellValue = 500, dropWeight = 5 },
	winter_axe = { name = "Winter Axe", rarity = "Rare", damage = 18, sellValue = 40, dropWeight = 0, hidden = true },
}

for _, def in DEFS do
	table.freeze(def)
end
table.freeze(DEFS)

local ItemDefs = {}

function ItemDefs.get(id: string): ItemDef?
	return DEFS[id]
end

-- Display data only: what the inventory and shop UI need, nothing the server decides with.
function ItemDefs.publicView(): { [string]: { name: string, rarity: string, damage: number? } }
	local view = {}
	for id, def in DEFS do
		if not def.hidden then
			view[id] = { name = def.name, rarity = def.rarity, damage = def.damage }
		end
	end
	return view
end

return ItemDefs
```

At server start, publish the view (clients read it through attributes, a RemoteFunction, or a generated ModuleScript):

```lua
--!strict
local HttpService = game:GetService("HttpService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerScriptService = game:GetService("ServerScriptService")
local ItemDefs = require(ServerScriptService.ItemDefs)

local catalog = Instance.new("StringValue")
catalog.Name = "ItemCatalog"
catalog.Value = HttpService:JSONEncode(ItemDefs.publicView())
catalog.Parent = ReplicatedStorage
```

- Frozen tables turn an accidental `def.sellValue = 0` somewhere in server code into an immediate error instead of a silent economy bug.
- Server systems (loot, selling, crafting) always call `ItemDefs.get(id)`; a client-supplied id that is not in the table simply returns `nil`.
- Even the display view is a convenience; never read a price or damage value back from the client.

# Test
```lua
check("server can read full definitions", item.get("void_edge").dropWeight == 5 and item.get("void_edge").sellValue == 500)
check("unknown ids return nil", item.get("admin_sword") == nil)
check("definitions are frozen", not pcall(function()
	item.get("wood_sword").sellValue = 99999
end))
local view = item.publicView()
check("public view has display fields", view.ruby_blade.name == "Ruby Blade" and view.ruby_blade.damage == 20)
check("public view omits server-only fields", view.ruby_blade.dropWeight == nil and view.ruby_blade.sellValue == nil)
check("hidden items are not published", view.winter_axe == nil)
check("the view can be serialised for clients", type(game:GetService("HttpService"):JSONEncode(view)) == "string")
```
