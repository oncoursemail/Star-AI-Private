---
id: gb-src-grenade-state-vfx
category: vfx-particles
topics: ParticleEmitter, Emit, attributes, state machine, Highlight, client visuals, server state
source: adapted
source_id: creator-docs
source_path: content/en-us/projects/server-authority/techniques.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
My grenade logic and effects are all in one server script: it enables sparks, plays the explosion particles with `Emit`, changes a highlight... and it looks laggy for players. How should I split the grenade so the server decides what happens and clients only do the effects?

# Answer
Keep the grenade's state on the server as attributes (`State`, `LitAt`), advanced by a small pure state machine. Clients watch the attributes and play effects locally: sparks while lit, one `Emit` burst on the transition to exploded, and a highlight that fills in as the fuse burns.

```lua
--!strict
local Grenade = {}

Grenade.States = { Idle = 0, Lit = 1, Exploded = 2, Defused = 3 }
Grenade.FUSE_SECONDS = 3

function Grenade.nextState(state: number, litAt: number, now: number): number
	if state == Grenade.States.Lit and now - litAt >= Grenade.FUSE_SECONDS then
		return Grenade.States.Exploded
	end
	return state
end

function Grenade.serverStep(grenade: BasePart, now: number)
	local state = grenade:GetAttribute("State")
	local litAt = grenade:GetAttribute("LitAt")
	if typeof(state) ~= "number" or typeof(litAt) ~= "number" then
		return
	end
	local newState = Grenade.nextState(state, litAt, now)
	if newState ~= state then
		grenade:SetAttribute("State", newState)
	end
end

function Grenade.bindVisuals(grenade: BasePart, sparks: ParticleEmitter, burst: ParticleEmitter, highlight: Highlight): () -> ()
	local initial = grenade:GetAttribute("State")
	local previous: number? = if typeof(initial) == "number" then initial else nil
	local function refresh()
		local state = grenade:GetAttribute("State")
		sparks.Enabled = state == Grenade.States.Lit
		if state ~= previous and state == Grenade.States.Exploded then
			burst:Emit(100)
		end
		previous = if typeof(state) == "number" then state else nil
		if state == Grenade.States.Lit then
			highlight.FillColor = Color3.fromRGB(255, 0, 0)
		elseif state == Grenade.States.Defused then
			highlight.FillColor = Color3.fromRGB(0, 255, 125)
			highlight.FillTransparency = 0.5
		else
			highlight.FillTransparency = 1
		end
	end
	local connection = grenade:GetAttributeChangedSignal("State"):Connect(refresh)
	refresh()
	return function()
		connection:Disconnect()
	end
end

function Grenade.fuseFill(litAt: number, now: number): number
	return 1 - math.clamp((now - litAt) / Grenade.FUSE_SECONDS, 0, 1)
end

return Grenade
```

- Attributes replicate, so every client sees the same state change and plays its own effects with no extra remotes.
- `Emit(100)` fires one burst only on a change into Exploded; `previous` starts at the current state, so a client that joins or streams the grenade in after the explosion does not replay it.
- `fuseFill` gives the highlight transparency per frame on the client (`workspace:GetServerTimeNow()` as `now`, with `LitAt` set from the same clock on the server).

# Test
```lua
local S = item.States
check("lit grenade waits for the fuse", item.nextState(S.Lit, 10, 12.9) == S.Lit)
check("explodes after the fuse", item.nextState(S.Lit, 10, 13) == S.Exploded)
check("idle and defused never explode", item.nextState(S.Idle, 0, 99) == S.Idle and item.nextState(S.Defused, 0, 99) == S.Defused)
local grenade = Instance.new("Part")
local sparks = Instance.new("ParticleEmitter")
local burst = Instance.new("ParticleEmitter")
local highlight = Instance.new("Highlight")
grenade:SetAttribute("State", S.Lit)
grenade:SetAttribute("LitAt", 0)
item.bindVisuals(grenade, sparks, burst, highlight)
check("sparks on while lit", sparks.Enabled == true)
item.serverStep(grenade, 3.5)
check("server step explodes and client bursts once", grenade:GetAttribute("State") == S.Exploded and burst.__emitted == 100 and sparks.Enabled == false)
grenade:SetAttribute("State", S.Exploded)
check("no second burst", burst.__emitted == 100)
local late = Instance.new("Part")
late:SetAttribute("State", S.Exploded)
late:SetAttribute("LitAt", 0)
local lateBurst = Instance.new("ParticleEmitter")
item.bindVisuals(late, Instance.new("ParticleEmitter"), lateBurst, Instance.new("Highlight"))
check("binding to an already exploded grenade does not burst", (lateBurst.__emitted or 0) == 0)
check("fuse fill goes from 1 to 0", item.fuseFill(0, 0) == 1 and item.fuseFill(0, 3) == 0)
```
