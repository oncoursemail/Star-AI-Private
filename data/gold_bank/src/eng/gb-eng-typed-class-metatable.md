---
id: gb-eng-typed-class-metatable
category: luau-typing
topics: luau types, metatable class, typeof setmetatable, strict mode, OOP
source: original
---
# Request
I write classes with `setmetatable` but under `--!strict` every method call on my objects is untyped, and `self` inside methods is `any`. How do I type a metatable class properly? My class is a simple `Wallet` with a balance, `Deposit` and `TrySpend`.

# Answer
Describe the instance fields in one type, build the class table, then derive the object type with `typeof(setmetatable(...))` so methods and fields both type-check. Annotate `self` in every method with that type.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Wallet
local Wallet = {}
Wallet.__index = Wallet

type WalletFields = {
	_balance: number,
	_owner: string,
}

export type Wallet = typeof(setmetatable({} :: WalletFields, Wallet))

function Wallet.new(owner: string, startingBalance: number?): Wallet
	local self = setmetatable({} :: WalletFields, Wallet)
	self._owner = owner
	self._balance = math.max(0, startingBalance or 0)
	return self
end

function Wallet.Deposit(self: Wallet, amount: number): ()
	assert(amount > 0 and amount == amount, "deposit must be a positive number")
	self._balance += amount
end

function Wallet.TrySpend(self: Wallet, amount: number): boolean
	if amount <= 0 or amount ~= amount or amount > self._balance then
		return false
	end
	self._balance -= amount
	return true
end

function Wallet.GetBalance(self: Wallet): number
	return self._balance
end

function Wallet.GetOwner(self: Wallet): string
	return self._owner
end

return Wallet
```

- `typeof(setmetatable({} :: WalletFields, Wallet))` gives a type that includes both the fields and every function on `Wallet`, so `wallet:TrySpend("10")` is a type error at edit time.
- Writing methods as `function Wallet.Deposit(self: Wallet, ...)` instead of `Wallet:Deposit(...)` is what lets you annotate `self`; callers still use `wallet:Deposit(5)`.
- Consumers import the type with `local Wallet = require(path)` and `local w: Wallet.Wallet`.
- `amount ~= amount` catches NaN, which would otherwise poison the balance forever.

# Test
```lua
local w = item.new("Ana", 50)
check("starting balance", w:GetBalance() == 50)
w:Deposit(25)
check("deposit adds", w:GetBalance() == 75)
check("spend within balance", w:TrySpend(70) and w:GetBalance() == 5)
check("overspend rejected", not w:TrySpend(6) and w:GetBalance() == 5)
check("NaN rejected", not w:TrySpend(0 / 0))
check("negative start clamps", item.new("Bo", -10):GetBalance() == 0)
check("bad deposit errors", not pcall(function() w:Deposit(-1) end))
check("owner kept", w:GetOwner() == "Ana")
```
