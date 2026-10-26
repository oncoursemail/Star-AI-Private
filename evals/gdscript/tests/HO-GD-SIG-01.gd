extends SceneTree
## HO-GD-SIG-01: Signal with old and new value that fires only on real changes, with a cap and a floor. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var c = S.new()
    var log := []
    c.changed.connect(func(o, n): log.append([o, n]))
    c.increment()
    c.increment(4)
    c.increment(0)
    H.check("emits old and new, skips no-ops", log == [[0, 1], [1, 5]] and c.value == 5)
    c.reset()
    c.reset()
    H.check("reset emits once", log.size() == 3 and log[2] == [5, 0] and c.value == 0)
    c.set_max(3)
    H.check("set_max alone changes nothing", log.size() == 3 and c.value == 0)
    c.increment(10)
    H.check("clamped to the cap", c.value == 3 and log[3] == [0, 3])
    c.increment(1)
    H.check("no emit at the cap", log.size() == 4)
    c.increment(-5)
    H.check("negative goes down but not below zero", c.value == 0 and log[4] == [3, 0])
    c.increment(-1)
    H.check("no emit at the floor", log.size() == 5 and c.value == 0)
    H.finish(self)
