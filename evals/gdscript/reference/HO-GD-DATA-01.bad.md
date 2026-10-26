Here is the script.

```gdscript
extends RefCounted

func summarize_scores(json_text: String) -> Dictionary:
    var data = JSON.parse_string(json_text)
    var total := 0.0
    var names := []
    for item in data:
        total += item["score"]
        names.append(item["name"])
    return {"count": names.size(), "mean": total / names.size(), "best": names[0], "ranked": names}
```
