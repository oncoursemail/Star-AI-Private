Here is the script.

```gdscript
extends RefCounted

func build_menu(titles: Array) -> Control:
    var menu := VBoxContainer.new()
    menu.name = "Menu"
    menu.add_theme_constant_override("separation", 12)
    var title := Label.new()
    title.name = "Title"
    title.text = "Main Menu"
    menu.add_child(title)
    for t in titles:
        var button := Button.new()
        button.name = str(t).replace(" ", "")
        button.text = str(t)
        button.custom_minimum_size = Vector2(160, 40)
        menu.add_child(button)
    return menu
```
