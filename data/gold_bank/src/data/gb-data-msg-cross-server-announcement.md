---
id: gb-data-msg-cross-server-announcement
category: messaging
topics: MessagingService, announcement, admin, text filtering, cross-server
source: original
---
# Request
I want admins to type an announcement in one server and have it show as a banner in every server of my game. How do I do this with MessagingService?

# Answer
The admin's server filters the text, then publishes it on one topic; every server subscribes to that topic at startup and forwards the message to its own players through a RemoteEvent. Publishing and subscribing both go in `pcall`, and the receiving side validates the payload because anything on a topic is just data.

```lua
--!strict
-- ModuleScript: ServerScriptService.Announcements
local MessagingService = game:GetService("MessagingService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TextService = game:GetService("TextService")

local TOPIC = "Announcements"
local MAX_LENGTH = 200

local banner = Instance.new("RemoteEvent")
banner.Name = "AnnouncementBanner"
banner.Parent = ReplicatedStorage

local Announcements = {}

local function onMessage(message: { Data: any, Sent: number })
	local data = message.Data
	if type(data) ~= "table" or type(data.text) ~= "string" or #data.text > MAX_LENGTH then
		return
	end
	banner:FireAllClients(data.text, if type(data.from) == "string" then data.from else "Staff")
end

-- Call only after your admin check. Returns false if filtering or publishing failed.
function Announcements.send(admin: Player, text: string): boolean
	if #text == 0 or #text > MAX_LENGTH then
		return false
	end
	local ok, filtered = pcall(function()
		return TextService:FilterStringAsync(text, admin.UserId):GetNonChatStringForBroadcastAsync()
	end)
	if not ok or type(filtered) ~= "string" then
		return false
	end
	local published = pcall(function()
		MessagingService:PublishAsync(TOPIC, { text = filtered, from = admin.Name })
	end)
	return published
end

local subscribed, err = pcall(function()
	return MessagingService:SubscribeAsync(TOPIC, onMessage)
end)
if not subscribed then
	warn("announcements unavailable in this server:", err)
end

return Announcements
```

- The publishing server also receives its own message through the subscription, so there is one code path for showing the banner everywhere.
- Filter once before publishing, with the admin as the author; receivers then show the already-filtered broadcast text.
- Delivery is best effort and usually under a second; for something that must reach every server (a forced update), combine it with a DataStore or MemoryStore flag that new servers read at startup.

# Test
```lua
local remote = game:GetService("ReplicatedStorage"):WaitForChild("AnnouncementBanner")
local admin = __makePlayer(1, "Admin")
__makePlayer(2, "Viewer")

check("an announcement is published and shown", item.send(admin, "Double XP this weekend!"))
local last = remote.__sent[#remote.__sent]
check("every client gets the banner text and author", last[1] == "all" and last[2] == "Double XP this weekend!" and last[3] == "Admin")

item.send(admin, "Badword event")
check("text is filtered before it is published", remote.__sent[#remote.__sent][2] == "####### event")

local count = #remote.__sent
check("empty and overlong text is refused", not item.send(admin, "") and not item.send(admin, string.rep("a", 201)))
game:GetService("MessagingService"):PublishAsync("Announcements", { text = 42 })
game:GetService("MessagingService"):PublishAsync("Announcements", "junk")
check("malformed messages on the topic are ignored", #remote.__sent == count)
```
