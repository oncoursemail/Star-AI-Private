"""Exact-answer tasks (no code is run): game math, collision, networking, algorithms, big-O, audio, animation,
procedural generation, UI layout. Every task has a computed answer; the reply must end with `ANSWER: <value>`.
Generated from seeded random parameters, so the set is the same on every build."""
from __future__ import annotations

import math
import random

TAIL = ("\n\nWork it out step by step if you like, then end your reply with one line of the form "
        "`ANSWER: <value>` (numbers rounded to 3 decimals; several numbers separated by spaces).")


def fmt(*values) -> str:
    out = []
    for v in values:
        if isinstance(v, float):
            out.append(("%.3f" % v).rstrip("0").rstrip(".") if abs(v - round(v)) > 1e-9 else str(int(round(v))))
        else:
            out.append(str(v))
    return " ".join(out)


def _v(r, n=3, lo=-6, hi=6):
    return [r.randint(lo, hi) for _ in range(n)]


def _q_mul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return (w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2)


def generators() -> list[tuple[str, str, callable]]:
    """(family, topic, make(r) -> (prompt, answer_spec)) ; make is called with a seeded Random."""
    G = []

    def add(family, topic, count=12):
        def wrap(fn):
            G.append((family, topic, count, fn))
            return fn
        return wrap

    @add("game-math", "vector-dot")
    def _(r):
        a, b = _v(r), _v(r)
        return (f"Vectors a = ({a[0]}, {a[1]}, {a[2]}) and b = ({b[0]}, {b[1]}, {b[2]}). What is the dot product a . b?",
                {"value": fmt(sum(x * y for x, y in zip(a, b)))})

    @add("game-math", "vector-cross")
    def _(r):
        a, b = _v(r), _v(r)
        c = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
        return (f"Vectors a = ({a[0]}, {a[1]}, {a[2]}) and b = ({b[0]}, {b[1]}, {b[2]}). Give the cross product a x b as three numbers x y z.",
                {"value": fmt(*c), "kind": "list"})

    @add("game-math", "vector-normalize")
    def _(r):
        a = _v(r)
        while not any(a):
            a = _v(r)
        m = math.sqrt(sum(x * x for x in a))
        return (f"Normalize the vector ({a[0]}, {a[1]}, {a[2]}): give the unit vector as three numbers x y z (3 decimals).",
                {"value": fmt(*(x / m for x in a)), "kind": "list", "tolerance": 2e-3})

    @add("game-math", "vector-angle")
    def _(r):
        a, b = _v(r), _v(r)
        while not any(a) or not any(b):
            a, b = _v(r), _v(r)
        cosv = sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b)))
        return (f"What is the angle in degrees between the vectors ({a[0]}, {a[1]}, {a[2]}) and ({b[0]}, {b[1]}, {b[2]})? (3 decimals)",
                {"value": fmt(math.degrees(math.acos(max(-1.0, min(1.0, cosv))))), "tolerance": 2e-3})

    @add("game-math", "vector-reflect")
    def _(r):
        d = _v(r, 2)
        while not any(d):
            d = _v(r, 2)
        n = r.choice([(0, 1), (1, 0), (0, -1), (-1, 0)])
        k = 2 * (d[0] * n[0] + d[1] * n[1])
        return (f"A 2D velocity ({d[0]}, {d[1]}) hits a wall with unit normal ({n[0]}, {n[1]}). Reflect it (v - 2 (v . n) n). Give the reflected velocity as two numbers.",
                {"value": fmt(d[0] - k * n[0], d[1] - k * n[1]), "kind": "list"})

    @add("game-math", "quaternion-multiply")
    def _(r):
        a = tuple(r.randint(-3, 3) for _ in range(4))
        b = tuple(r.randint(-3, 3) for _ in range(4))
        q = _q_mul(a, b)
        return (f"Quaternions are written (w, x, y, z). Multiply q1 = ({a[0]}, {a[1]}, {a[2]}, {a[3]}) by q2 = ({b[0]}, {b[1]}, {b[2]}, {b[3]}) "
                f"(Hamilton product q1 * q2). Give the result as four numbers w x y z.", {"value": fmt(*q), "kind": "list"})

    @add("game-math", "quaternion-rotate")
    def _(r):
        axis = r.choice(["x", "y", "z"])
        deg = r.choice([90, 180, -90, 270])
        v = _v(r)
        rad = math.radians(deg)
        c, s = math.cos(rad), math.sin(rad)
        x, y, z = v
        if axis == "x":
            out = (x, c * y - s * z, s * y + c * z)
        elif axis == "y":
            out = (c * x + s * z, y, -s * x + c * z)
        else:
            out = (c * x - s * y, s * x + c * y, z)
        return (f"Rotate the point ({x}, {y}, {z}) by {deg} degrees about the +{axis} axis (right-handed, counter-clockwise when "
                f"looking from +{axis} toward the origin). Give the rotated point as three numbers.",
                {"value": fmt(*(round(o, 6) + 0.0 for o in out)), "kind": "list", "tolerance": 1e-3})

    @add("game-math", "lerp-value")
    def _(r):
        a, b, t = r.randint(-20, 20), r.randint(-20, 20), r.choice([0.1, 0.25, 0.4, 0.5, 0.75, 0.9])
        return (f"lerp(a, b, t) = a + (b - a) * t. What is lerp({a}, {b}, {t})?", {"value": fmt(a + (b - a) * t)})

    @add("animation", "easing-value")
    def _(r):
        t = r.choice([0.1, 0.2, 0.25, 0.3, 0.4, 0.6, 0.75, 0.8, 0.9])
        kind, fn = r.choice([("easeInQuad (t^2)", lambda t: t * t), ("easeOutQuad (1 - (1 - t)^2)", lambda t: 1 - (1 - t) ** 2),
                             ("easeInOutQuad (2t^2 for t < 0.5, else 1 - (-2t + 2)^2 / 2)", lambda t: 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2),
                             ("easeInCubic (t^3)", lambda t: t ** 3), ("smoothstep (3t^2 - 2t^3)", lambda t: 3 * t * t - 2 * t ** 3)])
        return (f"An animation uses the easing curve {kind}. What is the eased value at t = {t}? (3 decimals)", {"value": fmt(fn(t)), "tolerance": 2e-3})

    @add("animation", "frame-index")
    def _(r):
        fps, frames, t = r.choice([12, 24, 30, 60]), r.randint(4, 16), round(r.uniform(0.1, 3.0), 2)
        return (f"A sprite animation has {frames} frames and plays at {fps} frames per second, looping. Which frame index (0-based) "
                f"is shown at time t = {t} s? Use floor(t * fps) mod frame_count.", {"value": fmt(int(math.floor(t * fps + 1e-9)) % frames)})

    @add("animation", "blend-weights")
    def _(r):
        th = sorted(r.sample([0, 2, 4, 6, 8, 10], 3))
        v = round(r.uniform(th[0], th[2]), 1)
        w = [0.0, 0.0, 0.0]
        for i in range(2):
            if th[i] <= v <= th[i + 1]:
                f = (v - th[i]) / (th[i + 1] - th[i])
                w[i], w[i + 1] = 1 - f, f
                break
        return (f"A 1D blend tree (like Unity's Animator or Godot's AnimationNodeBlendSpace1D) has three clips at thresholds {th[0]}, {th[1]} and {th[2]}. "
                f"The blend parameter is {v}. Give the three clip weights (linear blend between the two nearest thresholds) as three numbers.",
                {"value": fmt(*w), "kind": "list", "tolerance": 2e-3})

    @add("animation", "spring-step")
    def _(r):
        x, v, target, k, d, dt = r.randint(-5, 5), r.randint(-3, 3), r.randint(-5, 5), r.choice([10, 20, 50]), r.choice([2, 4, 5]), 0.1
        a = -k * (x - target) - d * v
        v2 = v + a * dt
        x2 = x + v2 * dt
        return (f"A damped spring (semi-implicit Euler): a = -k (x - target) - d v; v += a dt; x += v dt. With x = {x}, v = {v}, target = {target}, "
                f"k = {k}, d = {d}, dt = {dt}: give the new x and v after one step as two numbers.", {"value": fmt(x2, v2), "kind": "list", "tolerance": 2e-3})

    @add("collision", "aabb-area")
    def _(r):
        ax, ay, aw, ah = r.randint(0, 5), r.randint(0, 5), r.randint(2, 6), r.randint(2, 6)
        bx, by, bw, bh = r.randint(0, 5), r.randint(0, 5), r.randint(2, 6), r.randint(2, 6)
        ox = max(0, min(ax + aw, bx + bw) - max(ax, bx))
        oy = max(0, min(ay + ah, by + bh) - max(ay, by))
        return (f"Rectangle A has min corner ({ax}, {ay}), width {aw}, height {ah}. Rectangle B has min corner ({bx}, {by}), width {bw}, height {bh}. "
                f"What is the area of their overlap (0 if they do not overlap)?", {"value": fmt(ox * oy)})

    @add("collision", "circle-circle")
    def _(r):
        x1, y1, r1 = r.randint(-5, 5), r.randint(-5, 5), r.randint(1, 4)
        x2, y2, r2 = r.randint(-5, 5), r.randint(-5, 5), r.randint(1, 4)
        d = math.hypot(x2 - x1, y2 - y1)
        pen = r1 + r2 - d
        return (f"Circle 1: centre ({x1}, {y1}), radius {r1}. Circle 2: centre ({x2}, {y2}), radius {r2}. Do they overlap, and by how much? "
                f"Answer with the penetration depth r1 + r2 - distance (3 decimals; a negative number means no overlap).", {"value": fmt(pen), "tolerance": 2e-3})

    @add("collision", "ray-plane")
    def _(r):
        oy, dy, py = r.randint(2, 9), -r.randint(1, 3), r.randint(0, 1)
        t = (py - oy) / dy
        return (f"A ray starts at y = {oy} and moves with direction y-component {dy} per unit t (x and z components do not matter). "
                f"At what t does it hit the horizontal plane y = {py}? (3 decimals)", {"value": fmt(t), "tolerance": 2e-3})

    @add("physics", "projectile")
    def _(r):
        v, g = r.choice([10, 15, 20, 25]), r.choice([9.81, 10.0, 196.2])
        h = v * v / (2 * g)
        return (f"A character jumps straight up with initial speed {v} m/s under gravity {g} m/s^2 (no drag). What is the maximum height gained? (3 decimals)",
                {"value": fmt(h), "tolerance": 2e-3})

    @add("physics", "knockback")
    def _(r):
        ax, ay, px, py, f = r.randint(-5, 5), r.randint(-5, 5), r.randint(-5, 5), r.randint(-5, 5), r.choice([5, 8, 10, 12])
        while (ax, ay) == (px, py):
            px += 1
        dx, dy = px - ax, py - ay
        m = math.hypot(dx, dy)
        return (f"An attacker at ({ax}, {ay}) hits a player at ({px}, {py}). Knockback = normalize(player - attacker) * {f}. Give the knockback vector as two numbers (3 decimals).",
                {"value": fmt(dx / m * f, dy / m * f), "kind": "list", "tolerance": 2e-3})

    @add("physics", "camera-shake")
    def _(r):
        trauma, decay, dt, maxoff = r.choice([0.6, 0.8, 1.0]), r.choice([0.5, 1.0, 2.0]), r.choice([0.1, 0.25, 0.5]), r.choice([10, 20])
        t2 = max(0.0, trauma - decay * dt)
        return (f"Camera shake: trauma starts at {trauma}, decays linearly by {decay} per second, and the shake offset amplitude is max_offset * trauma^2 with max_offset = {maxoff}. "
                f"After {dt} s, what is the amplitude? (3 decimals)", {"value": fmt(maxoff * t2 * t2), "tolerance": 2e-3})

    @add("physics", "hit-stop")
    def _(r):
        fps, ms = r.choice([30, 60]), r.choice([50, 83, 100, 150, 200])
        return (f"A hit-stop freezes the game for {ms} ms. At {fps} frames per second, how many whole frames does the freeze last (round down)?",
                {"value": fmt(int(ms / 1000 * fps + 1e-9))})

    @add("networking", "bandwidth")
    def _(r):
        tick, size, players = r.choice([10, 20, 30, 60]), r.choice([24, 48, 64, 128]), r.randint(2, 32)
        return (f"A server sends one snapshot per tick to every player; the tick rate is {tick} Hz and each snapshot is {size} bytes. "
                f"With {players} players, how many kilobits per second does the server send in total? (1 kilobit = 1000 bits; 3 decimals)",
                {"value": fmt(tick * size * 8 * players / 1000), "tolerance": 1e-3})

    @add("networking", "interp-delay")
    def _(r):
        tick, mult = r.choice([10, 20, 30, 64]), r.choice([2, 3])
        return (f"A client interpolates between the last two received snapshots and keeps a buffer of {mult} ticks behind the server. "
                f"The server tick rate is {tick} Hz. What is the interpolation delay in milliseconds? (3 decimals)", {"value": fmt(mult * 1000 / tick), "tolerance": 1e-3})

    @add("networking", "rtt-lead")
    def _(r):
        rtt, speed = r.choice([40, 80, 120, 200]), r.choice([8, 12, 16, 20])
        return (f"A player's round-trip time is {rtt} ms and their character moves at {speed} studs per second. With client-side prediction, "
                f"how far (in studs) is the predicted position ahead of what the server has confirmed, using one-way latency = RTT / 2? (3 decimals)",
                {"value": fmt(speed * rtt / 2 / 1000), "tolerance": 1e-3})

    @add("networking", "packet-loss")
    def _(r):
        p, n = r.choice([0.01, 0.02, 0.05, 0.1]), r.choice([2, 3, 4])
        return (f"Each packet is lost independently with probability {p}. A message is sent {n} times. What is the probability that at least one copy arrives? (3 decimals)",
                {"value": fmt(1 - p ** n), "tolerance": 2e-3})

    @add("algorithms", "big-o")
    def _(r):
        kind = r.choice([
            ("for i in range(n):\n    for j in range(n):\n        total += a[i] * a[j]", "O(n^2)"),
            ("for i in range(n):\n    total += a[i]", "O(n)"),
            ("while n > 1:\n    n = n // 2\n    steps += 1", "O(log n)"),
            ("for i in range(n):\n    for j in range(i, n):\n        for k in range(n):\n            total += 1", "O(n^3)"),
            ("a.sort()  # comparison sort\nfor x in a:\n    total += x", "O(n log n)"),
            ("return a[0] + a[-1]", "O(1)"),
            ("for i in range(n):\n    j = 1\n    while j < n:\n        j *= 2\n        total += 1", "O(n log n)"),
            ("for i in range(n):\n    for j in range(100):\n        total += a[i]", "O(n)"),
        ])
        return (f"What is the time complexity in big-O notation of this code as a function of n (the length of `a`)?\n\n```python\n{kind[0]}\n```\n\nAnswer like `O(n log n)`.",
                {"value": kind[1], "kind": "text"})

    @add("algorithms", "binary-search-steps")
    def _(r):
        n = r.choice([7, 15, 31, 63, 100, 1000, 1024, 4096])
        return (f"Binary search over a sorted array of {n} elements: in the worst case, how many elements are inspected before the search ends "
                f"(floor(log2 n) + 1)?", {"value": fmt(int(math.floor(math.log2(n))) + 1)})

    @add("algorithms", "stack-ops")
    def _(r):
        ops, stack = [], []
        for _ in range(r.randint(5, 8)):
            if stack and r.random() < 0.4:
                ops.append("pop")
                stack.pop()
            else:
                v = r.randint(1, 9)
                ops.append(f"push {v}")
                stack.append(v)
        return (f"Start with an empty stack and apply in order: {', '.join(ops)}. What is on the stack afterwards, bottom to top? "
                f"(numbers separated by spaces; answer `empty` if nothing)", {"value": fmt(*stack) if stack else "empty", "kind": "list" if stack else "text"})

    @add("algorithms", "bits")
    def _(r):
        a, b = r.randint(1, 255), r.randint(1, 255)
        op, val = r.choice([("AND", a & b), ("OR", a | b), ("XOR", a ^ b)])
        return (f"Compute {a} {op} {b} bitwise on 8-bit unsigned integers. Give the decimal result.", {"value": fmt(val)})

    @add("algorithms", "hex")
    def _(r):
        n = r.randint(16, 4095)
        return (f"Write the decimal number {n} in hexadecimal (upper-case, no prefix).", {"value": format(n, "X"), "kind": "text"})

    @add("game-design", "dps")
    def _(r):
        dmg, rpm, crit, mult = r.choice([12, 18, 25, 40]), r.choice([300, 450, 600, 900]), r.choice([0.1, 0.2, 0.25]), r.choice([1.5, 2.0])
        dps = dmg * rpm / 60 * (1 - crit + crit * mult)
        return (f"A weapon deals {dmg} damage per shot at {rpm} rounds per minute; {int(crit * 100)}% of shots crit for x{mult}. "
                f"What is the expected damage per second? (3 decimals)", {"value": fmt(dps), "tolerance": 2e-3})

    @add("game-design", "loot-expectation")
    def _(r):
        items = [(r.choice(["coin", "gem", "potion", "key"]), r.randint(1, 5), r.choice([10, 20, 50, 100])) for _ in range(3)]
        total = sum(w for _, w, _ in items)
        ev = sum(w / total * v for _, w, v in items)
        desc = "; ".join(f"{n} (weight {w}, worth {v})" for n, w, v in items)
        return (f"A loot table rolls one entry by weight: {desc}. What is the expected worth of one roll? (3 decimals)", {"value": fmt(ev), "tolerance": 2e-3})

    @add("game-design", "drop-chance")
    def _(r):
        p, n = r.choice([0.05, 0.1, 0.2, 0.25]), r.choice([3, 5, 10])
        return (f"An item drops with probability {p} per kill. What is the chance of at least one drop in {n} kills? (3 decimals)", {"value": fmt(1 - (1 - p) ** n), "tolerance": 2e-3})

    @add("audio", "db-linear")
    def _(r):
        db = r.choice([-20, -12, -6, -3, 0, 3, 6])
        return (f"Convert a gain of {db} dB to a linear amplitude factor (10^(dB/20)). (3 decimals)", {"value": fmt(10 ** (db / 20)), "tolerance": 2e-3})

    @add("audio", "semitones")
    def _(r):
        n = r.choice([-12, -7, -5, 2, 3, 5, 7, 12])
        return (f"A sound is pitched by {n} semitones. By what factor does its playback speed change (2^(n/12))? (3 decimals)", {"value": fmt(2 ** (n / 12)), "tolerance": 2e-3})

    @add("audio", "crossfade")
    def _(r):
        t = r.choice([0.1, 0.25, 0.5, 0.75, 0.9])
        return (f"An equal-power crossfade at position t = {t} uses gains cos(t * pi/2) for the outgoing track and sin(t * pi/2) for the incoming one. "
                f"Give both gains as two numbers (3 decimals).", {"value": fmt(math.cos(t * math.pi / 2), math.sin(t * math.pi / 2)), "kind": "list", "tolerance": 2e-3})

    @add("vfx", "particles-alive")
    def _(r):
        rate, life, t = r.choice([10, 25, 50, 100]), r.choice([0.5, 1.0, 2.0, 3.0]), r.choice([0.2, 0.5, 1.0, 2.5, 5.0])
        return (f"A particle emitter spawns {rate} particles per second, each living exactly {life} s. How many particles are alive at t = {t} s after it starts "
                f"(steady state once t >= lifetime)?", {"value": fmt(int(round(rate * min(t, life))))})

    @add("vfx", "pool-size")
    def _(r):
        shots, life = r.choice([5, 8, 10, 15]), r.choice([0.5, 1.5, 2.0, 3.0])
        return (f"Bullets are fired at {shots} per second and each bullet lives {life} s before it is recycled. What is the minimum object pool size so no bullet is ever missing "
                f"(ceil(rate * lifetime))?", {"value": fmt(int(math.ceil(shots * life - 1e-9)))})

    @add("procgen", "lcg")
    def _(r):
        seed, n = r.randint(1, 100), r.choice([1, 2, 3])
        x = seed
        for _ in range(n):
            x = (1103515245 * x + 12345) % 2147483648
        return (f"A linear congruential generator uses x' = (1103515245 * x + 12345) mod 2^31. Starting from seed {seed}, what is the value after {n} step(s)?",
                {"value": fmt(x)})

    @add("procgen", "grid-cells")
    def _(r):
        w, h, p = r.choice([8, 10, 16]), r.choice([8, 10, 12]), r.choice([0.3, 0.45, 0.5])
        return (f"A {w} x {h} cellular-automaton cave is seeded so that {int(p * 100)}% of cells are walls. How many wall cells is that (round to nearest)?", {"value": fmt(int(round(w * h * p)))})

    @add("pathfinding", "manhattan")
    def _(r):
        a, b = _v(r, 2, 0, 9), _v(r, 2, 0, 9)
        return (f"On a 4-connected grid, what is the Manhattan distance heuristic h between ({a[0]}, {a[1]}) and ({b[0]}, {b[1]})?", {"value": fmt(abs(a[0] - b[0]) + abs(a[1] - b[1]))})

    @add("pathfinding", "bfs-steps")
    def _(r):
        w, h = 5, 4
        walls = set()
        col = r.randint(1, 3)
        gap = r.randint(0, h - 1)
        for y in range(h):
            if y != gap:
                walls.add((col, y))
        start, goal = (0, r.randint(0, h - 1)), (w - 1, r.randint(0, h - 1))
        from collections import deque
        dist = {start: 0}
        q = deque([start])
        while q:
            x, y = q.popleft()
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in walls and (nx, ny) not in dist:
                    dist[(nx, ny)] = dist[(x, y)] + 1
                    q.append((nx, ny))
        rows = []
        for y in range(h):
            rows.append("".join("S" if (x, y) == start else "G" if (x, y) == goal else "#" if (x, y) in walls else "." for x in range(w)))
        return (f"Grid (row 0 at the top, `#` = wall, S = start, G = goal, 4-directional moves):\n\n```\n" + "\n".join(rows) +
                "\n```\n\nWhat is the length of the shortest path from S to G in moves?", {"value": fmt(dist[goal])})

    @add("ui", "anchor-position")
    def _(r):
        pw, ph = r.choice([800, 1280, 1920]), r.choice([600, 720, 1080])
        ax, ay = r.choice([0, 0.5, 1]), r.choice([0, 0.5, 1])
        ox, oy = r.randint(-50, 50), r.randint(-50, 50)
        w, h = r.choice([100, 200]), r.choice([40, 80])
        px, py = r.choice([0, 0.5, 1]), r.choice([0, 0.5, 1])
        x = ax * pw + ox - px * w
        y = ay * ph + oy - py * h
        return (f"A UI element in a {pw} x {ph} parent has anchor ({ax}, {ay}), offset ({ox}, {oy}) pixels from the anchor, size {w} x {h} and pivot ({px}, {py}) "
                f"(like Roblox AnchorPoint or Unity RectTransform pivot). What is the position of its top-left corner? Give x y.", {"value": fmt(x, y), "kind": "list"})

    @add("ui", "scroll-pages")
    def _(r):
        items, per, pad = r.randint(7, 60), r.choice([4, 6, 8, 10]), r.choice([0, 1])
        pages = math.ceil(items / per)
        return (f"An inventory grid shows {per} items per page and holds {items} items. How many pages are needed?", {"value": fmt(pages)})

    @add("languages", "integer-division")
    def _(r):
        a, b = r.randint(-20, 20), r.choice([3, 4, 5, 7])
        while a % b == 0 or a > 0:
            a = r.randint(-20, -1)
        return (f"In C, C++, C#, Java, Go and Rust, integer division truncates toward zero and `%` keeps the sign of the dividend; in Python `//` floors and `%` takes the divisor's sign. "
                f"Give {a} / {b} and {a} % {b} as computed in C (two numbers), then the Python results {a} // {b} and {a} % {b} (two numbers): four numbers total.",
                {"value": fmt(int(a / b), a - int(a / b) * b, a // b, a % b), "kind": "list"})

    @add("languages", "lua-index")
    def _(r):
        n = r.randint(3, 8)
        return (f"In Lua and Luau a table literal `{{10, 20, 30, ...}}` with {n} elements is 1-indexed. If `t` has {n} elements, what index does `t[#t]` read, and what does `t[0]` return? "
                f"Answer with the index then the word for the value (for example `5 nil`).", {"value": f"{n} nil", "kind": "text"})

    @add("languages", "float-precision")
    def _(r):
        k = r.choice([0.1, 0.2, 0.7])
        return (f"In IEEE-754 double precision, is `{k} + {k} + {k} == {round(3 * k, 1)}` true or false in JavaScript, Python, C# and Java? Answer `true` or `false`.",
                {"value": "true" if k + k + k == round(3 * k, 1) else "false", "kind": "text"})

    return G


def make_tasks(date: str) -> list[dict]:
    tasks = []
    for family, topic, count, fn in generators():
        r = random.Random(f"multi-exact-{family}-{topic}-{date}")
        seen = set()
        made = 0
        tries = 0
        while made < count and tries < count * 20:
            tries += 1
            prompt, spec = fn(r)
            if prompt in seen:
                continue
            seen.add(prompt)
            made += 1
            spec.setdefault("kind", "number")
            tasks.append({
                "id": f"multi-exact-{topic}-{made:02d}",
                "category": "multi-exact-" + family,
                "difficulty": 1,
                "goal": f"Exact answer: {topic.replace('-', ' ')}",
                "prompt": prompt + TAIL,
                "run_mode": "judge",
                "hard_fail": ["The final ANSWER line is missing or wrong"],
                "auto": {"code": False, "compile": False, "answer": spec},
                "source": "multi-school-" + date,
                "family": family,
                "topic": topic,
                "required_evidence": ["answer.md", "check-results.json"],
                "pass_conditions": ["the final ANSWER line matches the computed value"],
                "_reference": "ANSWER: " + str(spec["value"]),
                "_trivial": "ANSWER: 0",
            })
    return tasks
