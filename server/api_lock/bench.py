"""Paired speed check of the API lock on one server: the same greedy Luau prompts with "api_lock" off and on.

usage: python3 bench.py URL OUT.json [ORDER]     ORDER: "ab" (off first) or "ba" (on first, default "ab")
Each prompt runs once per arm, arms alternating; per run it records the server's timings (tokens/s, draft and
api_lock_forced counts) and the answer, so invented members can be counted afterwards (star.api_lock audit / star.slop).
Standard library only (runs in the server container).
"""
import json
import sys
import time
import urllib.request

PROMPTS = [
    "Write a Roblox server Script in Luau: when a player joins, give them a leaderstats folder with Coins, and "
    "every 10 seconds add 5 Coins. Use game:GetService. Reply with one ```lua code block.",
    "Write a Roblox LocalScript in Luau that tweens a Part named Door in workspace up by 8 studs when the player "
    "presses E, using TweenService and UserInputService. Reply with one ```lua code block.",
    "Write a Roblox server Script in Luau that creates a ScreenGui in StarterGui with a Frame, a UIGridLayout with "
    "3 columns and six TextLabels. Reply with one ```lua code block.",
    "Write a Roblox server Script in Luau that creates a Part with a ParticleEmitter and a PointLight, and makes it "
    "spin with RunService.Heartbeat. Reply with one ```lua code block.",
]
MAX_TOKENS = 300


def ask(url: str, prompt: str, lock: bool) -> dict:
    body = {"model": "star-fast", "temperature": 0, "max_tokens": MAX_TOKENS, "cache_prompt": False,
            "messages": [{"role": "user", "content": prompt}]}
    if lock:
        body["api_lock"] = True
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    started = time.time()
    data = json.load(urllib.request.urlopen(req, timeout=600))
    return {"lock": lock, "seconds": round(time.time() - started, 2), "timings": data.get("timings", {}),
            "answer": data["choices"][0]["message"]["content"]}


def main() -> int:
    url, out = sys.argv[1], sys.argv[2]
    order = sys.argv[3] if len(sys.argv) > 3 else "ab"
    runs = []
    for i, prompt in enumerate(PROMPTS):
        arms = (False, True) if (order == "ab") == (i % 2 == 0) else (True, False)
        for lock in arms:
            run = ask(url, prompt, lock)
            run["prompt"] = i
            t = run["timings"]
            print(f"p{i} lock={int(lock)} {t.get('predicted_per_second', 0):.2f} tok/s n={t.get('predicted_n')} "
                  f"draft {t.get('draft_n_accepted', 0)}/{t.get('draft_n', 0)} forced {t.get('api_lock_forced', 0)}",
                  flush=True)
            runs.append(run)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"order": order, "max_tokens": MAX_TOKENS, "runs": runs}, f, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
