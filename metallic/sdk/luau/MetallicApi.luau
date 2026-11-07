--!strict
-- Metallic API v1 client for Roblox game servers (HttpService). SERVER ONLY.
--
--   local MetallicApi = require(game:GetService("ServerScriptService").MetallicApi)
--   local api = MetallicApi.new({ baseUrl = "https://metallic-api.example:8476", secretName = "metallic_api_key" })
--   local ok, res = api:serverHeartbeat({ game = "RB", server_id = game.JobId, players = #game.Players:GetPlayers() })
--
-- Key handling: store the server key (msk_...) in the experience's secrets (Creator Hub > Secrets) and name it
-- here; HttpService:GetSecret returns a Secret that can only be sent in a request header, never read or printed.
-- Put this module in ServerScriptService or ServerStorage (clients cannot see those); it refuses to run on a client.
-- Every method returns (ok: boolean, result: table). On failure result = { status, error, text, retryAfter }.
-- GENERATED from metallic/metallic/api/openapi.json by `python -m metallic.api.sdkgen`. Do not edit by hand.

local HttpService = game:GetService("HttpService")
local RunService = game:GetService("RunService")

local MetallicApi = {}
MetallicApi.__index = MetallicApi
MetallicApi.VERSION = "1.0.0"

export type Config = { baseUrl: string, secretName: string?, key: any? }

function MetallicApi.new(config: Config)
	assert(RunService:IsServer(), "MetallicApi is server-only: never give a server key to a client")
	assert(type(config.baseUrl) == "string", "baseUrl is required")
	local key = config.key
	if key == nil and config.secretName then
		key = HttpService:GetSecret(config.secretName)
	end
	local self = setmetatable({}, MetallicApi)
	self._base = string.gsub(config.baseUrl, "/$", "")
	self._auth = nil
	if typeof(key) == "string" then
		self._auth = "Bearer " .. key -- plain strings only for Studio tests; use secretName in live games
	elseif key ~= nil then
		self._auth = key:AddPrefix("Bearer ")
	end
	return self
end

local function encode(s: string): string
	return HttpService:UrlEncode(s)
end

function MetallicApi:request(method: string, path: string, body: any?, query: { [string]: any }?): (boolean, any)
	local url = self._base .. path
	if query then
		local parts = {}
		for k, v in query do
			if v ~= nil then
				table.insert(parts, encode(k) .. "=" .. encode(tostring(v)))
			end
		end
		table.sort(parts)
		if #parts > 0 then
			url ..= "?" .. table.concat(parts, "&")
		end
	end
	local headers: { [string]: any } = { Accept = "application/json" }
	if self._auth ~= nil then
		headers.Authorization = self._auth
	end
	local req: { [string]: any } = { Url = url, Method = method, Headers = headers }
	if body ~= nil then
		headers["Content-Type"] = "application/json"
		req.Body = HttpService:JSONEncode(body)
	end
	local sent, res = pcall(function()
		return HttpService:RequestAsync(req)
	end)
	if not sent then
		return false, { status = 0, error = "unreachable", text = tostring(res) }
	end
	local data = {}
	if res.Body and #res.Body > 0 then
		local parsed, obj = pcall(function()
			return HttpService:JSONDecode(res.Body)
		end)
		if parsed then
			data = obj
		end
	end
	if res.StatusCode >= 400 then
		local ra = res.Headers and (res.Headers["retry-after"] or res.Headers["Retry-After"])
		return false, { status = res.StatusCode, error = data.error or "error", text = data.text or "Request failed.",
			retryAfter = ra and tonumber(ra) or nil }
	end
	return true, data
end

-- Service health. Public.
function MetallicApi:health(): (boolean, any)
	return self:request("GET", "/health", nil)
end

-- This document. Public.
function MetallicApi:getOpenapi(): (boolean, any)
	return self:request("GET", "/v1/openapi.json", nil)
end

-- Every scope and who may hold it. Public.
function MetallicApi:listScopes(): (boolean, any)
	return self:request("GET", "/v1/scopes", nil)
end

-- Make a scoped token from a sign-in token. Public.
function MetallicApi:exchangeToken(body: { [string]: any }): (boolean, any)
	return self:request("POST", "/v1/oauth/token", body)
end

-- Revoke a scoped token. Public.
function MetallicApi:revokeToken(body: { [string]: any }): (boolean, any)
	return self:request("POST", "/v1/oauth/revoke", body)
end

-- News posts. Public.
function MetallicApi:listNews(query: { [string]: any }?): (boolean, any)
	return self:request("GET", "/v1/news", nil, query)
end

-- RC, MC, RB and PX status. Public.
function MetallicApi:listGames(): (boolean, any)
	return self:request("GET", "/v1/games", nil)
end

-- One game's status. Public.
function MetallicApi:getGame(game: string): (boolean, any)
	return self:request("GET", "/v1/games/" .. encode(game), nil)
end

-- Every Rec Room revival: status and people online. Public.
function MetallicApi:listRevivals(): (boolean, any)
	return self:request("GET", "/v1/revivals", nil)
end

-- One revival's status and people online. Public.
function MetallicApi:getRevival(revival: string): (boolean, any)
	return self:request("GET", "/v1/revivals/" .. encode(revival), nil)
end

-- Latest news from the Rec Room revivals. Public.
function MetallicApi:listRevivalNews(): (boolean, any)
	return self:request("GET", "/v1/revival-news", nil)
end

-- Release channels. Public.
function MetallicApi:listReleases(): (boolean, any)
	return self:request("GET", "/v1/releases", nil)
end

-- A verified release channel. Public.
function MetallicApi:getRelease(channel: string): (boolean, any)
	return self:request("GET", "/v1/releases/" .. encode(channel), nil)
end

-- PX progress (public view). Public.
function MetallicApi:getProgress(): (boolean, any)
	return self:request("GET", "/v1/progress", nil)
end

-- One project's progress. Public.
function MetallicApi:getProjectProgress(project: string): (boolean, any)
	return self:request("GET", "/v1/progress/" .. encode(project), nil)
end

-- Litha and STAR status (read-only). Public.
function MetallicApi:getProjectStatus(): (boolean, any)
	return self:request("GET", "/v1/projects/status", nil)
end

-- Report a live game server. Needs server key [servers:write].
function MetallicApi:serverHeartbeat(body: { [string]: any }): (boolean, any)
	return self:request("POST", "/v1/servers/heartbeat", body)
end

-- Report a player joining or leaving (sends player.joined / player.left). Needs server key [servers:write].
function MetallicApi:serverEvent(body: { [string]: any }): (boolean, any)
	return self:request("POST", "/v1/servers/events", body)
end

-- Check a player's Metallic sign-in token. Needs server key [players:read].
function MetallicApi:verifyPlayer(body: { [string]: any }): (boolean, any)
	return self:request("POST", "/v1/players/verify", body)
end

-- Your webhooks. Needs server key [webhooks:manage] or sign-in [webhooks:manage].
function MetallicApi:listWebhooks(): (boolean, any)
	return self:request("GET", "/v1/webhooks", nil)
end

-- Add a webhook (the secret is shown once). Needs server key [webhooks:manage] or sign-in [webhooks:manage].
function MetallicApi:createWebhook(body: { [string]: any }): (boolean, any)
	return self:request("POST", "/v1/webhooks", body)
end

-- Delete a webhook. Needs server key [webhooks:manage] or sign-in [webhooks:manage].
function MetallicApi:deleteWebhook(webhook_id: string): (boolean, any)
	return self:request("DELETE", "/v1/webhooks/" .. encode(webhook_id), nil)
end

-- Delivery log (newest first). Needs server key [webhooks:manage] or sign-in [webhooks:manage].
function MetallicApi:listDeliveries(webhook_id: string, query: { [string]: any }?): (boolean, any)
	return self:request("GET", "/v1/webhooks/" .. encode(webhook_id) .. "/deliveries", nil, query)
end

-- Send a signed `ping` event. Needs server key [webhooks:manage] or sign-in [webhooks:manage].
function MetallicApi:pingWebhook(webhook_id: string): (boolean, any)
	return self:request("POST", "/v1/webhooks/" .. encode(webhook_id) .. "/ping", nil)
end

return MetallicApi
