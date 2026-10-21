The original code, unchanged.

```lua
-- EventBus: in-game events (RoundStarted, PlayerSplatted, FlagCaptured) shared by server modules.
local EventBus = {}
EventBus.__index = EventBus

function EventBus.new()
	local self = setmetatable({}, EventBus)
	self.handlers = {}
	self.counts = {}
	return self
end

function EventBus:on(name, fn)
	local list = self.handlers[name]
	if list == nil then
		list = {}
		self.handlers[name] = list
	end
	table.insert(list, fn)
	local connection = {}
	function connection.disconnect()
		local index = table.find(list, fn)
		if index then
			table.remove(list, index)
		end
	end
	return connection
end

function EventBus:emit(name, ...)
	self.counts[name] = (self.counts[name] or 0) + 1
	local list = self.handlers[name]
	if list == nil then
		return 0
	end
	local ran = 0
	local i = 1
	while i <= #list do
		list[i](...)
		ran += 1
		i += 1
	end
	return ran
end

function EventBus:count(name)
	return self.counts[name] or 0
end

function EventBus:listeners(name)
	local list = self.handlers[name]
	return list and #list or 0
end

function EventBus:clear(name)
	self.handlers[name] = nil
end

return EventBus
```
