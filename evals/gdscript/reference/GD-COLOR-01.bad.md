Here is the script.

```gdscript
extends RefCounted

func hex_to_color(hex: String) -> Color:
    return Color(hex)

func lighten(c: Color, amount: float) -> Color:
    return c.lightened(amount)

func to_hex(c: Color) -> String:
    return "#" + c.to_html()
```
