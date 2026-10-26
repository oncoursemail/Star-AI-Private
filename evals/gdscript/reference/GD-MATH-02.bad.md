Here is the script.

```gdscript
extends RefCounted

func pick_weighted(weights: Array, roll: float) -> int:
    var acc := 0.0
    for i in weights.size():
        acc += weights[i]
        if roll <= acc:
            return i
    return weights.size() - 1
```
