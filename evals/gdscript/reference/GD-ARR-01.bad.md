Here is the script.

```gdscript
extends RefCounted

func top_n(values: Array, n: int) -> Array:
    values.sort()
    return values.slice(0, n)

func chunk(values: Array, size: int) -> Array:
    var out := []
    for i in range(0, values.size(), size):
        out.append(values.slice(i, i + size))
    return out

func unique_sorted(values: Array) -> Array:
    var out := []
    for v in values:
        if not out.has(v):
            out.append(v)
    return out
```
