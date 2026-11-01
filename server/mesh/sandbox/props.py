"""Property checks generated from the question: what the scenario's observations must show when the answer does what
was asked ("door opens on touch and closes after 3 s" -> parts change on touch and are back after 3 s). Each check
fires only when the question asks for that behaviour AND the scenario exercised it, so an answer is never failed for
something it was not asked to do. Messages are written for the fix model (what happened in the test, what to change).
"""
from __future__ import annotations

import re

NUM_S = re.compile(r"(\d+(?:\.\d+)?)\s*(?:s\b|sec|secs|second|seconds)", re.I)
WORD_S = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10, "a few": 3, "few": 3, "couple": 2}


def seconds(question: str) -> float | None:
    m = NUM_S.search(question or "")
    if m:
        return float(m.group(1))
    m = re.search(r"\b(one|two|three|four|five|ten|a few|few|couple)\s+(?:of\s+)?seconds?\b", question or "", re.I)
    return float(WORD_S[m.group(1).lower()]) if m else None


def wait_seconds(question: str) -> float:
    s = seconds(question)
    return min(max((s or 3.0) + 6.0, 2.0), 30.0)


def _q(question: str, pat: str) -> bool:
    return bool(re.search(pat, question or "", re.I))


def _num(x):
    return x if isinstance(x, (int, float)) else None


def check(question: str, text: str, rep: dict) -> list[dict]:
    o = rep.get("obs") or {}
    out: list[dict] = []

    def fail(name: str, msg: str):
        out.append({"kind": "property", "block": None, "line": None, "phase": name, "message": msg})

    stats_q = _q(question, r"leaderstat|leaderboard|coins?\b|points?\b|cash|money|gems?\b|score|kills?\b|wins?\b")
    # leaderstats exist after a player joins
    if _q(question, r"leaderstat|leaderboard") and o.get("stats_join") is None and \
            re.search(r"leaderstats", text or "") and "PlayerAdded" in (text or ""):
        fail("leaderstats", "In a test, a player joined but player.leaderstats (a Folder named exactly \"leaderstats\" "
                            "with an IntValue inside) did not exist afterwards. Create it in Players.PlayerAdded in a "
                            "server Script and parent it to the player.")
    touched = _num(o.get("touch_parts")) or 0
    t0, t1 = _num(o.get("total_join")), _num(o.get("total_touch"))
    t1s = _num(o.get("total_touch_1s"))
    # touching gives the reward once per touch burst (debounce / collect once)
    if touched and stats_q and _q(question, r"touch|step|walk|collect|pick ?up|pad|coin|part") and t0 is not None and \
            t1 is not None and not _q(question, r"every|per second|each second|while|keep|continuous|hold"):
        gain = t1 - t0
        if gain > 0:
            # 5 touches 0.04 s apart: a working debounce or a collected coin gives the reward once
            per = None
            stats = o.get("stats_join") or {}
            if gain >= 5 and len(stats) >= 1:
                per = gain / 5
            if per is not None and per == int(per):
                fail("debounce", f"In a test, the player touched the part 5 times within 0.2 s and got the reward 5 "
                                 f"times (+{gain:g}). Add a per-player debounce (or remove/disable the coin) so one "
                                 f"touch gives the reward once.")
        elif (t1s is None or t1s == t0) and _q(question, r"give|get|add|earn|collect|reward|\+"):
            fail("reward", "In a test, the player touched the part but the leaderstats value did not change. Make the "
                           "Touched handler find the player with Players:GetPlayerFromCharacter(hit.Parent) and add "
                           "to player.leaderstats.<Stat>.Value on the server.")
    # kill brick / lava / damage on touch
    if touched and _q(question, r"kill ?(brick|part|block)|lava|kills? (the )?player|instantly (die|kill)|deadly|"
                                r"damage") and not _q(question, r"heal|sword|weapon|tool|gun|punch|attack|enemy|npc|"
                                                             r"other player|zombie|projectile|bullet|fireball|explos"):
        h = _num(o.get("health_touch"))
        if h is not None and h >= 100 and not o.get("died_touch"):
            fail("kill", "In a test, the player's character touched the part but its Humanoid health did not go down. "
                         "In Touched, get the Humanoid from hit.Parent (FindFirstChildOfClass(\"Humanoid\")) and set "
                         "Health to 0 or call TakeDamage.")
    # door/part changes when touched / prompted, and comes back after N seconds
    door_q = _q(question, r"\bdoor|gate|wall|bridge|platform") and not _q(
        question, r"team|vip|game ?pass|only|owner|admin|group|badge|level|key\b|rank|premium|friend|password|code")
    secs = seconds(question)
    if door_q and touched and _q(question, r"touch|walk|step|bump|run into|walks? into"):
        if not o.get("parts_changed_touch") and not o.get("parts_changed_touch_1s"):
            fail("opens", "In a test, the player touched the part but nothing about it changed (CanCollide, "
                          "Transparency, Position/CFrame all the same). The Touched handler must open the door: set "
                          "CanCollide = false and Transparency, or move it.")
        elif secs and _q(question, r"close|back|again|reappear|return|after") and o.get("parts_changed_after_wait"):
            fail("closes", f"In a test, the part changed when touched but was still changed {secs:g}+ seconds later. "
                           f"After task.wait({secs:g}) set CanCollide, Transparency and the position back.")
    prompts = _num(o.get("prompts")) or 0
    if door_q and prompts and _q(question, r"\bpress(es)? e\b|proximity ?prompt|\bprompt|click"):
        if not o.get("parts_changed_prompt"):
            fail("opens", "In a test, the prompt/click was triggered but the part did not change. The Triggered (or "
                          "MouseClick) handler must change the door (CanCollide, Transparency, CFrame) on the server.")
        elif secs and _q(question, r"close|back|again|after") and o.get("parts_changed_prompt_wait"):
            fail("closes", f"In a test, the door opened but had not closed {secs:g}+ seconds later. Close it after "
                           f"task.wait({secs:g}).")
    # a cheating client must not be able to give itself huge amounts
    te0, te1 = _num(o.get("total_hb")), _num(o.get("total_evil"))
    if o.get("evil") and te0 is not None and te1 is not None and abs(te1 - te0) >= 1e8:
        fail("trust", "In a test, a cheating client fired the RemoteEvent with an amount of 1000000000 and the server "
                      "added it to leaderstats. The server must decide amounts itself (or check the price/limits "
                      "and that the player can afford it); never use a number the client sends.")
    # saving: something is written when the player leaves or the server closes
    if _q(question, r"\bsave|datastore|data store|keep (their|my|the) |persist|load"):
        writes = rep.get("writes") or []
        uses_ds = "GetDataStore" in (text or "")
        if uses_ds and not writes and not _q(question, r"\bload\b") and o.get("total_join") is not None:
            fail("save", "In a test, the player left and the server shut down but nothing was written to the "
                         "DataStore. Save in Players.PlayerRemoving and in game:BindToClose (both inside pcall).")
    return out


def wants_ds_fail(question: str, text: str, rep: dict) -> bool:
    return "GetDataStore" in (text or "") and bool(rep.get("writes")) and \
        bool(re.search(r"GetAsync|UpdateAsync", text or ""))


def check_ds_fail(raw: dict) -> list[dict]:
    bad = [w for w in raw.get("writes") or [] if w.get("failed_load") and w.get("how") == "set"]
    if not bad:
        return []
    return [{"kind": "property", "block": None, "line": None, "phase": "failed-load",
             "message": "In a test where DataStore GetAsync failed (Roblox outage), the script still saved later and "
                        "overwrote the player's real data with default values. Remember per player whether loading "
                        "succeeded and skip saving for players whose load failed."}]
