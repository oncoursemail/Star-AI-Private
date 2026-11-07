---
id: gb-src-camera-cutscene-tween
category: gameplay-systems
topics: Camera, CameraType Scriptable, TweenService, CFrame.lookAt, Focus, cutscene
source: adapted
source_id: creator-docs
source_path: content/en-us/reference/engine/classes/Camera.yaml
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
When a boss spawns I want a short cutscene: the camera flies from the player to look at the boss arena over 2 seconds, holds for a moment, then gives control back to the player. How do I take over the camera and return it properly?

# Answer
On the client, set the camera to `Scriptable`, tween its `CFrame` (and `Focus`) to a `CFrame.lookAt` shot, then restore `CameraType = Custom` and the subject when the cutscene ends. Keep it in a function that returns when done, so the caller can sequence it.

```lua
--!strict
local TweenService = game:GetService("TweenService")

local Cutscene = {}

function Cutscene.shotLookingAt(target: Vector3, distance: number, height: number): CFrame
	local eye = target + Vector3.new(0, height, distance)
	return CFrame.lookAt(eye, target)
end

function Cutscene.run(camera: Camera, shot: CFrame, flySeconds: number, holdSeconds: number, subject: Humanoid?)
	camera.CameraType = Enum.CameraType.Scriptable
	local tween = TweenService:Create(camera, TweenInfo.new(flySeconds, Enum.EasingStyle.Sine, Enum.EasingDirection.InOut), {
		CFrame = shot,
		Focus = shot * CFrame.new(0, 0, -10),
	})
	tween:Play()
	tween.Completed:Wait()
	task.wait(holdSeconds)

	camera.CameraType = Enum.CameraType.Custom
	if subject then
		camera.CameraSubject = subject
	end
end

return Cutscene
```

LocalScript usage, when the server fires a `BossSpawned` remote with the arena position:

```lua
--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Cutscene = require(ReplicatedStorage:WaitForChild("Cutscene"))
local bossSpawned = ReplicatedStorage:WaitForChild("BossSpawned") :: RemoteEvent

bossSpawned.OnClientEvent:Connect(function(arenaPosition: Vector3)
	local character = Players.LocalPlayer.Character
	local humanoid = if character then character:FindFirstChildOfClass("Humanoid") else nil
	Cutscene.run(workspace.CurrentCamera, Cutscene.shotLookingAt(arenaPosition, 40, 20), 2, 1.5, humanoid)
end)
```

- The default camera scripts stop moving the camera only while `CameraType` is `Scriptable`; setting it back to `Custom` hands control back.
- Restoring `CameraSubject` matters if the character respawned during the cutscene.
- Camera work belongs on the client; the server only tells clients when to play it.

# Test
```lua
local camera = workspace.CurrentCamera
camera.CameraType = Enum.CameraType.Custom
local shot = item.shotLookingAt(Vector3.new(0, 0, 0), 40, 20)
check("shot looks toward the target", (shot.Position - Vector3.new(0, 20, 40)).Magnitude < 1e-4 and shot.LookVector.Z < 0)
local finished = false
task.spawn(function()
	item.run(camera, shot, 2, 1.5, nil)
	finished = true
end)
check("camera taken over", camera.CameraType == Enum.CameraType.Scriptable)
__advance(2.1)
check("camera reached the shot", (camera.CFrame.Position - shot.Position).Magnitude < 1e-3 and not finished)
__advance(1.5)
check("control returned after the hold", finished and camera.CameraType == Enum.CameraType.Custom)
```
