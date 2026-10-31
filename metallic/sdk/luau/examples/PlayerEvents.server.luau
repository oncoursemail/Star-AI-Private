--!strict
-- ServerScriptService/MetallicPlayerEvents (Script). Sends player.joined / player.left with counts only:
-- no names and no Roblox user ids leave the server (webhook receivers get the server id and the player count).
local Players = game:GetService("Players")
local ServerScriptService = game:GetService("ServerScriptService")
local MetallicApi = require(ServerScriptService:WaitForChild("MetallicApi"))

local api = MetallicApi.new({ baseUrl = "https://metallic-api.example:8476", secretName = "metallic_api_key" })
local serverId = string.sub(if game.JobId ~= "" then game.JobId else "studio", 1, 64)

local function report(kind: string, count: number)
	task.spawn(function()
		local ok, res = api:serverEvent({ type = kind, game = "RB", server_id = serverId, players = count })
		if not ok then
			warn("Metallic event failed:", res.status, res.error)
		end
	end)
end

Players.PlayerAdded:Connect(function()
	report("player.joined", #Players:GetPlayers())
end)
Players.PlayerRemoving:Connect(function()
	report("player.left", #Players:GetPlayers() - 1)
end)
