---
id: gb-eng-tdd-chat-command-parser
category: engineering-test-first
topics: test-first, command parser, tokenizer, quoted arguments, admin commands
source: original
test_block: 2
---
# Request
Before I write my admin command system I want the parser fully tested. Input like `/give ana 50` or `/announce "server restarts soon" 30` should become a command name plus a list of arguments. Rules: prefix `/`, command names are case-insensitive, double quotes group words, `\"` inside quotes is a literal quote, an unterminated quote is an error. Tests first, then the parser.

# Answer
The spec lists the grammar as cases, including the error cases, so the tokenizer's behaviour is pinned down before it exists. The parser is a single pass over the characters with a small in-quote state.

```lua
--!strict
-- Script: ServerScriptService.Tests.CommandParserSpec
local CommandParser = require(game:GetService("ServerScriptService").CommandParser)

local failures = 0
local function test(name: string, fn: () -> ())
	local ok, err = pcall(fn)
	if not ok then
		failures += 1
		warn(`FAIL {name}: {err}`)
	end
end

test("splits on whitespace and lowercases the name", function()
	local cmd = CommandParser.parse("/GIVE  ana   50")
	assert(cmd and cmd.name == "give" and cmd.args[1] == "ana" and cmd.args[2] == "50")
end)
test("quotes group words", function()
	local cmd = CommandParser.parse('/announce "server restarts soon" 30')
	assert(cmd and cmd.args[1] == "server restarts soon" and cmd.args[2] == "30")
end)
test("escaped quote inside quotes", function()
	local cmd = CommandParser.parse('/say "he said \\"hi\\""')
	assert(cmd and cmd.args[1] == 'he said "hi"')
end)
test("not a command without prefix", function()
	local cmd, err = CommandParser.parse("give ana 50")
	assert(cmd == nil and err == "not a command")
end)
test("unterminated quote is an error", function()
	local cmd, err = CommandParser.parse('/say "oops')
	assert(cmd == nil and err == "unterminated quote")
end)

print(`CommandParser spec: {failures} failure(s)`)
```

```lua
--!strict
-- ModuleScript: ServerScriptService.CommandParser
export type Command = { name: string, args: { string } }

local MAX_LENGTH = 200

local CommandParser = {}

function CommandParser.parse(text: string): (Command?, string?)
	if string.sub(text, 1, 1) ~= "/" then
		return nil, "not a command"
	end
	if #text > MAX_LENGTH then
		return nil, "too long"
	end
	local tokens: { string } = {}
	local current: { string } = {}
	local inQuotes, hasToken = false, false
	local i = 2
	while i <= #text do
		local c = string.sub(text, i, i)
		if inQuotes then
			if c == "\\" and string.sub(text, i + 1, i + 1) == '"' then
				table.insert(current, '"')
				i += 1
			elseif c == '"' then
				inQuotes = false
			else
				table.insert(current, c)
			end
		elseif c == '"' then
			inQuotes, hasToken = true, true
		elseif string.match(c, "%s") then
			if hasToken then
				table.insert(tokens, table.concat(current))
				table.clear(current)
				hasToken = false
			end
		else
			table.insert(current, c)
			hasToken = true
		end
		i += 1
	end
	if inQuotes then
		return nil, "unterminated quote"
	end
	if hasToken then
		table.insert(tokens, table.concat(current))
	end
	if #tokens == 0 or tokens[1] == "" then
		return nil, "missing command name"
	end
	local name = string.lower(tokens[1])
	local args: { string } = {}
	for n = 2, #tokens do
		args[n - 1] = tokens[n]
	end
	return { name = name, args = args }, nil
end

return CommandParser
```

- `hasToken` is separate from "current is non-empty" so `""` (an empty quoted argument) still counts as an argument.
- The length cap bounds the work per message; parsing happens on the server, and permission checks (is this player an admin?) belong in the dispatcher, after parsing.
- Arguments stay strings; each command converts its own (`tonumber(args[2])`) and validates ranges, because only the command knows what is valid.

# Test
```lua
local c1 = item.parse("/GIVE  ana   50")
check("whitespace and lowercase", c1 and c1.name == "give" and c1.args[1] == "ana" and c1.args[2] == "50" and #c1.args == 2)
local c2 = item.parse('/announce "server restarts soon" 30')
check("quotes group", c2 and c2.args[1] == "server restarts soon" and c2.args[2] == "30")
local c3 = item.parse('/say "he said \\"hi\\""')
check("escaped quote", c3 and c3.args[1] == 'he said "hi"')
check("needs prefix", select(2, item.parse("give ana")) == "not a command")
check("unterminated quote", select(2, item.parse('/say "oops')) == "unterminated quote")
local c4 = item.parse('/tag "" x')
check("empty quoted argument kept", c4 and c4.args[1] == "" and c4.args[2] == "x")
check("missing name", select(2, item.parse("/   ")) == "missing command name")
check("too long", select(2, item.parse("/" .. string.rep("a", 300))) == "too long")
```
