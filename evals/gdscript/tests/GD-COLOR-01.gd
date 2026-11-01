extends SceneTree
## GD-COLOR-01: Hex colour parsing with a sentinel, lightening with clamped alpha-preserving mix. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var u = S.new()
    H.check("long form", u.hex_to_color("#ff8000").is_equal_approx(Color8(255, 128, 0)))
    H.check("no hash and upper case", u.hex_to_color("00FF7F").is_equal_approx(Color8(0, 255, 127)))
    H.check("short form", u.hex_to_color("#f80").is_equal_approx(Color8(255, 136, 0)) and u.hex_to_color("0af").is_equal_approx(Color8(0, 170, 255)))
    H.check("invalid gives magenta", u.hex_to_color("zzz") == Color.MAGENTA and u.hex_to_color("#12345") == Color.MAGENTA and u.hex_to_color("") == Color.MAGENTA and u.hex_to_color("#gg0000") == Color.MAGENTA)
    H.check("lighten halfway keeps alpha", u.lighten(Color(0, 0, 0, 0.5), 0.5).is_equal_approx(Color(0.5, 0.5, 0.5, 0.5)))
    H.check("lighten clamps", u.lighten(Color(0.2, 0.4, 0.6, 0.3), 2.0).is_equal_approx(Color(1, 1, 1, 0.3)) and u.lighten(Color(0.2, 0.4, 0.6), -1.0).is_equal_approx(Color(0.2, 0.4, 0.6)))
    H.check("to_hex", u.to_hex(Color8(255, 128, 0)) == "#ff8000" and u.to_hex(Color8(10, 11, 12, 99)) == "#0a0b0c")
    H.finish(self)
