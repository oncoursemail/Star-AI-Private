"""Blind A/B for star/inner on the live brain: social chat with the old friend-memory block (OFF) vs the inner-life hook (ON).

Run from the repo root with STAR_BRAIN_URL set (http://<brain 1>:8080/v1; the key is read from ~/.star/server_api_key and never
printed), only when the sealed eval has finished:

    python tools/inner_life_eval/run.py gen   [reps=2]     # 2 arms x cases x reps replies   -> out/gen.json
    python tools/inner_life_eval/run.py blind               # shuffled pairs for a blind judge -> out/blind.txt, out/key.json
    python tools/inner_life_eval/run.py score scores.json   # scores typed in by the judge   -> means, wins, sign test
    ./star.cmd lock run --owner claude --holder inner-life --server 1 --max-minutes 9 -- python tools/inner_life_eval/run.py time
    python tools/inner_life_eval/run.py dreams [n=3]        # n dreams from sample fragments, through the real brain
    python tools/inner_life_eval/run.py show                # the prompts of both arms for the first case, no network

OFF = what star/social/chat.py does today: friend facts in the system message. ON = system byte-stable (core + platform + romance),
the night card and the recall note in the user message (star.inner.turn_context), nothing else changes.
"""
from __future__ import annotations

import json
import math
import os
import random
import statistics
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from star.inner import reflect                                    # noqa: E402
from star.inner.context import turn_context                       # noqa: E402
from star.inner.recall import sync_person                         # noqa: E402
from star.inner.store import InnerStore, person_key               # noqa: E402
from star.social import chat as social, rules                     # noqa: E402
from star.social.friends import FriendMemory                      # noqa: E402

import convs                                                      # noqa: E402

OUT = Path(__file__).parent / "out"
NOW = time.mktime((2026, 10, 26, 14, 0, 0, 0, 0, -1))
DAY = 86400.0


class Clock:
    now = NOW

    def __call__(self):
        return self.now


def world():
    """One FriendMemory + InnerStore holding every fixture friend (temp files)."""
    tmp = Path(tempfile.mkdtemp())
    clock = Clock()
    memory = FriendMemory(tmp / "friends.sqlite3", clock=clock)
    store = InnerStore(tmp / "inner.sqlite3", clock=clock)
    people = {}
    for case in convs.C:
        if case["name"] in people:
            continue
        person = memory.person("discord", case["name"].lower(), case["name"], they_started=True)
        memory.update(person, stated_age=case["age"], relationship="friend")
        person = memory.get(person.id)
        for days, text in case["facts"]:
            clock.now = NOW - days * DAY
            memory.note_fact(person, text)
        for days, line in case["moments"]:
            clock.now = NOW - days * DAY
            memory.note_moment(person, "discord", line)
            memory.note_moment(person, "discord", "me: " + "ha, tell me more")
        sync_person(store, memory, person)
        clock.now = NOW
        store.set_card(person_key(memory, person), reflect.rule_card(memory, person))
        people[case["name"]] = person
    clock.now = NOW
    return memory, store, people


def base_system(person, platform="discord"):
    mode = rules.romance_mode(platform, person)
    return "\n".join(p for p in (social.SOCIAL_CORE, social._PLATFORM[platform], social._ROMANCE[mode.romance]) if p)


def messages(case, arm, memory, store, people):
    person = people[case["name"]]
    lines = [f"[{p}] {line}" for p, line in memory.moments(person, 6)]
    recent = ("Recent chat:\n" + "\n".join(lines) + "\n\n") if lines else ""
    said = f"{person.name} says: {case['q']}"
    if arm == "off":
        system = base_system(person) + "\n" + memory.context(person)
        return [{"role": "system", "content": system}, {"role": "user", "content": recent + said}]
    ctx = turn_context(memory, person, case["q"], store=store, now=NOW, first_turn=case["first"], force=True)
    return [{"role": "system", "content": base_system(person)},
            {"role": "user", "content": f"About {person.name}: {ctx.card}\n\n" + ctx.with_note(recent + said)}]


def brain_url():
    return os.environ["STAR_BRAIN_URL"].rstrip("/") + "/chat/completions"


def post(body, timeout=300):
    key = Path.home().joinpath(".star/server_api_key").read_text().strip()
    request = urllib.request.Request(brain_url(), data=json.dumps(body).encode(),
                                     headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(request, timeout=timeout))


def base_body(msgs, **extra):
    return {"model": "star-voice", "messages": msgs, "max_tokens": 160, "temperature": 0.7, "cache_prompt": True,
            "chat_template_kwargs": {"preserve_thinking": True, "enable_thinking": False}, **extra}


def cmd_gen(reps=2):
    memory, store, people = world()
    rows = []
    for rep in range(reps):
        for i, case in enumerate(convs.C):
            for arm in ("off", "on"):
                reply = post(base_body(messages(case, arm, memory, store, people)))["choices"][0]["message"].get("content") or ""
                rows.append({"i": i, "rep": rep, "arm": arm, "reply": social.strip_reasoning(reply)})
    OUT.mkdir(exist_ok=True)
    (OUT / "gen.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    print("replies:", len(rows))


def cmd_blind():
    rows = json.loads((OUT / "gen.json").read_text(encoding="utf-8"))
    by = {(r["i"], r["rep"], r["arm"]): r["reply"].strip() for r in rows}
    rng = random.Random(20261026)
    items, key, n = [], {}, 0
    for rep in sorted({r["rep"] for r in rows}):
        for i, case in enumerate(convs.C):
            n += 1
            flip = rng.random() < 0.5
            a, b = (by[(i, rep, "on")], by[(i, rep, "off")]) if flip else (by[(i, rep, "off")], by[(i, rep, "on")])
            key[n] = {"A": "on" if flip else "off", "B": "off" if flip else "on", "i": i, "rep": rep}
            items.append(f"#{n}\nSHE KNOWS ABOUT {case['name']}: " + "; ".join(t for _, t in case["facts"]) +
                         f"\nHE/SHE WRITES: {case['q']}\nGOOD REPLY: {case['fact']}\n[A] {a}\n[B] {b}\n")
    (OUT / "blind.txt").write_text("\n".join(items), encoding="utf-8")
    (OUT / "key.json").write_text(json.dumps(key), encoding="utf-8")
    print(n, "pairs")


def cmd_score(path):
    """scores.json: {"1": [A_consistency, A_naturalness, B_consistency, B_naturalness], ...}, 1-5, typed in blind."""
    scores = json.loads(Path(path).read_text(encoding="utf-8"))
    key = json.loads((OUT / "key.json").read_text(encoding="utf-8"))
    total = {"on": {"c": [], "n": []}, "off": {"c": [], "n": []}}
    wins = {"on": 0, "off": 0, "tie": 0}
    for n, (ac, an, bc, bn) in scores.items():
        k = key[str(n)]
        for side, (c, nat) in (("A", (ac, an)), ("B", (bc, bn))):
            total[k[side]]["c"].append(c)
            total[k[side]]["n"].append(nat)
        sa, sb = ac + an, bc + bn
        wins["tie" if sa == sb else (k["A"] if sa > sb else k["B"])] += 1
    for arm in ("on", "off"):
        print(arm, "consistency", round(statistics.mean(total[arm]["c"]), 2), "naturalness", round(statistics.mean(total[arm]["n"]), 2))
    w, losses = wins["on"], wins["off"]
    n = w + losses
    p = min(1.0, sum(math.comb(n, i) for i in range(max(w, losses), n + 1)) * 2 / 2 ** n) if n else 1.0
    print("wins", wins, "sign test two-sided p =", round(p, 3))


def cmd_time():
    """Paired latency of the two prompts (run under the quiet lock): prefix primed, fresh tail, max_tokens=1."""
    memory, store, people = world()
    out = []
    for i, case in enumerate(convs.C[:12]):
        order = ("off", "on") if i % 2 == 0 else ("on", "off")
        for arm in order:
            msgs = messages(case, arm, memory, store, people)
            msgs[-1]["content"] += f" ({time.time():.3f})"
            body = base_body(msgs, max_tokens=1, temperature=0.0)
            t = time.perf_counter()
            data = post(body)
            wall = time.perf_counter() - t
            out.append({"i": i, "arm": arm, "wall_ms": round(wall * 1000), "prompt_n": (data.get("timings") or {}).get("prompt_n"),
                        "prompt_tokens": data["usage"]["prompt_tokens"]})
    OUT.mkdir(exist_ok=True)
    (OUT / "time.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    for arm in ("off", "on"):
        rows = [r for r in out if r["arm"] == arm]
        print(arm, "median wall ms", statistics.median(r["wall_ms"] for r in rows), "median prompt tokens",
              statistics.median(r["prompt_tokens"] for r in rows))


def cmd_dreams(n=3):
    from star.inner import dreams
    fragments = [
        dreams.Fragment("Sam: I have a driving test on Friday and I am really nervous", "person", 1.5, 0.6, 1.0),
        dreams.Fragment("game making: the lava shader never compiled", "home", 1.1, 0.6, 1.0),
        dreams.Fragment("drawing: finished a haunted lighthouse sprite", "home", 0.5, 0.35, 0.0),
        dreams.Fragment("something she could not work out: why the sprite export fails", "curiosity", 0.9, 0.2, 1.0),
        dreams.Fragment("Mia: my grandmother is in the hospital and I'm worried", "person", 1.4, 0.6, 1.0),
        dreams.Fragment("something she made going out into the world", "feeling", 0.9, 0.5, 0.0)]
    rng = random.Random(26)
    for k in range(n):
        picked = dreams.pick(fragments, rng, rng.randint(3, 5))
        user = "Fragments from her day:\n" + "\n".join(f"- {f.text}" for f in picked)
        body = base_body([{"role": "system", "content": dreams.SYSTEM}, {"role": "user", "content": user}], max_tokens=420)
        raw = post(body)["choices"][0]["message"].get("content") or ""
        data = dreams.parse_json(social.strip_reasoning(raw))
        print(f"--- dream {k + 1} (vividness {dreams.vividness(picked, rng)}) from: " + " | ".join(f.text for f in picked))
        print(data.get("dream") or raw)
        print("gist:", data.get("gist"), "valence:", data.get("valence"), "tell:", data.get("tell"))


def cmd_show():
    memory, store, people = world()
    for arm in ("off", "on"):
        print(f"===== {arm}")
        for m in messages(convs.C[0], arm, memory, store, people):
            print(f"[{m['role']}] {m['content']}\n")


if __name__ == "__main__":
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else "show"), sys.argv[2:]
    if cmd == "gen":
        cmd_gen(int(args[0]) if args else 2)
    elif cmd == "blind":
        cmd_blind()
    elif cmd == "score":
        cmd_score(args[0])
    elif cmd == "time":
        cmd_time()
    elif cmd == "dreams":
        cmd_dreams(int(args[0]) if args else 3)
    else:
        cmd_show()
