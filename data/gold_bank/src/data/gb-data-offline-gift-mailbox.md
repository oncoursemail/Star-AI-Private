---
id: gb-data-offline-gift-mailbox
category: datastore-safety
topics: DataStore, mailbox, offline player, gifting, UpdateAsync
source: original
---
# Request
I want players to send gifts to friends who are offline, and the friend gets them next time they join, even in a different server. How do I do this without gifts getting lost or claimed twice?

# Answer
Give each player a mailbox key. Senders append to it with `UpdateAsync` (capped in size), and the owner takes everything out with one `UpdateAsync` that returns the mail and empties the box in the same atomic step. Each gift carries a unique id so the receiving code can ignore anything it has already granted.

```lua
--!strict
-- ModuleScript: ServerScriptService.Mailbox
local DataStoreService = game:GetService("DataStoreService")
local HttpService = game:GetService("HttpService")

local store = DataStoreService:GetDataStore("Mailboxes")
local MAX_MAIL = 50

export type Gift = { id: string, from: number, itemId: string, sentAt: number }

local Mailbox = {}

local function keyFor(userId: number): string
	return "mail_" .. userId
end

-- itemId must already be validated and removed from the sender's inventory by the caller.
function Mailbox.send(fromUserId: number, toUserId: number, itemId: string): (boolean, string?)
	local gift: Gift = { id = HttpService:GenerateGUID(false), from = fromUserId, itemId = itemId, sentAt = os.time() }
	local full = false
	local ok = pcall(function()
		store:UpdateAsync(keyFor(toUserId), function(box: { Gift }?): { Gift }?
			local mail = box or {}
			if #mail >= MAX_MAIL then
				full = true
				return nil
			end
			full = false
			table.insert(mail, gift)
			return mail
		end)
	end)
	if not ok then
		return false, "error"
	elseif full then
		return false, "full"
	end
	return true, nil
end

-- Takes every gift out of the mailbox atomically. Returns nil when the read failed (try again later).
function Mailbox.takeAll(userId: number): { Gift }?
	local taken: { Gift } = {}
	local ok = pcall(function()
		store:UpdateAsync(keyFor(userId), function(box: { Gift }?): { Gift }?
			taken = box or {}
			if #taken == 0 then
				return nil
			end
			return {}
		end)
	end)
	return if ok then taken else nil
end

return Mailbox
```

- If `send` fails, give the item back to the sender; the mailbox write is the moment ownership transfers.
- Call `takeAll` after the player's profile has loaded and save the profile soon after granting; store granted gift ids in the profile for a while if you want a crash between take and save to be detectable.
- The cap keeps one key far from the 4 MB limit and stops a spammer from filling someone's box with junk.

# Test
```lua
local ok1 = item.send(1, 2, "Sword")
local ok2 = item.send(3, 2, "Shield")
check("gifts are delivered to an offline player", ok1 and ok2)

local mail = item.takeAll(2)
check("owner receives both gifts in order", mail ~= nil and #mail == 2 and mail[1].itemId == "Sword" and mail[2].from == 3)
check("gifts have unique ids", mail ~= nil and mail[1].id ~= mail[2].id)
local again = item.takeAll(2)
check("a second take finds nothing", again ~= nil and #again == 0)

for i = 1, 50 do
	item.send(i, 9, "Coin")
end
local sent, why = item.send(51, 9, "Coin")
check("full mailbox refuses more mail", not sent and why == "full")

game:GetService("DataStoreService").__failNext = 1
check("a failed take returns nil and keeps the mail", item.takeAll(9) == nil and #item.takeAll(9) == 50)
```
