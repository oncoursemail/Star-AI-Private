"""Domain problems (animation, VFX, audio, physics / game feel, procedural generation, UI, pathfinding / AI,
networking) in Python, TypeScript (+ derived JavaScript), C#, GDScript and Lua. Same shape as bank.PROBLEMS."""
from __future__ import annotations

import math

from .bank import PROBLEMS as _ALL

PROBLEMS: list[dict] = []
FLAVOR = {
    "unity": "Unity-style logic (plain C#, no UnityEngine reference available in the tests). ",
    "godot": "Godot 4 logic (a plain static function; no scene tree in the tests). ",
    "roblox": "Roblox-style logic in plain Lua (no game services in the tests). ",
    "": "",
}


def problem(fn, params, ret, family, desc, oracle, cases, flavor="", **refs):
    p = {"fn": fn, "params": params, "ret": ret, "family": family, "desc": desc, "oracle": oracle,
         "cases": [((c,) if not isinstance(c, tuple) or len(c) != 1 else c) for c in cases], "refs": refs,
         "flavor": FLAVOR[flavor], "file": "code-" + family}
    PROBLEMS.append(p)


def C(*cases):
    return [(c,) for c in cases]


# ---------------------------------------------------------------- animation
problem("ease_in_out_quad", [("t", "float")], "float", "animation",
        "Quadratic ease-in-out: 2t^2 for t < 0.5, otherwise 1 - (-2t + 2)^2 / 2. `t` is already in [0, 1].",
        lambda t: 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2, C((0.0,), (0.25,), (0.5,), (0.75,), (1.0,), (0.1,), (0.9,)),
        python="def ease_in_out_quad(t):\n    return 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2\n",
        typescript="function easeInOutQuad(t: number): number {\n    return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;\n}\n",
        csharp="public static double EaseInOutQuad(double t) {\n    return t < 0.5 ? 2 * t * t : 1 - Math.Pow(-2 * t + 2, 2) / 2;\n}\n",
        gdscript="static func ease_in_out_quad(t: float) -> float:\n\treturn 2.0 * t * t if t < 0.5 else 1.0 - pow(-2.0 * t + 2.0, 2) / 2.0\n",
        lua="function ease_in_out_quad(t)\n    if t < 0.5 then return 2 * t * t end\n    return 1 - (-2 * t + 2) ^ 2 / 2\nend\n")


def _move_toward(c, t, d):
    if abs(t - c) <= d:
        return float(t)
    return c + d * (1 if t > c else -1)


problem("move_toward", [("current", "float"), ("target", "float"), ("max_delta", "float")], "float", "animation",
        "Move `current` toward `target` by at most `max_delta` (never overshooting), like Unity's Mathf.MoveTowards or Godot's move_toward.",
        _move_toward, C((0.0, 10.0, 3.0), (9.0, 10.0, 3.0), (10.0, 0.0, 4.0), (5.0, 5.0, 1.0), (-2.0, -8.0, 10.0), (1.5, 2.0, 0.25)), flavor="unity",
        python="def move_toward(current, target, max_delta):\n    if abs(target - current) <= max_delta:\n        return target\n    return current + max_delta * (1 if target > current else -1)\n",
        typescript="function moveToward(current: number, target: number, maxDelta: number): number {\n    if (Math.abs(target - current) <= maxDelta) return target;\n    return current + Math.sign(target - current) * maxDelta;\n}\n",
        csharp="public static double MoveToward(double current, double target, double max_delta) {\n    if (Math.Abs(target - current) <= max_delta) return target;\n    return current + Math.Sign(target - current) * max_delta;\n}\n",
        gdscript="static func move_toward(current: float, target: float, max_delta: float) -> float:\n\tif absf(target - current) <= max_delta:\n\t\treturn target\n\treturn current + signf(target - current) * max_delta\n",
        lua="function move_toward(current, target, max_delta)\n    if math.abs(target - current) <= max_delta then return target end\n    return current + (target > current and 1 or -1) * max_delta\nend\n")


def _ping_pong(t, length):
    t = t % (length * 2)
    return length - abs(t - length)


problem("ping_pong", [("t", "float"), ("length", "float")], "float", "animation",
        "PingPong: `t` (>= 0) bounces between 0 and `length` (like Unity's Mathf.PingPong): 0 -> length -> 0 -> ...",
        _ping_pong, C((0.0, 3.0), (2.0, 3.0), (3.0, 3.0), (4.0, 3.0), (6.0, 3.0), (7.5, 3.0), (13.0, 5.0)), flavor="unity",
        python="def ping_pong(t, length):\n    t = t % (length * 2)\n    return length - abs(t - length)\n",
        typescript="function pingPong(t: number, length: number): number {\n    t = t % (length * 2);\n    return length - Math.abs(t - length);\n}\n",
        csharp="public static double PingPong(double t, double length) {\n    t = t % (length * 2);\n    return length - Math.Abs(t - length);\n}\n",
        gdscript="static func ping_pong(t: float, length: float) -> float:\n\tt = fmod(t, length * 2.0)\n\treturn length - absf(t - length)\n",
        lua="function ping_pong(t, length)\n    t = t % (length * 2)\n    return length - math.abs(t - length)\nend\n")


def _frame_index(time, fps, count, loop):
    f = int(math.floor(time * fps + 1e-9))
    return f % count if loop else min(f, count - 1)


problem("frame_index", [("time", "float"), ("fps", "int"), ("frame_count", "int"), ("loop", "bool")], "int", "animation",
        "The sprite frame (0-based) shown at `time` seconds: floor(time * fps), wrapped with modulo when `loop`, otherwise clamped to the last frame.",
        _frame_index, C((0.0, 12, 6, True), (0.5, 12, 6, True), (1.0, 12, 6, False), (0.25, 24, 8, True), (3.0, 10, 4, False), (0.95, 10, 4, True)),
        python="def frame_index(time, fps, frame_count, loop):\n    f = int(time * fps + 1e-9)\n    return f % frame_count if loop else min(f, frame_count - 1)\n",
        typescript="function frameIndex(time: number, fps: number, frameCount: number, loop: boolean): number {\n    const f = Math.floor(time * fps + 1e-9);\n    return loop ? f % frameCount : Math.min(f, frameCount - 1);\n}\n",
        csharp="public static int FrameIndex(double time, int fps, int frame_count, bool loop) {\n    int f = (int)Math.Floor(time * fps + 1e-9);\n    return loop ? f % frame_count : Math.Min(f, frame_count - 1);\n}\n",
        gdscript="static func frame_index(time: float, fps: int, frame_count: int, loop: bool) -> int:\n\tvar f := int(floor(time * fps + 1e-9))\n\treturn f % frame_count if loop else mini(f, frame_count - 1)\n",
        lua="function frame_index(time, fps, frame_count, loop)\n    local f = math.floor(time * fps + 1e-9)\n    if loop then return f % frame_count end\n    return math.min(f, frame_count - 1)\nend\n")


def _blend(value, th):
    w = [0.0] * len(th)
    if value <= th[0]:
        w[0] = 1.0
    elif value >= th[-1]:
        w[-1] = 1.0
    else:
        for i in range(len(th) - 1):
            if th[i] <= value <= th[i + 1]:
                f = (value - th[i]) / (th[i + 1] - th[i])
                w[i], w[i + 1] = 1 - f, f
                break
    return w


problem("blend_weights_1d", [("value", "float"), ("thresholds", "float[]")], "float[]", "animation",
        "Weights of a 1D blend tree: clips sit at ascending `thresholds`; the two clips around `value` get linear weights that sum to 1, all others 0; "
        "below the first or above the last threshold the end clip gets weight 1.",
        _blend, C((0.0, [0.0, 5.0, 10.0]), (2.5, [0.0, 5.0, 10.0]), (7.0, [0.0, 5.0, 10.0]), (12.0, [0.0, 5.0, 10.0]), (-1.0, [0.0, 5.0, 10.0]), (3.0, [1.0, 2.0, 4.0, 8.0])),
        python="def blend_weights_1d(value, thresholds):\n    w = [0.0] * len(thresholds)\n    if value <= thresholds[0]:\n        w[0] = 1.0\n    elif value >= thresholds[-1]:\n        w[-1] = 1.0\n    else:\n        for i in range(len(thresholds) - 1):\n            if thresholds[i] <= value <= thresholds[i + 1]:\n                f = (value - thresholds[i]) / (thresholds[i + 1] - thresholds[i])\n                w[i], w[i + 1] = 1 - f, f\n                break\n    return w\n",
        typescript="function blendWeights1d(value: number, thresholds: number[]): number[] {\n    const w = thresholds.map(() => 0);\n    const n = thresholds.length;\n    if (value <= thresholds[0]) w[0] = 1;\n    else if (value >= thresholds[n - 1]) w[n - 1] = 1;\n    else {\n        for (let i = 0; i < n - 1; i++) {\n            if (thresholds[i] <= value && value <= thresholds[i + 1]) {\n                const f = (value - thresholds[i]) / (thresholds[i + 1] - thresholds[i]);\n                w[i] = 1 - f;\n                w[i + 1] = f;\n                break;\n            }\n        }\n    }\n    return w;\n}\n",
        csharp="public static double[] BlendWeights1d(double value, double[] thresholds) {\n    int n = thresholds.Length;\n    var w = new double[n];\n    if (value <= thresholds[0]) w[0] = 1;\n    else if (value >= thresholds[n - 1]) w[n - 1] = 1;\n    else {\n        for (int i = 0; i < n - 1; i++) {\n            if (thresholds[i] <= value && value <= thresholds[i + 1]) {\n                double f = (value - thresholds[i]) / (thresholds[i + 1] - thresholds[i]);\n                w[i] = 1 - f;\n                w[i + 1] = f;\n                break;\n            }\n        }\n    }\n    return w;\n}\n",
        gdscript="static func blend_weights_1d(value: float, thresholds: Array) -> Array:\n\tvar n := thresholds.size()\n\tvar w := []\n\tfor i in range(n):\n\t\tw.append(0.0)\n\tif value <= thresholds[0]:\n\t\tw[0] = 1.0\n\telif value >= thresholds[n - 1]:\n\t\tw[n - 1] = 1.0\n\telse:\n\t\tfor i in range(n - 1):\n\t\t\tif thresholds[i] <= value and value <= thresholds[i + 1]:\n\t\t\t\tvar f: float = (value - thresholds[i]) / (thresholds[i + 1] - thresholds[i])\n\t\t\t\tw[i] = 1.0 - f\n\t\t\t\tw[i + 1] = f\n\t\t\t\tbreak\n\treturn w\n",
        lua="function blend_weights_1d(value, thresholds)\n    local n = #thresholds\n    local w = {}\n    for i = 1, n do w[i] = 0 end\n    if value <= thresholds[1] then\n        w[1] = 1\n    elseif value >= thresholds[n] then\n        w[n] = 1\n    else\n        for i = 1, n - 1 do\n            if thresholds[i] <= value and value <= thresholds[i + 1] then\n                local f = (value - thresholds[i]) / (thresholds[i + 1] - thresholds[i])\n                w[i], w[i + 1] = 1 - f, f\n                break\n            end\n        end\n    end\n    return w\nend\n")


def _spring(x, v, target, k, d, dt):
    a = -k * (x - target) - d * v
    v2 = v + a * dt
    return [x + v2 * dt, v2]


problem("spring_step", [("x", "float"), ("v", "float"), ("target", "float"), ("k", "float"), ("d", "float"), ("dt", "float")], "float[]", "animation",
        "One semi-implicit Euler step of a damped spring: a = -k (x - target) - d v; v = v + a dt; x = x + v dt. Return [x, v].",
        _spring, C((0.0, 0.0, 1.0, 10.0, 2.0, 0.1), (1.0, 0.0, 1.0, 10.0, 2.0, 0.1), (5.0, -2.0, 0.0, 20.0, 4.0, 0.05), (-3.0, 1.0, 2.0, 50.0, 5.0, 0.016)),
        python="def spring_step(x, v, target, k, d, dt):\n    a = -k * (x - target) - d * v\n    v = v + a * dt\n    return [x + v * dt, v]\n",
        typescript="function springStep(x: number, v: number, target: number, k: number, d: number, dt: number): number[] {\n    const a = -k * (x - target) - d * v;\n    v = v + a * dt;\n    return [x + v * dt, v];\n}\n",
        csharp="public static double[] SpringStep(double x, double v, double target, double k, double d, double dt) {\n    double a = -k * (x - target) - d * v;\n    v = v + a * dt;\n    return new double[] { x + v * dt, v };\n}\n",
        gdscript="static func spring_step(x: float, v: float, target: float, k: float, d: float, dt: float) -> Array:\n\tvar a := -k * (x - target) - d * v\n\tv = v + a * dt\n\treturn [x + v * dt, v]\n",
        lua="function spring_step(x, v, target, k, d, dt)\n    local a = -k * (x - target) - d * v\n    v = v + a * dt\n    return { x + v * dt, v }\nend\n")

# ---------------------------------------------------------------- vfx
problem("particles_alive", [("rate", "float"), ("lifetime", "float"), ("t", "float")], "int", "vfx",
        "Particles alive at time `t` for an emitter that spawns `rate` per second and whose particles live `lifetime` seconds: floor(rate * min(t, lifetime)).",
        lambda rate, life, t: int(math.floor(rate * min(t, life) + 1e-9)), C((10.0, 2.0, 0.5), (10.0, 2.0, 2.0), (10.0, 2.0, 5.0), (25.0, 1.0, 0.3), (100.0, 0.5, 10.0), (7.0, 3.0, 1.0)),
        python="def particles_alive(rate, lifetime, t):\n    return int(rate * min(t, lifetime) + 1e-9)\n",
        typescript="function particlesAlive(rate: number, lifetime: number, t: number): number {\n    return Math.floor(rate * Math.min(t, lifetime) + 1e-9);\n}\n",
        csharp="public static int ParticlesAlive(double rate, double lifetime, double t) {\n    return (int)Math.Floor(rate * Math.Min(t, lifetime) + 1e-9);\n}\n",
        gdscript="static func particles_alive(rate: float, lifetime: float, t: float) -> int:\n\treturn int(floor(rate * minf(t, lifetime) + 1e-9))\n",
        lua="function particles_alive(rate, lifetime, t)\n    return math.floor(rate * math.min(t, lifetime) + 1e-9)\nend\n")

problem("fade_alpha", [("age", "float"), ("lifetime", "float"), ("start_alpha", "float"), ("end_alpha", "float")], "float", "vfx",
        "A particle's alpha at `age` seconds: linear from `start_alpha` (age 0) to `end_alpha` (age = lifetime), clamped at both ends.",
        lambda age, life, a0, a1: a0 + (a1 - a0) * max(0.0, min(1.0, age / life)), C((0.0, 2.0, 1.0, 0.0), (1.0, 2.0, 1.0, 0.0), (2.0, 2.0, 1.0, 0.0), (3.0, 2.0, 1.0, 0.0), (0.5, 1.0, 0.2, 0.8), (-1.0, 1.0, 0.5, 0.0)),
        python="def fade_alpha(age, lifetime, start_alpha, end_alpha):\n    t = max(0.0, min(1.0, age / lifetime))\n    return start_alpha + (end_alpha - start_alpha) * t\n",
        typescript="function fadeAlpha(age: number, lifetime: number, startAlpha: number, endAlpha: number): number {\n    const t = Math.max(0, Math.min(1, age / lifetime));\n    return startAlpha + (endAlpha - startAlpha) * t;\n}\n",
        csharp="public static double FadeAlpha(double age, double lifetime, double start_alpha, double end_alpha) {\n    double t = Math.Max(0, Math.Min(1, age / lifetime));\n    return start_alpha + (end_alpha - start_alpha) * t;\n}\n",
        gdscript="static func fade_alpha(age: float, lifetime: float, start_alpha: float, end_alpha: float) -> float:\n\tvar t := clampf(age / lifetime, 0.0, 1.0)\n\treturn start_alpha + (end_alpha - start_alpha) * t\n",
        lua="function fade_alpha(age, lifetime, start_alpha, end_alpha)\n    local t = math.max(0, math.min(1, age / lifetime))\n    return start_alpha + (end_alpha - start_alpha) * t\nend\n")

problem("pool_size", [("rate", "float"), ("lifetime", "float")], "int", "vfx",
        "Smallest object pool that never runs out for objects spawned at `rate` per second living `lifetime` seconds: ceil(rate * lifetime), at least 1.",
        lambda rate, life: max(1, int(math.ceil(rate * life - 1e-9))), C((10.0, 2.0), (10.0, 0.25), (3.0, 0.1), (0.5, 1.0), (7.0, 1.5), (60.0, 0.5)),
        python="import math\n\ndef pool_size(rate, lifetime):\n    return max(1, math.ceil(rate * lifetime - 1e-9))\n",
        typescript="function poolSize(rate: number, lifetime: number): number {\n    return Math.max(1, Math.ceil(rate * lifetime - 1e-9));\n}\n",
        csharp="public static int PoolSize(double rate, double lifetime) {\n    return Math.Max(1, (int)Math.Ceiling(rate * lifetime - 1e-9));\n}\n",
        gdscript="static func pool_size(rate: float, lifetime: float) -> int:\n\treturn maxi(1, int(ceil(rate * lifetime - 1e-9)))\n",
        lua="function pool_size(rate, lifetime)\n    return math.max(1, math.ceil(rate * lifetime - 1e-9))\nend\n")

# ---------------------------------------------------------------- audio
problem("db_to_linear", [("db", "float")], "float", "audio", "Convert a decibel gain to a linear amplitude: 10^(db / 20).",
        lambda db: 10 ** (db / 20), C((0.0,), (-6.0,), (-20.0,), (6.0,), (-60.0,), (3.0,)),
        python="def db_to_linear(db):\n    return 10 ** (db / 20)\n",
        typescript="function dbToLinear(db: number): number {\n    return Math.pow(10, db / 20);\n}\n",
        csharp="public static double DbToLinear(double db) {\n    return Math.Pow(10, db / 20);\n}\n",
        gdscript="static func db_to_linear(db: float) -> float:\n\treturn pow(10.0, db / 20.0)\n",
        lua="function db_to_linear(db)\n    return 10 ^ (db / 20)\nend\n")

problem("semitone_ratio", [("semitones", "int")], "float", "audio", "Playback-speed factor for a pitch shift of `semitones`: 2^(semitones / 12).",
        lambda n: 2 ** (n / 12), C((0,), (12,), (-12,), (7,), (1,), (-5,)),
        python="def semitone_ratio(semitones):\n    return 2 ** (semitones / 12)\n",
        typescript="function semitoneRatio(semitones: number): number {\n    return Math.pow(2, semitones / 12);\n}\n",
        csharp="public static double SemitoneRatio(int semitones) {\n    return Math.Pow(2, semitones / 12.0);\n}\n",
        gdscript="static func semitone_ratio(semitones: int) -> float:\n\treturn pow(2.0, semitones / 12.0)\n",
        lua="function semitone_ratio(semitones)\n    return 2 ^ (semitones / 12)\nend\n")

problem("distance_attenuation", [("dist", "float"), ("min_d", "float"), ("max_d", "float")], "float", "audio",
        "Linear roll-off volume for a 3D sound: 1 at or inside `min_d`, 0 at or beyond `max_d`, linear in between.",
        lambda d, lo, hi: 1.0 if d <= lo else 0.0 if d >= hi else 1 - (d - lo) / (hi - lo), C((0.0, 5.0, 50.0), (5.0, 5.0, 50.0), (27.5, 5.0, 50.0), (50.0, 5.0, 50.0), (80.0, 5.0, 50.0), (10.0, 0.0, 40.0)),
        python="def distance_attenuation(dist, min_d, max_d):\n    if dist <= min_d:\n        return 1.0\n    if dist >= max_d:\n        return 0.0\n    return 1 - (dist - min_d) / (max_d - min_d)\n",
        typescript="function distanceAttenuation(dist: number, minD: number, maxD: number): number {\n    if (dist <= minD) return 1;\n    if (dist >= maxD) return 0;\n    return 1 - (dist - minD) / (maxD - minD);\n}\n",
        csharp="public static double DistanceAttenuation(double dist, double min_d, double max_d) {\n    if (dist <= min_d) return 1;\n    if (dist >= max_d) return 0;\n    return 1 - (dist - min_d) / (max_d - min_d);\n}\n",
        gdscript="static func distance_attenuation(dist: float, min_d: float, max_d: float) -> float:\n\tif dist <= min_d:\n\t\treturn 1.0\n\tif dist >= max_d:\n\t\treturn 0.0\n\treturn 1.0 - (dist - min_d) / (max_d - min_d)\n",
        lua="function distance_attenuation(dist, min_d, max_d)\n    if dist <= min_d then return 1 end\n    if dist >= max_d then return 0 end\n    return 1 - (dist - min_d) / (max_d - min_d)\nend\n")

# ---------------------------------------------------------------- physics / game feel
def _knock(ax, ay, px, py, f):
    dx, dy = px - ax, py - ay
    m = math.hypot(dx, dy)
    return [dx / m * f, dy / m * f]


problem("knockback", [("ax", "float"), ("ay", "float"), ("px", "float"), ("py", "float"), ("force", "float")], "float[]", "physics",
        "Knockback vector [vx, vy] applied to a player at (px, py) hit by an attacker at (ax, ay): the unit direction from attacker to player times `force` (the points differ).",
        _knock, C((0.0, 0.0, 3.0, 4.0, 10.0), (1.0, 1.0, 1.0, 5.0, 2.0), (5.0, 0.0, 0.0, 0.0, 8.0), (-2.0, -2.0, 2.0, 2.0, 1.0)),
        python="import math\n\ndef knockback(ax, ay, px, py, force):\n    dx, dy = px - ax, py - ay\n    m = math.hypot(dx, dy)\n    return [dx / m * force, dy / m * force]\n",
        typescript="function knockback(ax: number, ay: number, px: number, py: number, force: number): number[] {\n    const dx = px - ax, dy = py - ay;\n    const m = Math.hypot(dx, dy);\n    return [dx / m * force, dy / m * force];\n}\n",
        csharp="public static double[] Knockback(double ax, double ay, double px, double py, double force) {\n    double dx = px - ax, dy = py - ay;\n    double m = Math.Sqrt(dx * dx + dy * dy);\n    return new double[] { dx / m * force, dy / m * force };\n}\n",
        gdscript="static func knockback(ax: float, ay: float, px: float, py: float, force: float) -> Array:\n\tvar d := Vector2(px - ax, py - ay).normalized() * force\n\treturn [d.x, d.y]\n",
        lua="function knockback(ax, ay, px, py, force)\n    local dx, dy = px - ax, py - ay\n    local m = math.sqrt(dx * dx + dy * dy)\n    return { dx / m * force, dy / m * force }\nend\n")

problem("shake_amplitude", [("trauma", "float"), ("max_offset", "float")], "float", "physics",
        "Camera-shake amplitude from a trauma value in [0, 1]: max_offset * trauma^2 (trauma clamped to [0, 1] first).",
        lambda t, m: m * max(0.0, min(1.0, t)) ** 2, C((0.0, 10.0), (0.5, 10.0), (1.0, 10.0), (1.5, 10.0), (0.3, 20.0), (-0.2, 5.0)),
        python="def shake_amplitude(trauma, max_offset):\n    t = max(0.0, min(1.0, trauma))\n    return max_offset * t * t\n",
        typescript="function shakeAmplitude(trauma: number, maxOffset: number): number {\n    const t = Math.max(0, Math.min(1, trauma));\n    return maxOffset * t * t;\n}\n",
        csharp="public static double ShakeAmplitude(double trauma, double max_offset) {\n    double t = Math.Max(0, Math.Min(1, trauma));\n    return max_offset * t * t;\n}\n",
        gdscript="static func shake_amplitude(trauma: float, max_offset: float) -> float:\n\tvar t := clampf(trauma, 0.0, 1.0)\n\treturn max_offset * t * t\n",
        lua="function shake_amplitude(trauma, max_offset)\n    local t = math.max(0, math.min(1, trauma))\n    return max_offset * t * t\nend\n")

problem("hitstop_frames", [("ms", "float"), ("fps", "int")], "int", "physics", "Whole frames a hit-stop of `ms` milliseconds lasts at `fps` frames per second (round down).",
        lambda ms, fps: int(math.floor(ms / 1000 * fps + 1e-9)), C((100.0, 60), (50.0, 60), (83.0, 60), (100.0, 30), (16.0, 60), (0.0, 60)),
        python="def hitstop_frames(ms, fps):\n    return int(ms / 1000 * fps + 1e-9)\n",
        typescript="function hitstopFrames(ms: number, fps: number): number {\n    return Math.floor(ms / 1000 * fps + 1e-9);\n}\n",
        csharp="public static int HitstopFrames(double ms, int fps) {\n    return (int)Math.Floor(ms / 1000 * fps + 1e-9);\n}\n",
        gdscript="static func hitstop_frames(ms: float, fps: int) -> int:\n\treturn int(floor(ms / 1000.0 * fps + 1e-9))\n",
        lua="function hitstop_frames(ms, fps)\n    return math.floor(ms / 1000 * fps + 1e-9)\nend\n")

problem("apply_gravity", [("vy", "float"), ("gravity", "float"), ("dt", "float"), ("terminal", "float")], "float", "physics",
        "Vertical velocity after one step: vy - gravity * dt, never below -terminal (terminal velocity, positive number).",
        lambda vy, g, dt, term: max(-term, vy - g * dt), C((0.0, 9.8, 0.1, 50.0), (-49.5, 9.8, 0.1, 50.0), (10.0, 20.0, 0.5, 30.0), (-30.0, 10.0, 1.0, 30.0), (5.0, 0.0, 1.0, 10.0)),
        python="def apply_gravity(vy, gravity, dt, terminal):\n    return max(-terminal, vy - gravity * dt)\n",
        typescript="function applyGravity(vy: number, gravity: number, dt: number, terminal: number): number {\n    return Math.max(-terminal, vy - gravity * dt);\n}\n",
        csharp="public static double ApplyGravity(double vy, double gravity, double dt, double terminal) {\n    return Math.Max(-terminal, vy - gravity * dt);\n}\n",
        gdscript="static func apply_gravity(vy: float, gravity: float, dt: float, terminal: float) -> float:\n\treturn maxf(-terminal, vy - gravity * dt)\n",
        lua="function apply_gravity(vy, gravity, dt, terminal)\n    return math.max(-terminal, vy - gravity * dt)\nend\n")

# ---------------------------------------------------------------- procedural generation
problem("lcg_next", [("seed", "int")], "int", "procgen", "The next value of the MINSTD generator: (seed * 48271) mod 2147483647 (use 64-bit arithmetic).",
        lambda s: (s * 48271) % 2147483647, C((1,), (42,), (12345,), (2147483646,), (99999,), (7,)),
        python="def lcg_next(seed):\n    return (seed * 48271) % 2147483647\n",
        typescript="function lcgNext(seed: number): number {\n    return (seed * 48271) % 2147483647;\n}\n",
        csharp="public static int LcgNext(int seed) {\n    return (int)(((long)seed * 48271L) % 2147483647L);\n}\n",
        gdscript="static func lcg_next(seed: int) -> int:\n\treturn (seed * 48271) % 2147483647\n",
        lua="function lcg_next(seed)\n    return (seed * 48271) % 2147483647\nend\n")


def _neighbours(cells, w, h, x, y):
    n = 0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            nx, ny = x + dx, y + dy
            if nx < 0 or ny < 0 or nx >= w or ny >= h or cells[ny * w + nx] == 1:
                n += 1
    return n


_GRID = [1, 0, 0, 1,
         0, 0, 1, 0,
         1, 0, 0, 0]
problem("wall_neighbours", [("cells", "int[]"), ("w", "int"), ("h", "int"), ("x", "int"), ("y", "int")], "int", "procgen",
        "For a cellular-automaton cave stored row-major (1 = wall, 0 = floor) count the wall cells among the 8 neighbours of (x, y); cells outside the grid count as walls.",
        _neighbours, C((_GRID, 4, 3, 1, 1), (_GRID, 4, 3, 0, 0), (_GRID, 4, 3, 3, 2), (_GRID, 4, 3, 2, 1), (_GRID, 4, 3, 1, 2)),
        python="def wall_neighbours(cells, w, h, x, y):\n    n = 0\n    for dy in (-1, 0, 1):\n        for dx in (-1, 0, 1):\n            if dx == 0 and dy == 0:\n                continue\n            nx, ny = x + dx, y + dy\n            if nx < 0 or ny < 0 or nx >= w or ny >= h or cells[ny * w + nx] == 1:\n                n += 1\n    return n\n",
        typescript="function wallNeighbours(cells: number[], w: number, h: number, x: number, y: number): number {\n    let n = 0;\n    for (let dy = -1; dy <= 1; dy++) {\n        for (let dx = -1; dx <= 1; dx++) {\n            if (dx === 0 && dy === 0) continue;\n            const nx = x + dx, ny = y + dy;\n            if (nx < 0 || ny < 0 || nx >= w || ny >= h || cells[ny * w + nx] === 1) n++;\n        }\n    }\n    return n;\n}\n",
        csharp="public static int WallNeighbours(int[] cells, int w, int h, int x, int y) {\n    int n = 0;\n    for (int dy = -1; dy <= 1; dy++) {\n        for (int dx = -1; dx <= 1; dx++) {\n            if (dx == 0 && dy == 0) continue;\n            int nx = x + dx, ny = y + dy;\n            if (nx < 0 || ny < 0 || nx >= w || ny >= h || cells[ny * w + nx] == 1) n++;\n        }\n    }\n    return n;\n}\n",
        gdscript="static func wall_neighbours(cells: Array, w: int, h: int, x: int, y: int) -> int:\n\tvar n := 0\n\tfor dy in range(-1, 2):\n\t\tfor dx in range(-1, 2):\n\t\t\tif dx == 0 and dy == 0:\n\t\t\t\tcontinue\n\t\t\tvar nx := x + dx\n\t\t\tvar ny := y + dy\n\t\t\tif nx < 0 or ny < 0 or nx >= w or ny >= h or cells[ny * w + nx] == 1:\n\t\t\t\tn += 1\n\treturn n\n",
        lua="function wall_neighbours(cells, w, h, x, y)\n    local n = 0\n    for dy = -1, 1 do\n        for dx = -1, 1 do\n            if not (dx == 0 and dy == 0) then\n                local nx, ny = x + dx, y + dy\n                if nx < 0 or ny < 0 or nx >= w or ny >= h or cells[ny * w + nx + 1] == 1 then n = n + 1 end\n            end\n        end\n    end\n    return n\nend\n")

# ---------------------------------------------------------------- ui
def _anchor(pw, ph, ax, ay, ox, oy, w, h, px, py):
    return [ax * pw + ox - px * w, ay * ph + oy - py * h]


problem("anchor_position", [("parent_w", "float"), ("parent_h", "float"), ("anchor_x", "float"), ("anchor_y", "float"), ("offset_x", "float"), ("offset_y", "float"),
                            ("w", "float"), ("h", "float"), ("pivot_x", "float"), ("pivot_y", "float")], "float[]", "ui",
        "Top-left corner [x, y] of a UI element: anchor (0..1 of the parent size) plus pixel offset, minus pivot (0..1 of the element size) times the element size "
        "(as Roblox AnchorPoint / Unity RectTransform pivot).",
        _anchor, C((800.0, 600.0, 0.5, 0.5, 0.0, 0.0, 200.0, 100.0, 0.5, 0.5), (800.0, 600.0, 1.0, 0.0, -10.0, 10.0, 100.0, 40.0, 1.0, 0.0), (1920.0, 1080.0, 0.0, 1.0, 20.0, -20.0, 300.0, 50.0, 0.0, 1.0), (400.0, 300.0, 0.5, 1.0, 0.0, -8.0, 120.0, 30.0, 0.5, 1.0)),
        python="def anchor_position(parent_w, parent_h, anchor_x, anchor_y, offset_x, offset_y, w, h, pivot_x, pivot_y):\n    return [anchor_x * parent_w + offset_x - pivot_x * w, anchor_y * parent_h + offset_y - pivot_y * h]\n",
        typescript="function anchorPosition(parentW: number, parentH: number, anchorX: number, anchorY: number, offsetX: number, offsetY: number, w: number, h: number, pivotX: number, pivotY: number): number[] {\n    return [anchorX * parentW + offsetX - pivotX * w, anchorY * parentH + offsetY - pivotY * h];\n}\n",
        csharp="public static double[] AnchorPosition(double parent_w, double parent_h, double anchor_x, double anchor_y, double offset_x, double offset_y, double w, double h, double pivot_x, double pivot_y) {\n    return new double[] { anchor_x * parent_w + offset_x - pivot_x * w, anchor_y * parent_h + offset_y - pivot_y * h };\n}\n",
        gdscript="static func anchor_position(parent_w: float, parent_h: float, anchor_x: float, anchor_y: float, offset_x: float, offset_y: float, w: float, h: float, pivot_x: float, pivot_y: float) -> Array:\n\treturn [anchor_x * parent_w + offset_x - pivot_x * w, anchor_y * parent_h + offset_y - pivot_y * h]\n",
        lua="function anchor_position(parent_w, parent_h, anchor_x, anchor_y, offset_x, offset_y, w, h, pivot_x, pivot_y)\n    return { anchor_x * parent_w + offset_x - pivot_x * w, anchor_y * parent_h + offset_y - pivot_y * h }\nend\n")

problem("fit_scale", [("content_w", "float"), ("content_h", "float"), ("box_w", "float"), ("box_h", "float")], "float", "ui",
        "Uniform scale that fits content inside a box while keeping its aspect ratio: min(box_w / content_w, box_h / content_h).",
        lambda cw, ch, bw, bh: min(bw / cw, bh / ch), C((1920.0, 1080.0, 960.0, 540.0), (100.0, 200.0, 300.0, 300.0), (400.0, 300.0, 200.0, 300.0), (10.0, 10.0, 25.0, 50.0)),
        python="def fit_scale(content_w, content_h, box_w, box_h):\n    return min(box_w / content_w, box_h / content_h)\n",
        typescript="function fitScale(contentW: number, contentH: number, boxW: number, boxH: number): number {\n    return Math.min(boxW / contentW, boxH / contentH);\n}\n",
        csharp="public static double FitScale(double content_w, double content_h, double box_w, double box_h) {\n    return Math.Min(box_w / content_w, box_h / content_h);\n}\n",
        gdscript="static func fit_scale(content_w: float, content_h: float, box_w: float, box_h: float) -> float:\n\treturn minf(box_w / content_w, box_h / content_h)\n",
        lua="function fit_scale(content_w, content_h, box_w, box_h)\n    return math.min(box_w / content_w, box_h / content_h)\nend\n")

problem("page_count", [("items", "int"), ("per_page", "int")], "int", "ui", "Pages needed to show `items` entries with `per_page` per page (0 items -> 0 pages).",
        lambda n, k: -(-n // k), C((0, 8), (1, 8), (8, 8), (9, 8), (57, 10), (100, 7)),
        python="def page_count(items, per_page):\n    return (items + per_page - 1) // per_page\n",
        typescript="function pageCount(items: number, perPage: number): number {\n    return Math.ceil(items / perPage);\n}\n",
        csharp="public static int PageCount(int items, int per_page) {\n    return (items + per_page - 1) / per_page;\n}\n",
        gdscript="static func page_count(items: int, per_page: int) -> int:\n\treturn (items + per_page - 1) / per_page\n",
        lua="function page_count(items, per_page)\n    return (items + per_page - 1) // per_page\nend\n")

# ---------------------------------------------------------------- pathfinding / ai
def _bfs(w, h, walls, sx, sy, gx, gy):
    from collections import deque
    blocked = set(walls)
    dist = {(sx, sy): 0}
    q = deque([(sx, sy)])
    while q:
        x, y = q.popleft()
        if (x, y) == (gx, gy):
            return dist[(x, y)]
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and ny * w + nx not in blocked and (nx, ny) not in dist:
                dist[(nx, ny)] = dist[(x, y)] + 1
                q.append((nx, ny))
    return -1


problem("grid_bfs", [("w", "int"), ("h", "int"), ("walls", "int[]"), ("sx", "int"), ("sy", "int"), ("gx", "int"), ("gy", "int")], "int", "pathfinding",
        "Shortest path length in 4-directional moves on a w x h grid from (sx, sy) to (gx, gy); `walls` holds blocked cell indices (y * w + x). -1 when unreachable.",
        _bfs, C((5, 4, [1, 6, 11], 0, 0, 4, 0), (5, 4, [1, 6, 11, 16], 0, 0, 4, 3), (3, 3, [], 0, 0, 2, 2), (3, 3, [1, 4, 7], 0, 0, 2, 0), (4, 1, [], 0, 0, 3, 0), (2, 2, [], 1, 1, 1, 1)),
        python="from collections import deque\n\ndef grid_bfs(w, h, walls, sx, sy, gx, gy):\n    blocked = set(walls)\n    dist = {(sx, sy): 0}\n    q = deque([(sx, sy)])\n    while q:\n        x, y = q.popleft()\n        if (x, y) == (gx, gy):\n            return dist[(x, y)]\n        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):\n            if 0 <= nx < w and 0 <= ny < h and ny * w + nx not in blocked and (nx, ny) not in dist:\n                dist[(nx, ny)] = dist[(x, y)] + 1\n                q.append((nx, ny))\n    return -1\n",
        typescript="function gridBfs(w: number, h: number, walls: number[], sx: number, sy: number, gx: number, gy: number): number {\n    const blocked = new Set(walls);\n    const dist = new Map<number, number>();\n    const start = sy * w + sx;\n    dist.set(start, 0);\n    const queue = [start];\n    while (queue.length > 0) {\n        const cur = queue.shift()!;\n        const x = cur % w, y = Math.floor(cur / w);\n        if (x === gx && y === gy) return dist.get(cur)!;\n        for (const [nx, ny] of [[x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]]) {\n            const idx = ny * w + nx;\n            if (nx >= 0 && nx < w && ny >= 0 && ny < h && !blocked.has(idx) && !dist.has(idx)) {\n                dist.set(idx, dist.get(cur)! + 1);\n                queue.push(idx);\n            }\n        }\n    }\n    return -1;\n}\n",
        csharp="public static int GridBfs(int w, int h, int[] walls, int sx, int sy, int gx, int gy) {\n    var blocked = new HashSet<int>(walls);\n    var dist = new Dictionary<int, int>();\n    var queue = new Queue<int>();\n    int start = sy * w + sx;\n    dist[start] = 0;\n    queue.Enqueue(start);\n    int[] dx = { 1, -1, 0, 0 }, dy = { 0, 0, 1, -1 };\n    while (queue.Count > 0) {\n        int cur = queue.Dequeue();\n        int x = cur % w, y = cur / w;\n        if (x == gx && y == gy) return dist[cur];\n        for (int k = 0; k < 4; k++) {\n            int nx = x + dx[k], ny = y + dy[k], idx = ny * w + nx;\n            if (nx >= 0 && nx < w && ny >= 0 && ny < h && !blocked.Contains(idx) && !dist.ContainsKey(idx)) {\n                dist[idx] = dist[cur] + 1;\n                queue.Enqueue(idx);\n            }\n        }\n    }\n    return -1;\n}\n",
        gdscript="static func grid_bfs(w: int, h: int, walls: Array, sx: int, sy: int, gx: int, gy: int) -> int:\n\tvar dist := {}\n\tvar start := sy * w + sx\n\tdist[start] = 0\n\tvar queue := [start]\n\twhile not queue.is_empty():\n\t\tvar cur: int = queue.pop_front()\n\t\tvar x := cur % w\n\t\tvar y := cur / w\n\t\tif x == gx and y == gy:\n\t\t\treturn dist[cur]\n\t\tfor d in [[1, 0], [-1, 0], [0, 1], [0, -1]]:\n\t\t\tvar nx: int = x + d[0]\n\t\t\tvar ny: int = y + d[1]\n\t\t\tvar idx := ny * w + nx\n\t\t\tif nx >= 0 and nx < w and ny >= 0 and ny < h and not walls.has(idx) and not dist.has(idx):\n\t\t\t\tdist[idx] = dist[cur] + 1\n\t\t\t\tqueue.append(idx)\n\treturn -1\n",
        lua="function grid_bfs(w, h, walls, sx, sy, gx, gy)\n    local blocked = {}\n    for _, i in ipairs(walls) do blocked[i] = true end\n    local start = sy * w + sx\n    local dist = { [start] = 0 }\n    local queue, head = { start }, 1\n    while head <= #queue do\n        local cur = queue[head]\n        head = head + 1\n        local x, y = cur % w, cur // w\n        if x == gx and y == gy then return dist[cur] end\n        for _, d in ipairs({ { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 } }) do\n            local nx, ny = x + d[1], y + d[2]\n            local idx = ny * w + nx\n            if nx >= 0 and nx < w and ny >= 0 and ny < h and not blocked[idx] and dist[idx] == nil then\n                dist[idx] = dist[cur] + 1\n                queue[#queue + 1] = idx\n            end\n        end\n    end\n    return -1\nend\n")


def _pick(distances, aggro):
    best, best_d = -1, aggro
    for i, d in enumerate(distances):
        if d <= best_d and (best == -1 or d < best_d):
            best, best_d = i, d
    return best


problem("pick_target", [("distances", "float[]"), ("aggro_range", "float")], "int", "ai",
        "Index of the nearest target whose distance is within `aggro_range` (inclusive), or -1 when none is; the first index wins a tie.",
        _pick, C(([12.0, 5.0, 8.0], 10.0), ([12.0, 15.0], 10.0), ([], 10.0), ([3.0, 3.0, 1.0], 5.0), ([10.0, 4.0, 4.0], 10.0), ([7.0], 7.0)),
        python="def pick_target(distances, aggro_range):\n    best, best_d = -1, aggro_range\n    for i, d in enumerate(distances):\n        if d <= best_d and (best == -1 or d < best_d):\n            best, best_d = i, d\n    return best\n",
        typescript="function pickTarget(distances: number[], aggroRange: number): number {\n    let best = -1, bestD = aggroRange;\n    for (let i = 0; i < distances.length; i++) {\n        if (distances[i] <= bestD && (best === -1 || distances[i] < bestD)) {\n            best = i;\n            bestD = distances[i];\n        }\n    }\n    return best;\n}\n",
        csharp="public static int PickTarget(double[] distances, double aggro_range) {\n    int best = -1;\n    double bestD = aggro_range;\n    for (int i = 0; i < distances.Length; i++) {\n        if (distances[i] <= bestD && (best == -1 || distances[i] < bestD)) {\n            best = i;\n            bestD = distances[i];\n        }\n    }\n    return best;\n}\n",
        gdscript="static func pick_target(distances: Array, aggro_range: float) -> int:\n\tvar best := -1\n\tvar best_d := aggro_range\n\tfor i in range(distances.size()):\n\t\tif distances[i] <= best_d and (best == -1 or distances[i] < best_d):\n\t\t\tbest = i\n\t\t\tbest_d = distances[i]\n\treturn best\n",
        lua="function pick_target(distances, aggro_range)\n    local best, best_d = -1, aggro_range\n    for i, d in ipairs(distances) do\n        if d <= best_d and (best == -1 or d < best_d) then\n            best, best_d = i - 1, d\n        end\n    end\n    return best\nend\n")

_FSM = {("idle", "see_player"): "chase", ("patrol", "see_player"): "chase", ("chase", "in_range"): "attack",
        ("chase", "lose_player"): "patrol", ("attack", "out_of_range"): "chase", ("attack", "lose_player"): "patrol", ("idle", "tick"): "patrol"}
problem("fsm_next", [("state", "str"), ("event", "str")], "str", "ai",
        "Enemy state machine: idle --see_player--> chase; patrol --see_player--> chase; chase --in_range--> attack; chase --lose_player--> patrol; "
        "attack --out_of_range--> chase; attack --lose_player--> patrol; idle --tick--> patrol. Any other (state, event) pair keeps the state.",
        lambda s, e: _FSM.get((s, e), s), C(("idle", "see_player"), ("chase", "in_range"), ("attack", "lose_player"), ("patrol", "tick"), ("idle", "tick"), ("attack", "out_of_range"), ("chase", "tick")),
        python="def fsm_next(state, event):\n    table = {(\"idle\", \"see_player\"): \"chase\", (\"patrol\", \"see_player\"): \"chase\", (\"chase\", \"in_range\"): \"attack\",\n             (\"chase\", \"lose_player\"): \"patrol\", (\"attack\", \"out_of_range\"): \"chase\", (\"attack\", \"lose_player\"): \"patrol\", (\"idle\", \"tick\"): \"patrol\"}\n    return table.get((state, event), state)\n",
        typescript="function fsmNext(state: string, event: string): string {\n    const table: { [k: string]: string } = {\n        \"idle/see_player\": \"chase\", \"patrol/see_player\": \"chase\", \"chase/in_range\": \"attack\", \"chase/lose_player\": \"patrol\",\n        \"attack/out_of_range\": \"chase\", \"attack/lose_player\": \"patrol\", \"idle/tick\": \"patrol\",\n    };\n    const next = table[state + \"/\" + event];\n    return next === undefined ? state : next;\n}\n",
        csharp="public static string FsmNext(string state, string ev) {\n    switch (state + \"/\" + ev) {\n        case \"idle/see_player\": case \"patrol/see_player\": return \"chase\";\n        case \"chase/in_range\": return \"attack\";\n        case \"chase/lose_player\": case \"attack/lose_player\": return \"patrol\";\n        case \"attack/out_of_range\": return \"chase\";\n        case \"idle/tick\": return \"patrol\";\n        default: return state;\n    }\n}\n",
        gdscript="static func fsm_next(state: String, event: String) -> String:\n\tvar table := {\"idle/see_player\": \"chase\", \"patrol/see_player\": \"chase\", \"chase/in_range\": \"attack\", \"chase/lose_player\": \"patrol\",\n\t\t\"attack/out_of_range\": \"chase\", \"attack/lose_player\": \"patrol\", \"idle/tick\": \"patrol\"}\n\treturn table.get(state + \"/\" + event, state)\n",
        lua="function fsm_next(state, event)\n    local table_ = { [\"idle/see_player\"] = \"chase\", [\"patrol/see_player\"] = \"chase\", [\"chase/in_range\"] = \"attack\", [\"chase/lose_player\"] = \"patrol\",\n        [\"attack/out_of_range\"] = \"chase\", [\"attack/lose_player\"] = \"patrol\", [\"idle/tick\"] = \"patrol\" }\n    return table_[state .. \"/\" .. event] or state\nend\n")

# ---------------------------------------------------------------- networking
problem("interp_delay_ms", [("tick_rate", "int"), ("buffer_ticks", "int")], "float", "networking",
        "Snapshot interpolation delay in milliseconds for a server at `tick_rate` Hz with a buffer of `buffer_ticks` ticks: buffer_ticks * 1000 / tick_rate.",
        lambda t, b: b * 1000 / t, C((20, 2), (60, 3), (10, 2), (64, 2), (30, 1)),
        python="def interp_delay_ms(tick_rate, buffer_ticks):\n    return buffer_ticks * 1000 / tick_rate\n",
        typescript="function interpDelayMs(tickRate: number, bufferTicks: number): number {\n    return bufferTicks * 1000 / tickRate;\n}\n",
        csharp="public static double InterpDelayMs(int tick_rate, int buffer_ticks) {\n    return buffer_ticks * 1000.0 / tick_rate;\n}\n",
        gdscript="static func interp_delay_ms(tick_rate: int, buffer_ticks: int) -> float:\n\treturn buffer_ticks * 1000.0 / tick_rate\n",
        lua="function interp_delay_ms(tick_rate, buffer_ticks)\n    return buffer_ticks * 1000 / tick_rate\nend\n")

problem("reconcile", [("server_x", "float"), ("pending_moves", "float[]")], "float", "networking",
        "Client-side reconciliation: start from the server's confirmed position and re-apply every pending (not yet acknowledged) move delta in order; return the predicted position.",
        lambda x, moves: x + sum(moves), C((10.0, [1.0, 1.0, 0.5]), (0.0, []), (-5.0, [2.0, -3.0]), (100.0, [0.25, 0.25, 0.25, 0.25])),
        python="def reconcile(server_x, pending_moves):\n    x = server_x\n    for m in pending_moves:\n        x += m\n    return x\n",
        typescript="function reconcile(serverX: number, pendingMoves: number[]): number {\n    let x = serverX;\n    for (const m of pendingMoves) x += m;\n    return x;\n}\n",
        csharp="public static double Reconcile(double server_x, double[] pending_moves) {\n    double x = server_x;\n    foreach (double m in pending_moves) x += m;\n    return x;\n}\n",
        gdscript="static func reconcile(server_x: float, pending_moves: Array) -> float:\n\tvar x := server_x\n\tfor m in pending_moves:\n\t\tx += m\n\treturn x\n",
        lua="function reconcile(server_x, pending_moves)\n    local x = server_x\n    for _, m in ipairs(pending_moves) do x = x + m end\n    return x\nend\n")


def _newer(a, b):
    return ((a > b) and (a - b <= 32768)) or ((a < b) and (b - a > 32768))


problem("sequence_newer", [("a", "int"), ("b", "int")], "bool", "networking",
        "For 16-bit packet sequence numbers (0..65535) that wrap around: true when `a` is newer than `b` (a > b and a - b <= 32768, or a < b and b - a > 32768).",
        _newer, C((5, 3), (3, 5), (0, 65535), (65535, 0), (40000, 1000), (1000, 40000), (7, 7)),
        python="def sequence_newer(a, b):\n    return (a > b and a - b <= 32768) or (a < b and b - a > 32768)\n",
        typescript="function sequenceNewer(a: number, b: number): boolean {\n    return (a > b && a - b <= 32768) || (a < b && b - a > 32768);\n}\n",
        csharp="public static bool SequenceNewer(int a, int b) {\n    return (a > b && a - b <= 32768) || (a < b && b - a > 32768);\n}\n",
        gdscript="static func sequence_newer(a: int, b: int) -> bool:\n\treturn (a > b and a - b <= 32768) or (a < b and b - a > 32768)\n",
        lua="function sequence_newer(a, b)\n    return (a > b and a - b <= 32768) or (a < b and b - a > 32768)\nend\n")
