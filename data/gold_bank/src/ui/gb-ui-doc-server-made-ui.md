---
id: gb-ui-doc-server-made-ui
category: docs-question
topics: server UI, StarterGui, PlayerGui, RemoteEvent, client-built UI
source: original
---
# Request
My round announcement is made by a server Script: it creates a ScreenGui with a TextLabel and parents it to StarterGui. Nobody sees it until they die and respawn. If I put it in each player's PlayerGui from the server it shows, but my LocalScripts can't seem to change it reliably. What's the right way?

# Answer
StarterGui is only a template: its contents are copied into PlayerGui when a character spawns, so adding to it at runtime does nothing for players already playing. Parenting server-made UI into PlayerGui works, but the server then owns those instances, and replication of later changes can fight with client edits. Let the server send data (a RemoteEvent with the message) and let a LocalScript build and animate the UI.

```lua
--!strict
-- LocalScript: StarterPlayerScripts.Announcements
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local announce = ReplicatedStorage:WaitForChild("Announce") :: RemoteEvent
local playerGui = Players.LocalPlayer:WaitForChild("PlayerGui")

local gui = Instance.new("ScreenGui")
gui.Name = "Announcements"
gui.ResetOnSpawn = false

local banner = Instance.new("TextLabel")
banner.Name = "Banner"
banner.AnchorPoint = Vector2.new(0.5, 0)
banner.Position = UDim2.new(0.5, 0, 0, 24)
banner.Size = UDim2.fromOffset(420, 48)
banner.BackgroundColor3 = Color3.fromRGB(24, 26, 31)
banner.TextColor3 = Color3.fromRGB(240, 240, 240)
banner.TextSize = 22
banner.Visible = false
banner.Parent = gui
gui.Parent = playerGui

local shown = 0
announce.OnClientEvent:Connect(function(message: string, seconds: number)
	if type(message) ~= "string" or type(seconds) ~= "number" then
		return
	end
	shown += 1
	local token = shown
	banner.Text = message
	banner.Visible = true
	task.delay(math.clamp(seconds, 1, 15), function()
		if shown == token then
			banner.Visible = false
		end
	end)
end)
```

```lua
--!strict
-- ModuleScript: ServerScriptService.RoundAnnouncer (server side, sends data only)
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local announce = Instance.new("RemoteEvent")
announce.Name = "Announce"
announce.Parent = ReplicatedStorage

local function announceAll(message: string)
	announce:FireAllClients(message, 4)
end

return announceAll
```

- The client keeps full control of its UI (animations, layout per device), and the server sends a few bytes instead of instances.
- The token check stops an older announcement's timer from hiding a newer one.
- Players who join mid-round can ask for the current state with a RemoteFunction or read replicated attributes when the UI starts.

# Test
```lua
__setClient(true)
__makePlayer(1, "Ava")
local remote = Instance.new("RemoteEvent")
remote.Name = "Announce"
remote.Parent = game:GetService("ReplicatedStorage")
```
```lua
local gui = game:GetService("Players").LocalPlayer.PlayerGui:FindFirstChild("Announcements")
local remote = game:GetService("ReplicatedStorage").Announce
check("client built its own gui", gui ~= nil and gui.Banner.Visible == false)
remote.OnClientEvent:Fire("Round starts!", 3)
check("message shown", gui.Banner.Visible and gui.Banner.Text == "Round starts!")
__advance(2)
remote.OnClientEvent:Fire("Sudden death", 3)
__advance(1.5)
check("newer message not hidden by older timer", gui.Banner.Visible and gui.Banner.Text == "Sudden death")
__advance(2)
check("hidden after its time", gui.Banner.Visible == false)
remote.OnClientEvent:Fire(42, "x")
check("bad payload ignored", gui.Banner.Visible == false)
```
