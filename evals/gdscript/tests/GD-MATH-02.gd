extends SceneTree
## GD-MATH-02: Weighted pick by cumulative buckets with exact boundary handling. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var p = S.new()
    var w: Array[float] = [1.0, 1.0, 2.0]
    H.check("first bucket", p.pick_weighted(w, 0.0) == 0 and p.pick_weighted(w, 0.5) == 0 and p.pick_weighted(w, 0.999) == 0)
    H.check("boundaries belong to the next bucket", p.pick_weighted(w, 1.0) == 1 and p.pick_weighted(w, 2.0) == 2)
    H.check("inside buckets", p.pick_weighted(w, 1.99) == 1 and p.pick_weighted(w, 3.99) == 2)
    var z: Array[float] = [0.0, 3.0, 0.0, 1.0]
    H.check("zero weights are skipped", p.pick_weighted(z, 0.0) == 1 and p.pick_weighted(z, 2.99) == 1 and p.pick_weighted(z, 3.0) == 3)
    H.check("roll past the end", p.pick_weighted(z, 10.0) == 3 and p.pick_weighted([5.0, 0.0], 99.0) == 0)
    H.check("negative roll counts as zero", p.pick_weighted(w, -4.0) == 0)
    H.check("negative weights own nothing", p.pick_weighted([-2.0, 1.0], 0.5) == 1)
    H.check("nothing to pick", p.pick_weighted([0.0, 0.0], 0.5) == -1 and p.pick_weighted([], 0.0) == -1)
    H.check("ints work too", p.pick_weighted([2, 3], 2.5) == 1)
    H.finish(self)
