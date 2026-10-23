---
id: gb-src-cmdr-admin-command
category: remote-security
topics: Cmdr, admin commands, command definition, server implementation, BeforeRun hook, permissions
source: adapted
source_id: cmdr
source_path: docs/04-commands.md
source_commit: ba4f0ffed0c3a0c90932f8e541cd362160bffd81
---
# Request
I installed Cmdr for admin commands. I want a `givecash` command (alias `gc`) that gives an amount of cash to one or more players, usable only by admins. How do I define the command and lock it down?

# Answer
A Cmdr command is two ModuleScripts: the definition (name, aliases, group, typed args), which replicates to clients, and a `<Name>Server` module with the implementation, which never leaves the server. Restrict it with a server `BeforeRun` hook that checks the executor against your admin list for the command's group.

```lua
--!strict
-- ModuleScript: ServerScriptService.CmdrCommands.GiveCash
return {
	Name = "givecash",
	Aliases = { "gc" },
	Description = "Gives cash to one or more players.",
	Group = "Admin",
	Args = {
		{ Type = "players", Name = "targets", Description = "Who receives the cash" },
		{ Type = "integer", Name = "amount", Description = "Cash to give (1-100000)" },
	},
}
```

```lua
--!strict
-- ModuleScript: ServerScriptService.CmdrCommands.GiveCashServer
local MAX_AMOUNT = 100000

return function(_context: any, targets: { Player }, amount: number): string
	if amount < 1 or amount > MAX_AMOUNT then
		return "Amount must be between 1 and " .. MAX_AMOUNT .. "."
	end
	for _, player in targets do
		local cash = player:GetAttribute("Cash")
		player:SetAttribute("Cash", (if typeof(cash) == "number" then cash else 0) + amount)
	end
	return "Gave " .. amount .. " cash to " .. #targets .. " player(s)."
end
```

```lua
--!strict
-- Script: ServerScriptService.CmdrSetup
local ServerScriptService = game:GetService("ServerScriptService")

local Cmdr = require(ServerScriptService:WaitForChild("Cmdr"))

local ADMINS: { [number]: boolean } = {
	[123456] = true,
}

Cmdr:RegisterCommandsIn(ServerScriptService:WaitForChild("CmdrCommands"))
Cmdr.Registry:RegisterHook("BeforeRun", function(context: any): string?
	if context.Group == "Admin" and not ADMINS[context.Executor.UserId] then
		return "You don't have permission to run this command."
	end
	return nil
end)
```

- The hook runs on the server, so editing the client console cannot skip it; returning a string cancels the command and shows that message.
- Cmdr parses and type-checks the arguments (`players`, `integer`) before the implementation runs, but the range check is still yours.
- Keep the admin list on the server (or check group rank with `player:GetRankInGroup`), never in the replicated definition.
