---
id: gb-world-anim-track-cache
category: animation
topics: Animator, LoadAnimation, track cache, AnimationTrack, memory
source: original
---
# Request
My sword LocalScript calls `animator:LoadAnimation(slashAnim)` every time I click. After a few minutes of fighting the slash stops playing and the output warns about too many animation tracks. How should I be loading animations?

# Answer
Load each Animation once per character and reuse the track. A small cache keyed by animation name owns the tracks, hands back the same one on every play, and stops everything when the character goes away so a respawn starts clean.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.AnimationCache
export type Cache = {
	playTrack: (name: string, fadeTime: number?, weight: number?, speed: number?) -> AnimationTrack?,
	stopTrack: (name: string, fadeTime: number?) -> (),
	stopAll: (fadeTime: number?) -> (),
	cleanup: () -> (),
}

local AnimationCache = {}

function AnimationCache.new(character: Model, animations: Instance): Cache
	local humanoid = character:FindFirstChildOfClass("Humanoid")
	local animator = if humanoid then humanoid:FindFirstChildOfClass("Animator") else nil
	assert(animator, "character needs a Humanoid with an Animator")

	local tracks: { [string]: AnimationTrack } = {}
	local alive = true

	local function get(name: string): AnimationTrack?
		local cached = tracks[name]
		if cached then
			return cached
		end
		local animation = animations:FindFirstChild(name)
		if not alive or animation == nil or not animation:IsA("Animation") then
			return nil
		end
		local track = animator:LoadAnimation(animation)
		tracks[name] = track
		return track
	end

	local function stopAll(fadeTime: number?)
		for _, track in tracks do
			track:Stop(fadeTime or 0.1)
		end
	end

	local function cleanup()
		alive = false
		stopAll(0)
		for _, track in tracks do
			track:Destroy()
		end
		table.clear(tracks)
	end

	character.Destroying:Connect(cleanup)

	return {
		playTrack = function(name: string, fadeTime: number?, weight: number?, speed: number?): AnimationTrack?
			local track = get(name)
			if track then
				track:Play(fadeTime or 0.1, weight or 1, speed or 1)
			end
			return track
		end,
		stopTrack = function(name: string, fadeTime: number?)
			local track = tracks[name]
			if track then
				track:Stop(fadeTime or 0.1)
			end
		end,
		stopAll = stopAll,
		cleanup = cleanup,
	}
end

return AnimationCache
```

Usage in the tool's LocalScript (the Animation objects live in a folder next to it, with their AnimationId set in Studio):

```lua
--!strict
local Players = game:GetService("Players")
local AnimationCache = require(game:GetService("ReplicatedStorage"):WaitForChild("AnimationCache"))

local tool = script.Parent
type Cache = { playTrack: (name: string) -> AnimationTrack?, cleanup: () -> () }
local cache: Cache? = nil

tool.Equipped:Connect(function()
	local character = Players.LocalPlayer.Character
	if character then
		cache = AnimationCache.new(character, tool:WaitForChild("Animations"))
	end
end)

tool.Unequipped:Connect(function()
	if cache then
		cache.cleanup()
		cache = nil
	end
end)

tool.Activated:Connect(function()
	if cache then
		cache.playTrack("Slash")
	end
end)
```

- Every `LoadAnimation` call creates a new track the Animator keeps until it is destroyed; loading per click is the leak behind that warning.
- Tracks belong to one Animator, so the cache is per character and is rebuilt on respawn instead of being shared globally.
- Animations played on the local player's own character from a LocalScript replicate to everyone, so no server round trip is needed for cosmetic swings.

# Test
```lua
local player = __makePlayer(10, "Fighter")
local character = __makeCharacter(player)
local folder = Instance.new("Folder")
local slash = Instance.new("Animation")
slash.Name = "Slash"
slash.Parent = folder
local cache = item.new(character, folder)
local animator = character.Humanoid.Animator

local first = cache.playTrack("Slash")
local second = cache.playTrack("Slash")
check("same track reused", first ~= nil and first == second)
check("only one track loaded", #animator.__tracks == 1)
check("unknown animation returns nil", cache.playTrack("Kick") == nil)
check("track is playing", first ~= nil and first.IsPlaying)
character:Destroy()
check("tracks stopped when character is destroyed", first ~= nil and not first.IsPlaying)
check("no loads after destroy", cache.playTrack("Slash") == nil and #animator.__tracks == 1)
```
