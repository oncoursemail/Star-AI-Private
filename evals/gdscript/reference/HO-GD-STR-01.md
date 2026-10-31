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
        out += s[i] + str(j - i)
        i = j
    return out

func decode(s: String) -> String:
    var out := ""
    var i := 0
    while i < s.length():
        var ch := s[i]
        if not ((ch >= "a" and ch <= "z") or (ch >= "A" and ch <= "Z")):
            return ""
        i += 1
        var digits := ""
        while i < s.length() and s[i] >= "0" and s[i] <= "9":
            digits += s[i]
            i += 1
        if digits == "" or int(digits) < 1:
            return ""
        out += ch.repeat(int(digits))
    return out
```
