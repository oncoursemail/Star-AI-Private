"""Player Twin personas (P2): parameters for the Luau human model in ``luau/human.luau``.

Times are seconds. ``rt`` is the median of a log-normal reaction time (simple visual RT medians sit
near 250 ms); ``device`` picks the Fitts' law constants; ``motor`` scales pointing spread;
``patience`` is how long a player tolerates waiting past ``acceptableWait`` before quitting bored;
``frustTol`` is the frustration (repeated failure) level that makes them quit. The numbers are
hand-set archetypes, not fitted to real Roblox telemetry: calibrate them against the deep-player tier
or live analytics (P9) before trusting absolute quit rates.
"""
from __future__ import annotations

PERSONAS: dict[str, dict] = {
    "casual_kid_mobile": {
        "label": "Casual kid on a phone", "device": "touch", "rt": 0.42, "rtSigma": 0.35, "motor": 1.6,
        "skill0": 1.0, "learn": 0.30, "patience": 150, "frustTol": 4.0, "sessionMin": 12, "decision": 1.4,
        "misread": 0.10, "clickMin": 3, "clickMax": 10, "clickGap": 0.18, "idleProb": 0.12, "idleMin": 4,
        "idleMax": 25, "strategy": "cheapest", "prestige": 0.6, "challengePref": 0.40, "acceptableWait": 45,
        "returnBase": 0.55, "fuzz": False,
    },
    "speedrunner": {
        "label": "Speedrunner", "device": "mouse", "rt": 0.21, "rtSigma": 0.20, "motor": 0.8,
        "skill0": 3.5, "learn": 0.10, "patience": 420, "frustTol": 9.0, "sessionMin": 45, "decision": 0.4,
        "misread": 0.01, "clickMin": 10, "clickMax": 25, "clickGap": 0.04, "idleProb": 0.01, "idleMin": 2,
        "idleMax": 6, "strategy": "roi", "prestige": 1.0, "challengePref": 0.50, "acceptableWait": 90,
        "returnBase": 0.70, "fuzz": False,
    },
    "explorer": {
        "label": "Explorer", "device": "mouse", "rt": 0.30, "rtSigma": 0.30, "motor": 1.2,
        "skill0": 2.0, "learn": 0.20, "patience": 240, "frustTol": 6.0, "sessionMin": 25, "decision": 1.0,
        "misread": 0.04, "clickMin": 2, "clickMax": 6, "clickGap": 0.12, "idleProb": 0.10, "idleMin": 3,
        "idleMax": 15, "strategy": "random", "prestige": 0.5, "challengePref": 0.60, "acceptableWait": 60,
        "returnBase": 0.50, "fuzz": False,
    },
    "afk_grinder": {
        "label": "AFK grinder", "device": "mouse", "rt": 0.35, "rtSigma": 0.30, "motor": 1.0,
        "skill0": 1.5, "learn": 0.10, "patience": 7200, "frustTol": 5.0, "sessionMin": 120, "decision": 1.2,
        "misread": 0.03, "clickMin": 3, "clickMax": 10, "clickGap": 0.20, "idleProb": 0.6, "idleMin": 60,
        "idleMax": 240, "strategy": "cheapest", "prestige": 0.8, "challengePref": 0.05, "acceptableWait": 3600,
        "returnBase": 0.85, "fuzz": False,
    },
    "completionist": {
        "label": "Completionist", "device": "mouse", "rt": 0.28, "rtSigma": 0.25, "motor": 1.0,
        "skill0": 2.5, "learn": 0.15, "patience": 900, "frustTol": 10.0, "sessionMin": 60, "decision": 0.8,
        "misread": 0.02, "clickMin": 5, "clickMax": 15, "clickGap": 0.08, "idleProb": 0.05, "idleMin": 3,
        "idleMax": 10, "strategy": "cheapest", "prestige": 0.9, "challengePref": 0.50, "acceptableWait": 300,
        "returnBase": 0.75, "fuzz": False,
    },
    "exploiter": {
        "label": "Exploiter (fuzzes remotes)", "device": "mouse", "rt": 0.25, "rtSigma": 0.25, "motor": 1.0,
        "skill0": 2.5, "learn": 0.15, "patience": 300, "frustTol": 6.0, "sessionMin": 20, "decision": 0.6,
        "misread": 0.02, "clickMin": 5, "clickMax": 15, "clickGap": 0.06, "idleProb": 0.03, "idleMin": 2,
        "idleMax": 8, "strategy": "roi", "prestige": 0.9, "challengePref": 0.40, "acceptableWait": 120,
        "returnBase": 0.60, "fuzz": True,
    },
}

# Share of each persona in an "all" population. A rough Roblox-like mix, not measured data.
DEFAULT_MIX: dict[str, float] = {
    "casual_kid_mobile": 0.30, "explorer": 0.20, "afk_grinder": 0.15, "completionist": 0.15,
    "speedrunner": 0.10, "exploiter": 0.10,
}


def parse_personas(spec: str) -> dict[str, float]:
    """``all`` or a comma list like ``speedrunner,exploiter`` or ``speedrunner=3,exploiter=1``."""
    if spec.strip() in ("", "all"):
        return dict(DEFAULT_MIX)
    mix: dict[str, float] = {}
    for part in spec.split(","):
        name, _, weight = part.strip().partition("=")
        if name not in PERSONAS:
            raise ValueError(f"unknown persona {name!r}; known: {', '.join(PERSONAS)}")
        mix[name] = float(weight) if weight else 1.0
        if mix[name] <= 0:
            raise ValueError(f"persona weight must be positive: {part!r}")
    total = sum(mix.values())
    return {k: v / total for k, v in mix.items()}


def assign(n: int, mix: dict[str, float]) -> list[str]:
    """Deterministic largest-remainder split of n twins over the mix."""
    raw = {k: n * w for k, w in mix.items()}
    counts = {k: int(v) for k, v in raw.items()}
    left = n - sum(counts.values())
    for k in sorted(raw, key=lambda k: raw[k] - counts[k], reverse=True)[:left]:
        counts[k] += 1
    out: list[str] = []
    for k in mix:
        out.extend([k] * counts[k])
    return out
