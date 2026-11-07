---
id: gb-sec-token-bucket-limiter
category: remote-security
topics: rate limit, token bucket, RemoteEvent, anti-spam
source: original
---
# Request
Players can spam my RemoteEvents. I want a reusable per-player rate limiter for the server that allows short bursts but caps the long-run rate, and forgets players when they leave.

# Answer
A token bucket per player: each request costs one token, tokens refill continuously up to a burst size. Keep it in a ModuleScript so every remote handler can share it.

```lua
--!strict
-- ModuleScript: ServerScriptService.RateLimiter
local Players = game:GetService("Players")

export type Limiter = {
	allow: (player: Player) -> boolean,
}

type Bucket = { tokens: number, updated: number }

local RateLimiter = {}

function RateLimiter.new(ratePerSecond: number, burst: number): Limiter
	assert(ratePerSecond > 0 and burst >= 1, "rate must be positive and burst at least 1")
	local buckets: { [Player]: Bucket } = {}

	Players.PlayerRemoving:Connect(function(player)
		buckets[player] = nil
	end)

	local function allow(player: Player): boolean
		local now = os.clock()
		local bucket = buckets[player]
		if bucket == nil then
			bucket = { tokens = burst, updated = now }
			buckets[player] = bucket
		end
		bucket.tokens = math.min(burst, bucket.tokens + (now - bucket.updated) * ratePerSecond)
		bucket.updated = now
		if bucket.tokens < 1 then
			return false
		end
		bucket.tokens -= 1
		return true
	end

	return { allow = allow }
end

return RateLimiter
```

- `os.clock()` is monotonic, so changing the server's wall clock cannot refill buckets.
- Rejected requests cost nothing, so a spammer stays limited instead of being locked out forever.
- Use it at the top of a handler: `if not limiter.allow(player) then return end`.

# Test
```lua
local limiter = item.new(2, 3)
local p = __makePlayer(1, "Spammer")
local allowed = 0
for _ = 1, 10 do
	if limiter.allow(p) then
		allowed += 1
	end
end
check("burst of 3 then blocked", allowed == 3)
__advance(1)
check("refills 2 per second", limiter.allow(p) and limiter.allow(p) and not limiter.allow(p))
local other = __makePlayer(2, "Calm")
check("buckets are per player", limiter.allow(other))
__removePlayer(p)
__advance(0.01)
check("fresh bucket after leaving and a new player object", limiter.allow(__makePlayer(1, "Spammer")))
```
