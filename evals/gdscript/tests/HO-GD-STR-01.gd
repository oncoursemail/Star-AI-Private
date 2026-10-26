extends SceneTree
## HO-GD-STR-01: Run-length encode and decode letters, with multi-digit counts and strict malformed-input handling. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var r = S.new()
    H.check("encode basics", r.encode("aaabcc") == "a3b1c2" and r.encode("") == "" and r.encode("x") == "x1")
    H.check("encode long run and case", r.encode("zzzzzzzzzzzz") == "z12" and r.encode("aA") == "a1A1" and r.encode("AAaa") == "A2a2")
    H.check("decode basics", r.decode("a3b1c2") == "aaabcc" and r.decode("x1") == "x" and r.decode("") == "")
    H.check("decode multi-digit", r.decode("z12") == "zzzzzzzzzzzz" and r.decode("q10p2") == "qqqqqqqqqqpp")
    H.check("round trip", r.decode(r.encode("wwwwxyyzzzzzzzzzzzzq")) == "wwwwxyyzzzzzzzzzzzzq")
    H.check("malformed: count first", r.decode("3a") == "")
    H.check("malformed: missing count", r.decode("a") == "" and r.decode("a3b") == "")
    H.check("malformed: zero count and junk", r.decode("a0") == "" and r.decode("a3-") == "" and r.decode("a 3") == "")
    H.finish(self)
