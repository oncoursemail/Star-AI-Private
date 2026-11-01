--!strict
-- ServerScriptService/MetallicHeartbeat (Script). Reports this server to Metallic every 30 s.
-- Setup: Game Settings > Security > Allow HTTP Requests; add the server key as a secret named "metallic_api_key"
-- (Creator Hub > your experience > Secrets, scoped to the API's domain). Never put the key in a script or attribute.
local Players = game:GetService("Players")
local ServerScriptService = game:GetService("ServerScriptService")
local MetallicApi = require(ServerScriptService:WaitForChild("MetallicApi"))

local api = MetallicApi.new({ baseUrl = "https://metallic-api.example:8476", secretName = "metallic_api_key" })
local serverId = if game.JobId ~= "" then game.JobId else "studio"

local function beat()
	local ok, res = api:serverHeartbeat({
		game = "RB",
		server_id = string.sub(serverId, 1, 64),
		players = #Players:GetPlayers(),
		max_players = Players.MaxPlayers,
	})
	if not ok then
		warn("Metallic heartbeat failed:", res.status, res.error)
		return res.retryAfter
	end
	return nil
end

task.spawn(function()
	while true do
		local wait = beat()
		task.wait(wait or 30)
	end
end)
