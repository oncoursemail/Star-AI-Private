---
id: gb-src-shop-remotefunction-validate
category: server-authoritative-inventory
topics: RemoteFunction, OnServerInvoke, shop, price validation, IsDescendantOf, spoofed instances
source: adapted
source_id: creator-docs
source_path: content/en-us/scripting/security/client-server-boundary.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
My shop client calls `BuyItem:InvokeServer(itemFolder)` where each item is a Folder in `ReplicatedStorage.ItemData` with a `Price` NumberValue inside. The server reads the price from the folder it receives. Is that safe? Can you write the server side properly?

# Answer
Never trust the argument shape: a client can send a table that looks like a Folder with `Price = 0`, or an instance it created itself. Accept only a real Instance that lives inside your server-known `ItemData` folder, read the price from that instance on the server, and check the player can afford it before deducting.

```lua
--!strict
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local itemData = ReplicatedStorage:WaitForChild("ItemData")
local buyItem = ReplicatedStorage:WaitForChild("BuyItem") :: RemoteFunction

local function buy(player: Player, item: any): (boolean, string)
	if typeof(item) ~= "Instance" or not item:IsDescendantOf(itemData) then
		return false, "Invalid item"
	end
	local priceValue = item:FindFirstChild("Price")
	if not priceValue or not priceValue:IsA("NumberValue") then
		return false, "Item has no price"
	end
	local price = priceValue.Value
	if price ~= price or price < 0 then
		return false, "Invalid price"
	end

	if player:GetAttribute("Owned_" .. item.Name) then
		return false, "Already owned"
	end
	local gold = player:GetAttribute("Gold")
	if typeof(gold) ~= "number" or gold < price then
		return false, "Not enough gold"
	end

	player:SetAttribute("Gold", gold - price)
	player:SetAttribute("Owned_" .. item.Name, true)
	return true, "Purchased"
end

buyItem.OnServerInvoke = buy
```

- `IsDescendantOf(itemData)` rejects fake tables and client-created instances, because neither exists in the server's tree.
- The price is read on the server; nothing the client sends affects how much is charged.
- Returning `(ok, message)` lets the client UI show why a purchase failed without trusting its own checks.

# Test
```lua
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local folder = Instance.new("Folder")
folder.Name = "ItemData"
folder.Parent = ReplicatedStorage
local blade = Instance.new("Folder")
blade.Name = "Blade"
local price = Instance.new("NumberValue")
price.Name = "Price"
price.Value = 50
price.Parent = blade
blade.Parent = folder
local remote = Instance.new("RemoteFunction")
remote.Name = "BuyItem"
remote.Parent = ReplicatedStorage
```

```lua
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local remote = ReplicatedStorage.BuyItem
local blade = ReplicatedStorage.ItemData.Blade
local p = __makePlayer(1, "Shopper")
p:SetAttribute("Gold", 80)
local invoke = remote.OnServerInvoke

local ok1 = invoke(p, { Name = "Blade", Price = { Value = 0 } })
check("fake table rejected", ok1 == false)
local fake = Instance.new("Folder")
fake.Name = "Blade"
local ok2 = invoke(p, fake)
check("instance outside ItemData rejected", ok2 == false)
local ok3 = invoke(p, blade)
check("real purchase succeeds", ok3 == true and p:GetAttribute("Gold") == 30)
local ok4, msg4 = invoke(p, blade)
check("second purchase blocked", ok4 == false and msg4 == "Already owned")
local poor = __makePlayer(2, "Poor")
poor:SetAttribute("Gold", 10)
local ok5 = invoke(poor, blade)
check("cannot afford", ok5 == false and poor:GetAttribute("Gold") == 10)
```
