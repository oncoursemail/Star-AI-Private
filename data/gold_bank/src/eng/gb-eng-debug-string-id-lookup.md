---
id: gb-eng-debug-string-id-lookup
category: engineering-debugging
topics: table keys, string vs number, tonumber, RemoteEvent validation, shop
source: original
---
# Request
My shop server errors with "attempt to compare nil with number" when a player buys something. The buttons are named after the item id (e.g. a button named "3"), and the client sends the button name:

```lua
-- server
local PRICES = { [1] = 50, [2] = 120, [3] = 300 }

buyRemote.OnServerEvent:Connect(function(plr, itemId)
	local coins = plr.leaderstats.Coins
	if coins.Value >= PRICES[itemId] then
		coins.Value -= PRICES[itemId]
	end
end)
```

# Answer
`button.Name` is the string `"3"`, and in Luau `t["3"]` and `t[3]` are different keys, so `PRICES["3"]` is nil and the comparison errors. Convert on the server with `tonumber`, and validate it like any client input (type, whole number, known item) before using it; never assume the client sent the type you expect.

```lua
--!strict
-- Script: ServerScriptService.Shop
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local PRICES: { [number]: number } = { [1] = 50, [2] = 120, [3] = 300 }

local buyRemote = Instance.new("RemoteEvent")
buyRemote.Name = "BuyItem"
buyRemote.Parent = ReplicatedStorage

local function toItemId(raw: unknown): number?
	local id = if type(raw) == "number" then raw elseif type(raw) == "string" then tonumber(raw) else nil
	if id == nil or id % 1 ~= 0 or PRICES[id] == nil then
		return nil
	end
	return id
end

buyRemote.OnServerEvent:Connect(function(player: Player, raw: unknown)
	local itemId = toItemId(raw)
	if itemId == nil then
		return
	end
	local stats = player:FindFirstChild("leaderstats")
	local coins = stats and stats:FindFirstChild("Coins")
	if coins == nil or not coins:IsA("IntValue") then
		return
	end
	local price = PRICES[itemId]
	if coins.Value < price then
		return
	end
	coins.Value -= price
	local owned = player:GetAttribute(`Owns{itemId}`)
	player:SetAttribute(`Owns{itemId}`, (if type(owned) == "number" then owned else 0) + 1)
end)
```

- `tonumber` also accepts `" 3 "`, `"0x3"` and `"3.0"`; the `% 1` and `PRICES[id] == nil` checks keep only real item ids, and NaN fails the lookup.
- Pick one key type per table and convert at the boundary (remotes, attributes, button names, DataStore keys) so the rest of the code never mixes them.
- The price comes from the server's table only; the client sends just the id.

# Test
```lua
local remote = game:GetService("ReplicatedStorage"):WaitForChild("BuyItem")
local p = __makePlayer(1, "Buyer")
local ls = Instance.new("Folder")
ls.Name = "leaderstats"
ls.Parent = p
local coins = Instance.new("IntValue")
coins.Name = "Coins"
coins.Value = 400
coins.Parent = ls
remote.OnServerEvent:Fire(p, "3")
check("string id from button works", coins.Value == 100 and p:GetAttribute("Owns3") == 1)
remote.OnServerEvent:Fire(p, 1)
check("number id works", coins.Value == 50 and p:GetAttribute("Owns1") == 1)
remote.OnServerEvent:Fire(p, "2")
check("cannot afford", coins.Value == 50 and p:GetAttribute("Owns2") == nil)
remote.OnServerEvent:Fire(p, "1.5")
remote.OnServerEvent:Fire(p, 9)
remote.OnServerEvent:Fire(p, { 1 })
remote.OnServerEvent:Fire(p, 0 / 0)
check("bad ids ignored without errors", coins.Value == 50)
```
