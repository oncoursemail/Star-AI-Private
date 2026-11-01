local Kit = require("../../testkit")
local UIKit = require("./UIKit")

Kit.test("scale fits the reference design and stays within limits", function()
	Kit.eq(UIKit.computeScale(1280, 720, 1280, 720, 0.5, 2), 1)
	Kit.eq(UIKit.computeScale(1920, 1080, 1280, 720, 0.5, 2), 1.5)
	Kit.eq(UIKit.computeScale(2560, 720, 1280, 720, 0.5, 2), 1, "ultrawide is limited by height")
	Kit.eq(UIKit.computeScale(400, 200, 1280, 720, 0.5, 2), 0.5, "tiny phone clamps")
	Kit.eq(UIKit.computeScale(7680, 4320, 1280, 720, 0.5, 2), 2)
	Kit.eq(UIKit.computeScale(0, 0, 1280, 720, 0.5, 2), 1, "zero viewport during load")
end)

Kit.test("input device maps to a mode", function()
	Kit.eq(UIKit.inputMode("Touch"), "Touch")
	Kit.eq(UIKit.inputMode("Gamepad1"), "Gamepad")
	Kit.eq(UIKit.inputMode("Keyboard"), "Desktop")
	Kit.eq(UIKit.inputMode("MouseMovement"), "Desktop")
end)

Kit.test("touch targets are at least 44 pixels on screen", function()
	Kit.eq(UIKit.minTarget(1, 44), 44)
	Kit.eq(UIKit.minTarget(0.5, 44), 88)
	Kit.truthy(UIKit.minTarget(0, 44) > 0)
end)

Kit.test("prompts follow the mode", function()
	local prompts = { Interact = { Touch = "Tap", Gamepad = "A", Desktop = "E" } }
	Kit.eq(UIKit.prompt(prompts, "Interact", "Gamepad"), "A")
	Kit.eq(UIKit.prompt(prompts, "Missing", "Touch"), "Missing")
end)

Kit.test("mount scales, sets safe insets, reacts to changes and cleans up", function()
	local viewportChanged, inputChanged = Kit.signal(), Kit.signal()
	local size, input, tenFoot, modes = { 1280, 720 }, "Keyboard", false, {}
	local gui, scale = {}, { Scale = 1 }
	local destroy = UIKit.mount({
		gui = gui, scale = scale, safeInsets = "DeviceSafeInsets",
		viewport = function() return size[1], size[2] end, viewportChanged = viewportChanged,
		lastInputType = function() return input end, inputChanged = inputChanged,
		isTenFoot = function() return tenFoot end,
		onMode = function(mode, tf) table.insert(modes, mode .. (tf and "+tv" or "")) end,
	})
	Kit.eq(gui.ScreenInsets, "DeviceSafeInsets")
	Kit.eq(gui.ResetOnSpawn, false)
	size = { 640, 360 }
	viewportChanged:Fire()
	Kit.eq(scale.Scale, 0.5)
	input, tenFoot, size = "Gamepad1", true, { 1920, 1080 }
	inputChanged:Fire()
	Kit.eq(scale.Scale, 1.875)
	Kit.eq(modes[#modes], "Gamepad+tv")
	destroy()
	size = { 1280, 720 }
	viewportChanged:Fire()
	Kit.eq(scale.Scale, 1.875, "no updates after cleanup")
end)

Kit.finish("uikit")
