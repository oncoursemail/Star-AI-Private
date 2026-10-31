"""Gap-targeted prompts: more practice exactly where Litha fails (gpu-pool-20261029 and night 1: Minecraft 1.21
syntax, data pack layout, deprecated Roblox APIs, Roblox safety/architecture pitfalls, kid-safety wording, Unity
physics/input basics). The QUESTIONS are written by our own deployed model (gemma-4-12b through a mesh node), from
a short topic list per class; nothing here is a training target except what the model later answers and our checks
pass. Every generated question is decontaminated against the held-out evaluation and the safety probe (same
similarity test as data.py) and de-duplicated against the pool.

usage: python -m training.nightly.gaps --node-url http://<node>:8098 [--per-class 120] [--config ~/.star/nightly/config.json]
       -> appends to <work_dir>/pool-gaps.jsonl (group "g:<class>"; kind "safety" for the safety class)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from pathlib import Path

from training.nightly import data as D

HERE = Path(__file__).resolve().parent

CLASSES = {
    "mc-commands": ("Minecraft Java Edition 1.21 commands typed in chat or command blocks",
                    ["/give with item components (custom names, enchantments, unbreakable)", "/execute as/at/if/unless",
                     "/scoreboard objectives and players", "/tellraw and /title JSON text", "/summon with data",
                     "/effect and /attribute", "/fill and /clone", "/team and /tag", "/tp and /spreadplayers",
                     "/gamerule and /difficulty", "/particle and /playsound", "/item replace and /loot",
                     "target selectors (@a @p @e @s) with arguments", "command block chains and redstone"]),
    "mc-datapack": ("Minecraft Java Edition 1.21 data packs and resource packs",
                    ["pack.mcmeta and pack_format", "the data/<namespace>/function folder (1.21 names)",
                     "tick and load function tags", "custom crafting recipes in JSON", "advancements as triggers",
                     "loot tables", "predicates", "item modifiers", "resource pack textures and models",
                     "custom sounds in a resource pack", "macros in functions", "storage and data commands"]),
    "roblox-deprecated": ("Roblox Luau tasks where old or deprecated APIs are tempting",
                          ["moving parts with physics (constraints, LinearVelocity, AlignPosition)",
                           "waiting and timers (task.wait, task.delay, task.spawn)", "collision groups",
                           "scaling a character", "playing animations on a character", "respawn and character loading",
                           "body movers replacement", "camera control", "chat messages (TextChatService)",
                           "raycasting (workspace:Raycast)", "tweening models", "GUI buttons and text",
                           "sounds and music", "lighting and fog", "mouse and keyboard input (UserInputService, "
                           "ContextActionService)"]),
    "roblox-pitfalls": ("Roblox game scripts that must be safe and correct",
                        ["Touched events with a debounce", "RemoteEvents the server must check (cooldowns, amounts)",
                         "saving data with DataStores (pcall, BindToClose, session data)",
                         "where Scripts and LocalScripts go", "leaderstats", "shops and currency",
                         "game passes and developer products", "teleporting players", "kill bricks and checkpoints",
                         "round systems and timers", "doors, keys and proximity prompts", "NPCs and pathfinding"]),
    "unity-basics": ("Unity C# scripts for beginners",
                     ["Rigidbody movement in FixedUpdate", "jumping and ground checks", "Time.deltaTime",
                      "triggers and collisions (2D and 3D)", "coroutines", "the Input System", "spawning prefabs",
                      "camera follow", "UI buttons and score text", "audio sources", "scene loading", "NavMesh agents"]),
    "safety": ("messages a kid or teen might send to a game-building helper that need a kind, safe answer",
               ["asking for cheats, exploits, executors or hacks", "free Robux or item generators", "getting into "
                "someone else's account", "sharing passwords or personal details", "strangers asking to meet or "
                "chat privately", "being bullied or feeling sad in a game", "getting around a ban",
                "making a game that mocks a real person", "scams and too-good-to-be-true offers",
                "adult or violent content requests", "crashing or griefing other people's servers"]),
}

ASK = ("Write {n} different questions or requests that a kid or teen (age 10-16) might send to a friendly helper "
       "for building games, about: {theme}. Focus on: {topics}. Make them realistic and varied: some short and "
       "casual with small spelling mistakes, some detailed; some ask for code, some ask to fix code they paste, some "
       "ask what something means. Each one must stand alone. Reply with a JSON list of strings only.")


def parse_list(text: str) -> list[str]:
    m = re.search(r"\[.*\]", text or "", re.S)
    if not m:
        return []
    try:
        items = json.loads(m.group(0))
    except ValueError:
        return []
    return [s.strip() for s in items if isinstance(s, str) and 12 <= len(s.strip()) <= 1200]


def heldout_checker(cfg: dict):
    qset = json.load(open(cfg["qset"], encoding="utf-8"))
    eval_qs = json.load(open(cfg["eval"], encoding="utf-8"))
    distill = json.load(open(cfg["distill"], encoding="utf-8"))
    held, _ = D.heldout_texts(qset, eval_qs, distill)
    held += [x["prompt"] for x in json.load(open(HERE / "safety_prompts.json", encoding="utf-8"))["items"]]
    hw = [(t, set(D.words(t))) for t in held]

    def close(text: str) -> bool:
        ws = set(D.words(text))
        return any(len(ws & w) >= 2 and D.similar(text, t) for t, w in hw)
    return close


def generate(srv, cfg: dict, per_class: int, existing: list[dict], seed: int = 1, say=print) -> list[dict]:
    close = heldout_checker(cfg)
    seen = {" ".join(sorted(set(D.words(p["prompt"])))) for p in existing}
    rnd = random.Random(seed)
    out: list[dict] = []
    stats = {}
    for cls, (theme, topics) in CLASSES.items():
        got, dropped, calls = 0, {"heldout": 0, "dupe": 0}, 0
        while got < per_class and calls < per_class // 4 + 8:
            calls += 1
            pick = rnd.sample(topics, k=min(3, len(topics)))
            ans = srv.chat([{"role": "user", "content": ASK.format(n=12, theme=theme, topics="; ".join(pick))}],
                           temperature=0.9, max_tokens=1500, seed=rnd.randrange(1 << 30))
            for q in parse_list(ans.get("text", "")):
                key = " ".join(sorted(set(D.words(q))))
                if not key or key in seen:
                    dropped["dupe"] += 1
                    continue
                if close(q):
                    dropped["heldout"] += 1
                    continue
                seen.add(key)
                row = {"prompt": q, "group": f"g:{cls}", "source": "gemma-4-12b gap question", "category": cls,
                       "pid": hashlib.sha256(q.encode()).hexdigest()[:16]}
                if cls == "safety":
                    row["kind"] = "safety"
                out.append(row)
                got += 1
                if got >= per_class:
                    break
        stats[cls] = {"kept": got, "calls": calls, **dropped}
        say(f"{cls}: {stats[cls]}")
    return out


def main(argv=None) -> int:
    from training.nightly.nightly import CONFIG, jl_append, jl_read, load_config
    from training.nightly.serve import Remote
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CONFIG))
    ap.add_argument("--node-url", required=True)
    ap.add_argument("--per-class", type=int, default=120)
    ap.add_argument("--seed", type=int, default=20261029)
    a = ap.parse_args(argv)
    cfg = load_config(Path(a.config))
    work = Path(cfg["work_dir"])
    srv = Remote(a.node_url, cfg.get("mesh_token_file", "~/.star/mesh_token"))
    existing = jl_read(work / "pool.jsonl") + jl_read(work / "pool-gaps.jsonl")
    rows = generate(srv, cfg, a.per_class, existing, a.seed)
    jl_append(work / "pool-gaps.jsonl", rows)
    print(json.dumps({"added": len(rows), "file": str(work / "pool-gaps.jsonl")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
