Here is the script.

```gdscript
extends RefCounted

enum Direction { UP, RIGHT, DOWN, LEFT }

func turn_right(d: int) -> int:
    return posmod(d + 1, 4)

func turn_left(d: int) -> int:
    return posmod(d - 1, 4)

func opposite(d: int) -> int:
    return posmod(d + 2, 4)

func to_vector(d: int) -> Vector2i:
    match d:
        Direction.UP:
            return Vector2i(0, -1)
        Direction.RIGHT:
            return Vector2i(1, 0)
        Direction.DOWN:
            return Vector2i(0, 1)
        Direction.LEFT:
            return Vector2i(-1, 0)
    return Vector2i.ZERO

func name_of(d: int) -> String:
    if d < 0 or d > 3:
        return "UNKNOWN"
    return Direction.keys()[d]
```
