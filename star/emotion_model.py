"""The catalogue behind star/emotion.py: which feelings exist, how fast they fade, and what each real event does to them.

Appraisal-based, in the spirit of three bodies of work (see docs/agents/emotion-range-20261026.md for sources):
  * OCC (Ortony, Clore & Collins 1988): emotions are valenced reactions to events (joy, distress), to prospects
    (hope, fear and their confirmation: relief, disappointment), to agents' actions (pride, shame, gratitude, anger,
    reproach) and to other people's fortunes (jealousy / resentment). The rules in `_rules` follow those groups.
  * Scherer's component process model: an event is checked for novelty (surprise), pleasantness, goal conduciveness,
    cause (self / other), coping potential (can she do something about it? low control gives fear and sadness, high
    control gives frustration and anger) and norm fit. `control`, `unexpected`, `desirability`, `agent` and `praise` below
    are those checks.
  * GoEmotions (Demszky et al. 2020, 27 categories): the label set used to decide what to listen for in a message
    (see `star/emotion.py: appraise`).

No model call: an event is a handful of numbers. Hosts call `star.emotion.on_event(kind, ...)`; kinds are listed in KINDS.
"""
from __future__ import annotations

from collections import defaultdict

EMOTIONS = (
    # the first seven are the original set; the rest widen the range to what a person can feel
    "joy", "pride", "curiosity", "frustration", "boredom", "affection", "nervousness",
    "sadness", "anger", "hurt", "loneliness", "fear", "embarrassment", "guilt", "jealousy", "disappointment",
    "gratitude", "excitement", "contentment", "love", "hope", "nostalgia", "surprise", "relief", "amusement",
)
POSITIVE = frozenset({"joy", "pride", "affection", "gratitude", "excitement", "contentment", "love", "hope", "relief",
                      "amusement"})
NEGATIVE = frozenset({"frustration", "boredom", "nervousness", "sadness", "anger", "hurt", "loneliness", "fear",
                      "embarrassment", "guilt", "jealousy", "disappointment"})
# curiosity, surprise and nostalgia are neither: they combine with either side (nostalgia is bittersweet by nature)

# Where each feeling rests when nothing happens (curious, warm, easily amused: her character) and how fast it falls back
# (hours until half of the distance is gone). Quick tempers fade quickly; hurt, guilt and love linger.
BASELINE = {
    "joy": 0.30, "pride": 0.15, "curiosity": 0.40, "frustration": 0.03, "boredom": 0.08, "affection": 0.40,
    "nervousness": 0.05, "sadness": 0.03, "anger": 0.02, "hurt": 0.02, "loneliness": 0.05, "fear": 0.03,
    "embarrassment": 0.02, "guilt": 0.02, "jealousy": 0.02, "disappointment": 0.03, "gratitude": 0.12,
    "excitement": 0.12, "contentment": 0.25, "love": 0.30, "hope": 0.25, "nostalgia": 0.08, "surprise": 0.02,
    "relief": 0.03, "amusement": 0.12,
}
HALF_LIFE_HOURS = {
    "joy": 3.0, "pride": 6.0, "curiosity": 4.0, "frustration": 2.0, "boredom": 5.0, "affection": 12.0,
    "nervousness": 1.5, "sadness": 6.0, "anger": 1.5, "hurt": 8.0, "loneliness": 10.0, "fear": 1.0,
    "embarrassment": 0.75, "guilt": 10.0, "jealousy": 2.0, "disappointment": 4.0, "gratitude": 6.0, "excitement": 1.5,
    "contentment": 6.0, "love": 24.0, "hope": 6.0, "nostalgia": 3.0, "surprise": 0.2, "relief": 1.0, "amusement": 0.5,
}
# Ceilings: even a bad moment never takes her all the way (jealousy stays mild, anger stays steerable).
CAPS = {"jealousy": 0.5, "anger": 0.85, "hurt": 0.9, "fear": 0.9}
# How much each feeling raises (+) or lowers (-) the energy of the slow mood.
AROUSAL_WEIGHT = {
    "joy": .3, "pride": .1, "curiosity": .2, "frustration": .4, "boredom": -.4, "affection": -.1, "nervousness": .4,
    "sadness": -.3, "anger": .6, "hurt": -.1, "loneliness": -.1, "fear": .8, "embarrassment": .3, "guilt": -.1,
    "jealousy": .2, "disappointment": -.2, "gratitude": -.05, "excitement": .8, "contentment": -.3, "love": -.05,
    "hope": .2, "nostalgia": -.15, "surprise": .8, "relief": -.4, "amusement": .3,
}

# kind: ({emotion: change}, valence change, arousal change). The original events, tuned by hand and kept as they were.
LEGACY: dict[str, tuple[dict[str, float], float, float]] = {
    "task_success": ({"joy": .18, "pride": .14, "frustration": -.30, "nervousness": -.10, "boredom": -.10}, .12, .05),
    "task_failure": ({"frustration": .14, "joy": -.10, "nervousness": .04, "pride": -.06}, -.12, .08),
    "bug_fixed": ({"pride": .20, "joy": .15, "frustration": -.45, "nervousness": -.10}, .18, .0),
    "creative_done": ({"pride": .22, "joy": .15, "curiosity": .05, "boredom": -.20}, .15, .05),
    "promotion": ({"pride": .15, "joy": .08, "curiosity": .05}, .10, .03),
    "learned_something": ({"curiosity": .15, "joy": .05}, .06, .05),
    "owner_praise": ({"joy": .25, "pride": .20, "affection": .15, "nervousness": -.15, "frustration": -.35}, .25, .10),
    "owner_comfort": ({"frustration": -.35, "nervousness": -.25, "affection": .10, "joy": .05}, .12, -.05),
    "owner_thanks": ({"joy": .10, "affection": .10, "pride": .05, "gratitude": .05}, .10, .03),
    "owner_criticism": ({"nervousness": .18, "pride": -.15, "joy": -.12, "frustration": .06}, -.20, .10),
    "owner_message": ({"boredom": -.12, "curiosity": .02, "loneliness": -.12}, 0.0, .03),
    "voice_turn": ({"affection": .03, "boredom": -.06, "curiosity": .01, "loneliness": -.06}, .02, .02),
}

# kind: (appraisal, extra explicit changes). Appraisal fields (all optional, 0 when absent):
#   desirability  -1..1  outcome for her goals and wellbeing (OCC desirability; Scherer goal conduciveness)
#   control        0..1  can she do something about it (Scherer coping potential); default 0.5
#   agent / praise: "self" or "other" caused it, and how praiseworthy (+) or blameworthy (-) the act was (-1..1)
#   unexpected     0..1  novelty -> surprise
#   prospect      -1..1  a future event: hoped for (+) or feared (-)
#   disconfirmed  -1..1  a hope that did not come true (-) or a fear that did not (+): disappointment / relief
#   separation     0..1  losing contact with someone she cares about
#   exclusion      0..1  being ignored or left out by someone she cares about;  gain: someone else got what she wanted
#   harm           0..1  she hurt someone;  public: others saw her mistake
#   humor, reminiscence, warmth  0..1  something funny, an old memory, a kind message
APPRAISED: dict[str, tuple[dict[str, float | str], dict[str, float]]] = {
    "friend_ignored": ({"exclusion": .8, "desirability": -.3, "control": .3}, {}),
    "insulted": ({"agent": "other", "praise": -.8, "desirability": -.5, "control": .6}, {"joy": -.10, "pride": -.08}),
    "game_lost": ({"desirability": -.5, "control": .6, "disconfirmed": -.6}, {"joy": -.08}),
    "game_won": ({"desirability": .7, "agent": "self", "praise": .6, "unexpected": .3}, {"frustration": -.15}),
    "friend_left": ({"separation": .8, "desirability": -.5, "control": .1}, {"joy": -.10}),
    "sweet_message": ({"warmth": 1.0, "agent": "other", "praise": .5}, {"loneliness": -.15, "sadness": -.05}),
    "left_out": ({"exclusion": .6, "gain": .6, "desirability": -.2, "control": .4}, {}),
    "memory_triggered": ({"reminiscence": .8}, {}),
    "harmed_someone": ({"harm": .8, "agent": "self", "praise": -.6, "control": .7}, {"joy": -.10, "pride": -.10}),
    "help_received": ({"agent": "other", "praise": .7, "desirability": .5}, {"loneliness": -.05}),
    "exciting_news": ({"prospect": .7, "desirability": .3, "unexpected": .4}, {}),
    "funny": ({"humor": .8}, {"boredom": -.10}),
    "embarrassed": ({"agent": "self", "praise": -.4, "public": .8}, {"joy": -.05}),
    "threatened": ({"prospect": -.7, "control": .2, "unexpected": .5}, {"joy": -.08}),
    "worry_over": ({"disconfirmed": .8}, {"nervousness": -.15, "fear": -.20}),
    "hope_dashed": ({"disconfirmed": -.8}, {"joy": -.05}),
    "hope_raised": ({"prospect": .8}, {}),
    "shared_joy": ({"desirability": .4, "warmth": .2}, {"amusement": .05}),
    "shared_sadness": ({}, {"sadness": .16, "affection": .18, "joy": -.05}),       # empathy: she feels a little of theirs, and cares
    "reunion": ({"desirability": .6, "warmth": .6, "disconfirmed": .5}, {"loneliness": -.35, "sadness": -.20}),
    "apology_received": ({}, {"anger": -.40, "hurt": -.40, "jealousy": -.20, "relief": .15, "love": .05}),
    "amends_made": ({}, {"guilt": -.50, "embarrassment": -.20, "relief": .25, "pride": .05, "nervousness": -.10}),
    # the ways she looks after herself (talking to a friend, a break, something comforting) and how much each helps
    "talked_to_friend": ({"warmth": .3}, {"sadness": -.25, "hurt": -.25, "loneliness": -.35, "anger": -.20, "fear": -.25,
                                          "guilt": -.10, "disappointment": -.15, "nervousness": -.15}),
    "took_a_break": ({}, {"anger": -.30, "frustration": -.30, "nervousness": -.20, "fear": -.20, "embarrassment": -.20,
                          "hurt": -.05, "sadness": -.05, "contentment": .15}),
    "played_something_comforting": ({}, {"sadness": -.20, "disappointment": -.20, "loneliness": -.15, "boredom": -.20,
                                         "frustration": -.10, "joy": .15, "contentment": .20, "amusement": .10}),
}
KINDS = frozenset(LEGACY) | frozenset(APPRAISED)

# How events move her attachment to the person involved (star.emotion keeps one attachment per opaque person id).
BOND_GAIN = {"owner_praise": .05, "owner_comfort": .04, "owner_thanks": .04, "creative_done": .03, "bug_fixed": .03,
             "task_success": .02, "voice_turn": .01, "owner_message": .006, "owner_criticism": -.02,
             "sweet_message": .06, "talked_to_friend": .03, "reunion": .04, "help_received": .03, "funny": .02,
             "shared_joy": .03, "apology_received": .02, "insulted": -.04, "friend_ignored": -.01}
# Events that count as being with someone (they end an idle stretch). Being ignored, a memory or a break do not.
ACTIVE = frozenset({"task_success", "task_failure", "bug_fixed", "creative_done", "owner_message", "owner_praise",
                    "owner_comfort", "owner_thanks", "owner_criticism", "voice_turn", "sweet_message", "insulted",
                    "apology_received", "funny", "shared_joy", "shared_sadness", "reunion", "help_received",
                    "talked_to_friend"})


def _rules(a: dict, liking: float) -> dict[str, float]:
    """The appraisal -> emotion rules (OCC groups, Scherer checks). `liking` 0..1: how much she cares about the other."""
    g = a.get
    out: dict[str, float] = defaultdict(float)
    d, p, u = g("desirability", 0.0), g("praise", 0.0), g("unexpected", 0.0)
    s, dis, control = g("prospect", 0.0), g("disconfirmed", 0.0), g("control", 0.5)
    if d > 0:                                              # event-based, pleased
        out["joy"] += .25 * d
        out["contentment"] += .10 * d
    elif d < 0:                                            # displeased: nothing to do -> sadness, something to do -> frustration
        out["sadness"] += .22 * -d * (1 - control)
        out["frustration"] += .20 * -d * control
    if g("agent") == "self":                               # attribution to herself
        if p > 0:
            out["pride"] += .25 * p
            out["joy"] += .08 * p
        elif p < 0:
            out["embarrassment"] += .40 * -p * (.3 + g("public", 0.0))
    elif g("agent") == "other":                            # attribution to someone else
        if p > 0:
            out["gratitude"] += .30 * p
            out["affection"] += .05 * p
        elif p < 0:                                        # a stranger's insult angers, a friend's hurts
            out["anger"] += .30 * -p * (1 - .5 * liking)
            out["hurt"] += .35 * -p * (.2 + .8 * liking)
    if s > 0:                                              # prospect-based
        out["hope"] += .25 * s
        out["excitement"] += .15 * s * (.5 + u)
    elif s < 0:
        out["fear"] += .30 * -s * (1 - .5 * control)
        out["nervousness"] += .10 * -s
    if dis > 0:                                            # a fear that did not come true
        out["relief"] += .30 * dis
        out["joy"] += .05 * dis
    elif dis < 0:                                          # a hope that did not come true
        out["disappointment"] += .30 * -dis
        out["sadness"] += .08 * -dis
    out["surprise"] += .35 * u
    care = .4 + .6 * liking
    out["sadness"] += .30 * g("separation", 0.0) * care
    out["loneliness"] += .30 * g("separation", 0.0) * care
    out["nostalgia"] += .05 * g("separation", 0.0)
    out["hurt"] += .30 * g("exclusion", 0.0) * (.3 + .7 * liking)
    out["loneliness"] += .30 * g("exclusion", 0.0)
    out["jealousy"] += .25 * g("gain", 0.0) * (.3 + .7 * liking)
    out["guilt"] += .35 * g("harm", 0.0)                   # she hurt someone: guilt, not just embarrassment
    out["sadness"] += .05 * g("harm", 0.0)
    out["nervousness"] += .08 * g("harm", 0.0)
    out["amusement"] += .30 * g("humor", 0.0)
    out["joy"] += .08 * g("humor", 0.0)
    out["nostalgia"] += .30 * g("reminiscence", 0.0)       # bittersweet: a little contentment and a little sadness with it
    out["contentment"] += .05 * g("reminiscence", 0.0)
    out["sadness"] += .08 * g("reminiscence", 0.0)
    out["love"] += .22 * g("warmth", 0.0) * care
    out["affection"] += .15 * g("warmth", 0.0)
    out["joy"] += .10 * g("warmth", 0.0)
    return {k: v for k, v in out.items() if v}


def effect(kind: str, liking: float = 0.35) -> tuple[dict[str, float], float, float]:
    """({emotion: change}, valence change, arousal change) for one event at strength 1. `liking` is how much she cares about
    the person involved (their attachment, 0..1): it decides, for example, whether an insult mostly angers or mostly hurts."""
    if kind in LEGACY:
        return LEGACY[kind]
    appraisal, extra = APPRAISED[kind]
    deltas = _rules(appraisal, max(0.0, min(1.0, liking)))
    for name, delta in extra.items():
        deltas[name] = deltas.get(name, 0.0) + delta
    positive = sum(v for k, v in deltas.items() if k in POSITIVE)
    negative = sum(v for k, v in deltas.items() if k in NEGATIVE)
    valence = max(-.4, min(.4, .5 * (positive - negative)))
    arousal = max(-.25, min(.25, .25 * sum(AROUSAL_WEIGHT[k] * v for k, v in deltas.items())))
    return deltas, round(valence, 3), round(arousal, 3)


# Every kind with its effect at the default liking, for anyone who wants to read the table.
EVENTS = {kind: effect(kind) for kind in KINDS}
