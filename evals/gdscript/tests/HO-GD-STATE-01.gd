extends SceneTree
## HO-GD-STATE-01: State machine over Callables: enter/exit order, previous-state argument, refused transitions. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var sm = S.new()
    var log := []
    sm.add_state("idle", func(prev): log.append("enter idle from " + prev), func(): log.append("exit idle"))
    sm.add_state("run", func(prev): log.append("enter run from " + prev), func(): log.append("exit run"))
    sm.add_state("bare")
    H.check("unknown state refused", sm.transition("fly") == false and sm.current == "" and sm.start("fly") == false)
    H.check("start enters with an empty previous", sm.start("idle") == true and sm.current == "idle" and log == ["enter idle from "])
    H.check("same state refused", sm.transition("idle") == false and log.size() == 1)
    H.check("transition order", sm.transition("run") == true and sm.current == "run" and log == ["enter idle from ", "exit idle", "enter run from idle"])
    H.check("states without callables work", sm.transition("bare") == true and sm.current == "bare" and log[-1] == "exit run" and log.size() == 4)
    H.check("leaving a bare state", sm.transition("idle") == true and log[-1] == "enter idle from bare" and log.size() == 5)
    H.check("unknown after start", sm.transition("fly") == false and sm.current == "idle")
    H.finish(self)
