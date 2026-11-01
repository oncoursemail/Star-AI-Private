Here is the script.

```gdscript
extends RefCounted

func merge_deep(a: Dictionary, b: Dictionary) -> Dictionary:
    var out: Dictionary = a.duplicate(true)
    for key in b:
        if out.get(key) is Dictionary and b[key] is Dictionary:
            out[key] = merge_deep(out[key], b[key])
        else:
            var v = b[key]
            out[key] = v.duplicate(true) if (v is Dictionary or v is Array) else v
    return out
```
