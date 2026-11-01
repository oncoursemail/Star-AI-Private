Here is the script.

```gdscript
extends RefCounted

enum Direction { UP, RIGHT, DOWN, LEFT }

func turn_right(d: int) -> int:
    return (d + 1) % 4

func turn_left(d: int) -> int:
    return (d - 1) % 4

func opposite(d: int) -> int:
    return (d + 2) % 4

func to_vector(d: int) -> Vector2i:
    var table := [Vector2i(0, -1), Vector2i(1, 0), Vector2i(0, 1), Vector2i(-1, 0)]
    return table[d]

func name_of(d: int) -> String:
    return Direction.keys()[d]
```
