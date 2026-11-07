---
id: gb-ui-purchase-confirm-intent
category: ui-interaction
topics: confirmation dialog, RemoteEvent, purchase intent, double click, timeout
source: original
---
# Request
My shop's Buy button fires `BuyItem:FireServer(itemId, price)` straight away. Players complain about accidental purchases, and spamming the button sometimes buys twice. I want a confirm step and a button that waits for the server. What should the client side look like?

# Answer
Make the client a small state machine: idle, confirming, waiting. Buy opens the confirmation with the display price; Confirm sends only the item id and locks the button until the server answers or a timeout passes. The server owns the price, so the client never sends it.

```lua
--!strict
-- ModuleScript: StarterPlayerScripts.PurchaseFlow
local PurchaseFlow = {}

export type State = "idle" | "confirming" | "waiting"
export type Flow = {
	requestBuy: (itemId: string) -> (),
	confirm: () -> (),
	cancel: () -> (),
	state: () -> State,
	pendingItem: () -> string?,
}

local TIMEOUT = 5

function PurchaseFlow.new(remote: RemoteEvent, onState: (state: State, itemId: string?) -> ()): Flow
	local state: State = "idle"
	local selected: string? = nil
	local attempt = 0

	local function set(newState: State)
		state = newState
		onState(state, selected)
	end

	local function requestBuy(itemId: string)
		if state ~= "idle" then
			return
		end
		selected = itemId
		set("confirming")
	end

	local function confirm()
		if state ~= "confirming" or selected == nil then
			return
		end
		attempt += 1
		local thisAttempt = attempt
		remote:FireServer(selected)
		set("waiting")
		task.delay(TIMEOUT, function()
			if state == "waiting" and attempt == thisAttempt then
				selected = nil
				set("idle")
			end
		end)
	end

	local function cancel()
		if state == "confirming" then
			selected = nil
			set("idle")
		end
	end

	remote.OnClientEvent:Connect(function(itemId: string, _ok: boolean)
		if state == "waiting" and itemId == selected then
			selected = nil
			set("idle")
		end
	end)

	return {
		requestBuy = requestBuy,
		confirm = confirm,
		cancel = cancel,
		state = function()
			return state
		end,
		pendingItem = function()
			return selected
		end,
	}
end

return PurchaseFlow
```

- `onState` is where the UI shows the confirm panel, greys out Buy while waiting, and shows the result message.
- The attempt counter stops an old timeout from resetting a newer purchase.
- On the server, look up the price from the item id, check the balance and a per-player cooldown, deduct, then `FireClient(player, itemId, ok)`; the client's lock is only for comfort, not security.

# Test
```lua
local remote = Instance.new("RemoteEvent")
local states = {}
local flow = item.new(remote, function(s)
	table.insert(states, s)
end)
flow.confirm()
check("confirm without a request does nothing", #remote.__sent == 0)
flow.requestBuy("sword")
flow.requestBuy("bow")
check("second buy ignored while confirming", flow.pendingItem() == "sword")
flow.confirm()
flow.confirm()
check("only the item id is sent, once", #remote.__sent == 1 and remote.__sent[1][2] == "sword" and remote.__sent[1][3] == nil)
check("locked while waiting", flow.state() == "waiting")
remote.OnClientEvent:Fire("sword", true)
check("server reply unlocks", flow.state() == "idle")
flow.requestBuy("bow")
flow.confirm()
__advance(5)
check("timeout unlocks a lost reply", flow.state() == "idle" and #remote.__sent == 2)
flow.requestBuy("shield")
flow.cancel()
check("cancel returns to idle without sending", flow.state() == "idle" and #remote.__sent == 2)
```
