# Inventory

Server-owned. The client asks, the server decides.

## API
- `Inventories.new({ capacity, items = { [id] = { maxStack } }, onChanged? }, saved?) -> inv`.
- `inv:CanAdd(id, n)`, `inv:Add(id, n)`, `inv:Remove(id, n)`: all or nothing, return `ok, reason`.
- `inv:Count(id)`, `inv:Has(id, n)`, `inv:Serialize()` (copy for the profile; pass it back as `saved`).

## Wire it
Create one per player after the profile loads (`saved = profile.Data.Inventory`), write `inv:Serialize()` back before saving, and replicate in `onChanged` (RemoteEvent to the owner or attributes).

## Pitfalls
- `n` must be a positive integer: fractions, zero, NaN and negatives are refused.
- Loading drops unknown ids and clamps oversized stacks, so item removals do not corrupt old saves.
- Keep item definitions in one shared module so shop, loot and crafting agree on `maxStack`.
