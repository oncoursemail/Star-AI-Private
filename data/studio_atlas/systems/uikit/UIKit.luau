--!strict
-- Responsive UI pattern: design at one reference resolution and let a UIScale adapt it, keep UI inside the device
-- safe area, grow targets on touch and TV, and swap prompts when the active input device changes.

export type Mode = "Touch" | "Gamepad" | "Desktop"
export type Signal = { Connect: (self: Signal, fn: () -> ()) -> { Disconnect: (self: any) -> () } }
export type MountConfig = {
	gui: any, -- the ScreenGui
	scale: any, -- a UIScale parented to a full-size root Frame inside the gui
	safeInsets: any, -- Enum.ScreenInsets.DeviceSafeInsets
	viewport: () -> (number, number), -- workspace.CurrentCamera.ViewportSize.X, .Y
	viewportChanged: Signal, -- camera:GetPropertyChangedSignal("ViewportSize")
	lastInputType: () -> string, -- UserInputService:GetLastInputType().Name
	inputChanged: Signal, -- UserInputService.LastInputTypeChanged, adapted to take no arguments
	isTenFoot: () -> boolean, -- GuiService:IsTenFootInterface()
	onMode: (mode: Mode, tenFoot: boolean) -> (), -- swap button prompts, show or hide on-screen controls
	reference: { width: number, height: number }?, -- default 1280 x 720
	minScale: number?, -- default 0.5
	maxScale: number?, -- default 2
}

local UIKit = {}

-- Fit the reference design inside the viewport (letterbox rule), within sane limits.
function UIKit.computeScale(width: number, height: number, refW: number, refH: number, minScale: number, maxScale: number): number
	if width <= 0 or height <= 0 then
		return 1
	end
	return math.clamp(math.min(width / refW, height / refH), minScale, maxScale)
end

function UIKit.inputMode(lastInputType: string): Mode
	if lastInputType == "Touch" then
		return "Touch"
	elseif string.sub(lastInputType, 1, 7) == "Gamepad" then
		return "Gamepad"
	end
	return "Desktop"
end

-- Size in design pixels that ends up at least `minPixels` on screen (44 is the usual touch minimum).
function UIKit.minTarget(scale: number, minPixels: number): number
	return math.ceil(minPixels / math.max(scale, 0.01))
end

-- prompts = { Interact = { Touch = "Tap", Gamepad = "A", Desktop = "E" } }
function UIKit.prompt(prompts: { [string]: { [string]: string } }, action: string, mode: Mode): string
	local entry = prompts[action]
	return if entry then entry[mode] or entry.Desktop or action else action
end

function UIKit.mount(cfg: MountConfig): () -> ()
	local ref = cfg.reference or { width = 1280, height = 720 }
	local minScale, maxScale = cfg.minScale or 0.5, cfg.maxScale or 2
	cfg.gui.ScreenInsets = cfg.safeInsets -- the engine keeps this gui's content out of notches and home bars
	cfg.gui.ResetOnSpawn = false

	local function refresh()
		local width, height = cfg.viewport()
		local tenFoot = cfg.isTenFoot()
		local scale = UIKit.computeScale(width, height, ref.width, ref.height, minScale, maxScale)
		cfg.scale.Scale = if tenFoot then math.min(scale * 1.25, maxScale) else scale
		cfg.onMode(UIKit.inputMode(cfg.lastInputType()), tenFoot)
	end

	refresh()
	local connections = { cfg.viewportChanged:Connect(refresh), cfg.inputChanged:Connect(refresh) }
	return function()
		for _, connection in connections do
			connection:Disconnect()
		end
	end
end

return UIKit
