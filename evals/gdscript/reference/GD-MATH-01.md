Here is the script.

```gdscript
extends RefCounted

func step_toward(pos: Vector2, target: Vector2, speed: float, delta: float) -> Vector2:
    var to_target := target - pos
    var reach := speed * delta
    if to_target.length() <= reach:
        return target
    return pos + to_target.normalized() * reach

func wrap_angle(a: float) -> float:
    return wrapf(a, -PI, PI)

func angle_between_deg(a: Vector2, b: Vector2) -> float:
    if a.length() == 0.0 or b.length() == 0.0:
        return 0.0
    return rad_to_deg(absf(a.angle_to(b)))
```
