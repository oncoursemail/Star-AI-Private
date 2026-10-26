Here is the script.

```gdscript
extends RefCounted

func format_duration(seconds: int) -> String:
    var h := seconds / 3600
    var m := (seconds % 3600) / 60
    var s := seconds % 60
    if h > 0:
        return str(h) + "h " + str(m) + "m " + str(s) + "s"
    if m > 0:
        return str(m) + "m " + str(s) + "s"
    return str(s) + "s"

func title_case(s: String) -> String:
    return s.capitalize()

func truncate(s: String, max_len: int) -> String:
    if s.length() <= max_len:
        return s
    return s.substr(0, max_len) + "..."
```
