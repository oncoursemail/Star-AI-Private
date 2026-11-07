# Responsive UI kit

Client-side (LocalScript). Design at 1280x720, let one `UIScale` adapt it.

## API
- `UIKit.mount({ gui, scale, safeInsets, viewport, viewportChanged, lastInputType, inputChanged, isTenFoot, onMode, reference?, minScale?, maxScale? }) -> destroy`.
- `UIKit.computeScale(w, h, refW, refH, min, max)`, `UIKit.inputMode(lastInputTypeName) -> "Touch" | "Gamepad" | "Desktop"`, `UIKit.minTarget(scale, 44)`, `UIKit.prompt(prompts, action, mode)`.

## Wire it
`gui` is your ScreenGui, `scale` a `UIScale` inside a full-size root Frame. `safeInsets = Enum.ScreenInsets.DeviceSafeInsets`, `viewport = function() local v = workspace.CurrentCamera.ViewportSize return v.X, v.Y end`, `viewportChanged = camera:GetPropertyChangedSignal("ViewportSize")`, `lastInputType = function() return UserInputService:GetLastInputType().Name end`, `isTenFoot = function() return GuiService:IsTenFootInterface() end`; adapt `LastInputTypeChanged` to a no-argument signal.

## Pitfalls
- Use Scale/UDim2 and `AutomaticSize` inside the root frame, not hard pixel positions; one UIScale then covers phones to TVs.
- Touch buttons need at least 44 px on screen: use `minTarget`.
- Show on-screen controls and prompts by mode, and listen for input changes (players plug in a pad).
- The camera viewport can be 0 while loading; `computeScale` returns 1 then.
