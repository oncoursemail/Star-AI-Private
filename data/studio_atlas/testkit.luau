--!nocheck
-- Tiny test kit and fakes shared by the Lune tests. Fakes are deliberately simple and deterministic.
local process = require("@lune/process")

local Kit = {}
local passed, failed = 0, 0

function Kit.test(name, fn)
	local ok, err = pcall(fn)
	if ok then
		passed += 1
	else
		failed += 1
		print("FAIL " .. name .. ": " .. tostring(err))
	end
end

function Kit.eq(actual, expected, msg)
	if actual ~= expected then
		error(`{msg or "eq"}: expected {tostring(expected)}, got {tostring(actual)}`, 2)
	end
end

function Kit.truthy(value, msg)
	if not value then
		error(msg or "expected a truthy value", 2)
	end
end

function Kit.finish(name)
	print(`{name}: {passed} passed, {failed} failed`)
	if failed > 0 then
		process.exit(1)
	end
end

local function deepCopy(v)
	if type(v) ~= "table" then
		return v
	end
	local out = {}
	for k, x in v do
		out[k] = deepCopy(x)
	end
	return out
end
Kit.deepCopy = deepCopy

function Kit.clock(start)
	local t = start or 1000
	return {
		now = function()
			return t
		end,
		advance = function(dt)
			t += dt
		end,
	}
end

function Kit.signal()
	local handlers = {}
	local signal = {}
	function signal:Connect(fn)
		table.insert(handlers, fn)
		return {
			Disconnect = function()
				local i = table.find(handlers, fn)
				if i then
					table.remove(handlers, i)
				end
			end,
		}
	end
	function signal:Fire(...)
		for _, fn in table.clone(handlers) do
			fn(...)
		end
	end
	return signal
end

-- DataStore double: UpdateAsync keeps the stored value when the transform returns nil, like Roblox.
function Kit.datastore()
	local ds = { data = {}, failures = 0, updates = 0 }
	function ds:UpdateAsync(key, transform)
		if self.failures > 0 then
			self.failures -= 1
			error("simulated DataStore failure")
		end
		local old = self.data[key]
		local new = transform(deepCopy(old))
		if new == nil then
			return deepCopy(old)
		end
		self.updates += 1
		self.data[key] = deepCopy(new)
		return deepCopy(new)
	end
	return ds
end

function Kit.player(userId, name)
	return { UserId = userId, Name = name or ("Player" .. userId) }
end

return Kit
