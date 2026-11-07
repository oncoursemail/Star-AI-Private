Here is the script.

```gdscript
extends RefCounted

func format_duration(seconds: int) -> String:
    if seconds < 0:
        return "0s"
    var h := seconds / 3600
    var m := (seconds % 3600) / 60
    var s := seconds % 60
    if h > 0:
        return "%dh %02dm %02ds" % [h, m, s]
    if m > 0:
        return "%dm %02ds" % [m, s]
    return "%ds" % s

func title_case(s: String) -> String:
    var out: PackedStringArray = []
    for word in s.strip_edges().split(" ", false):
        out.append(word.substr(0, 1).to_upper() + word.substr(1).to_lower())
    return " ".join(out)

func truncate(s: String, max_len: int) -> String:
    if max_len < 1:
        return ""
    if s.length() <= max_len:
        return s
    return s.substr(0, max_len - 1) + "\u2026"
```
