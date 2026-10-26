Here is the script.

```gdscript
extends Node

@export_range(0, 500, 5) var speed: float = 100.0
@export_enum("Idle", "Walk", "Run") var mode: int = 0
@export_flags("Fire", "Ice", "Wind") var resist: int = 0
@export_multiline var notes: String = ""
@export var label: String = "unit"

@export_group("Combat")
@export var damage: int = 5

var _cache := {}
```
