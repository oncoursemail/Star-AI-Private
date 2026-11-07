extends SceneTree
## GD-STR-01: Duration formatting with padding rules, title case and ellipsis truncation. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var u = S.new()
    H.check("seconds only", u.format_duration(0) == "0s" and u.format_duration(5) == "5s" and u.format_duration(59) == "59s")
    H.check("minutes", u.format_duration(60) == "1m 00s" and u.format_duration(187) == "3m 07s" and u.format_duration(3599) == "59m 59s")
    H.check("hours", u.format_duration(3600) == "1h 00m 00s" and u.format_duration(3725) == "1h 02m 05s" and u.format_duration(90061) == "25h 01m 01s")
    H.check("negative", u.format_duration(-4) == "0s")
    H.check("title_case", u.title_case("  hello   WORLD of gdscript ") == "Hello World Of Gdscript" and u.title_case("") == "")
    H.check("title_case single", u.title_case("gODOT") == "Godot")
    H.check("truncate fits", u.truncate("hello", 5) == "hello" and u.truncate("hi", 10) == "hi")
    H.check("truncate cuts", u.truncate("hello world", 5) == "hell\u2026" and u.truncate("abc", 1) == "\u2026")
    H.check("truncate nothing", u.truncate("abc", 0) == "" and u.truncate("abc", -3) == "")
    H.finish(self)
