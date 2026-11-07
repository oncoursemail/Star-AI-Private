---
id: gb-src-chat-size-command
category: gameplay-systems
topics: TextChatService, TextChatCommand, Triggered, PrimaryAlias, Model:ScaleTo, chat commands
source: adapted
source_id: creator-docs
source_path: content/en-us/chat/examples/custom-text-chat-commands.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
I want VIP players to type `/super` to grow to double size and `/mini` to shrink to half size, with `/normal` to reset. How do I add chat commands with the new TextChatService and make sure only VIPs can use them?

# Answer
Create `TextChatCommand` instances under `TextChatService` from a server script and handle `Triggered`, which gives you the `TextSource` (its `UserId`) and the raw message. Check the permission on the server, then scale the character with `Model:ScaleTo`.

```lua
--!strict
local Players = game:GetService("Players")
local TextChatService = game:GetService("TextChatService")

local SCALES: { [string]: number } = {
	["/super"] = 2,
	["/mini"] = 0.5,
	["/normal"] = 1,
}

local command = Instance.new("TextChatCommand")
command.Name = "SizeCommand"
command.PrimaryAlias = "/super"
command.SecondaryAlias = "/mini"
command.Parent = TextChatService

local resetCommand = Instance.new("TextChatCommand")
resetCommand.Name = "SizeResetCommand"
resetCommand.PrimaryAlias = "/normal"
resetCommand.Parent = TextChatService

local function onTriggered(textSource: TextSource, message: string)
	local player = Players:GetPlayerByUserId(textSource.UserId)
	if not player or not player:GetAttribute("IsVip") then
		return
	end
	local alias = string.lower(string.split(message, " ")[1])
	local scale = SCALES[alias]
	local character = player.Character
	if scale and character then
		character:ScaleTo(scale)
	end
end

command.Triggered:Connect(onTriggered)
resetCommand.Triggered:Connect(onTriggered)
```

- A command has two aliases at most, so `/normal` gets its own command object sharing the same handler.
- `Triggered` fires on the server for commands created by the server, so the VIP check cannot be bypassed.
- `Model:ScaleTo` scales the whole rig (body parts, joints, accessories) in one call instead of editing the old `BodyHeightScale` values.
