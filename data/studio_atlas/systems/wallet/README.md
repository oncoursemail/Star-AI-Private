# Wallet and leaderstats

## API
- `Wallets.new({ currencies = { Coins = { max = 1e9 } }, publisher? }) -> wallet`.
- `wallet:Attach(player, balances)` with `balances = profile.Data.Currency` (repairs corrupt values), `wallet:Detach(player)`.
- `wallet:Get(player, c)`, `wallet:Add(player, c, n)` (caps at `max`, returns `true, "capped"`), `wallet:Spend(player, c, n)` (`false, "insufficient funds"`).
- `Wallets.leaderstats(Instance.new)` is a publisher that makes `player.leaderstats` with one IntValue per currency.

## Wire it
After the profile loads: `wallet:Attach(player, profile.Data.Currency)`. On leave: `wallet:Detach(player)`.

## Pitfalls
- Clients can change leaderstats values locally but that never replicates back; the real balance is the table in the profile.
- Amounts are positive integers; never pass a client-sent amount without validation.
- IntValue holds integers up to 2^53 safely; keep `max` below that.
