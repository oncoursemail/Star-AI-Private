extends SceneTree
## GD-CLASS-01: Inner class used by outer methods: reverse words and bracket matching. Harness-owned; the model's script is res://answer.gd (see harness.gd).
const H = preload("res://harness.gd")

func _initialize() -> void:
    var S = H.answer_script()
    if S == null:
        quit(2)
        return
    await process_frame  # the tree is running from here on: nodes added to root are inside the tree
    var u = S.new()
    H.check("reverse_words", u.reverse_words("a b  c") == "c b a" and u.reverse_words("  one ") == "one")
    H.check("reverse_words blank", u.reverse_words("") == "" and u.reverse_words("   ") == "")
    H.check("balanced yes", u.balanced("([]{})") and u.balanced("") and u.balanced("a(b)c[d]"))
    H.check("balanced no", not u.balanced("([)]") and not u.balanced("(") and not u.balanced(")") and not u.balanced("{[}"))
    var consts: Dictionary = S.get_script_constant_map()
    H.check("inner class Stack exists", consts.has("Stack"))
    var st = consts["Stack"].new() if consts.has("Stack") else null
    if st != null:
        st.push(1)
        st.push(2)
    H.check("stack behaves", st != null and st.peek() == 2 and st.size() == 2 and st.pop() == 2 and st.pop() == 1 and st.pop() == null and st.peek() == null and st.size() == 0)
    H.finish(self)
