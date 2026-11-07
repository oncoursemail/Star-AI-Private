Here is the script.

```gdscript
extends RefCounted

func build_menu(titles: Array) -> Control:
    var menu := VBoxContainer.new()
    menu.name = "Menu"
    var title := Label.new()
    title.text = "Main Menu"
    menu.add_child(title)
    for t in titles:
        var button := Button.new()
        button.text = t
        button.rect_min_size = Vector2(160, 40)
        menu.add_child(button)
    return menu
```
