"""Static authoring diagnostics do not certify rendered Roblox contrast."""
import math

import pytest

from star.roblox_ui_compiler import SpecError, compile_ui


PALETTE = {"black": "#000000", "white": "#FFFFFF", "boundary": "#00827F"}
CHILD = "$.root.children[0]"


def ui(*children):
    return {"palette": PALETTE, "root": {
        "type": "screen", "id": "screen", "children": list(children)}}


def control(**overrides):
    return {"type": "button", "id": "action", "text": "Continue",
            "background": "black", "textColor": "white", **overrides}


@pytest.mark.parametrize("kind", ["button", "toggle", "input"])
@pytest.mark.parametrize("state", ["hover", "pressed", "selected", "disabled"])
def test_each_authored_interaction_state_checks_its_effective_color_pair(kind, state):
    result = compile_ui(ui(control(type=kind, states={state: {"background": "white"}})))
    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert warning.path == f"{CHILD}.states.{state}.textColor"
    assert warning.severity == "warning"
    assert "below the 4.5:1 authoring target" in warning.message
    if state == "disabled":
        assert "inactive controls are exempt" in warning.message


def test_state_overrides_restart_from_base_instead_of_carrying_hover_colors():
    result = compile_ui(ui(control(states={
        "hover": {"background": "white", "textColor": "black"},
        "pressed": {"textColor": "black"},
        "selected": {"background": "white", "textColor": "black"},
    })))
    assert [w.path for w in result.warnings] == [f"{CHILD}.states.pressed.textColor"]
    assert "below" in result.warnings[0].message


def test_a_text_color_override_uses_the_base_background():
    result = compile_ui(ui(control(states={"hover": {"textColor": "black"}})))
    assert len(result.warnings) == 1
    assert result.warnings[0].path == f"{CHILD}.states.hover.textColor"


@pytest.mark.parametrize("kind", ["text", "button", "toggle", "input"])
def test_unset_native_background_is_not_mistaken_for_parent_color(kind):
    child = {"type": kind, "id": "label", "text": "Read me", "textColor": "white"}
    result = compile_ui(ui({"type": "frame", "id": "panel", "background": "black",
                            "children": [child]}))
    assert len(result.warnings) == 1
    assert "indeterminate" in result.warnings[0].message
    assert result.warnings[0].path == f"{CHILD}.children[0].textColor"


@pytest.mark.parametrize("kind", ["frame", "scroll", "grid"])
@pytest.mark.parametrize("transparency", [None, 0, 0.5, 1])
def test_emitter_forced_transparent_containers_preserve_a_known_backdrop(kind, transparency):
    container = {"type": kind, "id": "layout", "children": [
        {"type": "text", "id": "label", "textColor": "white", "transparency": 1}]}
    if transparency is not None:
        container["transparency"] = transparency
    result = compile_ui(ui({"type": "frame", "id": "panel", "background": "black",
                            "children": [container]}))
    assert result.warnings == ()


def test_translucent_ancestor_stays_unknown_until_an_opaque_backdrop_replaces_it():
    result = compile_ui(ui({"type": "frame", "id": "panel", "background": "black",
                            "transparency": 0.5, "children": [
        {"type": "frame", "id": "layout", "children": [
            {"type": "text", "id": "unresolved", "textColor": "white", "transparency": 1},
            {"type": "text", "id": "opaque", "textColor": "white", "background": "black"},
        ]}]}))
    assert len(result.warnings) == 1
    assert result.warnings[0].path == f"{CHILD}.children[0].children[0].textColor"
    assert "indeterminate" in result.warnings[0].message


def test_fully_transparent_text_background_uses_parent_instead_of_its_hidden_color():
    result = compile_ui(ui({"type": "frame", "id": "panel", "background": "white",
                            "children": [
        {"type": "text", "id": "label", "textColor": "white",
         "background": "black", "transparency": 1}]}))
    assert len(result.warnings) == 1
    assert "below" in result.warnings[0].message


def test_each_state_resolves_transparency_independently():
    child = control(background="white", textColor="black", transparency=0.5, states={
        "hover": {"transparency": 1},
        "pressed": {"transparency": 0.5},
        "selected": {"transparency": 0},
    })
    result = compile_ui(ui({"type": "frame", "id": "panel", "background": "black",
                            "children": [child]}))
    warnings = {w.path: w.message for w in result.warnings}
    prefix = f"{CHILD}.children[0]"
    assert len(warnings) == 3
    assert "indeterminate" in warnings[f"{prefix}.textColor"]
    assert "below" in warnings[f"{prefix}.states.hover.textColor"]
    assert "indeterminate" in warnings[f"{prefix}.states.pressed.textColor"]
    assert f"{prefix}.states.selected.textColor" not in warnings


def test_unset_native_foreground_is_indeterminate_even_with_an_explicit_background():
    result = compile_ui(ui({"type": "text", "id": "label", "background": "white"}))
    assert len(result.warnings) == 1
    assert "indeterminate" in result.warnings[0].message


def test_contrast_uses_full_precision_at_the_authoring_threshold():
    result = compile_ui(ui(control(textColor="boundary")))
    assert len(result.warnings) == 1  # 4.499513915165525:1 must not round up to a pass.
    assert "below" in result.warnings[0].message


def test_initially_inactive_control_diagnostic_is_an_authoring_target():
    result = compile_ui(ui(control(textColor="black", enabled=False)))
    assert len(result.warnings) == 1
    assert "authoring target" in result.warnings[0].message
    assert "inactive controls are exempt" in result.warnings[0].message


@pytest.mark.parametrize("field,bad", [
    ("background", ["black"]), ("textColor", {"name": "white"}),
    ("background", "missing"), ("transparency", math.nan),
    ("transparency", math.inf), ("transparency", {"value": 0}),
    ("transparency", True), ("transparency", 10 ** 400),
])
@pytest.mark.parametrize("state", [None, "hover"])
def test_malformed_contrast_inputs_produce_spec_errors_without_raw_exceptions(field, bad, state):
    child = control()
    if state is None:
        child[field] = bad
        expected_path = f"{CHILD}.{field}"
    else:
        child["states"] = {state: {field: bad}}
        expected_path = f"{CHILD}.states.{state}.{field}"
    with pytest.raises(SpecError) as error:
        compile_ui(ui(child))
    assert any(d.severity == "error" and d.path == expected_path for d in error.value.diagnostics)
