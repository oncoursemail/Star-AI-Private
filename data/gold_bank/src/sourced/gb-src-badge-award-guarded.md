---
id: gb-src-badge-award-guarded
category: gameplay-systems
topics: BadgeService, AwardBadgeAsync, UserHasBadgeAsync, GetBadgeInfoAsync, pcall, caching
source: adapted
source_id: creator-docs
source_path: content/en-us/production/publishing/badges.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
I award a "Reached the Summit" badge when players touch the top checkpoint. Players stand on it and my output fills with badge errors and throttling warnings because it tries to award on every touch. How should badge awarding be structured?

# Answer
Award from the server through one helper that remembers who already has the badge this session, checks ownership once with `UserHasBadgeAsync`, confirms the badge is enabled with `GetBadgeInfoAsync`, and wraps every BadgeService call in `pcall`. Touch spam then costs nothing after the first attempt.

```lua
--!strict
local BadgeService = game:GetService("BadgeService")
local Players = game:GetService("Players")

local Badges = {}

local owned: { [number]: { [number]: boolean } } = {}
local pending: { [number]: { [number]: boolean } } = {}
local enabled: { [number]: boolean } = {}

-- One lookup per badge per server, and a disabled badge is remembered too. A failed lookup is not cached.
local function isEnabled(badgeId: number): boolean
	local known = enabled[badgeId]
	if known ~= nil then
		return known
	end
	local ok, info = pcall(BadgeService.GetBadgeInfoAsync, BadgeService, badgeId)
	if not ok then
		return false
	end
	local result = info.IsEnabled == true
	enabled[badgeId] = result
	return result
end

local function setFlag(map: { [number]: { [number]: boolean } }, userId: number, badgeId: number, value: boolean?)
	local perUser = map[userId]
	if not perUser then
		if value == nil then
			return
		end
		perUser = {}
		map[userId] = perUser
	end
	perUser[badgeId] = value
end

function Badges.award(player: Player, badgeId: number): boolean
	local userId = player.UserId
	local userOwned = owned[userId]
	local userPending = pending[userId]
	if (userOwned and userOwned[badgeId]) or (userPending and userPending[badgeId]) then
		return false
	end
	setFlag(pending, userId, badgeId, true)

	if not isEnabled(badgeId) then
		setFlag(pending, userId, badgeId, nil)
		return false
	end

	local okHas, hasBadge = pcall(BadgeService.UserHasBadgeAsync, BadgeService, userId, badgeId)
	if okHas and hasBadge then
		if player.Parent ~= nil then
			setFlag(owned, userId, badgeId, true)
		end
		setFlag(pending, userId, badgeId, nil)
		return false
	end

	local okAward, awarded = pcall(BadgeService.AwardBadgeAsync, BadgeService, userId, badgeId)
	setFlag(pending, userId, badgeId, nil)
	if not okAward or awarded ~= true then
		warn("Badge award failed:", awarded)
		return false
	end
	if player.Parent ~= nil then
		setFlag(owned, userId, badgeId, true)
	end
	return true
end

Players.PlayerRemoving:Connect(function(player: Player)
	owned[player.UserId] = nil
	pending[player.UserId] = nil
end)

return Badges
```

- The `pending` flag stops a second touch from starting another award while the first request is still yielding.
- Badge info is cached per badge (a disabled badge too), so touches on a disabled badge make no web calls at all; the cache lasts until the server closes, so enabling a badge later needs a new server.
- A confirmed ownership result is cached per player and badge for the session; a failed `UserHasBadgeAsync` or `GetBadgeInfoAsync` call is not cached and is tried again on the next touch.
- A failed award (an error, or `AwardBadgeAsync` returning false) is not cached, so the next touch retries it.
- Ownership is cached only while the player is still in the server, so someone who leaves mid-award is not re-added after `PlayerRemoving` cleared them.

# Test
```lua
local BadgeService = game:GetService("BadgeService")
local p = __makePlayer(7, "Climber")
check("first award succeeds", item.award(p, 555) == true)
check("repeat award skipped", item.award(p, 555) == false)
check("badge recorded by the service", BadgeService:UserHasBadgeAsync(7, 555) == true)
local veteran = __makePlayer(8, "Veteran")
BadgeService.__awarded[8] = { [555] = true }
check("already-owned badge not re-awarded", item.award(veteran, 555) == false)

local infoCalls = 0
local failInfo = true
BadgeService.GetBadgeInfoAsync = function(_: any, badgeId: number)
	infoCalls += 1
	if badgeId == 557 and failInfo then
		error("HTTP 500", 0)
	end
	return { IsEnabled = badgeId ~= 556, Name = "Badge" }
end
for _ = 1, 3 do
	check("disabled badge is never awarded", item.award(p, 556) == false)
end
check("disabled badge info fetched once", infoCalls == 1)
check("failed info lookup awards nothing", item.award(p, 557) == false and BadgeService:UserHasBadgeAsync(7, 557) == false)
failInfo = false
check("failed info lookup is retried on the next touch", item.award(p, 557) == true and infoCalls == 3)
```
