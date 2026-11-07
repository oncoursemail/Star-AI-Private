---
id: gb-eng-frozen-config
category: luau-typing
topics: table.freeze, read-only tables, config module, deep freeze, typed config
source: original
---
# Request
We keep a shared `Config` ModuleScript with weapon stats, and twice now some script did `Config.Weapons.Rifle.Damage = 999` while testing and forgot to remove it, which changed it for every other script. How can I make the config read-only and still typed?

# Answer
Type the config shape, then deep-freeze it before returning. `table.freeze` is shallow, so nested tables need freezing too; any later write raises an error at the line that tried it.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Config
export type WeaponStats = {
	Damage: number,
	FireRate: number,
	MagazineSize: number,
}

export type Config = {
	MaxPlayers: number,
	RoundSeconds: number,
	Weapons: { [string]: WeaponStats },
}

local function deepFreeze<T>(value: T): T
	if type(value) == "table" and not table.isfrozen(value) then
		for _, child in value :: any do
			deepFreeze(child)
		end
		table.freeze(value :: any)
	end
	return value
end

local config: Config = {
	MaxPlayers = 12,
	RoundSeconds = 180,
	Weapons = {
		Rifle = { Damage = 22, FireRate = 8, MagazineSize = 30 },
		Shotgun = { Damage = 9, FireRate = 1.2, MagazineSize = 6 },
	},
}

return deepFreeze(config)
```

- A write to a frozen table errors with "attempt to modify a readonly table", so the stray test edit fails loudly instead of leaking into other scripts.
- Code that needs a tweaked copy (a power-up, a test) should use `table.clone(Config.Weapons.Rifle)`; the clone is not frozen.
- Freezing happens once at require time, and reads from a frozen table cost the same as reads from a normal one.

# Test
```lua
check("values readable", item.Weapons.Rifle.Damage == 22 and item.MaxPlayers == 12)
check("top level frozen", not pcall(function() item.MaxPlayers = 99 end))
check("nested frozen", not pcall(function() item.Weapons.Rifle.Damage = 999 end))
check("cannot add weapons", not pcall(function() item.Weapons.Laser = { Damage = 1, FireRate = 1, MagazineSize = 1 } end))
local copy = table.clone(item.Weapons.Shotgun)
copy.Damage = 50
check("clone is writable and original untouched", copy.Damage == 50 and item.Weapons.Shotgun.Damage == 9)
```
