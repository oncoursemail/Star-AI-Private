extends SceneTree
## HO-GD-DATA-01: Parse JSON text defensively and summarise valid rows with a deterministic ranking. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var s = S.new()
    var r = s.summarize_scores('[{"name":"ann","score":10},{"name":"bob","score":30.5},{"name":"cy","score":30.5},{"name":"dee","score":"x"},{"score":4},7,{"name":5,"score":1}]')
    H.check("count counts only valid rows", r.get("count") == 3 and typeof(r.get("count")) == TYPE_INT)
    H.check("mean", absf(float(r.get("mean", 0.0)) - (10.0 + 30.5 + 30.5) / 3.0) < 0.0001)
    H.check("best", r.get("best") == "bob")
    H.check("ranked", r.get("ranked") == ["bob", "cy", "ann"])
    H.check("invalid json", s.summarize_scores("[1,") == {})
    H.check("not an array", s.summarize_scores('{"name":"a","score":1}') == {})
    H.check("no valid rows", s.summarize_scores('[{"name":1}, "x"]') == {})
    H.check("empty array and empty text", s.summarize_scores("[]") == {} and s.summarize_scores("") == {})
    H.check("single row", s.summarize_scores('[{"name":"z","score":2}]') == {"count": 1, "mean": 2.0, "best": "z", "ranked": ["z"]})
    H.finish(self)
