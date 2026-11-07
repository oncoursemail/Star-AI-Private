Here is the script.

```gdscript
extends RefCounted

func compose(fns: Array) -> Callable:
    var chain := fns.duplicate()
    return func(x):
        var v = x
        for fn in chain:
            v = fn.call(v)
        return v

func partial(fn: Callable, first: Variant) -> Callable:
    return func(x): return fn.call(first, x)

func apply_n(fn: Callable, x: Variant, n: int) -> Variant:
    var v = x
    for i in n:
        v = fn.call(v)
    return v
```
