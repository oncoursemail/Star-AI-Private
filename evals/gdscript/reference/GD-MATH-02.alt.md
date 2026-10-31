Here is the script.

```gdscript
extends RefCounted

func pick_weighted(weights: Array, roll: float) -> int:
    var total := 0.0
    var last := -1
    for i in weights.size():
        if weights[i] > 0:
            total += weights[i]
            last = i
    if last == -1:
        return -1
    if roll >= total:
        return last
    var r := maxf(roll, 0.0)
    var acc := 0.0
    for i in weights.size():
        if weights[i] <= 0:
            continue
        if r < acc + weights[i]:
            return i
        acc += weights[i]
    return last
```
