# Reference layouts
Nine answers that pass the design checker (docs/design/anti-ai-look-rubric.md). Use them as the shape of a good answer: adapt the content, palette and type to the brief; do not copy the bakery into a racing game.

## Web landing page (one subject, left-aligned, two colours plus one accent)

```html
<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Harbor Bakery</title>
<style>
:root{--ink:#1d1a16;--paper:#f3efe6;--stone:#ddd6c8;--accent:#1f4f5a;--muted:#5b554b}
body{margin:0;font-family:"Source Serif 4",Georgia,serif;background:var(--paper);color:var(--ink);line-height:1.55;font-size:18px}
header{display:flex;justify-content:space-between;align-items:baseline;padding:24px 32px}
header a{color:var(--ink);text-decoration:none;font-weight:600}
nav a{margin-left:24px;font-weight:400}
main{padding:0 32px 64px;max-width:1120px}
h1{font-size:clamp(40px,7vw,80px);line-height:1.02;font-weight:700;margin:48px 0 24px;max-width:16ch;letter-spacing:-0.02em}
h2{font-size:28px;margin:48px 0 16px;font-weight:600}
p{max-width:60ch;margin:0 0 16px}
.lead{font-size:24px;max-width:40ch;margin-bottom:32px}
.action{display:inline-block;background:var(--accent);color:#fff;padding:16px 24px;text-decoration:none;font-weight:600;transition:transform 140ms cubic-bezier(0.22,1,0.36,1)}
.action:active{transform:scale(0.97)}
.action:focus-visible,a:focus-visible,button:focus-visible,input:focus-visible{outline:3px solid var(--ink);outline-offset:4px}
.band{background:var(--stone);padding:48px 32px;margin:48px -32px 0}
ul{margin:0;padding:0;list-style:none;font-size:20px}
li{padding:8px 0}
footer{padding:32px;font-size:16px;color:var(--muted)}
@media (max-width:640px){header{padding:16px}main{padding:0 16px 48px}.band{margin:32px -16px 0;padding:32px 16px}.lead{font-size:20px}}
@media (prefers-reduced-motion:reduce){.action{transition:none}}
</style></head><body>
<header><a href="/">Harbor Bakery</a><nav><a href="#hours">Hours</a></nav></header>
<main>
<h1>Sourdough from the pier, out of the oven at seven.</h1><p class="lead">Forty loaves a morning, shaped by hand on Water Street. When they are gone, the sign goes up.</p><a class="action" href="#book">Reserve a loaf for tomorrow</a><div class="band" id="hours"><h2>Hours</h2><ul><li>Tuesday to Friday, 7:00 to 13:00</li><li>Saturday, 7:00 to 15:00</li><li>Sunday and Monday, closed</li></ul></div></main>
<footer>Harbor Bakery, a sourdough bakery on the Bellingham pier.</footer>
</body></html>
```

## Web dashboard (figures as large text, a plain table, no cards)

```html
<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Paintball Peaks studio dashboard</title>
<style>
:root{--ink:#1d1a16;--paper:#f3efe6;--stone:#ddd6c8;--accent:#1f4f5a;--muted:#5b554b}
body{margin:0;font-family:"Source Serif 4",Georgia,serif;background:var(--paper);color:var(--ink);line-height:1.55;font-size:18px}
header{display:flex;justify-content:space-between;align-items:baseline;padding:24px 32px}
header a{color:var(--ink);text-decoration:none;font-weight:600}
nav a{margin-left:24px;font-weight:400}
main{padding:0 32px 64px;max-width:1120px}
h1{font-size:clamp(40px,7vw,80px);line-height:1.02;font-weight:700;margin:48px 0 24px;max-width:16ch;letter-spacing:-0.02em}
h2{font-size:28px;margin:48px 0 16px;font-weight:600}
p{max-width:60ch;margin:0 0 16px}
.lead{font-size:24px;max-width:40ch;margin-bottom:32px}
.action{display:inline-block;background:var(--accent);color:#fff;padding:16px 24px;text-decoration:none;font-weight:600;transition:transform 140ms cubic-bezier(0.22,1,0.36,1)}
.action:active{transform:scale(0.97)}
.action:focus-visible,a:focus-visible,button:focus-visible,input:focus-visible{outline:3px solid var(--ink);outline-offset:4px}
.band{background:var(--stone);padding:48px 32px;margin:48px -32px 0}
ul{margin:0;padding:0;list-style:none;font-size:20px}
li{padding:8px 0}
footer{padding:32px;font-size:16px;color:var(--muted)}
@media (max-width:640px){header{padding:16px}main{padding:0 16px 48px}.band{margin:32px -16px 0;padding:32px 16px}.lead{font-size:20px}}
@media (prefers-reduced-motion:reduce){.action{transition:none}}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:32px;margin:32px 0 48px}.stats b{display:block;font-size:48px;font-weight:700;line-height:1.1}.stats span{color:var(--muted);font-size:16px}table{border-collapse:collapse;width:100%;max-width:640px;font-size:18px}td{padding:12px 0;border-bottom:1px solid var(--stone)}td+td{text-align:right}</style></head><body>
<header><a href="/">Paintball Peaks studio dashboard</a><nav><a href="#detail">Detail</a></nav></header>
<main>
<h1>Paintball Peaks studio dashboard</h1><p class="lead">Daily players, Robux revenue and the five most-played maps.</p><div class="stats"><div><b>4,812</b><span>Players today</span></div><div><b>61,300</b><span>Robux this week</span></div><div><b>22 min</b><span>Average session</span></div></div><h2 id="detail">Most played maps</h2><table><tr><td>River Crossing</td><td>1,920 plays</td></tr><tr><td>Quarry</td><td>1,210</td></tr><tr><td>Night Harbor</td><td>880</td></tr><tr><td>Depot</td><td>540</td></tr><tr><td>Rooftops</td><td>262</td></tr></table></main>
<footer>Figures update every minute.</footer>
</body></html>
```

## Web form (labels above fields, one button, an error line, visible focus)

```html
<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Night School sign-up</title>
<style>
:root{--ink:#1d1a16;--paper:#f3efe6;--stone:#ddd6c8;--accent:#1f4f5a;--muted:#5b554b}
body{margin:0;font-family:"Source Serif 4",Georgia,serif;background:var(--paper);color:var(--ink);line-height:1.55;font-size:18px}
header{display:flex;justify-content:space-between;align-items:baseline;padding:24px 32px}
header a{color:var(--ink);text-decoration:none;font-weight:600}
nav a{margin-left:24px;font-weight:400}
main{padding:0 32px 64px;max-width:1120px}
h1{font-size:clamp(40px,7vw,80px);line-height:1.02;font-weight:700;margin:48px 0 24px;max-width:16ch;letter-spacing:-0.02em}
h2{font-size:28px;margin:48px 0 16px;font-weight:600}
p{max-width:60ch;margin:0 0 16px}
.lead{font-size:24px;max-width:40ch;margin-bottom:32px}
.action{display:inline-block;background:var(--accent);color:#fff;padding:16px 24px;text-decoration:none;font-weight:600;transition:transform 140ms cubic-bezier(0.22,1,0.36,1)}
.action:active{transform:scale(0.97)}
.action:focus-visible,a:focus-visible,button:focus-visible,input:focus-visible{outline:3px solid var(--ink);outline-offset:4px}
.band{background:var(--stone);padding:48px 32px;margin:48px -32px 0}
ul{margin:0;padding:0;list-style:none;font-size:20px}
li{padding:8px 0}
footer{padding:32px;font-size:16px;color:var(--muted)}
@media (max-width:640px){header{padding:16px}main{padding:0 16px 48px}.band{margin:32px -16px 0;padding:32px 16px}.lead{font-size:20px}}
@media (prefers-reduced-motion:reduce){.action{transition:none}}
form{max-width:480px}label{display:block;font-weight:600;margin:24px 0 8px}input[type=text],input[type=email],input[type=password]{width:100%;box-sizing:border-box;font:inherit;padding:12px;border:2px solid var(--stone);background:#fff;color:var(--ink)}.check{display:flex;gap:12px;align-items:center;margin:24px 0;font-weight:400}.error{color:#8a2f1c;font-size:16px;margin:8px 0 0}button{font:inherit;font-weight:600;background:var(--accent);color:#fff;border:0;padding:16px 24px;transition:transform 140ms cubic-bezier(0.22,1,0.36,1)}button:active{transform:scale(0.97)}</style></head><body>
<header><a href="/">Night School sign-up</a><nav></nav></header>
<main>
<h1>Night School sign-up</h1><p class="lead">Takes about a minute. We only ask for what the sign-up needs.</p><form><label for="f0">Name</label><input type="text" id="f0" name="f0" aria-describedby="f0-error"><p class="error" id="f0-error">Enter your name so we can reach you.</p><label for="f1">Email</label><input type="email" id="f1" name="f1" aria-describedby="f1-error"><label for="f2">Password</label><input type="password" id="f2" name="f2" aria-describedby="f2-error"><label class="check"><input type="checkbox" name="opt"> Email me the morning report</label><button type="submit">Start the first night</button></form></main>
<footer>Questions? Reply to any email from us.</footer>
</body></html>
```

## UI motion: dropdown (ease-out 180 ms, transform and opacity, reduced-motion)

```html
<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Dropdown menu</title>
<style>
:root{--ink:#1d1a16;--paper:#f3efe6;--stone:#ddd6c8;--accent:#1f4f5a;--muted:#5b554b}
body{margin:0;font-family:"Source Serif 4",Georgia,serif;background:var(--paper);color:var(--ink);line-height:1.55;font-size:18px}
header{display:flex;justify-content:space-between;align-items:baseline;padding:24px 32px}
header a{color:var(--ink);text-decoration:none;font-weight:600}
nav a{margin-left:24px;font-weight:400}
main{padding:0 32px 64px;max-width:1120px}
h1{font-size:clamp(40px,7vw,80px);line-height:1.02;font-weight:700;margin:48px 0 24px;max-width:16ch;letter-spacing:-0.02em}
h2{font-size:28px;margin:48px 0 16px;font-weight:600}
p{max-width:60ch;margin:0 0 16px}
.lead{font-size:24px;max-width:40ch;margin-bottom:32px}
.action{display:inline-block;background:var(--accent);color:#fff;padding:16px 24px;text-decoration:none;font-weight:600;transition:transform 140ms cubic-bezier(0.22,1,0.36,1)}
.action:active{transform:scale(0.97)}
.action:focus-visible,a:focus-visible,button:focus-visible,input:focus-visible{outline:3px solid var(--ink);outline-offset:4px}
.band{background:var(--stone);padding:48px 32px;margin:48px -32px 0}
ul{margin:0;padding:0;list-style:none;font-size:20px}
li{padding:8px 0}
footer{padding:32px;font-size:16px;color:var(--muted)}
@media (max-width:640px){header{padding:16px}main{padding:0 16px 48px}.band{margin:32px -16px 0;padding:32px 16px}.lead{font-size:20px}}
@media (prefers-reduced-motion:reduce){.action{transition:none}}
.menu{position:relative;display:inline-block}.menu button{font:inherit;font-weight:600;background:var(--accent);color:#fff;border:0;padding:12px 20px;transition:transform 140ms cubic-bezier(0.22,1,0.36,1),background-color 180ms ease}.menu button:active{transform:scale(0.97)}.panel{position:absolute;top:calc(100% + 8px);left:0;min-width:240px;background:#fff;color:var(--ink);padding:8px 0;opacity:0;transform:translateY(-4px) scale(0.97);transform-origin:top left;pointer-events:none;transition:opacity 180ms cubic-bezier(0.22,1,0.36,1),transform 180ms cubic-bezier(0.22,1,0.36,1);box-shadow:0 8px 24px rgba(29,26,22,0.18)}.menu[data-open=true] .panel{opacity:1;transform:none;pointer-events:auto}.panel a{display:block;padding:12px 20px;color:var(--ink);text-decoration:none}.panel a:hover{background:var(--stone)}@media (prefers-reduced-motion:reduce){.panel,.menu button{transition:none}}</style></head><body>
<header><a href="/">Dropdown menu</a><nav></nav></header>
<main>
<h1>Dropdown menu</h1><p class="lead">A button that opens a dropdown menu of four options. Opens with ease-out in 180 ms, leaves faster.</p><div class="menu" id="m"><button aria-expanded="false" aria-controls="p" onclick="toggle()">Choose a map</button><div class="panel" id="p" role="menu"><a href="#river">River Crossing</a><a href="#quarry">Quarry</a><a href="#harbor">Night Harbor</a><a href="#depot">Depot</a></div></div><script>function toggle(){var m=document.getElementById('m');var open=m.dataset.open==='true';m.dataset.open=String(!open);m.querySelector('button').setAttribute('aria-expanded',String(!open));}document.addEventListener('keydown',function(e){if(e.key==='Escape'){var m=document.getElementById('m');m.dataset.open='false';}});</script></main>
<footer>Escape closes the menu.</footer>
</body></html>
```

## Roblox shop (Theme table, Scale panel with aspect constraint, UIGridLayout, Quad Out feedback)

```luau
local Players = game:GetService("Players")
local TweenService = game:GetService("TweenService")

local Theme = {
	ground = Color3.fromRGB(24, 26, 31),
	surface = Color3.fromRGB(40, 43, 50),
	surfaceHover = Color3.fromRGB(52, 56, 64),
	ink = Color3.fromRGB(240, 240, 236),
	muted = Color3.fromRGB(180, 182, 176),
	accent = Color3.fromRGB(31, 79, 90),
	font = "rbxasset://fonts/families/GothamSSm.json",
	pad = 16,
	radius = 8,
}
local tweenOut = TweenInfo.new(0.12, Enum.EasingStyle.Quad, Enum.EasingDirection.Out)

local function text(parent: Instance, label: string, size: number, weight, color: Color3): TextLabel
	local t = Instance.new("TextLabel")
	t.Text = label
	t.FontFace = Font.new(Theme.font, weight)
	t.TextSize = size
	t.TextColor3 = color
	t.TextXAlignment = Enum.TextXAlignment.Left
	t.BackgroundTransparency = 1
	t.Size = UDim2.new(1, 0, 0, size + 8)
	t.Parent = parent
	return t
end

local function corner(parent: Instance)
	local c = Instance.new("UICorner")
	c.CornerRadius = UDim.new(0, Theme.radius)
	c.Parent = parent
end

local function padding(parent: Instance)
	local p = Instance.new("UIPadding")
	p.PaddingLeft = UDim.new(0, Theme.pad)
	p.PaddingRight = UDim.new(0, Theme.pad)
	p.PaddingTop = UDim.new(0, Theme.pad)
	p.PaddingBottom = UDim.new(0, Theme.pad)
	p.Parent = parent
end

local function feedback(button: GuiButton)
	button.AutoButtonColor = false
	button.MouseEnter:Connect(function()
		TweenService:Create(button, tweenOut, {BackgroundColor3 = Theme.surfaceHover}):Play()
	end)
	button.MouseLeave:Connect(function()
		TweenService:Create(button, tweenOut, {BackgroundColor3 = Theme.surface}):Play()
	end)
end

local gui = Instance.new("ScreenGui")
gui.Name = "ShopGui"
gui.ResetOnSpawn = false
gui.IgnoreGuiInset = false

local panel = Instance.new("Frame")
panel.Name = "Panel"
panel.AnchorPoint = Vector2.new(0.5, 0.5)
panel.Position = UDim2.fromScale(0.5, 0.5)
panel.Size = UDim2.new(0.7, 0, 0.75, 0)
panel.BackgroundColor3 = Theme.ground
panel.Parent = gui
corner(panel)
padding(panel)
local ratio = Instance.new("UIAspectRatioConstraint")
ratio.AspectRatio = 1.5
ratio.Parent = panel
local sizeLimit = Instance.new("UISizeConstraint")
sizeLimit.MinSize = Vector2.new(320, 220)
sizeLimit.Parent = panel
local column = Instance.new("UIListLayout")
column.Padding = UDim.new(0, 8)
column.SortOrder = Enum.SortOrder.LayoutOrder
column.Parent = panel

text(panel, "Gear shop", 28, Enum.FontWeight.Bold, Theme.ink)
text(panel, "1,240 coins", 16, Enum.FontWeight.Medium, Theme.muted)

local grid = Instance.new("ScrollingFrame")
grid.Name = "Items"
grid.Size = UDim2.new(1, 0, 1, -72)
grid.BackgroundTransparency = 1
grid.ScrollBarThickness = 4
grid.AutomaticCanvasSize = Enum.AutomaticSize.Y
grid.CanvasSize = UDim2.new()
grid.Parent = panel
local layout = Instance.new("UIGridLayout")
layout.CellSize = UDim2.new(0.3, 0, 0, 96)
layout.CellPadding = UDim2.new(0, 16, 0, 16)
layout.Parent = grid

local function card(name: string, price: number)
	local b = Instance.new("TextButton")
	b.Name = name
	b.Text = name .. "\n" .. tostring(price) .. " coins"
	b.FontFace = Font.new(Theme.font, Enum.FontWeight.Medium)
	b.TextSize = 16
	b.TextColor3 = Theme.ink
	b.BackgroundColor3 = Theme.surface
	b.Size = UDim2.new(0, 160, 0, 96)
	corner(b)
	feedback(b)
	b.Activated:Connect(function()
		TweenService:Create(b, tweenOut, {BackgroundColor3 = Theme.accent}):Play()
	end)
	b.Parent = grid
end
card("Grapple hook", 300)
card("Speed boots", 450)
card("Paint grenade", 120)
card("Smoke bomb", 90)
card("Scope", 260)
card("Flag glove", 500)

gui.Parent = Players.LocalPlayer:WaitForChild("PlayerGui")
```

## Roblox HUD (one scrim corner, UIListLayout, 18 px semibold, size constraint)

```luau
local Players = game:GetService("Players")

local Theme = {
	ink = Color3.fromRGB(240, 240, 236),
	muted = Color3.fromRGB(180, 182, 176),
	scrim = Color3.fromRGB(24, 26, 31),
	font = "rbxasset://fonts/families/GothamSSm.json",
}

local gui = Instance.new("ScreenGui")
gui.Name = "Hud"
gui.ResetOnSpawn = false

local corner = Instance.new("Frame")
corner.Name = "TopLeft"
corner.Position = UDim2.new(0, 16, 0, 16)
corner.Size = UDim2.new(0.28, 0, 0.2, 0)
corner.BackgroundColor3 = Theme.scrim
corner.BackgroundTransparency = 0.25
corner.Parent = gui
local round = Instance.new("UICorner")
round.CornerRadius = UDim.new(0, 8)
round.Parent = corner
local pad = Instance.new("UIPadding")
pad.PaddingLeft = UDim.new(0, 16)
pad.PaddingRight = UDim.new(0, 16)
pad.PaddingTop = UDim.new(0, 12)
pad.PaddingBottom = UDim.new(0, 12)
pad.Parent = corner
local sizeLimit = Instance.new("UISizeConstraint")
sizeLimit.MinSize = Vector2.new(180, 96)
sizeLimit.MaxSize = Vector2.new(360, 200)
sizeLimit.Parent = corner
local list = Instance.new("UIListLayout")
list.Padding = UDim.new(0, 4)
list.SortOrder = Enum.SortOrder.LayoutOrder
list.Parent = corner

local function hudLabel(name: string, value: string): TextLabel
	local t = Instance.new("TextLabel")
	t.Name = name
	t.Text = value
	t.FontFace = Font.new(Theme.font, Enum.FontWeight.SemiBold)
	t.TextSize = 18
	t.TextColor3 = Theme.ink
	t.TextXAlignment = Enum.TextXAlignment.Left
	t.BackgroundTransparency = 1
	t.Size = UDim2.new(1, 0, 0, 24)
	t.Parent = corner
	return t
end

hudLabel("Health", "Health: 0")
hudLabel("Ammo", "Ammo: 0")
hudLabel("Round timer", "Round timer: 0")
hudLabel("Team score", "Team score: 0")

gui.Parent = Players.LocalPlayer:WaitForChild("PlayerGui")
```

## Roblox main menu (title, one line of real copy, three buttons 48 px tall)

```luau
local Players = game:GetService("Players")
local TweenService = game:GetService("TweenService")

local Theme = {
	ground = Color3.fromRGB(24, 26, 31),
	surface = Color3.fromRGB(40, 43, 50),
	surfaceHover = Color3.fromRGB(52, 56, 64),
	ink = Color3.fromRGB(240, 240, 236),
	muted = Color3.fromRGB(180, 182, 176),
	accent = Color3.fromRGB(31, 79, 90),
	font = "rbxasset://fonts/families/GothamSSm.json",
	pad = 16,
	radius = 8,
}
local tweenOut = TweenInfo.new(0.12, Enum.EasingStyle.Quad, Enum.EasingDirection.Out)

local function text(parent: Instance, label: string, size: number, weight, color: Color3): TextLabel
	local t = Instance.new("TextLabel")
	t.Text = label
	t.FontFace = Font.new(Theme.font, weight)
	t.TextSize = size
	t.TextColor3 = color
	t.TextXAlignment = Enum.TextXAlignment.Left
	t.BackgroundTransparency = 1
	t.Size = UDim2.new(1, 0, 0, size + 8)
	t.Parent = parent
	return t
end

local function corner(parent: Instance)
	local c = Instance.new("UICorner")
	c.CornerRadius = UDim.new(0, Theme.radius)
	c.Parent = parent
end

local function padding(parent: Instance)
	local p = Instance.new("UIPadding")
	p.PaddingLeft = UDim.new(0, Theme.pad)
	p.PaddingRight = UDim.new(0, Theme.pad)
	p.PaddingTop = UDim.new(0, Theme.pad)
	p.PaddingBottom = UDim.new(0, Theme.pad)
	p.Parent = parent
end

local function feedback(button: GuiButton)
	button.AutoButtonColor = false
	button.MouseEnter:Connect(function()
		TweenService:Create(button, tweenOut, {BackgroundColor3 = Theme.surfaceHover}):Play()
	end)
	button.MouseLeave:Connect(function()
		TweenService:Create(button, tweenOut, {BackgroundColor3 = Theme.surface}):Play()
	end)
end

local gui = Instance.new("ScreenGui")
gui.Name = "MainMenu"
gui.ResetOnSpawn = false
gui.IgnoreGuiInset = false

local panel = Instance.new("Frame")
panel.Name = "Panel"
panel.AnchorPoint = Vector2.new(0.5, 0.5)
panel.Position = UDim2.fromScale(0.5, 0.5)
panel.Size = UDim2.new(0.7, 0, 0.75, 0)
panel.BackgroundColor3 = Theme.ground
panel.Parent = gui
corner(panel)
padding(panel)
local ratio = Instance.new("UIAspectRatioConstraint")
ratio.AspectRatio = 1.5
ratio.Parent = panel
local sizeLimit = Instance.new("UISizeConstraint")
sizeLimit.MinSize = Vector2.new(320, 220)
sizeLimit.Parent = panel
local column = Instance.new("UIListLayout")
column.Padding = UDim.new(0, 8)
column.SortOrder = Enum.SortOrder.LayoutOrder
column.Parent = panel

text(panel, "Paintball Peaks", 40, Enum.FontWeight.Bold, Theme.ink)
text(panel, "Round-based, 16 players, no pay to win", 16, Enum.FontWeight.Medium, Theme.muted)

local function menuButton(label: string, order: number)
	local b = Instance.new("TextButton")
	b.Name = label
	b.Text = label
	b.LayoutOrder = order
	b.FontFace = Font.new(Theme.font, Enum.FontWeight.Medium)
	b.TextSize = 20
	b.TextColor3 = Theme.ink
	b.BackgroundColor3 = Theme.surface
	b.Size = UDim2.new(0.5, 0, 0, 48)
	corner(b)
	feedback(b)
	b.Parent = panel
end
menuButton("Play", 10)
menuButton("Shop", 11)
menuButton("Settings", 12)

gui.Parent = Players.LocalPlayer:WaitForChild("PlayerGui")
```

## Roblox inventory (scrolling slot grid plus detail panel)

```luau
local Players = game:GetService("Players")
local TweenService = game:GetService("TweenService")

local Theme = {
	ground = Color3.fromRGB(24, 26, 31),
	surface = Color3.fromRGB(40, 43, 50),
	surfaceHover = Color3.fromRGB(52, 56, 64),
	ink = Color3.fromRGB(240, 240, 236),
	muted = Color3.fromRGB(180, 182, 176),
	accent = Color3.fromRGB(31, 79, 90),
	font = "rbxasset://fonts/families/GothamSSm.json",
	pad = 16,
	radius = 8,
}
local tweenOut = TweenInfo.new(0.12, Enum.EasingStyle.Quad, Enum.EasingDirection.Out)

local function text(parent: Instance, label: string, size: number, weight, color: Color3): TextLabel
	local t = Instance.new("TextLabel")
	t.Text = label
	t.FontFace = Font.new(Theme.font, weight)
	t.TextSize = size
	t.TextColor3 = color
	t.TextXAlignment = Enum.TextXAlignment.Left
	t.BackgroundTransparency = 1
	t.Size = UDim2.new(1, 0, 0, size + 8)
	t.Parent = parent
	return t
end

local function corner(parent: Instance)
	local c = Instance.new("UICorner")
	c.CornerRadius = UDim.new(0, Theme.radius)
	c.Parent = parent
end

local function padding(parent: Instance)
	local p = Instance.new("UIPadding")
	p.PaddingLeft = UDim.new(0, Theme.pad)
	p.PaddingRight = UDim.new(0, Theme.pad)
	p.PaddingTop = UDim.new(0, Theme.pad)
	p.PaddingBottom = UDim.new(0, Theme.pad)
	p.Parent = parent
end

local function feedback(button: GuiButton)
	button.AutoButtonColor = false
	button.MouseEnter:Connect(function()
		TweenService:Create(button, tweenOut, {BackgroundColor3 = Theme.surfaceHover}):Play()
	end)
	button.MouseLeave:Connect(function()
		TweenService:Create(button, tweenOut, {BackgroundColor3 = Theme.surface}):Play()
	end)
end

local gui = Instance.new("ScreenGui")
gui.Name = "Inventory"
gui.ResetOnSpawn = false
gui.IgnoreGuiInset = false

local panel = Instance.new("Frame")
panel.Name = "Panel"
panel.AnchorPoint = Vector2.new(0.5, 0.5)
panel.Position = UDim2.fromScale(0.5, 0.5)
panel.Size = UDim2.new(0.7, 0, 0.75, 0)
panel.BackgroundColor3 = Theme.ground
panel.Parent = gui
corner(panel)
padding(panel)
local ratio = Instance.new("UIAspectRatioConstraint")
ratio.AspectRatio = 1.5
ratio.Parent = panel
local sizeLimit = Instance.new("UISizeConstraint")
sizeLimit.MinSize = Vector2.new(320, 220)
sizeLimit.Parent = panel
local column = Instance.new("UIListLayout")
column.Padding = UDim.new(0, 8)
column.SortOrder = Enum.SortOrder.LayoutOrder
column.Parent = panel

text(panel, "Inventory", 28, Enum.FontWeight.Bold, Theme.ink)

local slots = Instance.new("ScrollingFrame")
slots.Name = "Slots"
slots.Size = UDim2.new(0.55, 0, 1, -48)
slots.BackgroundTransparency = 1
slots.ScrollBarThickness = 4
slots.AutomaticCanvasSize = Enum.AutomaticSize.Y
slots.CanvasSize = UDim2.new()
slots.Parent = panel
local grid = Instance.new("UIGridLayout")
grid.CellSize = UDim2.new(0, 72, 0, 72)
grid.CellPadding = UDim2.new(0, 8, 0, 8)
grid.Parent = slots

local detail = Instance.new("Frame")
detail.Name = "Detail"
detail.Size = UDim2.new(0.42, 0, 1, -48)
detail.Position = UDim2.new(0.58, 0, 0, 48)
detail.BackgroundColor3 = Theme.surface
detail.Parent = panel
corner(detail)
padding(detail)
local detailList = Instance.new("UIListLayout")
detailList.Padding = UDim.new(0, 8)
detailList.Parent = detail
local nameLabel = text(detail, "Choose an item", 20, Enum.FontWeight.Bold, Theme.ink)
local descLabel = text(detail, "", 16, Enum.FontWeight.Medium, Theme.muted)
descLabel.TextWrapped = true
descLabel.Size = UDim2.new(1, 0, 0, 64)
local equip = Instance.new("TextButton")
equip.Name = "Equip"
equip.Text = "Equip"
equip.FontFace = Font.new(Theme.font, Enum.FontWeight.Medium)
equip.TextSize = 16
equip.TextColor3 = Theme.ink
equip.BackgroundColor3 = Theme.accent
equip.Size = UDim2.new(1, 0, 0, 44)
corner(equip)
equip.Parent = detail

local function slot(name: string, description: string)
	local b = Instance.new("TextButton")
	b.Name = name
	b.Text = name
	b.FontFace = Font.new(Theme.font, Enum.FontWeight.Medium)
	b.TextSize = 14
	b.TextWrapped = true
	b.TextColor3 = Theme.ink
	b.BackgroundColor3 = Theme.surface
	b.Size = UDim2.new(0, 72, 0, 72)
	corner(b)
	feedback(b)
	b.Activated:Connect(function()
		nameLabel.Text = name
		descLabel.Text = description
	end)
	b.Parent = slots
end
slot("Marker rifle", "Mid-range, 24 rounds")
slot("Paint grenade", "Splashes 10 studs")
slot("Smoke bomb", "Blocks sight for 8 seconds")

gui.Parent = Players.LocalPlayer:WaitForChild("PlayerGui")
```

## Roblox VFX impact (three hues, three phases, mobile budget, Debris cleanup)

```luau
local Debris = game:GetService("Debris")

local HOT = Color3.fromRGB(255, 236, 200)
local BODY = Color3.fromRGB(31, 120, 160)
local DARK = Color3.fromRGB(70, 66, 60)

local function emitter(parent: Attachment, color: Color3, light: number): ParticleEmitter
	local e = Instance.new("ParticleEmitter")
	e.Rate = 0
	e.Enabled = false
	e.LightEmission = light
	e.Color = ColorSequence.new(color)
	e.Parent = parent
	return e
end

-- paintball hit: plays when a paintball bursting on a wall
local function play(at: Attachment)
	local flash = emitter(at, HOT, 1)
	flash.Lifetime = NumberRange.new(0.06, 0.1)
	flash.Size = NumberSequence.new({NumberSequenceKeypoint.new(0, 1), NumberSequenceKeypoint.new(1, 5)})
	flash.Transparency = NumberSequence.new({NumberSequenceKeypoint.new(0, 0.2), NumberSequenceKeypoint.new(1, 1)})

	local splash = emitter(at, BODY, 0.3)
	splash.Lifetime = NumberRange.new(0.4, 0.8)
	splash.Speed = NumberRange.new(10, 18)
	splash.SpreadAngle = Vector2.new(40, 40)
	splash.Acceleration = Vector3.new(0, -35, 0)
	splash.Size = NumberSequence.new({NumberSequenceKeypoint.new(0, 0.6), NumberSequenceKeypoint.new(1, 0.1)})
	splash.Transparency = NumberSequence.new({NumberSequenceKeypoint.new(0, 0), NumberSequenceKeypoint.new(1, 1)})

	local haze = emitter(at, DARK, 0)
	haze.Lifetime = NumberRange.new(1.0, 1.6)
	haze.Speed = NumberRange.new(1, 2)
	haze.Size = NumberSequence.new({NumberSequenceKeypoint.new(0, 2), NumberSequenceKeypoint.new(1, 6)})
	haze.Transparency = NumberSequence.new({NumberSequenceKeypoint.new(0, 0.6), NumberSequenceKeypoint.new(1, 1)})

	flash:Emit(1)          -- anticipation: a small flash
	task.wait(0.04)
	splash:Emit(28)        -- impact: the paint splash
	haze:Emit(5)           -- aftermath: slow haze that grows and fades
	Debris:AddItem(at, 2.5)
end

return play
```
