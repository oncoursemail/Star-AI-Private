---
id: gb-data-remote-function-safe-handler
category: remote-security
topics: RemoteFunction, OnServerInvoke, pcall, rate limit, response shape
source: original
---
# Request
I use a RemoteFunction so the shop UI can ask the server for a page of items. Sometimes the client gets a weird error message and exploiters spam it. What are the rules for writing an OnServerInvoke handler safely?

# Answer
Validate the arguments like any remote, rate-limit per player, keep the handler fast (no long yields), and never let it throw: wrap the work in `pcall` and always return a plain table with an `ok` flag, so errors are not shown to clients and the UI has one shape to handle. Return only data (strings, numbers, small tables), never Instances the client should not reach.

```lua
--!strict
-- Script: ServerScriptService.ShopQuery
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

type Entry = { id: string, name: string, price: number }
export type Response = { ok: boolean, reason: string?, items: { Entry }?, pages: number? }

local CATALOG: { Entry } = {
	{ id = "wood_sword", name = "Wood Sword", price = 50 },
	{ id = "iron_sword", name = "Iron Sword", price = 250 },
	{ id = "bow", name = "Bow", price = 180 },
	{ id = "shield", name = "Shield", price = 120 },
	{ id = "potion", name = "Potion", price = 25 },
}
local PAGE_SIZE = 2
local MIN_INTERVAL = 0.2

local getShopPage = Instance.new("RemoteFunction")
getShopPage.Name = "GetShopPage"
getShopPage.Parent = ReplicatedStorage

local lastCall: { [Player]: number } = {}

local function buildPage(page: number): Response
	local pages = math.ceil(#CATALOG / PAGE_SIZE)
	if page > pages then
		return { ok = false, reason = "no such page" }
	end
	local items: { Entry } = {}
	for i = (page - 1) * PAGE_SIZE + 1, math.min(#CATALOG, page * PAGE_SIZE) do
		local entry = CATALOG[i]
		table.insert(items, { id = entry.id, name = entry.name, price = entry.price })
	end
	return { ok = true, items = items, pages = pages }
end

local function onInvoke(player: Player, pageArg: unknown): Response
	local now = os.clock()
	local last = lastCall[player]
	if last and now - last < MIN_INTERVAL then
		return { ok = false, reason = "slow down" }
	end
	lastCall[player] = now
	if type(pageArg) ~= "number" or pageArg % 1 ~= 0 or pageArg < 1 or pageArg > 1000 then
		return { ok = false, reason = "bad page" }
	end
	local ok, response = pcall(buildPage, pageArg)
	if not ok then
		warn("shop page failed:", response)
		return { ok = false, reason = "server error" }
	end
	return response
end

getShopPage.OnServerInvoke = onInvoke
Players.PlayerRemoving:Connect(function(player: Player)
	lastCall[player] = nil
end)
```

Client side, the call itself goes in `pcall` too (the server may be shutting down or the remote may be gone):

```lua
--!strict
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local getShopPage = ReplicatedStorage:WaitForChild("GetShopPage") :: RemoteFunction

local function fetchPage(page: number): { [string]: any }?
	local ok, response = pcall(function()
		return getShopPage:InvokeServer(page)
	end)
	if ok and type(response) == "table" and response.ok then
		return response
	end
	return nil
end

return fetchPage
```

- Copying entries into new tables means a later change to the response cannot reach the catalogue, and the client gets exactly the fields you chose.
- Assign `OnServerInvoke` exactly once; setting it again elsewhere silently replaces the first handler.
- Purchases still go through their own validated remote; prices shown here are for display, the buy handler reads the catalogue again.

# Test
```lua
warn = function(...) end
```
```lua
local remote = game:GetService("ReplicatedStorage"):WaitForChild("GetShopPage")
local p = __makePlayer(1, "Shopper")
local first = remote.OnServerInvoke(p, 1)
check("first page returns two items and the page count", first.ok and #first.items == 2 and first.pages == 3)
check("entries carry server prices", first.items[1].id == "wood_sword" and first.items[1].price == 50)

local spam = remote.OnServerInvoke(p, 2)
check("calls faster than the limit are refused politely", spam.ok == false and spam.reason == "slow down")

__advance(0.3)
local last = remote.OnServerInvoke(p, 3)
check("last page is partial", last.ok and #last.items == 1 and last.items[1].id == "potion")

__advance(0.3)
local missing = remote.OnServerInvoke(p, 9)
check("pages past the end are refused", missing.ok == false)

for _, bad in { 0, -1, 1.5, 0 / 0, "1", math.huge } do
	__advance(0.3)
	local r = remote.OnServerInvoke(p, bad)
	check("bad page argument refused: " .. tostring(bad), r.ok == false and r.reason == "bad page")
end
```
