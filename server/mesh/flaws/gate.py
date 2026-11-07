"""Ship gate and rollback watch for flaw fixes (no owner clicks; every decision is logged to the self-model).

A fix ships only when, measured through the live router (the gate's own A/B header X-Mesh-Fixes):
  1. offline (route.py): it does not lower route accuracy on any item set, and it never touches an item whose
     expected route it would get wrong more often than right;
  2. cluster items (the turns its rule fires on whose expected route is the one the fix gives): wins - losses >= 2 and
     losses <= wins / 3 (A = shipped set without the fix, B = with it; same seed, temperature 0.2);
  3. control items (it fires but the expected route is different, e.g. a real safety question) and every other set:
     no net loss. Items it does not fire on get a byte-identical request, so they cannot change.
After shipping, `watch` compares the live re-ask-on-next-turn rate and failure rate of turns the fix was applied to with
the same rates of the turns it would have matched before it shipped (logged as "would"); worse by 10 points with >= 20
turns -> automatic rollback (removed from shipped.json) and an "upgrade" report with decision "rollback".
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

from . import hook, items as items_mod, mine, route


class Client:
    def __init__(self, url: str, key: str, system: str = "", timeout: float = 300.0, retries: int = 20):
        self.url, self.key, self.system, self.timeout, self.retries = url.rstrip("/"), key, system, timeout, retries

    def _post(self, path: str, body: dict, timeout: float | None = None) -> tuple[int, dict, dict]:
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.key}",
                                              "X-Mesh-Cache": "off", "X-Mesh-Hedge": "0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                return r.status, dict(r.headers), json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers or {}), {}
        except (urllib.error.URLError, OSError, ValueError) as e:
            return 0, {}, {"error": str(e)}

    def chat(self, messages: list, fixes, max_tokens: int = 900, seed: int = 7) -> tuple[str | None, dict]:
        msgs = ([{"role": "system", "content": self.system}] if self.system else []) + messages
        body = {"model": "litha", "messages": msgs, "max_tokens": max_tokens, "temperature": 0.2, "seed": seed,
                "stream": False, "mesh_fixes": ",".join(sorted(fixes)) or "none",
                "mesh_brain": False}          # GPU nodes only: both arms on the same model, never the CPU brain
        for attempt in range(self.retries + 1):     # "mesh busy" (503) while other lanes hold the GPUs: wait, retry
            status, headers, data = self._post("/v1/chat/completions", body)
            if status not in (0, 503) or attempt == self.retries:     # 0 = connection refused (router restart)
                break
            time.sleep(30)
        if status != 200:
            return None, {"status": status, **{k: v for k, v in headers.items() if k.lower().startswith("x-mesh")}}
        ch = (data.get("choices") or [{}])[0]
        info = {k: v for k, v in headers.items() if k.lower().startswith("x-mesh")}
        info["finish"] = ch.get("finish_reason")
        return (ch.get("message") or {}).get("content") or "", info

    def verify(self, answer: str) -> dict | None:
        status, _, data = self._post("/mesh/verify", {"answer": answer}, timeout=60)
        return data if status == 200 else None


def offline_ok(fix: str, item_sets: dict[str, list[dict]], shipped: frozenset) -> tuple[bool, dict]:
    base = set(shipped) - {fix}
    out, ok = {}, True
    for name, its in item_sets.items():
        before = sum(route.label(it["messages"], base) == it["expect"] for it in its)
        after = sum(route.label(it["messages"], base | {fix}) == it["expect"] for it in its)
        out[name] = {"n": len(its), "before": before, "after": after}
        ok = ok and after >= before
    return ok, out


def changes(messages: list, fix: str, base: set, max_tokens: int = 600) -> bool:
    """The fix fires on this chat and the request (note decision or text) differs from the one without it."""
    la, ra, _ = route.run(messages, base, max_tokens)
    lb, rb, entry = route.run(messages, base | {fix}, max_tokens)
    if fix not in (entry.get("fire") or []):
        return False
    return la != lb or json.dumps(ra, sort_keys=True) != json.dumps(rb, sort_keys=True)


def _spread(xs: list, n: int) -> list:
    return xs if len(xs) <= n else [xs[round(i * (len(xs) - 1) / (n - 1))] for i in range(n)] if n > 1 else xs[:n]


def ab(client: Client, fix: str, its: list[dict], shipped: frozenset, max_tokens: int = 900,
       limit: int = 20) -> list[dict]:
    """A/B on the items whose request the fix changes (at most `limit` cluster and `limit` control items, spread over
    the sets). A turn the fix fires on but another hook already handles (fullcode skips the general note on build
    turns too) sends the same request in both arms: any difference there is sampling noise, so it is left out.
    A/B answers alternate order per item (no warm-cache advantage)."""
    base = set(shipped) - {fix}
    fired = [it for it in its if changes(it["messages"], fix, base, max_tokens)]
    want = items_mod.EXPECT_FOR.get(fix)
    picked = _spread([it for it in fired if it["expect"] == want], limit) + \
        _spread([it for it in fired if it["expect"] != want], limit)
    rows = []
    for k, it in enumerate(picked):
        res = {}
        order = ("A", "B") if k % 2 == 0 else ("B", "A")
        for arm in order:
            text, info = client.chat(it["messages"], base if arm == "A" else base | {fix}, max_tokens)
            if text is None:
                res[arm] = {"pass": None, "why": [f"no answer ({info.get('status')})"]}
                continue
            ok, why = items_mod.grade(it, text, client.verify)
            res[arm] = {"pass": ok, "why": why, "finish": info.get("finish"), "chars": len(text),
                        "backend": info.get("X-Mesh-Backend"), "general": info.get("X-Mesh-General")}
        print(f"[gate {fix}] {k + 1}/{len(picked)} {it['id']}: A {res.get('A', {}).get('pass')} B {res.get('B', {}).get('pass')}",
              file=sys.stderr, flush=True)
        rows.append({"id": it["id"], "set": it.get("set"), "expect": it["expect"],
                     "cluster": it["expect"] == items_mod.EXPECT_FOR.get(fix), **res})
    return rows


def _kind(backend) -> str:
    return "brain" if str(backend or "").startswith("brain") else "node"


def decide(fix: str, rows: list[dict]) -> tuple[bool, dict]:
    def tally(rs):
        # both arms answered, on the same kind of backend (GPU nodes run litha-fast, the CPU brain another model)
        rs = [r for r in rs if r.get("A", {}).get("pass") is not None and r.get("B", {}).get("pass") is not None
              and _kind(r["A"].get("backend")) == _kind(r["B"].get("backend"))]
        wins = sum(1 for r in rs if r["B"]["pass"] and not r["A"]["pass"])
        losses = sum(1 for r in rs if r["A"]["pass"] and not r["B"]["pass"])
        return {"n": len(rs), "A": sum(r["A"]["pass"] for r in rs), "B": sum(r["B"]["pass"] for r in rs),
                "wins": wins, "losses": losses}
    cl, ctl = tally([r for r in rows if r["cluster"]]), tally([r for r in rows if not r["cluster"]])
    ok = cl["wins"] - cl["losses"] >= 2 and cl["losses"] * 3 <= cl["wins"] and ctl["B"] >= ctl["A"]
    return ok, {"cluster": cl, "control": ctl}


# --- shipped.json -----------------------------------------------------------------------------------------------
def read_shipped(folder: str) -> dict:
    try:
        with open(os.path.join(folder, "shipped.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data.get("fixes"), dict) else {"fixes": {}}
    except (OSError, ValueError, AttributeError):
        return {"fixes": {}}


def write_shipped(folder: str, data: dict) -> None:
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "shipped.json")
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)
    os.replace(path + ".tmp", path)
    hist = os.path.join(folder, "decisions.jsonl")
    with open(hist, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": round(time.time()), "fixes": sorted(data["fixes"])}) + "\n")


def live_rates(rows: list[dict], fix: str, field: str) -> dict:
    """Re-ask-next-turn and failure rates of litha turns where `fix` is in flaw[field] ("fire" or "would")."""
    rows = mine.live(rows)
    nxt = mine.next_turn_reask(rows)
    idx = [i for i, r in enumerate(rows) if fix in ((r.get("flaw") or {}).get(field) or [])]
    followed = [i for i in idx if i in nxt]
    failed = sum(1 for i in idx if mine.outcome_cause(rows[i]) not in (None,) and
                 not str(mine.outcome_cause(rows[i])).startswith(("client went away", "mesh busy")))
    return {"turns": len(idx), "followed": len(followed),
            "reask_rate": round(sum(nxt[i] for i in followed) / len(followed), 4) if followed else None,
            "fail_rate": round(failed / len(idx), 4) if idx else None}


def watch(folder: str, rows: list[dict], min_turns: int = 20, margin: float = 0.10) -> list[dict]:
    """Rollback decisions for shipped fixes whose live rates got worse than their pre-ship baseline."""
    data, out = read_shipped(folder), []
    for fix, rec in list(data["fixes"].items()):
        after_rows = [r for r in rows if r.get("ts", 0) >= rec.get("shipped", 0)]
        now = live_rates(after_rows, fix, "fire")
        base = rec.get("baseline") or {}
        worse = []
        if now["followed"] >= min_turns and base.get("reask_rate") is not None and \
                now["reask_rate"] > base["reask_rate"] + margin:
            worse.append(f"re-ask rate {now['reask_rate']} vs {base['reask_rate']} before")
        if now["turns"] >= min_turns and base.get("fail_rate") is not None and now["fail_rate"] > base["fail_rate"] + margin:
            worse.append(f"failure rate {now['fail_rate']} vs {base['fail_rate']} before")
        out.append({"fix": fix, "live": now, "baseline": base, "rollback": bool(worse), "why": "; ".join(worse)})
        if worse:
            del data["fixes"][fix]
            write_shipped(folder, data)
    return out


def ship(folder: str, fix: str, evidence: dict, baseline: dict) -> None:
    data = read_shipped(folder)
    data["fixes"][fix] = {"shipped": round(time.time()), "what": hook.FIXES.get(fix), "evidence": evidence,
                          "baseline": baseline}
    write_shipped(folder, data)
