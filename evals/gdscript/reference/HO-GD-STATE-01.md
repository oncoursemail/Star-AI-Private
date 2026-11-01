Here is the script.

```gdscript
extends RefCounted

var current: String = ""
var _states := {}

func add_state(name: String, on_enter: Callable = Callable(), on_exit: Callable = Callable()) -> void:
    _states[name] = {"enter": on_enter, "exit": on_exit}

func start(name: String) -> bool:
    if not _states.has(name):
        return false
    var previous := current
    current = name
    var enter: Callable = _states[name]["enter"]
    if enter.is_valid():
        enter.call(previous)
    return true

func transition(to: String) -> bool:
    if not _states.has(to) or to == current:
        return false
    var leave: Callable = _states[current]["exit"] if _states.has(current) else Callable()
    if leave.is_valid():
        leave.call()
    var previous := current
    current = to
    var enter: Callable = _states[to]["enter"]
    if enter.is_valid():
        enter.call(previous)
    return true
```
