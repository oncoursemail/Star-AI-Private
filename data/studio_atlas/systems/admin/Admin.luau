--!strict
-- Admin commands with permission levels. Levels come only from server data (owner ids, group rank), the command
-- table decides the minimum level, and commands that target a player cannot touch someone of equal or higher level.

export type ArgKind = "player" | "number" | "string" | "rest"
export type Context = { caller: any, level: number, reply: (text: string) -> () }
export type Command = {
	name: string,
	aliases: { string }?,
	level: number, -- minimum level to run it
	args: { ArgKind },
	outranks: boolean?, -- player arguments must have a strictly lower level than the caller
	run: (ctx: Context, ...any) -> (),
}
export type Config = {
	prefix: string,
	getLevel: (player: any) -> number, -- 0 = everyone; look the player up in server-side data only
	findPlayer: (query: string) -> any?, -- exact name or unique prefix
	reply: (player: any, text: string) -> (),
	audit: ((caller: any, line: string, ok: boolean) -> ())?, -- keep a log of every attempt
}
export type Admin = {
	Register: (self: Admin, command: Command) -> (),
	Run: (self: Admin, caller: any, text: string) -> (boolean, string?),
}

local Admins = {}

local function tokenize(text: string): { string }
	local tokens = {}
	local i = 1
	while i <= #text do
		local c = string.sub(text, i, i)
		if c == " " then
			i += 1
		elseif c == '"' then
			local close = string.find(text, '"', i + 1, true)
			local stop = close or #text + 1
			table.insert(tokens, string.sub(text, i + 1, stop - 1))
			i = stop + 1
		else
			local stop = string.find(text, " ", i, true) or #text + 1
			table.insert(tokens, string.sub(text, i, stop - 1))
			i = stop
		end
	end
	return tokens
end

function Admins.new(cfg: Config): Admin
	local commands: { [string]: Command } = {}
	local admin = {} :: Admin

	function admin.Register(_self, command)
		for _, name in { command.name, table.unpack(command.aliases or {}) } do
			assert(commands[string.lower(name)] == nil, `duplicate command {name}`)
			commands[string.lower(name)] = command
		end
	end

	local function fail(caller: any, text: string, reason: string): (boolean, string?)
		if cfg.audit then
			cfg.audit(caller, text, false)
		end
		cfg.reply(caller, reason)
		return false, reason
	end

	function admin.Run(_self, caller, text)
		if string.sub(text, 1, #cfg.prefix) ~= cfg.prefix then
			return false, "not a command"
		end
		local tokens = tokenize(string.sub(text, #cfg.prefix + 1))
		local name = string.lower(table.remove(tokens, 1) or "")
		local command = commands[name]
		local level = cfg.getLevel(caller)
		if command == nil or level < command.level then
			return fail(caller, text, "unknown command") -- same answer for both: do not reveal admin commands
		end
		local values: { any } = {}
		for i, kind in command.args do
			local token = tokens[i]
			if token == nil then
				return fail(caller, text, `missing argument {i}`)
			end
			if kind == "player" then
				local target = cfg.findPlayer(token)
				if target == nil then
					return fail(caller, text, `no player {token}`)
				end
				if command.outranks == true and cfg.getLevel(target) >= level then
					return fail(caller, text, "target has equal or higher permission")
				end
				values[i] = target
			elseif kind == "number" then
				local n = tonumber(token)
				if n == nil or n ~= n or n == math.huge or n == -math.huge then
					return fail(caller, text, `argument {i} must be a number`)
				end
				values[i] = n
			elseif kind == "rest" then
				values[i] = table.concat(tokens, " ", i)
			else
				values[i] = token
			end
		end
		local ctx: Context = {
			caller = caller,
			level = level,
			reply = function(line)
				cfg.reply(caller, line)
			end,
		}
		local ok, err = pcall(command.run, ctx, table.unpack(values, 1, #command.args))
		if cfg.audit then
			cfg.audit(caller, text, ok)
		end
		if not ok then
			cfg.reply(caller, "command failed")
			return false, tostring(err)
		end
		return true, nil
	end

	return admin
end

return { new = Admins.new, Level = { User = 0, Mod = 1, Admin = 2, Owner = 3 } }
