-- Minimal JSON encoder for twin results (runtime-agnostic: no @lune/serde).
local Json = {}

local ESC = { ['"'] = '\\"', ["\\"] = "\\\\", ["\b"] = "\\b", ["\f"] = "\\f", ["\n"] = "\\n", ["\r"] = "\\r", ["\t"] = "\\t" }

local function encodeString(s)
	return '"' .. s:gsub('[%c"\\]', function(c)
		return ESC[c] or string.format("\\u%04x", c:byte())
	end) .. '"'
end

local function encode(v, depth)
	local t = type(v)
	if v == nil then
		return "null"
	elseif t == "boolean" then
		return v and "true" or "false"
	elseif t == "number" then
		if v ~= v or v == math.huge or v == -math.huge then
			return "null"
		end
		if v == math.floor(v) and math.abs(v) < 1e15 then
			return string.format("%d", v)
		end
		return string.format("%.6g", v)
	elseif t == "string" then
		return encodeString(v)
	elseif t == "table" then
		if depth > 20 then
			return '"<too deep>"'
		end
		local n = #v
		local count = 0
		for _ in v do
			count += 1
		end
		local parts = {}
		if n > 0 and n == count then
			for i = 1, n do
				parts[i] = encode(v[i], depth + 1)
			end
			return "[" .. table.concat(parts, ",") .. "]"
		end
		if count == 0 then
			return "{}"
		end
		local keys = {}
		for k in v do
			table.insert(keys, tostring(k))
		end
		table.sort(keys)
		for _, k in keys do
			local x = v[k]
			if x == nil then
				x = v[tonumber(k)]
			end
			table.insert(parts, encodeString(k) .. ":" .. encode(x, depth + 1))
		end
		return "{" .. table.concat(parts, ",") .. "}"
	end
	return encodeString("<" .. t .. ">")
end

function Json.encode(v)
	return encode(v, 0)
end

return Json
