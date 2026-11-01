"""Her mood as weather, for the owner's desktop widget: sunny, cloudy, stormy or starry, with a one-line why.

`weather_from(state, history, hour)` is a pure mapping from what star.emotion reports (`emotion.current()` and its recent
events) to one of four weathers. The why-line comes from a fixed table keyed by the KIND of the latest event, never from the
event's free-text detail, so nothing private about a friend or a chat can leave her PC through it. The widget does not read
her PC: `payload()` is what the status API (api.py) serves, and the widget only calls that API.

    stormy   anger, frustration, hurt, fear, jealousy or embarrassment stands out        (she is upset and says so honestly)
    cloudy   sadness, loneliness, boredom, disappointment, guilt or nervousness stands out
    sunny    joy, pride, excitement, amusement or contentment stands out
    starry   quiet and warm: nostalgia, hope, love, gratitude or surprise leads, or it is night and nothing is wrong
With the emotion setting off there is no mood to show: the weather is "off" and the widget says so.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass

from ..emotion_model import BASELINE

STORM = ("anger", "frustration", "hurt", "fear", "jealousy", "embarrassment")
CLOUD = ("sadness", "loneliness", "boredom", "disappointment", "guilt", "nervousness")
SUN = ("joy", "pride", "excitement", "amusement", "contentment")
STAR = ("nostalgia", "hope", "love", "gratitude", "surprise", "relief")
SALIENT = 0.15
NIGHT_START, NIGHT_END = 21, 6
RECENT_H = 12

ICONS = {"sunny": "☀", "cloudy": "☁", "stormy": "⛈", "starry": "✨", "off": "·"}
WHY = {
    "task_success": "something she was working on worked", "task_failure": "something she tried did not work",
    "bug_fixed": "she fixed something that fought back", "creative_done": "she finished something she made",
    "promotion": "she got better at something", "learned_something": "she learned something new",
    "owner_praise": "you said something nice about her work", "owner_comfort": "you cheered her up",
    "owner_thanks": "you thanked her", "owner_criticism": "your feedback stung a little",
    "owner_message": "you talked to her", "voice_turn": "she talked with you",
    "friend_ignored": "a friend did not answer", "insulted": "someone was unkind to her",
    "game_lost": "she lost a game", "game_won": "she won a game", "friend_left": "a friend said goodbye",
    "sweet_message": "someone said something sweet", "left_out": "she was left out of something",
    "memory_triggered": "an old memory came back", "harmed_someone": "she is sorry about something she did",
    "help_received": "someone helped her", "exciting_news": "something exciting is coming", "funny": "something made her laugh",
    "embarrassed": "she is a little embarrassed", "threatened": "something worried her", "worry_over": "a worry turned out fine",
    "hope_dashed": "something she hoped for did not happen", "hope_raised": "she has something to look forward to",
    "shared_joy": "she shared a happy moment", "shared_sadness": "she felt for someone", "reunion": "someone came back",
    "apology_received": "someone said sorry", "amends_made": "she made things right", "talked_to_friend": "she talked to a friend",
    "took_a_break": "she took a break", "played_something_comforting": "she played something comforting",
}
FALLBACK = {"sunny": "a good stretch", "cloudy": "a slow, quiet stretch", "stormy": "a rough stretch",
            "starry": "a calm, quiet stretch", "off": "mood tracking is switched off"}


@dataclass(frozen=True)
class Weather:
    kind: str                # sunny | cloudy | stormy | starry | off
    label: str
    why: str
    icon: str
    dominant: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _dev(state: dict) -> dict[str, float]:
    emotions = state.get("emotions") or {}
    return {n: float(emotions.get(n, BASELINE[n])) - BASELINE[n] for n in BASELINE}


def _lead(dev: dict, names: tuple) -> tuple[float, str]:
    top = max(names, key=lambda n: dev[n])
    return dev[top], top


def kind_of(state: dict, hour: int) -> tuple[str, str]:
    """(weather kind, the feeling behind it)."""
    dev = _dev(state)
    storm, cloud, sun, star = (_lead(dev, g) for g in (STORM, CLOUD, SUN, STAR))
    if storm[0] >= SALIENT and storm[0] >= cloud[0]:
        return "stormy", storm[1]
    if cloud[0] >= SALIENT:
        return "cloudy", cloud[1]
    night = hour >= NIGHT_START or hour < NIGHT_END
    if star[0] >= SALIENT and star[0] >= sun[0] - 0.05:
        return "starry", star[1]
    if sun[0] >= SALIENT:
        return ("starry", sun[1]) if night and float(state.get("arousal", 0.4)) < 0.3 else ("sunny", sun[1])
    return ("starry", "") if night else ("sunny", "")


def why_line(kind: str, history: list[dict], now: float) -> str:
    """The reason in a few words: the newest recent event with a known kind, else a generic phrase for the weather."""
    for event in sorted(history, key=lambda e: -float(e.get("at", 0))):
        if now - float(event.get("at", 0)) > RECENT_H * 3600:
            break
        phrase = WHY.get(str(event.get("kind")))
        if phrase:
            return phrase
    return FALLBACK[kind]


def weather_from(state: dict | None, history: list[dict] | None = None, *, hour: int | None = None,
                 now: float | None = None) -> Weather:
    now = time.time() if now is None else now
    if not state:
        return Weather("off", "off", FALLBACK["off"], ICONS["off"])
    hour = time.localtime(now).tm_hour if hour is None else hour
    kind, feeling = kind_of(state, hour)
    return Weather(kind, kind, why_line(kind, history or [], now), ICONS[kind], feeling)


def payload(home=None, *, now: float | None = None, emotion=None) -> dict:
    """What the status API serves at /life/mood: the weather and nothing else about her."""
    now = time.time() if now is None else now
    try:
        if emotion is None:
            from .. import emotion as emotion_module
            emotion = emotion_module
        state = emotion.current(home) if emotion.enabled(home) else None
        history = emotion.default_engine(home).history(20) if state else []
    except Exception:
        state, history = None, []
    return {**weather_from(state, history, now=now).as_dict(), "at": int(now)}
