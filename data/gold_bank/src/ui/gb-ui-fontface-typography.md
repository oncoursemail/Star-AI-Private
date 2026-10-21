---
id: gb-ui-fontface-typography
category: ui-text
topics: FontFace, Font.new, FontWeight, typography roles, Enum.Font
source: original
---
# Request
I want a semibold weight for headings, but `Enum.Font` only has things like GothamBold and GothamMedium, and I keep mixing them up across menus. How do I use FontFace properly and keep fonts consistent?

# Answer
`FontFace` takes a `Font` built from a font family plus any weight and style, so one family covers every weight. Define typography roles once (family, weight, size) and apply them by role, so menus never pick fonts directly.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Typography
local Typography = {}

local FAMILY = "rbxasset://fonts/families/GothamSSm.json"

export type Role = "title" | "heading" | "body" | "caption" | "number"

type Spec = { weight: EnumItem, size: number }

local ROLES: { [Role]: Spec } = {
	title = { weight = Enum.FontWeight.Bold, size = 28 },
	heading = { weight = Enum.FontWeight.SemiBold, size = 20 },
	body = { weight = Enum.FontWeight.Regular, size = 16 },
	caption = { weight = Enum.FontWeight.Regular, size = 13 },
	number = { weight = Enum.FontWeight.Medium, size = 18 },
}

function Typography.font(role: Role): Font
	local spec = ROLES[role]
	return Font.new(FAMILY, spec.weight, Enum.FontStyle.Normal)
end

function Typography.apply(label: TextLabel | TextButton | TextBox, role: Role)
	local spec = ROLES[role]
	label.FontFace = Typography.font(role)
	label.TextSize = spec.size
end

return Typography
```

- Weight is just a field of the Font, so `heading` can move from SemiBold to Bold in one line for the whole game.
- Avoid setting the legacy `Font` property anywhere once you use FontFace; the last one written wins and mixes styles.
- Families are referenced by asset path; one family in the whole UI with two or three weights reads cleaner than several fonts.

# Test
```lua
local title = Instance.new("TextLabel")
item.apply(title, "heading")
check("family applied", title.FontFace.Family == "rbxasset://fonts/families/GothamSSm.json")
check("semibold heading", title.FontFace.Weight == Enum.FontWeight.SemiBold and title.TextSize == 20)
local button = Instance.new("TextButton")
item.apply(button, "body")
check("body is regular weight", button.FontFace.Weight == Enum.FontWeight.Regular)
check("upright style", item.font("title").Style == Enum.FontStyle.Normal and item.font("title").Weight == Enum.FontWeight.Bold)
```
