Here is the script.

```gdscript
extends RefCounted

func classify(v: Variant) -> String:
    match typeof(v):
        TYPE_NIL:
            return "nil"
        TYPE_BOOL:
            return "bool"
        TYPE_INT:
            return "int"
        TYPE_FLOAT:
            return "float"
        TYPE_STRING:
            return "string"
        TYPE_VECTOR2:
            return "vector2"
        TYPE_ARRAY:
            return "array"
        TYPE_DICTIONARY:
            return "dictionary"
        TYPE_OBJECT:
            return "object"
    return "other"

func sum_numbers(values: Array) -> float:
    var total := 0.0
    for v in values:
        var t := typeof(v)
        if t == TYPE_INT or t == TYPE_FLOAT:
            total += float(v)
    return total
```
