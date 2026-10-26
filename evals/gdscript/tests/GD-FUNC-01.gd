extends SceneTree
## GD-FUNC-01: Callable composition, partial application and repeated application. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var f = S.new()
    var add1: Callable = func(x): return x + 1
    var dbl: Callable = func(x): return x * 2
    var c = f.compose([add1, dbl])
    H.check("left to right", c.call(3) == 8)
    H.check("order matters", f.compose([dbl, add1]).call(3) == 7)
    H.check("empty is the identity", f.compose([]).call("same") == "same")
    var sub: Callable = func(a, b): return a - b
    H.check("partial binds the first argument", f.partial(sub, 10).call(3) == 7)
    H.check("apply_n", f.apply_n(dbl, 1, 5) == 32)
    H.check("apply_n zero and negative", f.apply_n(dbl, 7, 0) == 7 and f.apply_n(dbl, 7, -2) == 7)
    H.check("compose returns a valid Callable", c is Callable and c.is_valid())
    H.finish(self)
