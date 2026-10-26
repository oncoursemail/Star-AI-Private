Here is the script.

```gdscript
extends RefCounted

func merge_deep(a: Dictionary, b: Dictionary) -> Dictionary:
    var out := a.duplicate()
    out.merge(b, true)
    return out
```
