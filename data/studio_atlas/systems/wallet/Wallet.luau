--!strict
-- Currency service with leaderstats mirroring. Balances live in a plain table (your profile's Data) and only
-- this service changes them: integer amounts, per-currency cap, no negative balances.

export type CurrencyDef = { max: number }
export type Publisher = {
	Show: (player: any, currency: string, value: number) -> (), -- create or update the visible stat
	Hide: (player: any) -> (),
}
export type Config = { currencies: { [string]: CurrencyDef }, publisher: Publisher? }
export type Wallet = {
	Attach: (self: Wallet, player: any, balances: { [string]: number }) -> (),
	Detach: (self: Wallet, player: any) -> (),
	Get: (self: Wallet, player: any, currency: string) -> number,
	Add: (self: Wallet, player: any, currency: string, amount: number) -> (boolean, string?),
	Spend: (self: Wallet, player: any, currency: string, amount: number) -> (boolean, string?),
}

local Wallets = {}

local function validAmount(amount: number): boolean
	return type(amount) == "number" and amount >= 1 and amount % 1 == 0 and amount <= 2 ^ 53
end

function Wallets.new(cfg: Config): Wallet
	local balances: { [any]: { [string]: number } } = {}
	local wallet = {} :: Wallet

	local function publish(player: any, currency: string, value: number)
		if cfg.publisher then
			cfg.publisher.Show(player, currency, value)
		end
	end

	function wallet.Attach(_self, player, data)
		for name, def in cfg.currencies do
			local v = data[name]
			if type(v) ~= "number" or v ~= v or v < 0 then
				v = 0 -- repair corrupt saves instead of trusting them
			end
			data[name] = math.min(math.floor(v), def.max)
			publish(player, name, data[name])
		end
		balances[player] = data
	end

	function wallet.Detach(_self, player)
		balances[player] = nil
		if cfg.publisher then
			cfg.publisher.Hide(player)
		end
	end

	function wallet.Get(_self, player, currency)
		local data = balances[player]
		return if data then data[currency] or 0 else 0
	end

	function wallet.Add(_self, player, currency, amount)
		local data, def = balances[player], cfg.currencies[currency]
		if data == nil or def == nil then
			return false, "unknown player or currency"
		end
		if not validAmount(amount) then
			return false, "bad amount"
		end
		local new = math.min(data[currency] + amount, def.max)
		data[currency] = new
		publish(player, currency, new)
		return true, if new == def.max then "capped" else nil
	end

	function wallet.Spend(_self, player, currency, amount)
		local data = balances[player]
		if data == nil or cfg.currencies[currency] == nil then
			return false, "unknown player or currency"
		end
		if not validAmount(amount) then
			return false, "bad amount"
		end
		if data[currency] < amount then
			return false, "insufficient funds"
		end
		data[currency] -= amount
		publish(player, currency, data[currency])
		return true, nil
	end

	return wallet
end

-- instanceNew is Instance.new. Creates player.leaderstats with one IntValue per currency.
function Wallets.leaderstats(instanceNew: (className: string) -> any): Publisher
	return {
		Show = function(player, currency, value)
			local folder = player:FindFirstChild("leaderstats")
			if folder == nil then
				folder = instanceNew("Folder")
				folder.Name = "leaderstats"
				folder.Parent = player
			end
			local stat = folder:FindFirstChild(currency)
			if stat == nil then
				stat = instanceNew("IntValue")
				stat.Name = currency
				stat.Parent = folder
			end
			stat.Value = value
		end,
		Hide = function(_player) end, -- the folder dies with the Player instance
	}
end

return Wallets
