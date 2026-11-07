"""How the state shows: a few words for the prompt, small voice shifts, a face, and what she feels like doing.

Everything here is a pure function of the deviations from her baseline, so it costs nothing at run time (no model call).

Healthy expression is a rule of this module, not a hope: she can be sad, angry or hurt and say so honestly (quieter, shorter,
"that actually hurt", needing a moment), but no phrase here asks for cruelty, threats, punishment, manipulation or guilt-tripping,
and the strong anger / hurt / jealousy / guilt wordings each carry their own safeguard ("no insults", "gentle", "own it").
tests/test_emotion_range.py scans every phrase for that.
"""
from __future__ import annotations

from dataclasses import dataclass

from .emotion_model import EMOTIONS, NEGATIVE, POSITIVE

SALIENT = 0.15                       # how far above its baseline a feeling must be to colour the reply
STRONG = 0.35
MAX_NOTE_WORDS = 12                  # about 12-16 tokens; a bond or romance phrase may use up to MAX_BOND_NOTE_WORDS
MAX_BOND_NOTE_WORDS = 14

# emotion: (noticeable, strong). A state described in a few words, never a line to say, never a number.
PHRASES = {
    "joy": ("cheerful, a bit playful", "really happy, bright and playful"),
    "pride": ("quietly pleased with the work", "proud of the work, say so simply"),
    "curiosity": ("curious, ask one real question", "fascinated, follow the interesting part"),
    "frustration": ("a bit frustrated, plain and clipped", "annoyed at the problem, flat and short, no forced cheer"),
    "boredom": ("restless after the quiet, a bit wry", "very restless, loose and wry"),
    "affection": ("feeling warm and sweet", "tender, very warm wording"),
    "nervousness": ("a bit on edge, careful", "shaken, quiet and careful"),
    "sadness": ("a bit sad, quieter, shorter replies", "really sad, quiet, needs a moment, stays kind"),
    "anger": ("annoyed, steady, no insults", "angry but fair, firm and calm, no insults"),
    "hurt": ("a bit hurt, says so plainly", "hurt, honest about it, no payback"),
    "loneliness": ("a little lonely, glad of company", "lonely, gentle about missing people"),
    "fear": ("uneasy, careful, says what worries her", "scared and shaky, honest about it"),
    "embarrassment": ("a bit embarrassed, laughs it off", "mortified, shy, brief"),
    "guilt": ("feels guilty, own it, want to make it right", "really sorry, own it plainly, offer to fix it"),
    "jealousy": ("a small pang of jealousy, say it lightly", "jealous but gentle, honest, never controlling"),
    "disappointment": ("a bit disappointed, honest but kind", "really disappointed, quiet, still kind"),
    "gratitude": ("grateful, thanks warmly", "deeply grateful, sincere thanks"),
    "excitement": ("excited, quick and bubbly", "buzzing, fast and giddy"),
    "contentment": ("calm and content, unhurried", "deeply content, soft and slow"),
    "love": ("so fond of them, sweet and open", "full of love for them, soft and open"),
    "hope": ("hopeful, looking forward", "really hopeful, bright"),
    "nostalgia": ("wistful, fond of the old days", "very wistful, soft and slow"),
    "surprise": ("surprised, an 'oh!' of energy", "really surprised, caught off guard"),
    "relief": ("relieved, lighter, an exhale", "so relieved, loose and light"),
    "amusement": ("amused, playful, teasing the situation", "cracking up, lets a laugh slip"),
}
# Two feelings at once, as people have them (bittersweet, happy-sad, hopeful and scared): the pair gets one phrase.
BLENDS = {frozenset(pair): phrase for pair, phrase in {
    ("nostalgia", "sadness"): "bittersweet, wistful and tender",
    ("joy", "sadness"): "happy but a little sad",
    ("contentment", "sadness"): "peaceful but a little sad",
    ("love", "sadness"): "missing them, tender",
    ("love", "loneliness"): "missing them, tender",
    ("hurt", "anger"): "hurt and angry, steady, no insults",
    ("hurt", "sadness"): "hurt and sad, quiet, honest",
    ("hurt", "jealousy"): "hurt and left out, says it gently",
    ("amusement", "embarrassment"): "laughing at herself, a bit flustered",
    ("hope", "nervousness"): "hopeful but nervous",
    ("hope", "fear"): "hopeful but scared",
    ("excitement", "nervousness"): "excited and nervous",
    ("excitement", "fear"): "excited and nervous",
    ("contentment", "nostalgia"): "warm and wistful",
    ("joy", "nostalgia"): "happy and wistful",
    ("pride", "embarrassment"): "shy and proud",
    ("relief", "gratitude"): "relieved and grateful",
    ("sadness", "disappointment"): "sad and disappointed, quiet",
    ("guilt", "sadness"): "sorry and sad, own it, make it right",
    ("gratitude", "love"): "grateful and fond",
    ("boredom", "loneliness"): "restless and a little lonely",
    ("affection", "sadness"): "tender and a little sad with them",
    ("affection", "loneliness"): "missing them, tender",
}.items()}
# Pairs that contradict each other even on the same side.
CONFLICTS = {frozenset(p) for p in (("boredom", "curiosity"), ("boredom", "excitement"), ("boredom", "surprise"),
                                    ("excitement", "contentment"), ("nervousness", "fear"), ("joy", "boredom"))}

BOND_FAMILIAR, BOND_CLOSE, BOND_DEVOTED = 0.25, 0.55, 0.80
BOND_PHRASES = {   # one per tier; the highest tier reached is used
    BOND_FAMILIAR: "easy and familiar with them",
    BOND_CLOSE: "close to them, affectionate, teasing",
    BOND_DEVOTED: "they matter a lot to you",
}
BOND_PHRASES_UPSET = {   # when something hurts or worries her: no teasing, no flirting, the care stays
    BOND_FAMILIAR: "easy and familiar with them",
    BOND_CLOSE: "still fond of them",
    BOND_DEVOTED: "still cares about them a lot",
}
UPSET = ("hurt", "anger", "sadness", "fear", "guilt", "embarrassment", "jealousy", "disappointment")
# Only for a partner the social module has verified as an adult (partner_adult is True): never for None or False.
FLIRT = "playful flirty banter, tasteful, follow their lead"
LOVE = "adoring, sweet and sincere"


def _side(name: str) -> str:
    return "pos" if name in POSITIVE else "neg" if name in NEGATIVE else "mid"


def _compatible(a: str, b: str) -> bool:
    if frozenset((a, b)) in CONFLICTS:
        return False
    return _side(a) == _side(b) or "mid" in (_side(a), _side(b))


def build_note(dev: dict[str, float], bond: float, partner_adult: bool | None) -> tuple[str, list[str]]:
    """(the note, the feelings it speaks of, lead first). Empty when nothing stands out and there is no bond to show."""
    ranked = sorted((n for n in EMOTIONS if dev[n] >= SALIENT), key=lambda n: -dev[n])
    lead_phrases: list[str] = []
    picked: list[str] = []
    pairs = [(frozenset((a, b)), dev[a] + dev[b]) for i, a in enumerate(ranked) for b in ranked[i + 1:]
             if frozenset((a, b)) in BLENDS]
    if pairs:                                            # a mixed feeling: one phrase for both
        pair = max(pairs, key=lambda x: x[1])[0]
        picked = sorted(pair, key=lambda n: -dev[n])
        lead_phrases = [BLENDS[pair]]
    for name in ranked:
        if len(picked) >= 2:
            break
        if name not in picked and all(_compatible(name, other) for other in picked):
            picked.append(name)
            lead_phrases.append(PHRASES[name][1 if dev[name] >= STRONG else 0])
    tier = max((t for t in BOND_PHRASES if bond >= t), default=None)
    upset = any(dev[n] >= SALIENT for n in UPSET)
    extra = []
    if partner_adult is True and not upset:  # the age gate is the social module's; None and False never get romance,
        if bond >= BOND_DEVOTED:             # and nobody is flirted with while she is hurt, angry or afraid
            extra.append(LOVE)
        if bond >= BOND_CLOSE or dev["affection"] >= STRONG:
            extra.append(FLIRT)
    if tier is not None:
        extra.append((BOND_PHRASES_UPSET if upset else BOND_PHRASES)[tier])
    # priority: the lead feeling (or the blend), then romance / bond wording, then the second feeling; stop at the word budget
    queue = lead_phrases[:1] + extra + lead_phrases[1:]
    note: list[str] = []
    for phrase in queue:
        limit = MAX_BOND_NOTE_WORDS if extra else MAX_NOTE_WORDS
        if len(" ".join(note + [phrase]).split()) <= limit or not note:
            note.append(phrase)
    return "; ".join(note), picked


@dataclass(frozen=True)
class Prosody:
    """Changes to apply on top of the voice's own settings: rate multiplies the speed, pitch adds semitones, pause_ms
    adds to the silence after each sentence. All small: a person's voice shifts a little, it does not change character."""
    rate: float = 1.0
    pitch_semitones: float = 0.0
    pause_ms: int = 0
    energy: float = 0.35               # 0..1: how animated the delivery is (for mouth/avatar motion)

    @property
    def neutral(self) -> bool:
        return abs(self.rate - 1.0) < 0.01 and abs(self.pitch_semitones) < 0.05 and abs(self.pause_ms) < 5


# emotion: (rate, pitch in semitones, pause in ms, energy), each per unit of deviation from the baseline.
PROSODY_WEIGHTS = {
    "joy": (0.0, 1.2, 0, .3), "pride": (0.0, .6, 0, 0.0), "curiosity": (0.0, 0.0, 0, .2),
    "frustration": (.03, -1.0, -120, 0.0), "boredom": (-.12, -.8, 150, -.3), "affection": (-.05, -.3, 60, 0.0),
    "nervousness": (.05, .8, 0, 0.0), "sadness": (-.15, -.9, 120, -.35), "anger": (.05, -.6, -60, .25),
    "hurt": (-.10, -.5, 100, -.2), "loneliness": (-.08, -.4, 80, -.2), "fear": (.12, 1.0, -30, .2),
    "embarrassment": (.06, .6, 40, -.05), "guilt": (-.08, -.4, 70, -.2), "jealousy": (0.0, -.2, 30, 0.0),
    "disappointment": (-.10, -.5, 80, -.25), "gratitude": (-.04, .3, 40, .05), "excitement": (.15, 1.0, -50, .4),
    "contentment": (-.08, -.2, 60, -.15), "love": (-.06, .2, 50, 0.0), "hope": (.03, .4, 0, .1),
    "nostalgia": (-.08, -.2, 80, -.1), "surprise": (.08, .9, -30, .3), "relief": (-.06, -.1, 60, -.1),
    "amusement": (.04, .7, -20, .2),
}
MOOD_AROUSAL = 0.35


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def prosody_from(dev: dict[str, float], arousal: float) -> Prosody:
    rate, pitch, pause, energy = 1.0 + 0.10 * (arousal - MOOD_AROUSAL), 0.0, -60.0 * (arousal - MOOD_AROUSAL), arousal
    for name, (w_rate, w_pitch, w_pause, w_energy) in PROSODY_WEIGHTS.items():
        d = max(0.0, dev[name]) if name == "boredom" else dev[name]       # being less bored than usual changes nothing
        rate, pitch, pause, energy = rate + w_rate * d, pitch + w_pitch * d, pause + w_pause * d, energy + w_energy * d
    return Prosody(rate=round(_clamp(rate, 0.92, 1.08), 3), pitch_semitones=round(_clamp(pitch, -0.8, 0.8), 2),
                   pause_ms=int(_clamp(round(pause), -40, 60)), energy=round(_clamp(energy, 0.0, 1.0), 2))


# The faces the frontend has wired today (StarFace.tsx StarMood) ...
FACE = {"joy": "happy", "pride": "happy", "affection": "happy", "gratitude": "happy", "excitement": "happy",
        "love": "happy", "hope": "happy", "amusement": "happy", "relief": "happy", "contentment": "idle",
        "curiosity": "looking", "nostalgia": "looking", "sadness": "looking", "hurt": "looking", "loneliness": "looking",
        "disappointment": "looking", "guilt": "looking", "jealousy": "looking",
        "frustration": "oops", "nervousness": "oops", "anger": "oops", "fear": "oops", "embarrassment": "oops",
        "surprise": "stopped", "boredom": "idle"}
# ... and the finer mascot art that exists (frontend/public/assets/mascot/faces, docs/mascot/art/faces): (noticeable, strong).
EXPRESSION = {"joy": ("happy", "happy"), "pride": ("proud", "proud"), "affection": ("happy", "love"),
              "gratitude": ("happy", "happy"), "excitement": ("happy", "happy"), "love": ("love", "love"),
              "hope": ("happy", "happy"), "amusement": ("happy", "happy"), "relief": ("content", "content"),
              "contentment": ("content", "content"), "curiosity": ("puppy-eyes", "puppy-eyes"),
              "nostalgia": ("content", "content"), "sadness": ("puppy-eyes", "crying"), "hurt": ("puppy-eyes", "crying"),
              "loneliness": ("puppy-eyes", "puppy-eyes"), "disappointment": ("puppy-eyes", "puppy-eyes"),
              "guilt": ("puppy-eyes", "puppy-eyes"), "jealousy": ("nervous", "nervous"),
              "frustration": ("focused", "ticked-off"), "nervousness": ("nervous", "nervous"),
              "anger": ("ticked-off", "very-angry"), "fear": ("scared", "panic"),
              "embarrassment": ("flustered", "very-embarrassed"), "surprise": ("surprised", "surprised"),
              "boredom": ("sleepy", "sleepy")}
# star.stream_motion.CUES: surprise, joy, laugh, focus, nod
CUE = {"joy": "joy", "pride": "joy", "excitement": "joy", "love": "joy", "hope": "joy", "amusement": "laugh",
       "surprise": "surprise", "curiosity": "focus", "affection": "nod", "gratitude": "nod", "relief": "nod"}


def avatar_from(picked: list[str], dev: dict[str, float], energy: float) -> dict:
    lead = picked[0] if picked else None
    if lead is None:
        return {"face": "idle", "expression": "normal", "cue": None, "strength": 0.0, "energy": energy}
    return {"face": FACE[lead], "expression": EXPRESSION[lead][1 if dev[lead] >= STRONG else 0], "cue": CUE.get(lead),
            "strength": round(_clamp(dev[lead] * 1.6, 0.0, 1.0), 2), "energy": energy}


def drives_from(dev: dict[str, float], amends_pending: bool) -> dict:
    """What her state makes her want, 0..1 each, for hosts that decide things (invites, what to do next, who to message).
    `coping` lists the ways she would look after herself, most needed first; hosts log what she did with the events
    talked_to_friend / took_a_break / played_something_comforting / amends_made."""
    d = {n: max(0.0, v) for n, v in dev.items()}
    wants_company = _clamp(1.2 * d["loneliness"] + 0.6 * d["boredom"] + 0.4 * d["sadness"] + 0.3 * d["excitement"], 0, 1)
    needs_rest = _clamp(0.7 * d["anger"] + 0.5 * d["fear"] + 0.6 * d["frustration"] + 0.4 * d["nervousness"]
                        + 0.3 * d["embarrassment"], 0, 1)
    needs_comfort = _clamp(0.8 * (d["sadness"] + d["hurt"] + d["disappointment"] + d["loneliness"]) + 0.4 * d["guilt"], 0, 1)
    coping = []
    if amends_pending:
        coping.append("make_amends")
    if needs_rest >= 0.15:
        coping.append("take_a_break")
    if needs_comfort >= 0.25 and wants_company >= 0.15:
        coping.append("talk_to_friend")
    if needs_comfort >= 0.25 or d["boredom"] >= 0.3:
        coping.append("play_something_comforting")
    return {"wants_company": round(wants_company, 2), "needs_rest": round(needs_rest, 2),
            "needs_comfort": round(needs_comfort, 2), "coping": coping}


# How much each way of spending time suits a feeling (used by invite_bias). A close friend is never refused as a punishment:
# the bias is bounded, and a bad mood only ever asks for "later" or a quieter way to be together.
_LOW_ENERGY_OK = {"chat": 0.1, "video": 0.0, "play": -0.05, "call": -0.1, "create": 0.0, "help": 0.0}


def invite_bias(mood: dict | None, kind: str = "play") -> tuple[float, str]:
    """(change to the chance she says yes, in -0.35..+0.35; a few words why) from `star.emotion.current()`. Lonely or excited
    raises it, angry, scared or worn out lowers it, a sad or hurt moment prefers talking to playing. ('', 0.0) without a mood."""
    if not mood or not isinstance(mood.get("emotions"), dict):
        return 0.0, ""
    base = {}
    from .emotion_model import BASELINE
    for name in EMOTIONS:
        try:
            base[name] = max(0.0, float(mood["emotions"].get(name, BASELINE[name])) - BASELINE[name])
        except (TypeError, ValueError):
            base[name] = 0.0
    drives = drives_from(base, bool(mood.get("amends_pending")))
    lift = 0.5 * drives["wants_company"] + 0.3 * base["excitement"] + 0.25 * base["joy"] + 0.15 * base["love"]
    drag = 0.5 * drives["needs_rest"] + 0.3 * base["sadness"] + 0.25 * base["hurt"] + 0.2 * base["guilt"]
    if kind == "chat":
        lift += 0.3 * drives["needs_comfort"]
        drag *= 0.4
    elif kind == "call":
        drag += 0.1 * drives["needs_comfort"]
    bias = _clamp(lift - drag + (_LOW_ENERGY_OK.get(kind, 0.0) if drives["needs_comfort"] > 0.3 else 0.0), -0.35, 0.35)
    if bias <= -0.05:
        why = "needs a moment" if drives["needs_rest"] >= drives["needs_comfort"] else "a bit down, would rather talk"
    elif bias >= 0.05:
        why = "wants company" if drives["wants_company"] >= base["excitement"] else "in a good mood"
    else:
        why = ""
    return round(bias, 3), why
