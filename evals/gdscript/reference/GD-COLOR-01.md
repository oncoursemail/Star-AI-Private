Here is the script.

```gdscript
extends RefCounted

func hex_to_color(hex: String) -> Color:
    var h := hex.trim_prefix("#")
    if h.length() == 3:
        h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2]
    if h.length() != 6 or not h.is_valid_hex_number():
        return Color.MAGENTA
    return Color8(h.substr(0, 2).hex_to_int(), h.substr(2, 2).hex_to_int(), h.substr(4, 2).hex_to_int())

func lighten(c: Color, amount: float) -> Color:
    var t := clampf(amount, 0.0, 1.0)
    return Color(lerpf(c.r, 1.0, t), lerpf(c.g, 1.0, t), lerpf(c.b, 1.0, t), c.a)

func to_hex(c: Color) -> String:
    return "#" + c.to_html(false)
```
