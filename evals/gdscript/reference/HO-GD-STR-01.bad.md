Here is the script.

```gdscript
extends RefCounted

func encode(s: String) -> String:
    var out := ""
    var i := 0
    while i < s.length():
        var j := i
        while j < s.length() and s[j] == s[i]:
            j += 1
        out += s[i]
        if j - i > 1:
            out += str(j - i)
        i = j
    return out

func decode(s: String) -> String:
    var out := ""
    var i := 0
    while i < s.length():
        var ch := s[i]
        var n := 1
        if i + 1 < s.length() and s[i + 1].is_valid_int():
            n = int(s[i + 1])
            i += 1
        out += ch.repeat(n)
        i += 1
    return out
```
