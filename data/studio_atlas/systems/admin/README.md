# Admin commands

## API
- `Admins.new({ prefix = "!", getLevel, findPlayer, reply, audit? }) -> admin`. `Admins.Level = { User = 0, Mod = 1, Admin = 2, Owner = 3 }`.
- `admin:Register({ name, aliases?, level, args = {"player"|"number"|"string"|"rest"}, outranks?, run = function(ctx, ...) end })`.
- `admin:Run(caller, text) -> ok, reason`; `ctx` has `caller`, `level`, `reply(text)`.

## Wire it
`player.Chatted:Connect(function(msg) admin:Run(player, msg) end)` (or TextChatService commands). `getLevel` reads server data only: a table of owner UserIds plus `player:GetRankInGroup(groupId)`; cache it on join.

## Pitfalls
- Never decide the level from anything the client sends.
- Below the required level a command answers "unknown command", so it is not revealed.
- `outranks = true` stops mods from kicking admins; put it on every command that acts on a player.
- Numbers reject NaN and infinity; clamp the range inside the command (speed, size).
- Handlers run in `pcall`; an error replies "command failed" and is audited.
