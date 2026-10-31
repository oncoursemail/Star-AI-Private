Here is the script.

```gdscript
extends Node

export(float, 0, 500, 5) var speed = 100.0
export(int, "Idle", "Walk", "Run") var mode = 0
export(int, FLAGS, "Fire", "Ice", "Wind") var resist = 0
export(String, MULTILINE) var notes = ""
export var label = "unit"
export var damage = 5

var _cache = {}
```
