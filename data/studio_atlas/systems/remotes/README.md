# Secure remote layer

The client is untrusted. Each remote has a schema, a rate limit and a handler that receives only cleaned values.

## API
- `Remotes.new({ now = os.clock, onReject = fn? }) -> layer`.
- `layer:Bind(name, remote, { kind = "event" | "function", args = {validators}, rate = { perSecond, burst }, handler })`. The handler gets `(player, ...cleanArgs)`.
- Validators in `Remotes.t`: `number(min, max, integer)`, `string(maxLength, pattern?)`, `boolean`, `oneOf(list)`, `optional(v)`, `shape({ field = validator })` (unknown keys rejected).
- `layer:Dispatch(name, player, ...) -> ok, result` (what `Bind` uses, handy for tests), `layer:Forget(player)` from `PlayerRemoving`.

## Wire it
Create remotes in ReplicatedStorage from a server Script, then `layer:Bind("Buy", remote, spec)`. The handler decides everything (price, ownership); it never takes a price, damage or path from the client.

## Pitfalls
- Extra arguments are rejected, and so are NaN and infinity.
- Pass ids, not Instances; if you must accept an Instance, re-derive it on the server and check it.
- Rejections are logged through `onReject`; count strikes there and kick repeat offenders.
- Rate limits apply per player per remote; pick burst from the real use (a button click, not a loop).
