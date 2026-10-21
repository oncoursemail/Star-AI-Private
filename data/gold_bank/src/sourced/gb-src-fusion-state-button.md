---
id: gb-src-fusion-state-button
category: ui-style
topics: Fusion, scoped, Value, Computed, Spring, OnEvent, reactive UI, button states
source: adapted
source_id: fusion
source_path: docs/examples/cookbook/button-component.md
source_commit: 2790f7b6272bdf7cd0bbfee259a2f9d79ea20810
---
# Request
I'm moving my UI to Fusion 0.3. I need a reusable button component with hover, pressed and disabled colours that animate smoothly, and an `OnClick` callback that doesn't fire while disabled. How do I structure that as a Fusion component?

# Answer
A component is a function that takes a `scope` and typed props and returns an instance. Keep hover and pressed state in `scope:Value`s, derive the background colour with `scope:Computed`, smooth it with `scope:Spring`, and wire input with `OnEvent`. Props such as `Text` and `Disabled` accept either plain values or state objects (Fusion's `UsedAs<T>`; typed `any` here so the snippet checks without Fusion's type definitions).

```lua
--!strict
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Fusion = require(ReplicatedStorage:WaitForChild("Packages"):WaitForChild("Fusion"))
local peek = Fusion.peek
local Children, OnEvent = Fusion.Children, Fusion.OnEvent

local WHITE = Color3.new(1, 1, 1)
local BG_REST = Color3.fromHex("0085FF")
local BG_HOVER = BG_REST:Lerp(WHITE, 0.25)
local BG_HELD = BG_REST:Lerp(Color3.new(0, 0, 0), 0.25)
local BG_DISABLED = Color3.fromHex("CCCCCC")

export type ButtonProps = {
	Text: any,
	Size: any?,
	Disabled: any?,
	OnClick: (() -> ())?,
}

local function Button(scope: any, props: ButtonProps): TextButton
	local isHovering = scope:Value(false)
	local isHeld = scope:Value(false)

	return scope:New "TextButton" {
		Size = props.Size or UDim2.fromOffset(160, 40),
		Text = props.Text,
		TextColor3 = WHITE,
		AutoButtonColor = false,
		BackgroundColor3 = scope:Spring(scope:Computed(function(use)
			return if use(props.Disabled or false) then BG_DISABLED
				elseif use(isHeld) then BG_HELD
				elseif use(isHovering) then BG_HOVER
				else BG_REST
		end), 20),

		[OnEvent "Activated"] = function()
			if props.OnClick and not peek(props.Disabled or false) then
				props.OnClick()
			end
		end,
		[OnEvent "MouseButton1Down"] = function()
			isHeld:set(true)
		end,
		[OnEvent "MouseButton1Up"] = function()
			isHeld:set(false)
		end,
		[OnEvent "MouseEnter"] = function()
			isHovering:set(true)
		end,
		[OnEvent "MouseLeave"] = function()
			isHeld:set(false)
			isHovering:set(false)
		end,

		[Children] = {
			scope:New "UICorner" { CornerRadius = UDim.new(0, 6) },
		},
	}
end

return Button
```

Usage: `local scope = Fusion.scoped(Fusion)`, then `Button(scope, { Text = "Buy", Disabled = notEnoughCoins, OnClick = buy }).Parent = shopFrame`, and `scope:doCleanup()` when the shop closes.

- The order of the conditions sets priority: disabled beats pressed, pressed beats hover.
- `peek` reads the current disabled state without subscribing, which is what a one-off click check needs.
- Releasing the held state on `MouseLeave` stops the button from looking stuck when the cursor slides off while pressed.
- Everything created through `scope` is destroyed by `scope:doCleanup()`, so closing the menu leaks nothing.
