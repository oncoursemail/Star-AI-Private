-- Minimal Roblox globals for running MetallicApi.luau under Lune (tests only): HttpService over @lune/net.
local net = require("@lune/net")
local serde = require("@lune/serde")

local Secret = {}
Secret.__index = Secret
function Secret.new(v: string)
	return setmetatable({ _v = v }, Secret)
end
function Secret:AddPrefix(p: string)
	return Secret.new(p .. self._v)
end

local HttpService = {}
function HttpService:GetSecret(name: string)
	local v = _G.SHIM_SECRETS[name]
	assert(v, "no secret " .. name)
	return Secret.new(v)
end
function HttpService:JSONEncode(v)
	return serde.encode("json", v)
end
function HttpService:JSONDecode(s: string)
	return serde.decode("json", s)
end
function HttpService:UrlEncode(s: string)
	return (string.gsub(s, "[^%w%-_%.~]", function(c)
		return string.format("%%%02X", string.byte(c))
	end))
end
function HttpService:RequestAsync(req)
	local headers = {}
	for k, v in req.Headers do
		headers[k] = if type(v) == "table" then v._v else v -- a Secret becomes its value only inside the request
	end
	local res = net.request({ url = req.Url, method = req.Method, headers = headers, body = req.Body })
	return { Success = res.ok, StatusCode = res.statusCode, Body = res.body, Headers = res.headers }
end

local RunService = { server = true }
function RunService:IsServer()
	return self.server
end

local services = { HttpService = HttpService, RunService = RunService }
_G.SHIM_SECRETS = {}
return {
	game = {
		GetService = function(_, name: string)
			return services[name]
		end,
	},
	RunService = RunService,
}
