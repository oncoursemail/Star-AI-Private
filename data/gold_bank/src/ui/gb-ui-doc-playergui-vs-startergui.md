---
id: gb-ui-doc-playergui-vs-startergui
category: docs-question
topics: PlayerGui, StarterGui, template copy, LocalScript, HUD updates
source: original
---
# Request
I update the coin text with `game.StarterGui.HUD.Coins.Text = tostring(coins)` from a LocalScript and nothing changes on screen, even though printing the label shows the new text. What's the difference between StarterGui and PlayerGui?

# Answer
StarterGui holds templates; at spawn each player gets copies in their own `Player.PlayerGui`, and those copies are what is on screen. Editing StarterGui changes the template, which nobody is looking at. Reach the player's copy through `Players.LocalPlayer.PlayerGui` (with WaitForChild, since it is created after your script may start).

```lua
--!strict
-- LocalScript: StarterPlayerScripts.CoinDisplay
local Players = game:GetService("Players")

local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui")

local function coinsLabel(): TextLabel
	local hud = playerGui:WaitForChild("HUD")
	return hud:WaitForChild("Coins") :: TextLabel
end

local function setCoins(coins: number)
	coinsLabel().Text = tostring(coins)
end

return setCoins
```

- If HUD has `ResetOnSpawn = true`, the copy is replaced after each death; looking it up per update (as above) avoids holding a destroyed label.
- `game.StarterGui` also reaches the service by property; use `game:GetService("StarterGui")` when you genuinely need the template, for example `SetCoreGuiEnabled`.
- Server scripts should not write to PlayerGui text at all; send the value and let the client display it.

# Test
```lua
__setClient(true)
local player = __makePlayer(1, "Mia")
local hud = Instance.new("ScreenGui")
hud.Name = "HUD"
local coins = Instance.new("TextLabel")
coins.Name = "Coins"
coins.Text = "0"
coins.Parent = hud
hud.Parent = player.PlayerGui
local template = hud:Clone()
template.Parent = game:GetService("StarterGui")
```
```lua
local player = game:GetService("Players").LocalPlayer
local setCoins = item
setCoins(250)
check("player's copy updated", player.PlayerGui.HUD.Coins.Text == "250")
check("template untouched", game:GetService("StarterGui").HUD.Coins.Text == "0")
setCoins(0)
check("updates repeat", player.PlayerGui.HUD.Coins.Text == "0")
```
