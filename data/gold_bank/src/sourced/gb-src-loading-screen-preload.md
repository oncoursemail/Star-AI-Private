---
id: gb-src-loading-screen-preload
category: ui-interaction
topics: ReplicatedFirst, RemoveDefaultLoadingScreen, ContentProvider, PreloadAsync, game.Loaded, progress bar
source: adapted
source_id: creator-docs
source_path: content/en-us/players/loading-screens.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
I want a custom loading screen with a progress bar that fills while my menu images and sounds preload, stays up at least 2 seconds so it doesn't flash, and disappears once the game has loaded. Where does the script go and how do I track progress?

# Answer
Put a LocalScript and the loading ScreenGui in `ReplicatedFirst`, which replicates before everything else. Remove the default screen, preload your important assets in small batches with `ContentProvider:PreloadAsync` to update the bar between batches, then wait for `game.Loaded` and the minimum time before removing the GUI.

```lua
--!strict
local ContentProvider = game:GetService("ContentProvider")

local Loader = {}

function Loader.preload(assets: { Instance }, batchSize: number, onProgress: (fraction: number) -> ())
	local total = #assets
	if total == 0 then
		onProgress(1)
		return
	end
	local done = 0
	while done < total do
		local batch = {}
		for i = done + 1, math.min(done + batchSize, total) do
			table.insert(batch, assets[i])
		end
		local ok, err = pcall(function()
			ContentProvider:PreloadAsync(batch)
		end)
		if not ok then
			warn("Preload batch failed:", err)
		end
		done += #batch
		onProgress(done / total)
	end
end

function Loader.run(screen: ScreenGui, bar: Frame, assets: { Instance }, minSeconds: number)
	local started = os.clock()
	Loader.preload(assets, 5, function(fraction: number)
		bar.Size = UDim2.fromScale(fraction, 1)
	end)
	if not game:IsLoaded() then
		game.Loaded:Wait()
	end
	local remaining = minSeconds - (os.clock() - started)
	if remaining > 0 then
		task.wait(remaining)
	end
	screen:Destroy()
end

return Loader
```

LocalScript in ReplicatedFirst:

```lua
--!strict
local Players = game:GetService("Players")
local ReplicatedFirst = game:GetService("ReplicatedFirst")

local Loader = require(ReplicatedFirst:WaitForChild("Loader"))

local screen = ReplicatedFirst:WaitForChild("LoadingScreen") :: ScreenGui
local bar = screen:WaitForChild("Track"):WaitForChild("Fill") :: Frame
local menuAssets = ReplicatedFirst:WaitForChild("PreloadList"):GetChildren()

screen.IgnoreGuiInset = true
screen.ResetOnSpawn = false
screen.Parent = Players.LocalPlayer:WaitForChild("PlayerGui")
ReplicatedFirst:RemoveDefaultLoadingScreen()

Loader.run(screen, bar, menuAssets, 2)
```

- `PreloadAsync` yields until its list is downloaded; splitting the list is what makes the bar move.
- Preload only what is seen right away (menu images, music); preloading the whole game makes loading slower, not faster.
- `ResetOnSpawn = false` keeps the character's first spawn from removing the loading screen from PlayerGui early.
- A failed batch is logged and skipped, so one broken asset cannot trap players on the loading screen.

# Test
```lua
local fractions = {}
local assets = {}
for _ = 1, 12 do
	table.insert(assets, Instance.new("Decal"))
end
item.preload(assets, 5, function(f)
	table.insert(fractions, f)
end)
check("progress reported per batch", #fractions == 3)
check("progress ends at 1", fractions[3] == 1 and fractions[1] < fractions[2])
local empty = {}
item.preload({}, 5, function(f)
	table.insert(empty, f)
end)
check("empty list reports complete", empty[1] == 1)
local screen = Instance.new("ScreenGui")
local bar = Instance.new("Frame")
bar.Parent = screen
local finished = false
task.spawn(function()
	item.run(screen, bar, assets, 2)
	finished = true
end)
check("waits for the minimum time", not finished and bar.Size == UDim2.fromScale(1, 1))
__advance(2.1)
check("screen removed after minimum time", finished and screen.Parent == nil)
```
