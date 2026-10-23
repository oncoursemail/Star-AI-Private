---
id: gb-ui-shop-card-square-icon
category: ui-layout
topics: UIAspectRatioConstraint, shop card, ImageLabel, TextTruncate, component
source: original
---
# Request
My shop item cards stretch with the screen, and the item icons get squashed into wide ovals on phones. I want a card component where the icon always stays square, the name stays on one line, and the price sits at the bottom.

# Answer
Let the card fill whatever cell the grid gives it, and put a UIAspectRatioConstraint of 1 on the icon only, so the icon keeps its shape while the card stretches. The name uses truncation and the price row is anchored to the bottom edge.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.ShopCard
local ShopCard = {}

export type CardData = {
	name: string,
	price: number,
	image: string,
}

function ShopCard.build(data: CardData): Frame
	local card = Instance.new("Frame")
	card.Name = "Card"
	card.BackgroundColor3 = Color3.fromRGB(34, 36, 42)
	card.Size = UDim2.fromScale(1, 1)

	local corner = Instance.new("UICorner")
	corner.CornerRadius = UDim.new(0, 8)
	corner.Parent = card

	local icon = Instance.new("ImageLabel")
	icon.Name = "Icon"
	icon.BackgroundTransparency = 1
	icon.AnchorPoint = Vector2.new(0.5, 0)
	icon.Position = UDim2.new(0.5, 0, 0, 8)
	icon.Size = UDim2.new(1, -16, 0.62, 0)
	icon.ScaleType = Enum.ScaleType.Fit
	icon.Image = data.image
	icon.Parent = card

	local square = Instance.new("UIAspectRatioConstraint")
	square.AspectRatio = 1
	square.Parent = icon

	local name = Instance.new("TextLabel")
	name.Name = "ItemName"
	name.BackgroundTransparency = 1
	name.Position = UDim2.new(0, 8, 0.66, 0)
	name.Size = UDim2.new(1, -16, 0.14, 0)
	name.TextScaled = true
	name.TextTruncate = Enum.TextTruncate.AtEnd
	name.TextColor3 = Color3.fromRGB(236, 236, 240)
	name.Text = data.name
	name.Parent = card

	local price = Instance.new("TextLabel")
	price.Name = "Price"
	price.BackgroundTransparency = 1
	price.AnchorPoint = Vector2.new(0, 1)
	price.Position = UDim2.new(0, 8, 1, -6)
	price.Size = UDim2.new(1, -16, 0.13, 0)
	price.TextScaled = true
	price.TextXAlignment = Enum.TextXAlignment.Left
	price.TextColor3 = Color3.fromRGB(240, 200, 90)
	price.Text = tostring(data.price)
	price.Parent = card

	local textCap = Instance.new("UITextSizeConstraint")
	textCap.MaxTextSize = 20
	textCap.Parent = name
	textCap:Clone().Parent = price

	return card
end

return ShopCard
```

- The aspect constraint shrinks whichever axis is too long, so a wide card gets a centred square icon instead of a stretched one.
- `ScaleType.Fit` keeps non-square artwork inside the square without cropping.
- The text cap stops TextScaled names from becoming huge on tablets; pair it with the card size from your grid.
- The image id comes in through `data.image`, so the card works for any catalogue.

# Test
```lua
local card = item.build({ name = "Dragon Slayer Greatsword of the North", price = 1500, image = "rbxassetid://1" })
local ratio = card.Icon:FindFirstChildOfClass("UIAspectRatioConstraint")
check("icon kept square", ratio ~= nil and ratio.AspectRatio == 1)
check("long names truncate", card.ItemName.TextTruncate == Enum.TextTruncate.AtEnd)
check("price pinned to the bottom", card.Price.AnchorPoint.Y == 1 and card.Price.Position.Y.Scale == 1)
check("both labels capped", card.ItemName:FindFirstChildOfClass("UITextSizeConstraint") ~= nil
	and card.Price:FindFirstChildOfClass("UITextSizeConstraint") ~= nil)
check("data applied", card.Price.Text == "1500" and card.Icon.Image == "rbxassetid://1")
check("returned unparented for the caller to place", card.Parent == nil)
```
