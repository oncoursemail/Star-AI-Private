---
id: gb-data-remote-sign-text-filter
category: remote-security
topics: TextService, sign text, plot ownership, SurfaceGui, filtering
source: original
---
# Request
In my plot game players can place signs and type up to three lines on them. How do I make sure only the plot owner can edit their sign and that the text is filtered before other players see it?

# Answer
The server checks the sign belongs to the sender's plot (an `OwnerUserId` attribute set by the server when the plot was claimed), normalises the text to at most three short lines, filters the whole sign in one broadcast filter call, and only then writes it to the sign's TextLabel. The client never touches the label.

```lua
--!strict
-- Script: ServerScriptService.Signs
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TextService = game:GetService("TextService")
local CollectionService = game:GetService("CollectionService")

local MAX_LINES = 3
local MAX_LINE_LENGTH = 24
local EDIT_COOLDOWN = 5

local editSign = Instance.new("RemoteEvent")
editSign.Name = "EditSign"
editSign.Parent = ReplicatedStorage

local lastEdit: { [number]: number } = {}

local function normalise(raw: string): string?
	if #raw > MAX_LINES * (MAX_LINE_LENGTH + 1) * 4 or utf8.len(raw) == nil then
		return nil
	end
	local lines: { string } = {}
	for line in string.gmatch(string.gsub(raw, "\r", "") .. "\n", "(.-)\n") do
		local trimmed = string.match(line, "^%s*(.-)%s*$") or ""
		if (utf8.len(trimmed) or 0) > MAX_LINE_LENGTH or #lines >= MAX_LINES then
			return nil
		end
		table.insert(lines, trimmed)
	end
	return table.concat(lines, "\n")
end

local function onEdit(player: Player, signArg: unknown, textArg: unknown)
	local kind = typeof(signArg)
	if kind ~= "Instance" or type(textArg) ~= "string" then
		return
	end
	local sign = signArg :: any
	if not CollectionService:HasTag(sign, "Sign") or sign:GetAttribute("OwnerUserId") ~= player.UserId then
		return
	end
	local label: TextLabel? = sign:FindFirstChildWhichIsA("TextLabel", true)
	local text = normalise(textArg)
	if label == nil or text == nil then
		return
	end
	local userId: number = player.UserId
	local now = os.clock()
	if lastEdit[userId] and now - lastEdit[userId] < EDIT_COOLDOWN then
		return
	end
	lastEdit[userId] = now
	local ok, filtered = pcall(function()
		return TextService:FilterStringAsync(text, userId):GetNonChatStringForBroadcastAsync()
	end)
	if ok and type(filtered) == "string" then
		label.Text = filtered
	end
end

editSign.OnServerEvent:Connect(onEdit)
```

- Filtering the joined text in one call keeps context across lines, so a word split over two lines is still caught, and costs one request per edit.
- `OwnerUserId` must only ever be set by server code (plot claim); the check compares it with the sender's real UserId, not anything in the request.
- If filtering fails, the sign keeps its previous text; never fall back to the raw input.

# Test
```lua
local CollectionService = game:GetService("CollectionService")
local remote = game:GetService("ReplicatedStorage"):WaitForChild("EditSign")
local owner = __makePlayer(1, "Owner")
local stranger = __makePlayer(2, "Stranger")

local sign = Instance.new("Part")
sign:SetAttribute("OwnerUserId", 1)
CollectionService:AddTag(sign, "Sign")
local gui = Instance.new("SurfaceGui")
gui.Parent = sign
local label = Instance.new("TextLabel")
label.Text = ""
label.Parent = gui
sign.Parent = workspace

remote.OnServerEvent:Fire(owner, sign, "  Welcome \nto my\r\nshop ")
check("owner can write a trimmed three-line sign", label.Text == "Welcome\nto my\nshop")

__advance(6)
remote.OnServerEvent:Fire(stranger, sign, "Hacked")
check("other players cannot edit the sign", label.Text == "Welcome\nto my\nshop")

remote.OnServerEvent:Fire(owner, sign, "Badword sale")
check("text is filtered before display", label.Text == "####### sale")

__advance(6)
remote.OnServerEvent:Fire(owner, sign, "a\nb\nc\nd")
remote.OnServerEvent:Fire(owner, sign, string.rep("x", 25))
check("too many lines or long lines are refused", label.Text == "####### sale")

local untagged = Instance.new("Part")
untagged:SetAttribute("OwnerUserId", 1)
untagged.Parent = workspace
remote.OnServerEvent:Fire(owner, untagged, "hi")
remote.OnServerEvent:Fire(owner, sign, 5)
check("untagged parts and non-string text are ignored", label.Text == "####### sale")
```
