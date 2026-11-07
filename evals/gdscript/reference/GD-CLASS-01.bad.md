Here is the script.

```gdscript
extends RefCounted

func reverse_words(s: String) -> String:
    var words := s.split(" ")
    words.reverse()
    return " ".join(words)

func balanced(s: String) -> bool:
    return s.count("(") == s.count(")") and s.count("[") == s.count("]") and s.count("{") == s.count("}")
```
