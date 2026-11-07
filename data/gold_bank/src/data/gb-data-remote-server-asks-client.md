---
id: gb-data-remote-server-asks-client
category: remote-security
topics: RemoteFunction, InvokeClient, timeout, RemoteEvent, request response
source: original
---
# Request
My server uses `RemoteFunction:InvokeClient(player)` to ask the client which input device it is on, and sometimes the server script just hangs forever. Why, and what should I use instead?

# Answer
`InvokeClient` waits for the client with no timeout: a client that never answers (or an exploiter that refuses to) stalls that server thread forever, a client error is re-thrown on the server, and a disconnect throws too. Ask with a RemoteEvent instead, tag the request with an id, and wait for the matching reply with a timeout and a default.

```lua
--!strict
-- ModuleScript: ServerScriptService.AskClient
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Players = game:GetService("Players")

local ask = Instance.new("RemoteEvent")
ask.Name = "AskClient"
ask.Parent = ReplicatedStorage

type Pending = { player: Player, thread: thread, answered: boolean }

local pending: { [number]: Pending } = {}
local nextId = 0

local AskClient = {}

-- Yields until the client answers or the timeout passes. Returns the answer or nil.
function AskClient.request(player: Player, question: string, timeout: number): unknown
	nextId += 1
	local id = nextId
	local entry: Pending = { player = player, thread = coroutine.running(), answered = false }
	pending[id] = entry
	ask:FireClient(player, id, question)
	task.delay(timeout, function()
		if pending[id] == entry and not entry.answered then
			pending[id] = nil
			task.spawn(entry.thread, nil)
		end
	end)
	return coroutine.yield()
end

local function onReply(player: Player, idArg: unknown, answer: unknown)
	if type(idArg) ~= "number" then
		return
	end
	local entry = pending[idArg]
	if entry == nil or entry.player ~= player or entry.answered then
		return -- unknown id, or another player answering someone else's question
	end
	entry.answered = true
	pending[idArg] = nil
	task.spawn(entry.thread, answer)
end

ask.OnServerEvent:Connect(onReply)

Players.PlayerRemoving:Connect(function(player: Player)
	for id, entry in pending do
		if entry.player == player and not entry.answered then
			entry.answered = true
			pending[id] = nil
			task.spawn(entry.thread, nil)
		end
	end
end)

return AskClient
```

Usage, validating the answer like any other client input:

```lua
--!strict
local ServerScriptService = game:GetService("ServerScriptService")
local AskClient = require(ServerScriptService.AskClient)

local DEVICES = { Touch = true, Gamepad = true, Keyboard = true }

local function deviceOf(player: Player): string
	local answer = AskClient.request(player, "device", 5)
	if type(answer) == "string" and DEVICES[answer] then
		return answer
	end
	return "Keyboard"
end

return deviceOf
```

- The client answers with `ask:FireServer(id, value)` from its `OnClientEvent` handler.
- Client-to-server `RemoteFunction:InvokeServer` is fine; the risk only runs the other way, where the server would be waiting on code the player controls.
- Treat the reply as a hint for presentation only; never let it decide rewards or permissions.

# Test
```lua
local remote = game:GetService("ReplicatedStorage"):WaitForChild("AskClient")
local p = __makePlayer(1, "Asker")
local other = __makePlayer(2, "Other")

local answer = "unset"
task.spawn(function()
	answer = item.request(p, "device", 5)
end)
local sent = remote.__sent[#remote.__sent]
check("question is sent to the player with an id", sent[1] == p and type(sent[2]) == "number" and sent[3] == "device")
remote.OnServerEvent:Fire(other, sent[2], "Touch")
check("another player cannot answer", answer == "unset")
remote.OnServerEvent:Fire(p, sent[2], "Gamepad")
check("matching reply resumes the request", answer == "Gamepad")

local silent = "unset"
task.spawn(function()
	silent = item.request(p, "device", 5)
end)
__advance(5.1)
check("a client that never answers times out with nil", silent == nil)

local leaving = "unset"
task.spawn(function()
	leaving = item.request(other, "device", 30)
end)
__removePlayer(other)
check("leaving resolves pending requests immediately", leaving == nil)
```
