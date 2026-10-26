Here is the script.

```gdscript
extends RefCounted

func step_toward(pos: Vector2, target: Vector2, speed: float, delta: float) -> Vector2:
    return pos + (target - pos).normalized() * speed * delta

func wrap_angle(a: float) -> float:
    return fmod(a + PI, TAU) - PI

func angle_between_deg(a: Vector2, b: Vector2) -> float:
    return rad_to_deg(a.angle_to(b))
```
