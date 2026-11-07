extends RefCounted
## Shared helpers of the GDScript breadth suite. Every test (tests/<id>.gd) extends SceneTree and prints through this
## file; the grader (star/breadth_evals.py) reads the "@@" lines. The model's script is saved as res://answer.gd.

const WATCHDOG_SECONDS := 10.0


static func answer_script() -> GDScript:
    # A test that hits a script error stops where it is and would idle until the wall-clock limit; this ends it early.
    var tree := Engine.get_main_loop() as SceneTree
    tree.create_timer(WATCHDOG_SECONDS).timeout.connect(func() -> void:
        print("@@WATCHDOG\tthe test did not finish")
        tree.quit(3))
    var script = load("res://answer.gd")
    if script == null or not (script is GDScript) or not script.can_instantiate():
        print("@@LOADERR\tanswer.gd does not parse or cannot be instantiated")
        return null
    return script


static func check(name: String, ok: bool) -> void:
    print("@@T\t%s\t%s" % ["pass" if ok else "fail", name])


static func finish(tree: SceneTree) -> void:
    print("@@DONE")
    tree.quit(0)
