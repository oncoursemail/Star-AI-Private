Here is the script.

```gdscript
extends RefCounted

func flood_fill_count(grid: Array, start: Vector2i) -> int:
    var count := 0
    for row in grid:
        count += row.count(".")
    return count

func shortest_path(grid: Array, from: Vector2i, to: Vector2i) -> int:
    return absi(from.x - to.x) + absi(from.y - to.y)
```
