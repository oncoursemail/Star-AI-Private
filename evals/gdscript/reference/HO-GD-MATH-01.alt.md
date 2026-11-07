Here is the script.

```gdscript
extends RefCounted

func _is_open(grid: Array, x: int, y: int) -> bool:
    return y >= 0 and y < grid.size() and x >= 0 and x < grid[y].length() and grid[y][x] == "."

func _reach(grid: Array, start: Vector2i) -> Dictionary:
    var dist := {}
    if not _is_open(grid, start.x, start.y):
        return dist
    dist[start] = 0
    var frontier: Array = [start]
    while frontier.size() > 0:
        var next: Array = []
        for cell in frontier:
            for step in [Vector2i(1, 0), Vector2i(-1, 0), Vector2i(0, 1), Vector2i(0, -1)]:
                var n: Vector2i = cell + step
                if _is_open(grid, n.x, n.y) and not dist.has(n):
                    dist[n] = dist[cell] + 1
                    next.append(n)
        frontier = next
    return dist

func flood_fill_count(grid: Array, start: Vector2i) -> int:
    return _reach(grid, start).size()

func shortest_path(grid: Array, from: Vector2i, to: Vector2i) -> int:
    if not _is_open(grid, to.x, to.y):
        return -1
    return _reach(grid, from).get(to, -1)
```
