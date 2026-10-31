Here is the script.

```gdscript
extends RefCounted

var current: String = ""
var states := {}

func add_state(name: String, on_enter: Callable = Callable(), on_exit: Callable = Callable()) -> void:
    states[name] = [on_enter, on_exit]

func start(name: String) -> bool:
    current = name
    states[name][0].call(current)
    return true

func transition(to: String) -> bool:
    if not states.has(to):
        return false
    var previous := current
    current = to
    states[to][0].call(previous)
    states[previous][1].call()
    return true
```
