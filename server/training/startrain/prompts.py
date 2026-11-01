"""Prompts for the owner's own models (the teachers). None of them contains text from the evaluation suites."""
from __future__ import annotations

HARNESS_REFERENCE = """\
TEST BODY API (already defined, never define or redefine these):
  load_answer(extra?)        runs the solution and returns what its chunk returns (the ModuleScript's value),
                             then the table of its globals. `extra` overrides globals, for example
                             load_answer({ game = g }) or load_answer({ task = { wait = function() end } }).
  check(name, condition)     records one assertion; name is a short unique sentence, condition a boolean.
  throws(fn, ...)            true when fn(...) raised an error.
  deepEqual(a, b)  deepCopy(t)  countKeys(t)  approx(a, b, eps?)  lcg(seed)  (a deterministic random function)
  Signal.new()               :Connect(fn) :Once(fn) :Fire(...) :Count()
ROBLOX STAND-INS (for Roblox-flavoured tasks; deterministic, no real time, no physics):
  Instance.new(className, parent?) with Name, ClassName, Parent, :IsA :FindFirstChild(name, recursive?)
    :FindFirstChildOfClass :FindFirstChildWhichIsA :GetChildren :GetDescendants :Destroy :Clone :ClearAllChildren
    :SetAttribute :GetAttribute :AddTag :HasTag :GetFullName. Events are Signals you fire yourself:
    obj.Touched:Fire(hit), obj.Activated:Fire(), obj.Equipped:Fire(), obj.MouseButton1Click:Fire(),
    remote.OnServerEvent:Fire(player, ...). Other properties (Size, Position, Anchored, Text, Health ...) are plain
    fields. FireServer / FireClient / FireAllClients calls on a remote are recorded in remote._calls as
    { method = "FireClient", player = p, args = { ... } }. Humanoid has Health, MaxHealth, WalkSpeed, :TakeDamage.
  Vector3, Vector2, Color3, UDim, UDim2, NumberRange, Enum.Group.Item, Random.new(seed) behave as in Roblox for the
    usual operations. There is no CFrame, no raycasting, no real DataStore, no HttpService.
  mockGame(services?)        a `game`. game:GetService works for Players (with :AddPlayer(p) :RemovePlayer(p)
                             :GetPlayers() :GetPlayerFromCharacter(model) and PlayerAdded / PlayerRemoving
                             Signals), RunService (Heartbeat Signal you :Fire(dt)), Debris (records AddItem in
                             ._items), CollectionService (AddTag RemoveTag HasTag GetTagged), TweenService, and any
                             other name as an empty Instance. Pass your own tables for other services, for example
                             mockGame({ DataStoreService = myFakeStore }). game:BindToClose(fn) stores fn in
                             game.__closers. Give it to the solution with load_answer({ game = g }).
  mockPlayer(name, userId, coins?)   a Player Instance; set p.Character = model yourself.
  mockCharacter(health?)             returns a Model with a Humanoid and a HumanoidRootPart, and the Humanoid.
"""

EXAMPLE_PURE = """\
### PROMPT
Write a Luau ModuleScript named RollingStats in --!strict mode. RollingStats.new(size: number) returns an object that keeps only the most recent `size` numbers and raises an error when size is not a positive integer. It has :push(value: number), which adds a value and drops the oldest one when the window is full; :count(): number, how many values are stored; :mean(): number?, the average of the stored values or nil when none; and :max(): number?, the largest stored value or nil when none.
### TESTS
```luau
local RollingStats = load_answer()
local r = RollingStats.new(3)
check("an empty window has no mean", r:mean() == nil)
check("an empty window has no max", r:max() == nil)
r:push(2)
r:push(4)
check("mean of 2 and 4 is 3", r:mean() == 3)
check("count is 2 after two pushes", r:count() == 2)
r:push(6)
r:push(10)
check("the window never holds more than 3 values", r:count() == 3)
check("mean of 4, 6, 10", approx(r:mean(), 20 / 3))
check("max of 4, 6, 10 is 10", r:max() == 10)
check("size 0 raises", throws(RollingStats.new, 0))
check("size 1.5 raises", throws(RollingStats.new, 1.5))
local single = RollingStats.new(1)
single:push(7)
single:push(-3)
check("a window of one keeps the newest value", single:mean() == -3 and single:count() == 1)
```
"""

EXAMPLE_MOCK = """\
### PROMPT
In my Roblox game: write a server ModuleScript named Checkpoints. Checkpoints.register(part: BasePart, order: number) connects part.Touched. When the touching part belongs to a player's character (find the player with Players:GetPlayerFromCharacter(hit.Parent)), set the player attribute "Stage" to `order`, but only when `order` is higher than the player's current Stage (a missing Stage counts as 0), and fire the player's progress with `remote:FireClient(player, order)` where `remote` is the RemoteEvent named "StageChanged" found with ReplicatedStorage:FindFirstChild("StageChanged"). Touches by anything that is not a player's character are ignored. Look services up with game:GetService.
### TESTS
```luau
local g = mockGame()
local players = g:GetService("Players")
local remote = Instance.new("RemoteEvent")
remote.Name = "StageChanged"
remote.Parent = g:GetService("ReplicatedStorage")
local Checkpoints = load_answer({ game = g })

local alice = mockPlayer("Alice", 1)
local character = mockCharacter()
alice.Character = character
players:AddPlayer(alice)

local pad2 = Instance.new("Part")
local pad5 = Instance.new("Part")
Checkpoints.register(pad2, 2)
Checkpoints.register(pad5, 5)
local hit = character:FindFirstChild("HumanoidRootPart")

pad2.Touched:Fire(hit)
check("touching pad 2 sets Stage to 2", alice:GetAttribute("Stage") == 2)
check("the client is told about stage 2", #remote._calls == 1 and remote._calls[1].method == "FireClient" and remote._calls[1].args[1] == 2)
pad5.Touched:Fire(hit)
check("touching pad 5 raises Stage to 5", alice:GetAttribute("Stage") == 5)
pad2.Touched:Fire(hit)
check("touching a lower pad never lowers Stage", alice:GetAttribute("Stage") == 5)
check("a lower pad sends nothing", #remote._calls == 2)
pad5.Touched:Fire(hit)
check("touching the same pad again sends nothing", #remote._calls == 2)
local crate = Instance.new("Part")
pad5.Touched:Fire(crate)
check("a part that is not a character is ignored", alice:GetAttribute("Stage") == 5 and #remote._calls == 2)
```
"""

TASK_SYSTEM = f"""\
You write training tasks for a Roblox / Luau coding assistant, each with an executable test file. Reply with exactly two sections and nothing else:

### PROMPT
<the task, written the way a Roblox developer would ask an assistant: 40 to 130 words, self-contained, SMALL (at most 4 functions or methods), in plain English. Name every module, function, method, parameter and return value the solution must provide, state the exact behaviour for every edge case the tests check, and for Roblox-flavoured tasks name every engine API the solution is expected to use (the tests only stand in for those). Do not mention tests, harness, mocks or this format. Vary your voice: sometimes begin with "In my Roblox game:", sometimes with "Write a Luau ModuleScript named ...".>
### TESTS
```luau
<the test body: 6 to 14 check(...) calls>
```

Rules for the tests: they are run against an independent solution written only from your PROMPT, so test only what the PROMPT promises. Start with `local X = load_answer(...)`. Every check needs a deterministic boolean. Cover normal cases, boundaries, invalid input (use throws) and state changes over several calls. Do not print, do not use real time or math.random, do not redefine the helpers below. Wrong solutions must fail at least one check.

{HARNESS_REFERENCE}
Two complete examples of the reply format follow (different topics from yours; do not copy them).

EXAMPLE 1
{EXAMPLE_PURE}
EXAMPLE 2
{EXAMPLE_MOCK}"""

SOLVER_SYSTEM = """\
You are a senior Roblox and Luau engineer. Reply with the complete solution as ONE fenced ```luau code block, followed by at most three short sentences saying how it works and any assumption you made. Luau typing reminders: there is no void type (a function that returns nothing returns ()), function types are written (a: T) -> R and never with the bare word function, optional types are T?, table types are { [string]: number } or { number }. Rules: current APIs only (task.wait, task.spawn, task.delay, os.clock; never wait, spawn, delay or tick); use :Connect and :Destroy; the code must be self-contained (no require of other modules) and must not print; follow the requested names and signatures exactly; handle invalid input as the task says. {mode_rule}"""

MODE_RULE = {
    "pure": "The first line of the code block must be --!strict and the code must pass strict type checking: annotate parameters and return types and declare exported types. Strict-mode habits that pass the checker: build a typed table as ONE literal with all its fields (never `local t: T = {}` and fill it later); give methods a `self: T` parameter where T is a plain record type; keep optional values as `T?` and test them against nil before use; use `{ [string]: number }` for maps. A class pattern that type-checks: `export type Stack = { items: { number } }` then `local Stack = {}` / `Stack.__index = Stack` / `function Stack.new() return setmetatable({ items = {} }, Stack) end` / `function Stack.push(self: Stack, v: number) table.insert(self.items, v) end`.",
    "mock": "Do not add a --!strict header. Use game:GetService(...) for services and the engine APIs the task names; for a ModuleScript return the module table at the end.",
}

IDEA_SYSTEM = """\
You suggest small, self-contained programming tasks for a Roblox / Luau coding assistant. Each task is one line of at most 30 words naming what must be built and one tricky behaviour. Tasks must differ from each other in what they compute or enforce. No numbering, no code, no commentary."""


def task_user(topic, idea: str, difficulty: int) -> str:
    mode = {
        "pure": "PURE LUAU. The solution is a ModuleScript in --!strict mode that uses only the Luau standard library (string, table, math, buffer, coroutine, utf8, os.clock). No Roblox services, no Instance, no Vector3.",
        "mock": "ROBLOX-FLAVOURED. The solution is a server-side Script or ModuleScript that uses Roblox APIs which the stand-ins provide. No --!strict header. Use only the stand-ins listed above, and say in the PROMPT exactly which APIs the solution should use.",
    }[topic.mode]
    return (f"Topic area: {topic.category} - {topic.text}\n"
            f"Idea to turn into a task: {idea}\n"
            f"Kind: {mode}\n"
            f"Difficulty {difficulty} of 3 (1 = one or two behaviours, 3 = a few interacting behaviours and edge cases; never more than 4 functions or methods).\n"
            "Write the PROMPT and TESTS now.")


def ideas_user(topic, n: int = 6) -> str:
    return (f"Topic area: {topic.category} - {topic.text}\n"
            f"Kind: {'plain Luau, no Roblox services' if topic.mode == 'pure' else 'Roblox-flavoured, using services, Instances, remotes or events that can be simulated'}\n"
            f"Give {n} different task ideas, one per line.")


def solver_messages(prompt: str, mode: str) -> list[dict]:
    return [{"role": "system", "content": SOLVER_SYSTEM.replace("{mode_rule}", MODE_RULE[mode])},
            {"role": "user", "content": prompt}]


REPAIR_SYSTEM = """\
You repair a previously generated Roblox/Luau solution after an independent verifier rejected it.
Return the COMPLETE replacement solution as ONE fenced \`\`\`luau code block, followed by at most three short
sentences. Do not ask to weaken, remove, rewrite, or bypass the verifier. Do not invent hidden test contents.
Treat the verifier message as a symptom: re-check the task from first principles and fix the underlying cause.
Keep all requested names, signatures, edge cases and current-API rules. The verifier can be incomplete, so do not
overfit to one error. Never print, require another module, use loadstring, disable checking, or claim that tests pass."""


def repair_messages(prompt: str, previous_response: str, mode: str, gate: str, code: str, detail: str) -> list[dict]:
    feedback = " ".join(str(detail).split())[:500] or "The independent verifier rejected the solution."
    system = REPAIR_SYSTEM + "\n" + MODE_RULE[mode]
    user = (
        "TASK (authoritative):\n" + prompt + "\n\n"
        "PREVIOUS SOLUTION (replace it, do not patch around the verifier):\n" + previous_response[:12000] + "\n\n"
        f"VERIFIER FEEDBACK:\ngate={gate}\ncode={code}\ndetail={feedback}\n\n"
        "Re-solve the task and return the complete corrected solution now."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
