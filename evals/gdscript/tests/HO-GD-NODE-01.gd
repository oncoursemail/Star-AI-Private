extends SceneTree
## HO-GD-NODE-01: Build a menu Control tree in code with names, text, sizes and a theme override. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var u = S.new()
    var m = u.build_menu(["New Game", "Options", "Quit"])
    H.check("root is a VBoxContainer named Menu", m is VBoxContainer and str(m.name) == "Menu")
    H.check("title label first", m.get_child(0) is Label and str(m.get_child(0).name) == "Title" and m.get_child(0).text == "Main Menu")
    H.check("one button per title", m.get_child_count() == 4 and m.get_child(1) is Button and m.get_child(3) is Button)
    H.check("button text in order", m.get_child(1).text == "New Game" and m.get_child(2).text == "Options" and m.get_child(3).text == "Quit")
    H.check("button names have no spaces", str(m.get_child(1).name) == "NewGame" and str(m.get_child(3).name) == "Quit")
    H.check("minimum size", m.get_child(2).custom_minimum_size == Vector2(160, 40) and m.get_child(1).custom_minimum_size == Vector2(160, 40))
    H.check("separation override", m.get_theme_constant("separation") == 12)
    var e = u.build_menu([])
    H.check("empty list", e.get_child_count() == 1 and e.get_child(0) is Label)
    m.free()
    e.free()
    H.finish(self)
