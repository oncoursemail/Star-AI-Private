---
id: gb-src-keyed-cleanup-slots
category: performance
topics: Janitor, keyed cleanup, custom cleanup method, Tween Cancel, ability effects, memory leaks
source: adapted
source_id: janitor
source_path: README.md
source_commit: 47acf39d7b265fad409e438e976affa9468ff0a2
---
# Request
My character has "aura" effects: when a new aura starts, the old one's particles, tween and connections should be cleaned up, but I keep leaking the old tween or leaving particles behind. A plain cleanup list doesn't help because I only want to replace one slot. Is there a pattern for that?

# Answer
Use a cleaner with keyed slots, like Janitor's `Add(object, method, index)`: adding under a key first cleans whatever was stored under that key, and you can name the cleanup method per object (for example `"Cancel"` for a Tween). `remove(key)` cleans one slot; `cleanup()` cleans everything.

```lua
--!strict
export type Slots = {
	add: <T>(object: T, method: string?, key: string?) -> T,
	remove: (key: string) -> (),
	cleanup: () -> (),
}

type Entry = { object: any, method: string }

local Slots = {}

local function defaultMethod(object: any): string
	local kind = typeof(object)
	if kind == "function" then
		return "__call"
	elseif kind == "RBXScriptConnection" then
		return "Disconnect"
	end
	return "Destroy"
end

local function run(entry: Entry)
	local object = entry.object
	if entry.method == "__call" then
		object()
	else
		object[entry.method](object)
	end
end

function Slots.new(): Slots
	local keyed: { [string]: Entry } = {}
	local loose: { Entry } = {}

	local function remove(key: string)
		local entry = keyed[key]
		if entry then
			keyed[key] = nil
			run(entry)
		end
	end

	local function add<T>(object: T, method: string?, key: string?): T
		local entry = { object = object, method = method or defaultMethod(object) }
		if key then
			remove(key)
			keyed[key] = entry
		else
			table.insert(loose, entry)
		end
		return object
	end

	local function cleanup()
		for key in keyed do
			remove(key)
		end
		for i = #loose, 1, -1 do
			local entry = loose[i]
			loose[i] = nil
			run(entry)
		end
	end

	return { add = add, remove = remove, cleanup = cleanup }
end

return Slots
```

Aura usage:

```lua
--!strict
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")

local Slots = require(ReplicatedStorage:WaitForChild("Slots"))

local auraSlots = Slots.new()

local function startAura(root: BasePart, template: ParticleEmitter, light: PointLight)
	local emitter = template:Clone()
	emitter.Parent = root
	auraSlots.add(emitter, "Destroy", "AuraParticles")
	local pulse = TweenService:Create(light, TweenInfo.new(0.6, Enum.EasingStyle.Sine, Enum.EasingDirection.InOut, -1, true), { Brightness = 4 })
	pulse:Play()
	auraSlots.add(pulse, "Cancel", "AuraPulse")
end

local function stopAuras()
	auraSlots.cleanup()
end

return { startAura = startAura, stopAuras = stopAuras }
```

- Calling `startAura` again replaces both slots, so the previous emitter is destroyed and the endless tween cancelled automatically.
- The custom method name lets one cleaner handle objects whose cleanup is not `Destroy` (`Cancel`, `Stop`, `Disconnect`).
- Call `stopAuras()` when the character is removed to clear every slot at once.

# Test
```lua
local slots = item.new()
local first = Instance.new("Part")
first.Parent = workspace
slots.add(first, nil, "Aura")
local second = Instance.new("Part")
second.Parent = workspace
slots.add(second, nil, "Aura")
check("adding to a used key cleans the old object", first.Parent == nil and second.Parent == workspace)
local cancelled = 0
local fakeTween = { Cancel = function()
	cancelled += 1
end }
slots.add(fakeTween, "Cancel", "Pulse")
slots.remove("Pulse")
check("custom method used on remove", cancelled == 1)
slots.remove("Pulse")
check("removing an empty key is harmless", cancelled == 1)
local called = false
slots.add(function()
	called = true
end)
slots.cleanup()
check("cleanup clears keyed and loose entries", second.Parent == nil and called)
```
