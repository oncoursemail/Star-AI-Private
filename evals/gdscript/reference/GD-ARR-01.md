Here is the script.

```gdscript
extends RefCounted

func top_n(values: Array, n: int) -> Array:
    if n <= 0:
        return []
    var copy := values.duplicate()
    copy.sort()
    copy.reverse()
    return copy.slice(0, mini(n, copy.size()))

func chunk(values: Array, size: int) -> Array:
    var out := []
    if size < 1:
        return out
    var i := 0
    while i < values.size():
        out.append(values.slice(i, i + size))
        i += size
    return out

func unique_sorted(values: Array) -> Array:
    var out := []
    for v in values:
        if not out.has(v):
            out.append(v)
    out.sort()
    return out
```
