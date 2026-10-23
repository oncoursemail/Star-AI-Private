---
id: gb-data-msg-subscription-cleanup
category: messaging
topics: MessagingService, SubscribeAsync, Disconnect, private messages, cleanup
source: original
---
# Request
I'm adding cross-server friend whispers: each player subscribes to their own topic like "whisper_12345" when they join. After a while the server starts failing to subscribe. Do I need to clean up subscriptions?

# Answer
Yes. Each server can hold only a limited number of subscriptions (it scales with player count), and every `SubscribeAsync` returns a connection that stays alive until you `Disconnect` it. Keep the connection per player, disconnect it on `PlayerRemoving`, and check that the subscription actually succeeded.

```lua
--!strict
-- ModuleScript: ServerScriptService.Whispers
local MessagingService = game:GetService("MessagingService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local whisper = Instance.new("RemoteEvent")
whisper.Name = "Whisper"
whisper.Parent = ReplicatedStorage

local subscriptions: { [Player]: RBXScriptConnection } = {}

local Whispers = {}

local function topicFor(userId: number): string
	return "whisper_" .. userId
end

local function subscribe(player: Player)
	local ok, connection = pcall(function()
		return MessagingService:SubscribeAsync(topicFor(player.UserId), function(message: { Data: any })
			local data = message.Data
			if type(data) == "table" and type(data.from) == "string" and type(data.text) == "string" then
				whisper:FireClient(player, data.from, data.text)
			end
		end)
	end)
	if not ok then
		warn("whisper subscription failed for", player.UserId)
		return
	end
	if player.Parent == nil then
		connection:Disconnect() -- left while we were subscribing
		return
	end
	subscriptions[player] = connection
end

local function unsubscribe(player: Player)
	local connection = subscriptions[player]
	if connection then
		subscriptions[player] = nil
		connection:Disconnect()
	end
end

-- text must already be filtered for the recipient; fromName is the sender's name.
function Whispers.send(toUserId: number, fromName: string, text: string): boolean
	return (pcall(function()
		MessagingService:PublishAsync(topicFor(toUserId), { from = fromName, text = text })
	end))
end

function Whispers.count(): number
	local n = 0
	for _ in subscriptions do
		n += 1
	end
	return n
end

Players.PlayerAdded:Connect(subscribe)
Players.PlayerRemoving:Connect(unsubscribe)
for _, player in Players:GetPlayers() do
	task.spawn(subscribe, player)
end

return Whispers
```

- Without `unsubscribe`, a busy server accumulates one dead subscription per player who ever joined and eventually hits the limit, which is exactly the failure you saw.
- The `player.Parent == nil` check covers a player who leaves while `SubscribeAsync` is still yielding.
- Whisper text between users must be filtered for the recipient (`GetChatForUserAsync` or TextChatService); this example assumes the caller did that.

# Test
```lua
local remote = game:GetService("ReplicatedStorage"):WaitForChild("Whisper")
local a = __makePlayer(10, "Alice")
local b = __makePlayer(20, "Bob")
check("each player gets a subscription", item.count() == 2)

check("a whisper is delivered to the recipient's client", item.send(20, "Alice", "hi"))
local last = remote.__sent[#remote.__sent]
check("payload reaches only that player", last[1] == b and last[2] == "Alice" and last[3] == "hi")

__removePlayer(b)
check("leaving removes the subscription", item.count() == 1)
local before = #remote.__sent
item.send(20, "Alice", "are you there?")
check("messages to a player who left are not delivered here", #remote.__sent == before)

game:GetService("MessagingService"):PublishAsync("whisper_10", { from = 5, text = {} })
check("malformed payloads are ignored", #remote.__sent == before and a.Parent ~= nil)
```
