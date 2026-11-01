extends SceneTree
## GD-SORT-01: Multi-key stable sort of dictionaries without mutating the input. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var u = S.new()
    var players: Array[Dictionary] = [
        {"name": "bo", "score": 5, "id": 0},
        {"name": "Al", "score": 9, "id": 1},
        {"name": "cy", "score": 5, "id": 2},
        {"name": "al", "score": 9, "id": 3},
        {"name": "bo", "score": 5, "id": 4},
    ]
    var sorted_players = u.sort_players(players)
    var ids := []
    for p in sorted_players:
        ids.append(p["id"])
    H.check("score desc, name asc, ties keep order", ids == [1, 3, 0, 4, 2])
    var original_ids := []
    for p in players:
        original_ids.append(p["id"])
    H.check("input order unchanged", original_ids == [0, 1, 2, 3, 4])
    H.check("same objects, not copies", sorted_players[0] == players[1] and is_same(sorted_players[0], players[1]))
    var many: Array[Dictionary] = []
    for i in 60:
        many.append({"name": "n%d" % (i % 3), "score": i % 2, "id": i})
    var res = u.sort_players(many)
    var stable := true
    for i in range(1, res.size()):
        var a: Dictionary = res[i - 1]
        var b: Dictionary = res[i]
        if a["score"] < b["score"] or (a["score"] == b["score"] and a["name"] > b["name"]):
            stable = false
        if a["score"] == b["score"] and a["name"] == b["name"] and a["id"] > b["id"]:
            stable = false
    H.check("sixty entries: ordered and ties stable", stable and res.size() == 60)
    H.check("empty input", u.sort_players([]).size() == 0)
    H.finish(self)
