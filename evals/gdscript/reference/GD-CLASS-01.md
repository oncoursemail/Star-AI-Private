Here is the script.

```gdscript
extends RefCounted

class Stack:
    var _items: Array = []

    func push(v) -> void:
        _items.append(v)

    func pop():
        if _items.is_empty():
            return null
        return _items.pop_back()

    func peek():
        if _items.is_empty():
            return null
        return _items[-1]

    func size() -> int:
        return _items.size()

func reverse_words(s: String) -> String:
    var stack := Stack.new()
    for word in s.replace("\t", " ").replace("\n", " ").split(" ", false):
        stack.push(word)
    var out: PackedStringArray = []
    while stack.size() > 0:
        out.append(stack.pop())
    return " ".join(out)

func balanced(s: String) -> bool:
    var pairs := {")": "(", "]": "[", "}": "{"}
    var stack := Stack.new()
    for ch in s:
        if ch in "([{":
            stack.push(ch)
        elif pairs.has(ch):
            if stack.pop() != pairs[ch]:
                return false
    return stack.size() == 0
```
