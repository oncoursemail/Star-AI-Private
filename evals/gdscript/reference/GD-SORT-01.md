Here is the script.

```gdscript
extends RefCounted

func sort_players(players: Array) -> Array:
    var indexed := []
    for i in players.size():
        indexed.append([i, players[i]])
    indexed.sort_custom(func(a, b):
        var pa: Dictionary = a[1]
        var pb: Dictionary = b[1]
        if pa["score"] != pb["score"]:
            return pa["score"] > pb["score"]
        if pa["name"] != pb["name"]:
            return pa["name"] < pb["name"]
        return a[0] < b[0])
    var out := []
    for pair in indexed:
        out.append(pair[1])
    return out
```
