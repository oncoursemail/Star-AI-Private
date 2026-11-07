---
id: gb-src-numeric-textbox
category: ui-text
topics: TextBox, GetPropertyChangedSignal, FocusLost, input sanitizing, clamp, quantity input
source: adapted
source_id: creator-docs
source_path: content/en-us/ui/text-input.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
My shop has a quantity TextBox. Players type letters, negative numbers, or 99999999 and the purchase code breaks. I want the box to accept only digits, cap at 99, and submit when they press Enter. How do I do that?

# Answer
Sanitize on every text change with `GetPropertyChangedSignal("Text")` (strip non-digits and cap the length), then on `FocusLost` with `enterPressed` parse and clamp the number before using it. Treat it as a request: the server still validates the quantity.

```lua
--!strict
local QuantityBox = {}

local MAX_DIGITS = 2

function QuantityBox.sanitize(text: string): string
	local digits = string.gsub(text, "%D", "")
	return string.sub(digits, 1, MAX_DIGITS)
end

function QuantityBox.parse(text: string, minimum: number, maximum: number): number
	local value = tonumber(text)
	if value == nil then
		return minimum
	end
	return math.clamp(math.floor(value), minimum, maximum)
end

function QuantityBox.bind(textBox: TextBox, onSubmit: (quantity: number) -> ()): () -> ()
	textBox.ClearTextOnFocus = false
	local textChanged = textBox:GetPropertyChangedSignal("Text"):Connect(function()
		local clean = QuantityBox.sanitize(textBox.Text)
		if clean ~= textBox.Text then
			textBox.Text = clean
		end
	end)
	local focusLost = textBox.FocusLost:Connect(function(enterPressed: boolean)
		local quantity = QuantityBox.parse(textBox.Text, 1, 99)
		textBox.Text = tostring(quantity)
		if enterPressed then
			onSubmit(quantity)
		end
	end)
	return function()
		textChanged:Disconnect()
		focusLost:Disconnect()
	end
end

return QuantityBox
```

- Rewriting `Text` inside its own changed signal re-fires the signal once; the `clean ~= textBox.Text` check stops the loop.
- `%D` matches every non-digit, so minus signs, decimals and letters are all removed.
- Clicking away still normalizes the box but only Enter submits, matching what players expect.

# Test
```lua
check("non-digits removed", item.sanitize("a1-2.5") == "12")
check("length capped", item.sanitize("12345") == "12")
check("empty parses to minimum", item.parse("", 1, 99) == 1)
check("clamped to range", item.parse("0", 1, 99) == 1 and item.parse("150", 1, 99) == 99)
local box = Instance.new("TextBox")
local submitted = nil
item.bind(box, function(q)
	submitted = q
end)
box.Text = "x7y"
check("box sanitized live", box.Text == "7")
box:ReleaseFocus(true)
check("enter submits the quantity", submitted == 7)
submitted = nil
box.Text = ""
box:ReleaseFocus(false)
check("focus lost without enter does not submit", submitted == nil and box.Text == "1")
```
