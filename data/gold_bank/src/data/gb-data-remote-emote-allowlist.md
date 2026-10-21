---
id: gb-data-remote-emote-allowlist
category: remote-security
topics: emotes, allowlist, Animator, game pass, RemoteEvent
source: original
---
# Request
Players pick an emote from a wheel and the client sends the animation id to the server, which plays it on their character. Some emotes are supposed to be game-pass only, but exploiters play those (and random animations from the catalog). How should the server handle emote requests?

# Answer
The client sends an emote name, never an animation id. The server keeps the emote list: each name maps to an Animation object stored in ServerStorage and an optional game pass. The server checks the name, ownership (cached), the cooldown and a living character, then plays the animation through the character's Animator.

```lua
--!strict
-- ModuleScript: ServerScriptService.Emotes
local MarketplaceService = game:GetService("MarketplaceService")
local Players = game:GetService("Players")

export type EmoteDef = { animation: Animation, passId: number? }
export type Result = "ok" | "unknown" | "locked" | "cooldown" | "no character"

local COOLDOWN = 1.5

local Emotes = {}

function Emotes.new(defs: { [string]: EmoteDef }): (player: Player, name: unknown) -> Result
	local lastPlayed: { [Player]: number } = {}
	local tracks: { [Player]: AnimationTrack } = {}
	local ownsCache: { [Player]: { [number]: boolean } } = {}

	Players.PlayerRemoving:Connect(function(player: Player)
		lastPlayed[player], tracks[player], ownsCache[player] = nil, nil, nil
	end)

	-- A purchase made in this session must unlock the emote now, not after a rejoin.
	MarketplaceService.PromptGamePassPurchaseFinished:Connect(function(player: Player, passId: number, purchased: boolean)
		local cache = ownsCache[player]
		if purchased and cache then
			cache[passId] = true
		end
	end)

	local function owns(player: Player, passId: number): boolean
		local cache = ownsCache[player] or {}
		ownsCache[player] = cache
		if cache[passId] == nil then
			local ok, result = pcall(function()
				return MarketplaceService:UserOwnsGamePassAsync(player.UserId, passId)
			end)
			if not ok then
				return false -- do not cache failures; try again next time
			end
			cache[passId] = result
		end
		return cache[passId]
	end

	return function(player: Player, name: unknown): Result
		local def = if type(name) == "string" then defs[name] else nil
		if def == nil then
			return "unknown"
		end
		if def.passId and not owns(player, def.passId) then
			return "locked"
		end
		local now = os.clock()
		local last = lastPlayed[player]
		if last and now - last < COOLDOWN then
			return "cooldown"
		end
		local character = player.Character
		local humanoid: Humanoid? = if character then character:FindFirstChildOfClass("Humanoid") else nil
		local animator: Animator? = if humanoid then humanoid:FindFirstChildOfClass("Animator") else nil
		if humanoid == nil or animator == nil or humanoid.Health <= 0 then
			return "no character"
		end
		lastPlayed[player] = now
		local previous = tracks[player]
		if previous then
			previous:Stop()
			previous:Destroy()
		end
		local track = animator:LoadAnimation(def.animation)
		tracks[player] = track
		track:Play()
		return "ok"
	end
end

return Emotes
```

- Animations played through the character's Animator on the server replicate to everyone, so the client never needs to send an id at all.
- Each new emote stops and destroys the previous track, so spamming emotes does not pile up AnimationTracks on the Animator.
- Keep the Animation objects in ServerStorage with their ids set in Studio; the wheel UI only needs names and icons.

# Test
```lua
local function anim()
	local a = Instance.new("Animation")
	a.AnimationId = "rbxassetid://0"
	return a
end
local play = item.new({ Wave = { animation = anim() }, Dab = { animation = anim(), passId = 55 } })
local p = __makePlayer(1, "Dancer")
local character = __makeCharacter(p)

check("a free emote plays", play(p, "Wave") == "ok")
local animator = character.Humanoid.Animator
check("the track is playing on the character's Animator", #animator:GetPlayingAnimationTracks() >= 1)
check("spamming is limited", play(p, "Wave") == "cooldown")
local firstTrack = animator:GetPlayingAnimationTracks()[1]
local destroyed = false
firstTrack.Destroying:Connect(function()
	destroyed = true
end)
__advance(2)
check("locked emotes need the game pass", play(p, "Dab") == "locked")
game:GetService("MarketplaceService").__owned[1] = { [55] = true }
game:GetService("MarketplaceService").PromptGamePassPurchaseFinished:Fire(p, 55, true)
check("a purchase in this session unlocks the emote at once", play(p, "Dab") == "ok")
check("the previous track is stopped and destroyed", destroyed and not firstTrack.IsPlaying)
local fresh = __makePlayer(2, "Owner")
__makeCharacter(fresh)
game:GetService("MarketplaceService").__owned[2] = { [55] = true }
check("owners can play the locked emote", play(fresh, "Dab") == "ok")
check("unknown names and raw ids are refused", play(p, "rbxassetid://123") == "unknown" and play(p, 123) == "unknown")
fresh.Character.Humanoid.Health = 0
__advance(2)
check("dead characters cannot emote", play(fresh, "Wave") == "no character")
```
