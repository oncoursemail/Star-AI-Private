---
id: gb-data-msg-update-shutdown-notice
category: messaging
topics: MessagingService, shutdown notice, countdown, update, kick message
source: original
---
# Request
Before I shut down servers for an update I'd like to warn everyone: "Servers restart in 5 minutes", a countdown in the UI, and then everyone gets removed with a friendly message so their data saves first. How can I broadcast that to all servers?

# Answer
Publish one message with the restart time; each server shows the countdown to its players and, when the time arrives, kicks them with the update message, which runs `PlayerRemoving` saves. Guard against duplicate or late messages, and let a second message with `cancel = true` call it off.

```lua
--!strict
-- ModuleScript: ServerScriptService.RestartNotice
local MessagingService = game:GetService("MessagingService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local TOPIC = "RestartNotice"
local KICK_MESSAGE = "The game is updating. Rejoin in a minute for the new version!"

local notice = Instance.new("RemoteEvent")
notice.Name = "RestartNotice"
notice.Parent = ReplicatedStorage

local RestartNotice = {}
local pendingAt: number? = nil
local restarting = false

local function restartNow(at: number)
	if pendingAt ~= at then
		return -- cancelled or replaced by a newer notice
	end
	restarting = true -- this old server can still receive joins until it closes; send those players off too
	for _, player in Players:GetPlayers() do
		player:Kick(KICK_MESSAGE)
	end
end

local function onMessage(message: { Data: any })
	local data = message.Data
	if type(data) ~= "table" or type(data.at) ~= "number" then
		return
	end
	if data.cancel == true then
		pendingAt = nil
		notice:FireAllClients(nil)
		return
	end
	if pendingAt == data.at or data.at < os.time() - 5 then
		return
	end
	pendingAt = data.at
	notice:FireAllClients(data.at) -- clients count down to this Unix time
	task.delay(math.max(0, data.at - os.time()), restartNow, data.at)
end

function RestartNotice.announce(minutes: number): boolean
	return (pcall(function()
		MessagingService:PublishAsync(TOPIC, { at = os.time() + math.floor(minutes * 60) })
	end))
end

function RestartNotice.cancel(): boolean
	return (pcall(function()
		MessagingService:PublishAsync(TOPIC, { at = os.time(), cancel = true })
	end))
end

-- Players who join during the countdown see it too; players who join after the restart are kicked.
Players.PlayerAdded:Connect(function(player: Player)
	if restarting then
		player:Kick(KICK_MESSAGE)
	elseif pendingAt then
		notice:FireClient(player, pendingAt)
	end
end)
for _, player in Players:GetPlayers() do
	if pendingAt then
		notice:FireClient(player, pendingAt)
	end
end

task.spawn(function()
	for attempt = 1, 5 do
		local ok = pcall(function()
			MessagingService:SubscribeAsync(TOPIC, onMessage)
		end)
		if ok then
			return
		end
		task.wait(2 ^ attempt)
	end
	warn("RestartNotice could not subscribe; this server will not get restart notices")
end)

return RestartNotice
```

- Kicking runs each player's `PlayerRemoving` save while the server is still healthy, instead of relying on the 30-second `BindToClose` window during a forced shutdown.
- Publish the update first so new servers run the new version; players who rejoin after the kick land in fresh servers.
- Sending the Unix time (not "5 minutes") keeps every server's countdown identical despite delivery delays.

# Test
```lua
local remote = game:GetService("ReplicatedStorage"):WaitForChild("RestartNotice")
local a = __makePlayer(1, "A")
local b = __makePlayer(2, "B")

item.announce(1)
item.cancel()
__advance(61)
check("a cancelled restart does not kick", a.__kicked == nil and b.__kicked == nil)

local t0 = os.time()
check("announcing publishes the notice", item.announce(5))
local sent = remote.__sent[#remote.__sent]
check("clients get the restart time", sent[1] == "all" and sent[2] == t0 + 300)

local late = __makePlayer(3, "Late")
local lateSent = remote.__sent[#remote.__sent]
check("players joining mid-countdown are told too", lateSent[1] == late and lateSent[2] == t0 + 300)

__advance(299)
check("nobody is kicked before the time", a.__kicked == nil)
__advance(2)
check("everyone is kicked with the update message", a.__kicked ~= nil and b.__kicked ~= nil and late.__kicked ~= nil)

local after = __makePlayer(4, "After")
check("players matched into the old server after the restart are kicked too", after.__kicked ~= nil)
```
