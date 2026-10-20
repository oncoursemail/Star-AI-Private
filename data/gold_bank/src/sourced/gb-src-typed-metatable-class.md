---
id: gb-src-typed-metatable-class
category: luau-typing
topics: metatables, OOP, typeof setmetatable, self annotation, export type, strict mode
source: adapted
source_id: luau-site
source_path: src/content/docs/types/object-oriented-programs.md
source_commit: 41db794d9ee6e56a17b399f8a4520b92301fee59
---
# Request
I wrote a Wallet class with metatables in `--!strict`. `Wallet.new` works, but inside `function Wallet:spend(amount)` the type checker complains about `self.balance` and I get no autocomplete. How do I type a metatable class properly?

# Answer
Do not rely on Luau inferring one shared `self` type across `:` methods. Declare the data shape, build the class type with `typeof(setmetatable({} :: Data, Class))`, annotate the constructor's return, and write methods as `function Class.method(self: Class, ...)`. Callers still use `wallet:spend(5)`.

```lua
--!strict
local Wallet = {}
Wallet.__index = Wallet

type WalletData = {
	owner: string,
	balance: number,
	history: { number },
}

export type Wallet = typeof(setmetatable({} :: WalletData, Wallet))

function Wallet.new(owner: string, balance: number): Wallet
	assert(balance >= 0, "balance cannot be negative")
	local self: WalletData = { owner = owner, balance = balance, history = {} }
	return setmetatable(self, Wallet)
end

function Wallet.deposit(self: Wallet, amount: number)
	assert(amount > 0, "deposit must be positive")
	self.balance += amount
	table.insert(self.history, amount)
end

function Wallet.spend(self: Wallet, amount: number): boolean
	if not (amount > 0 and amount <= self.balance) then
		return false
	end
	self.balance -= amount
	table.insert(self.history, -amount)
	return true
end

return Wallet
```

- The return annotation on `new` makes the checker reject a constructor that forgets a field the methods rely on.
- Annotating `self: Wallet` makes the method types explicit; with `:` methods the type checker may infer a separate `self` per method and lose `self.balance`.
- `spend` is written as `not (amount > 0 and amount <= balance)` so NaN, which fails every comparison, is refused instead of turning the balance into NaN.
- Other modules use the exported type: `local w: Wallet.Wallet = Wallet.new("Hina", 500)`.

# Test
```lua
local w = item.new("Hina", 500)
w:deposit(20)
check("deposit adds", w.balance == 520)
check("spend within balance", w:spend(100) == true and w.balance == 420)
check("overspend refused", w:spend(1000) == false and w.balance == 420)
check("non-positive spend refused", w:spend(0) == false and w:spend(-5) == false)
check("NaN spend refused", w:spend(0 / 0) == false and w.balance == 420)
check("history recorded", #w.history == 2 and w.history[2] == -100)
check("negative opening balance rejected", pcall(item.new, "x", -1) == false)
```
