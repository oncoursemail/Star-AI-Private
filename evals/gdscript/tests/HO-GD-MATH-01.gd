extends SceneTree
## HO-GD-MATH-01: Grid flood fill and breadth-first path length over ragged string rows. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var g = S.new()
    var grid: Array[String] = [
        "..#..",
        "..#..",
        "###..",
        "....#",
    ]
    H.check("left pocket", g.flood_fill_count(grid, Vector2i(0, 0)) == 4)
    H.check("right region reaches the bottom row", g.flood_fill_count(grid, Vector2i(3, 0)) == 10)
    H.check("wall and outside give 0", g.flood_fill_count(grid, Vector2i(2, 0)) == 0 and g.flood_fill_count(grid, Vector2i(9, 9)) == 0 and g.flood_fill_count(grid, Vector2i(-1, 0)) == 0)
    var ragged: Array[String] = ["..", "...", "."]
    H.check("ragged rows", g.flood_fill_count(ragged, Vector2i(0, 0)) == 6)
    H.check("path inside a pocket", g.shortest_path(grid, Vector2i(0, 0), Vector2i(1, 1)) == 2)
    H.check("no route between regions", g.shortest_path(grid, Vector2i(0, 0), Vector2i(3, 0)) == -1)
    H.check("same cell and wall target", g.shortest_path(grid, Vector2i(3, 0), Vector2i(3, 0)) == 0 and g.shortest_path(grid, Vector2i(3, 0), Vector2i(2, 0)) == -1)
    H.check("longer route", g.shortest_path(grid, Vector2i(3, 0), Vector2i(0, 3)) == 6)
    H.check("detour around a wall", g.shortest_path(["...", ".#.", "..."] as Array[String], Vector2i(0, 1), Vector2i(2, 1)) == 4)
    H.finish(self)
