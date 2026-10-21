---
id: gb-world-vfx-status-aura
category: vfx-particles
topics: status effect, ParticleEmitter, attribute, fade out, task.cancel
source: original
---
# Request
When a player is burning the server sets a `Burning` attribute on their character. On the client I want fire particles while it's true, but when it turns off the flames should fade out naturally instead of vanishing. Re-igniting during the fade should keep the same emitter.

# Answer
Watch the attribute and keep one emitter per character. Turning off sets `Enabled = false` (existing particles finish their lifetime) and schedules destruction after the longest lifetime; turning back on cancels that scheduled cleanup and re-enables the same emitter.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.StatusAura
local StatusAura = {}

function StatusAura.bind(character: Model, attribute: string, template: ParticleEmitter): () -> ()
	local root = character:FindFirstChild("HumanoidRootPart")
	assert(root, "character needs a HumanoidRootPart")
	local emitter: ParticleEmitter? = nil
	local fadeThread: thread? = nil

	local function cancelFade()
		if fadeThread then
			task.cancel(fadeThread)
			fadeThread = nil
		end
	end

	local function refresh()
		local current = emitter
		if character:GetAttribute(attribute) == true then
			cancelFade()
			if current == nil then
				current = template:Clone()
				current.Parent = root
				emitter = current
			end
			current.Enabled = true
		elseif current and current.Enabled then
			current.Enabled = false
			fadeThread = task.delay(current.Lifetime.Max, function()
				fadeThread = nil
				current:Destroy()
				if emitter == current then
					emitter = nil
				end
			end)
		end
	end

	local connection = character:GetAttributeChangedSignal(attribute):Connect(refresh)
	refresh()

	return function()
		connection:Disconnect()
		cancelFade()
		if emitter then
			emitter:Destroy()
			emitter = nil
		end
	end
end

return StatusAura
```

- The attribute is set by the server, so every client shows the same state, and the visual layer can never change whether the player is burning.
- `Enabled = false` stops new particles only; flames already in the air live out their `Lifetime`, which is the natural fade.
- `task.cancel` on the pending cleanup is what lets a quick re-ignite reuse the emitter instead of destroying it a moment later.

# Test
```lua
local player = __makePlayer(14, "Torch")
local character = __makeCharacter(player)
local template = Instance.new("ParticleEmitter")
template.Name = "Flames"
template.Lifetime = NumberRange.new(0.4, 1)
local unbind = item.bind(character, "Burning", template)
local root = character.HumanoidRootPart

character:SetAttribute("Burning", true)
local flames = root:FindFirstChild("Flames")
check("flames appear while burning", flames ~= nil and flames.Enabled)
character:SetAttribute("Burning", false)
check("emitter disabled but kept during the fade", flames.Enabled == false and flames.Parent == root)
__advance(0.5)
character:SetAttribute("Burning", true)
__advance(1)
check("re-ignite reuses the emitter and cancels cleanup", root:FindFirstChild("Flames") == flames and flames.Enabled)
character:SetAttribute("Burning", false)
__advance(1.1)
check("destroyed after the longest lifetime", root:FindFirstChild("Flames") == nil)
character:SetAttribute("Burning", true)
unbind()
check("unbind removes the emitter", root:FindFirstChild("Flames") == nil)
```
