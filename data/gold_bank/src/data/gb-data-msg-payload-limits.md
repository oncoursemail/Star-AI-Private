---
id: gb-data-msg-payload-limits
category: messaging
topics: MessagingService, message size, topic length, publish rate, limits
source: original
---
# Request
My cross-server trade feed sometimes stops working and I see MessagingService errors about size and request limits. What are the limits I need to respect, and can you write a publish helper that checks them before sending?

# Answer
A message must stay under 1 KB once encoded, topic names are limited to 80 characters, and each server has a publish budget per minute that grows with its player count (check the current numbers on the MessagingService limits page). A small helper can check size and topic length up front, keep a per-server token bucket that stays below that budget, and report why a publish was refused instead of erroring.

```lua
--!strict
-- ModuleScript: ServerScriptService.SafePublish
local HttpService = game:GetService("HttpService")
local MessagingService = game:GetService("MessagingService")
local Players = game:GetService("Players")

export type Result = "ok" | "too large" | "bad topic" | "rate limited" | "error"

local MAX_BYTES = 1000 -- a little under the 1 KB limit for safety
local MAX_TOPIC = 80

local SafePublish = {}

local DOCUMENTED_BASE = 150 -- per-minute limit from the MessagingService limits page when this was written
local DOCUMENTED_PER_PLAYER = 60
local SAFETY = 0.8 -- stay under the limit so retries and other scripts have headroom

local tokens = math.floor(SAFETY * DOCUMENTED_BASE)
local updated = os.clock()

local function budgetPerMinute(): number
	return math.floor(SAFETY * (DOCUMENTED_BASE + DOCUMENTED_PER_PLAYER * #Players:GetPlayers()))
end

local function takeToken(): boolean
	local now = os.clock()
	local capacity = budgetPerMinute()
	tokens = math.min(capacity, tokens + (now - updated) * capacity / 60)
	updated = now
	if tokens < 1 then
		return false
	end
	tokens -= 1
	return true
end

function SafePublish.size(message: any): number
	local ok, encoded = pcall(HttpService.JSONEncode, HttpService, message)
	return if ok then #encoded else math.huge
end

function SafePublish.publish(topic: string, message: any): Result
	if #topic == 0 or #topic > MAX_TOPIC then
		return "bad topic"
	end
	if SafePublish.size(message) > MAX_BYTES then
		return "too large"
	end
	if not takeToken() then
		return "rate limited"
	end
	local ok = pcall(function()
		MessagingService:PublishAsync(topic, message)
	end)
	return if ok then "ok" else "error"
end

return SafePublish
```

- Send ids, not objects: a trade feed message like `{ s = sellerId, i = "ruby_blade", p = 500 }` is a few dozen bytes; receivers look up names and details themselves.
- When "rate limited" comes back, batch: collect events for a second or two and publish one message with a short list, which also cuts receive costs in every server.
- A message that `JSONEncode` cannot encode makes `size` return `math.huge`, so it is refused before it reaches the service; re-check the two documented numbers against the limits page, since they can change.

# Test
```lua
check("small messages publish", item.publish("TradeFeed", { s = 1, i = "ruby_blade", p = 500 }) == "ok")
check("topics over 80 characters are refused", item.publish(string.rep("t", 81), {}) == "bad topic")
check("empty topics are refused", item.publish("", {}) == "bad topic")
check("messages over 1 KB are refused", item.publish("TradeFeed", { text = string.rep("x", 1200) }) == "too large")
check("unencodable messages are refused", item.publish("TradeFeed", { value = 0 / 0 }) == "too large")

local results = { ok = 0, limited = 0 }
for _ = 1, 200 do
	local r = item.publish("TradeFeed", { n = 1 })
	if r == "ok" then
		results.ok += 1
	elseif r == "rate limited" then
		results.limited += 1
	end
end
check("a burst beyond the budget is rate limited", results.limited > 0 and results.ok < 200)
__advance(60)
check("budget refills over time", item.publish("TradeFeed", { n = 2 }) == "ok")
```
