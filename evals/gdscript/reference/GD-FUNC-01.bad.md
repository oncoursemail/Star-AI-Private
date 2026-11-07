Here is the script.

```gdscript
extends RefCounted

func compose(fns: Array) -> Callable:
    return func(x):
        var v = x
        for i in range(fns.size() - 1, -1, -1):
            v = fns[i].call(v)
        return v

func partial(fn: Callable, first: Variant) -> Callable:
    return func(x): return fn.call(x, first)

func apply_n(fn: Callable, x: Variant, n: int) -> Variant:
    var v = x
    for i in n:
        v = fn.call(v)
    return v
```
