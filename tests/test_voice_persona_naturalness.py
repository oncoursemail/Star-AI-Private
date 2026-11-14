"""Natural voice-persona contract for live, multi-person streaming."""
from star.voice.persona import STYLE_PROMPTS, system_message


def test_every_voice_style_uses_the_same_streaming_floor_rules():
    for style in STYLE_PROMPTS:
        content = system_message(style=style)["content"]
        assert "The host decides when you have the floor" in content
        assert "Do not use repeated greetings" in content
        assert "transparent that you are an AI character" in content


def test_voice_personas_do_not_require_a_stock_opening():
    for prompt in STYLE_PROMPTS.values():
        assert "Do not force a stock reaction" not in prompt or "Do not force an excited opener" in prompt
        assert "Vary sentence length and openings" in prompt or "natural variation" in prompt


def test_per_call_context_is_appended_after_the_stable_persona_prefix():
    base = system_message(style="warm-caring")["content"]
    contextual = system_message("Current game: a cooperative obby.", style="warm-caring")["content"]
    assert contextual.startswith(base)
    assert contextual.endswith("Current game: a cooperative obby.")
