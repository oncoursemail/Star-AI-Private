---
id: gb-src-profilestore-sessions
category: datastore-safety
topics: ProfileStore, session locking, StartSessionAsync, Reconcile, EndSession, OnSessionEnd, GDPR AddUserId
source: adapted
source_id: profilestore
source_path: docs/tutorial/index.md
source_commit: 45c9847cbcf1fc260369c50eb335aba7c35aecdd
---
# Request
I've had item duplication when players hop between servers quickly: the old server saves after the new one loaded. Someone told me to use ProfileStore for session locking. What does a correct player data setup with ProfileStore look like?

# Answer
ProfileStore gives each profile a session lock: only one server can hold a player's profile at a time, and it autosaves `Profile.Data` while the session is open. Start the session on join (cancel it if the player leaves while it loads), reconcile against the template, end it on leave, and kick if the session ends unexpectedly (for example another server took it).

```lua
--!strict
local Players = game:GetService("Players")
local ServerScriptService = game:GetService("ServerScriptService")

local ProfileStore = require(ServerScriptService:WaitForChild("ProfileStore"))

local PROFILE_TEMPLATE = {
	Cash = 0,
	Items = {} :: { string },
}

local PlayerStore = ProfileStore.New("PlayerStore", PROFILE_TEMPLATE)
local profiles: { [Player]: any } = {}

local function onPlayerAdded(player: Player)
	local profile = PlayerStore:StartSessionAsync(tostring(player.UserId), {
		Cancel = function(): boolean
			return player.Parent ~= Players
		end,
	})
	if profile == nil then
		player:Kick("Could not load your data. Please rejoin.")
		return
	end

	profile:AddUserId(player.UserId)
	profile:Reconcile()
	profile.OnSessionEnd:Connect(function()
		profiles[player] = nil
		player:Kick("Your data session ended. Please rejoin.")
	end)

	if player.Parent == Players then
		profiles[player] = profile
		player:SetAttribute("DataLoaded", true)
	else
		profile:EndSession()
	end
end

local function getData(player: Player): typeof(PROFILE_TEMPLATE)?
	local profile = profiles[player]
	return if profile then profile.Data else nil
end

for _, player in Players:GetPlayers() do
	task.spawn(onPlayerAdded, player)
end
Players.PlayerAdded:Connect(onPlayerAdded)
Players.PlayerRemoving:Connect(function(player: Player)
	local profile = profiles[player]
	if profile then
		profile:EndSession()
	end
end)

return { getData = getData }
```

- The session lock is what prevents the duplication: the new server's `StartSessionAsync` waits for (or steals from) the old session, which saves and stops writing first.
- `Cancel` stops waiting if the player leaves during the load, and a profile that arrives after they left is ended at once.
- `AddUserId` tags the key with the user id so GDPR erasure requests can find it.
- Game code reads and writes `getData(player).Cash`; ProfileStore saves it periodically and on `EndSession`, including at server shutdown.
