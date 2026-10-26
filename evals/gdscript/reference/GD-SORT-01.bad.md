Here is the script.

```gdscript
extends RefCounted

func sort_players(players: Array) -> Array:
    players.sort_custom(func(a, b): return a["score"] < b["score"])
    return players
```
