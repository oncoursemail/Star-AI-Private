Here is the script.

```gdscript
extends RefCounted

func pick_weighted(weights: Array, roll: float) -> int:
    var r := maxf(roll, 0.0)
    var acc := 0.0
    var last := -1
    for i in weights.size():
        var w := float(weights[i])
        if w <= 0.0:
            continue
        last = i
        acc += w
        if r < acc:
            return i
    return last
```
