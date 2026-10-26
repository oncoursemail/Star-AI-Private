Here is the script.

```gdscript
extends RefCounted

func _open(grid: Array, p: Vector2i) -> bool:
    if p.y < 0 or p.y >= grid.size():
        return false
    var row: String = grid[p.y]
    return p.x >= 0 and p.x < row.length() and row[p.x] == "."

func flood_fill_count(grid: Array, start: Vector2i) -> int:
    if not _open(grid, start):
        return 0
    var seen := {start: true}
    var queue: Array[Vector2i] = [start]
    while not queue.is_empty():
        var p: Vector2i = queue.pop_back()
        for d in [Vector2i.UP, Vector2i.DOWN, Vector2i.LEFT, Vector2i.RIGHT]:
            var q: Vector2i = p + d
            if not seen.has(q) and _open(grid, q):
                seen[q] = true
                queue.append(q)
    return seen.size()

func shortest_path(grid: Array, from: Vector2i, to: Vector2i) -> int:
    if not _open(grid, from) or not _open(grid, to):
        return -1
    var dist := {from: 0}
    var queue: Array[Vector2i] = [from]
    var head := 0
    while head < queue.size():
        var p: Vector2i = queue[head]
        head += 1
        if p == to:
            return dist[p]
        for d in [Vector2i.UP, Vector2i.DOWN, Vector2i.LEFT, Vector2i.RIGHT]:
            var q: Vector2i = p + d
            if not dist.has(q) and _open(grid, q):
                dist[q] = dist[p] + 1
                queue.append(q)
    return -1
```
