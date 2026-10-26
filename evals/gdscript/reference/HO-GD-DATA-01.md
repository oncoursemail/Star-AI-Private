Here is the script.

```gdscript
extends RefCounted

func summarize_scores(json_text: String) -> Dictionary:
    var data = JSON.parse_string(json_text)
    if not (data is Array):
        return {}
    var rows: Array = []
    for item in data:
        if item is Dictionary and item.get("name") is String and (item.get("score") is float or item.get("score") is int):
            rows.append({"name": item["name"], "score": float(item["score"])})
    if rows.is_empty():
        return {}
    rows.sort_custom(func(a, b):
        if a["score"] != b["score"]:
            return a["score"] > b["score"]
        return a["name"] < b["name"])
    var total := 0.0
    var names := []
    for row in rows:
        total += row["score"]
        names.append(row["name"])
    return {"count": rows.size(), "mean": total / rows.size(), "best": names[0], "ranked": names}
```
