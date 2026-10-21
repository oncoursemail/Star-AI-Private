"""Turn twin session records into metrics (P3), detected design problems and a markdown report.

Detectors are generic: they read only what the driver records (milestones, quit reasons, the
player's perceived wait, currency earned/sunk over time, fuzz results), never game-specific names.
Thresholds are set once here and checked against the fixed sample game as a negative control.
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict

WALL_QUITS = {"bored"}      # an economy wall shows up as players quitting bored while they wait
WALL_MIN_RATE = 0.30        # share of players reaching a step who quit bored before the next
WALL_MIN_RATIO = 2.0        # ... and at least this many times the median of the other steps
SPIKE_MIN_RATE = 0.30       # share of players attempting a challenge who quit frustrated on it
SPIKE_MIN_RATIO = 2.0
INFLATION_BIND_RATIO = 10   # a minute of income buys the dearest item this many times over ...
INFLATION_MIN_MINUTES = 3   # ... in at least this many separate minutes (one-off rewards do not count)
HIGH_SEVERITY = {"invalid_args_accepted", "no_rate_limit"}
CURVE_MINUTES = (1, 5, 10, 15, 20, 30, 45, 60, 90, 120)


def _list(x) -> list:
    return x if isinstance(x, list) else []  # Luau encodes empty tables as {}


def _dict(x) -> dict:
    return x if isinstance(x, dict) else {}


def _median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _pct(a: float, b: float) -> float:
    return round(100.0 * a / b, 1) if b else 0.0


def _rates(timeline: list, sample_sec: float) -> list[float]:
    """Earning rate (currency/s) over 60 s windows from [t, cash, earned, sunk] samples."""
    step = max(1, round(60 / sample_sec))
    return [(timeline[k + step][2] - timeline[k][2]) / (timeline[k + step][0] - timeline[k][0])
            for k in range(len(timeline) - step) if timeline[k + step][0] > timeline[k][0]]


def analyze(sessions: list[dict], meta: dict) -> dict:
    exploiters = set(meta.get("exploiters", []))
    sample_sec = float(meta.get("settings", {}).get("sampleSec", 30))
    by_twin: dict[int, list[dict]] = defaultdict(list)
    for s in sessions:
        by_twin[s["twin"]].append(s)
    for lst in by_twin.values():
        lst.sort(key=lambda s: s["day"])
    mainline = next((_list(s.get("mainline")) for s in sessions if _list(s.get("mainline"))), [])
    legit = {t: lst for t, lst in by_twin.items() if lst[0]["persona"] not in exploiters}
    legit_sessions = [s for lst in legit.values() for s in lst]
    n_legit = len(legit)

    report: dict = {"meta": meta, "findings": []}

    # ---------------------------------------------------------------- quit points (player level)
    churn, active = Counter(), Counter()
    reasons: dict[int, Counter] = defaultdict(Counter)
    waits: dict[int, list] = defaultdict(list)
    goals: dict[int, Counter] = defaultdict(Counter)
    for lst in legit.values():
        final = lst[-1]
        idx = int(final.get("mainlineIndex") or 0)
        if final.get("returns"):
            active[idx] += 1
            continue
        churn[idx] += 1
        reasons[idx][final.get("quit")] += 1
        qi = _dict(final.get("quitInfo"))
        waits[idx].append(qi.get("wait"))
        if qi.get("goal"):
            goals[idx][qi["goal"]] += 1
    rows, cumulative = [], 0.0
    for idx in range(len(mainline) + 1):
        if idx == 0:
            where = f"before {mainline[0]}" if mainline else "start"
        elif idx < len(mainline):
            where = f"after {mainline[idx - 1]} (next: {mainline[idx]})"
        else:
            where = f"after {mainline[-1]} (end of main line)"
        pct = _pct(churn[idx], n_legit)
        cumulative += pct
        top = reasons[idx].most_common(1)
        rows.append({"index": idx, "where": where, "quit": churn[idx], "pct": pct, "cumulative_pct": round(cumulative, 1),
                     "active": active[idx], "top_reason": top[0][0] if top else None,
                     "reasons": dict(reasons[idx]), "median_wait_s": _median(waits[idx]),
                     "waiting_for": goals[idx].most_common(1)[0][0] if goals[idx] else None})
    report["quit_table"] = {"players": n_legit, "still_playing": sum(active.values()), "rows": rows}

    # ---------------------------------------------------------------- milestones (play time)
    lifetime: dict[int, dict[str, float]] = {}
    for t, lst in legit.items():
        merged: dict[str, float] = {}
        for s in lst:
            for k, v in _dict(s.get("newMilestones")).items():
                merged.setdefault(k, v)
        lifetime[t] = merged
    all_ids = list(mainline) + sorted({k for m in lifetime.values() for k in m} - set(mainline))
    milestones = []
    for mid in all_ids:
        times = [m[mid] for m in lifetime.values() if mid in m]
        milestones.append({"id": mid, "reached": len(times), "pct": _pct(len(times), n_legit),
                           "median_min": round(statistics.median(times) / 60, 1) if times else None,
                           "p90_min": round(sorted(times)[int(0.9 * (len(times) - 1))] / 60, 1) if times else None})
    report["milestones"] = milestones

    # ---------------------------------------------------------------- progression walls
    steps = []
    for i in range(len(mainline)):
        reached = sum(1 for lst in legit.values() if int(lst[-1].get("mainlineIndex") or 0) >= i)
        bad = sum(1 for lst in legit.values()
                  if int(lst[-1].get("mainlineIndex") or 0) == i and not lst[-1].get("returns")
                  and lst[-1].get("quit") in WALL_QUITS)
        gap = None
        if i > 0:
            gaps = [m[mainline[i]] - m[mainline[i - 1]] for m in lifetime.values()
                    if mainline[i] in m and mainline[i - 1] in m]
            gap = round(statistics.median(gaps) / 60, 1) if gaps else None
        steps.append({"step": i, "from": mainline[i - 1] if i else "start", "to": mainline[i], "reached": reached,
                      "bored_quits": bad, "rate": round(bad / reached, 3) if reached else 0.0,
                      "median_gap_min": gap, "median_wait_at_quit_s": _median(waits[i]),
                      "waiting_for": goals[i].most_common(1)[0][0] if goals[i] else None})
    min_reached = max(20, int(0.02 * n_legit))
    eligible = [s for s in steps if s["reached"] >= min_reached]
    for s in eligible:
        others = [o["rate"] for o in eligible if o is not s]
        base = _median(others) or 0.0
        s["baseline_rate"] = round(base, 3)
        s["wall"] = s["rate"] >= WALL_MIN_RATE and s["rate"] >= WALL_MIN_RATIO * base
        if s["wall"]:
            wait = s["median_wait_at_quit_s"]
            report["findings"].append({
                "kind": "progression_wall", "severity": "high",
                "text": (f"Progression wall between {s['from']} and {s['to']}: {_pct(s['bored_quits'], s['reached'])}% "
                         f"of players who got there quit bored before the next step "
                         f"(other steps: {round(100 * base, 1)}%)."
                         + (f" At the moment they quit they faced a median estimated wait of {wait / 60:.0f} min"
                            f" for {s['waiting_for']}." if wait else "")),
                "evidence": s})
    report["walls"] = steps

    # ---------------------------------------------------------------- difficulty spikes
    tried: dict[str, set] = defaultdict(set)
    attempts, fails = Counter(), Counter()
    for t, lst in legit.items():
        for s in lst:
            for cid, c in _dict(s.get("challenges")).items():
                tried[cid].add(t)
                attempts[cid] += c.get("attempts", 0)
                fails[cid] += c.get("fails", 0)
    frustrated = Counter(_dict(lst[-1].get("quitInfo")).get("challenge") for lst in legit.values()
                         if not lst[-1].get("returns") and lst[-1].get("quit") == "frustrated")
    challenges = [{"id": cid, "players": len(tried[cid]), "attempts": attempts[cid],
                   "fail_pct": _pct(fails[cid], attempts[cid]), "frustrated_quits": frustrated[cid],
                   "rate": round(frustrated[cid] / len(tried[cid]), 3)}
                  for cid in sorted(tried, key=lambda c: (len(c), c))]
    eligible_c = [c for c in challenges if c["players"] >= min_reached]
    for c in eligible_c:
        base = _median([o["rate"] for o in eligible_c if o is not c]) or 0.0
        c["baseline_rate"] = round(base, 3)
        c["spike"] = c["rate"] >= SPIKE_MIN_RATE and c["rate"] >= SPIKE_MIN_RATIO * base
        if c["spike"]:
            report["findings"].append({
                "kind": "difficulty_spike", "severity": "high",
                "text": (f"Difficulty spike at {c['id']}: {round(100 * c['rate'], 1)}% of the {c['players']} players who "
                         f"tried it quit frustrated there (other challenges: {round(100 * base, 1)}%); "
                         f"{c['fail_pct']}% of attempts failed."),
                "evidence": c})
    report["challenges"] = challenges

    # ---------------------------------------------------------------- progression curve
    curve: dict[str, list] = {}
    for persona in sorted({s["persona"] for s in sessions}):
        day1 = [s for s in sessions if s["persona"] == persona and s["day"] == 1]
        points = []
        for minute in CURVE_MINUTES:
            t = minute * 60
            vals = [row[2] for s in day1 for row in _list(s.get("timeline")) if row[0] == t]
            if vals:
                points.append({"minute": minute, "players": len(vals), "median_earned": _median(vals)})
        curve[persona] = points
    report["progression_curve"] = curve

    # ---------------------------------------------------------------- economy and inflation
    flagged, bind_ratios, peak_rates = [], [], []
    minute_earned: dict[int, list[float]] = defaultdict(list)
    for s in legit_sessions:
        tl = _list(s.get("timeline"))
        rates = _rates(tl, sample_sec)
        peak = max(rates) if rates else 0.0
        peak_rates.append(peak)
        price = s.get("maxPrice") or 0
        ratio = peak * 60 / price if price else 0.0
        bind_ratios.append(ratio)
        step = max(1, round(60 / sample_sec))
        minutes = sum(1 for r in rates[::step] if price and r * 60 >= INFLATION_BIND_RATIO * price)
        if minutes >= INFLATION_MIN_MINUTES:
            flagged.append(s)
        for k in range(len(tl) - 1):
            if tl[k][0] % 60 == 0 and tl[k][0] < 120 * 60:
                minute_earned[tl[k][0] // 60].append(tl[k + 1][2] - tl[k][2])
    earned = sum(s.get("earned") or 0 for s in legit_sessions)
    sunk = sum(s.get("sunk") or 0 for s in legit_sessions)
    repeat = Counter()
    for s in flagged:
        skip = {"work", "idle", "exploit"} | set(_dict(s.get("challenges")))
        for aid, n in _dict(s.get("actions")).items():
            if n > 1 and aid not in skip:
                repeat[aid] += n
    economy = {
        "sessions": len(legit_sessions), "earned_total": earned, "sunk_total": sunk,
        "sink_ratio": round(sunk / earned, 3) if earned else None,
        "median_peak_rate_per_s": _median(peak_rates), "max_peak_rate_per_s": max(peak_rates, default=0),
        "median_bind_ratio": _median(bind_ratios), "inflated_sessions": len(flagged),
        "inflated_pct": _pct(len(flagged), len(legit_sessions)),
        "repeated_purchases_in_inflated": dict(repeat.most_common(5)),
        "earned_per_active_minute": [{"minute": m, "players": len(v), "median": _median(v)}
                                     for m, v in sorted(minute_earned.items()) if m in (0, 1, 5, 10, 20, 30, 45, 60, 90)],
    }
    if len(flagged) >= max(3, 0.01 * len(legit_sessions)):
        top = ", ".join(f"{k} x{v}" for k, v in repeat.most_common(3)) or "none"
        report["findings"].append({
            "kind": "inflation", "severity": "high",
            "text": (f"Currency inflation: in {len(flagged)} sessions ({economy['inflated_pct']}%) one minute of income "
                     f"bought the most expensive item at least {INFLATION_BIND_RATIO} times over, for "
                     f"{INFLATION_MIN_MINUTES}+ minutes (peak "
                     f"{economy['max_peak_rate_per_s']:.3g}/s); prices stop mattering. Purchases repeated most in "
                     f"those sessions: {top}."),
            "evidence": {k: economy[k] for k in ("inflated_sessions", "max_peak_rate_per_s", "repeated_purchases_in_inflated")}})
    report["economy"] = economy

    # ---------------------------------------------------------------- exploits (P5)
    agg: dict[tuple, dict] = {}
    tested: dict[str, bool] = {}
    fuzz_sessions = 0
    for s in sessions:
        tests = _list(s.get("fuzzTests"))
        if tests:
            fuzz_sessions += 1
        for t in tests:
            tested[t["remote"]] = tested.get(t["remote"], False) or bool(t.get("legitSample"))
        for f in _list(s.get("findings")):
            key = (f["remote"], f["kind"])
            a = agg.setdefault(key, {"remote": f["remote"], "kind": f["kind"], "sessions": 0, "examples": [],
                                     "severity": "high" if f["kind"] in HIGH_SEVERITY else "low"})
            a["sessions"] += 1
            for ex in _list(f.get("examples")):
                if len(a["examples"]) < 3 and ex not in a["examples"]:
                    a["examples"].append(ex)
    broken = sorted(agg.values(), key=lambda a: (a["severity"] != "high", a["remote"]))
    held = sorted(r for r in tested if not any(a["remote"] == r and a["severity"] == "high" for a in broken))
    report["exploits"] = {"fuzz_sessions": fuzz_sessions, "remotes_tested": sorted(tested),
                          "remotes_without_legit_sample": sorted(r for r, ok in tested.items() if not ok),
                          "checks_broken": broken, "checks_held": held}
    for a in broken:
        if a["severity"] != "high":
            continue
        ex = a["examples"][0] if a["examples"] else {}
        what = ("accepts invalid arguments" if a["kind"] == "invalid_args_accepted" else "has no server-side rate limit")
        report["findings"].append({
            "kind": "exploit", "severity": "high",
            "text": (f"{a['remote']} {what}: {ex.get('args', '')} raised {ex.get('stat')} by {ex.get('delta')} "
                     f"(largest legitimate change: {ex.get('legitMax')}); found in {a['sessions']} of "
                     f"{fuzz_sessions} exploiter sessions."),
            "evidence": a})

    # ---------------------------------------------------------------- errors, data, harness
    errors: dict[str, dict] = {}
    warnings: dict[str, dict] = {}
    for s in sessions:
        for e in _list(s.get("errors")):
            r = errors.setdefault(e["msg"], {"msg": e["msg"], "sessions": 0, "count": 0})
            r["sessions"] += 1
            r["count"] += e["count"]
        for w in _list(s.get("warnings")):
            r = warnings.setdefault(w["msg"], {"msg": w["msg"], "sessions": 0, "count": 0})
            r["sessions"] += 1
            r["count"] += w["count"]
    report["errors"] = sorted(errors.values(), key=lambda r: -r["sessions"])[:20]
    report["warnings"] = sorted(warnings.values(), key=lambda r: -r["sessions"])[:20]
    harness = Counter(s["harnessError"] for s in sessions if s.get("harnessError"))
    report["harness_errors"] = [{"msg": m, "sessions": n} for m, n in harness.most_common(10)]
    lost = [s for s in sessions if s["day"] > 1 and s.get("prevEndCash") is not None
            and (s.get("startCash") or 0) < s["prevEndCash"] * 0.99 - 5]
    report["data"] = {"datastore_calls": sum(s.get("dsCalls") or 0 for s in sessions),
                      "injected_failures": sum(s.get("dsFailures") or 0 for s in sessions),
                      "rejoin_sessions": sum(1 for s in sessions if s["day"] > 1),
                      "progress_lost_sessions": len(lost),
                      "progress_lost_examples": [{"twin": s["twin"], "day": s["day"], "before": s["prevEndCash"],
                                                  "after": s.get("startCash")} for s in lost[:5]]}
    game_errors = [e for e in report["errors"] if "twin mock" not in e["msg"] and "UNSUPPORTED" not in e["msg"]]
    if game_errors:
        report["findings"].append({"kind": "server_errors", "severity": "medium",
                                   "text": f"{len(game_errors)} distinct server errors; top: {game_errors[0]['msg'][:200]}",
                                   "evidence": game_errors[:5]})
    unsupported = [e for e in report["errors"] if "twin mock" in e["msg"] or "UNSUPPORTED" in e["msg"]]
    if unsupported:
        report["findings"].append({"kind": "mock_gap", "severity": "info",
                                   "text": f"The engine mock lacks something this game uses: {unsupported[0]['msg'][:200]}",
                                   "evidence": unsupported[:5]})
    if lost:
        report["findings"].append({"kind": "data_loss", "severity": "high",
                                   "text": f"Progress lost on rejoin in {len(lost)} sessions.",
                                   "evidence": report["data"]["progress_lost_examples"]})

    # ---------------------------------------------------------------- personas
    personas = {}
    for persona in sorted({s["persona"] for s in sessions}):
        twins = [lst for lst in by_twin.values() if lst[0]["persona"] == persona]
        ss = [s for lst in twins for s in lst]
        zone = Counter()
        for s in ss:
            zone.update({k: v for k, v in _dict(s.get("zone")).items()})
        total = sum(zone.values()) or 1
        personas[persona] = {
            "twins": len(twins), "sessions": len(ss),
            "median_session_min": round((_median([s.get("duration") or 0 for s in ss]) or 0) / 60, 1),
            "quit_reasons": dict(Counter(s.get("quit") for s in ss)),
            "returned_day2_pct": _pct(sum(1 for lst in twins if len(lst) > 1), len(twins)),
            "flow_pct": _pct(zone["flow"], total), "anxiety_pct": _pct(zone["anxiety"], total),
            "boredom_pct": _pct(zone["boredom"], total),
            "median_mainline_index": _median([int(lst[-1].get("mainlineIndex") or 0) for lst in twins]),
            "misclicks_per_100_clicks": _pct(sum(s.get("misclicks") or 0 for s in ss),
                                             sum(s.get("clicks") or 0 for s in ss)),
            "challenge_fail_pct": _pct(sum(s.get("fails") or 0 for s in ss), sum(s.get("attempts") or 0 for s in ss)),
            "median_final_skill": _median([lst[-1].get("skill") for lst in twins]),
        }
    report["personas"] = personas
    return report


def _fmt_wait(seconds) -> str:
    if seconds is None:
        return "-"
    if seconds > 36000:
        return ">10 h"
    return f"{seconds / 60:.0f} min" if seconds >= 60 else f"{seconds:.0f} s"


def render_markdown(report: dict) -> str:
    m = report["meta"]
    out = [f"# Player Twins report: {m['game']}", "",
           f"{m['sessions']} sessions from {m['twins']} twins (up to {m['days']} days each), runtime {m['runtime']}, "
           + (f"{m['workers']} workers, {m['elapsed_s']} s wall clock = **{m['sessions_per_min']} sessions/min**. "
              if m.get("sessions_per_min") else
              f"{m['workers']} shards, {m.get('sessions_per_cpu_min')} sessions per CPU-minute. ")
           + f"Seed {m['seed']}. Logic twins run the game's server Luau against engine doubles: this is not a Roblox "
           f"Studio or live-server result.", "", "## Findings", ""]
    if report["findings"]:
        for f in report["findings"]:
            out.append(f"- **{f['kind']}** ({f['severity']}): {f['text']}")
    else:
        out.append("- No problems detected by the current detectors.")
    q = report["quit_table"]
    out += ["", f"## Where players quit ({q['players']} non-exploiter players; {q['still_playing']} still playing at the end)", "",
            "| Where | Quit here | % of players | Cumulative % | Main reason | Median wait they faced | Waiting for |",
            "|---|---|---|---|---|---|---|"]
    for r in q["rows"]:
        out.append(f"| {r['where']} | {r['quit']} | {r['pct']} | {r['cumulative_pct']} | {r['top_reason'] or '-'} | "
                   f"{_fmt_wait(r['median_wait_s'])} | {r['waiting_for'] or '-'} |")
    out += ["", "## Progression steps", "", "| Step | Reached | Bored quits | Rate | Baseline | Median gap | Wall |",
            "|---|---|---|---|---|---|---|"]
    for s in report["walls"]:
        out.append(f"| {s['from']} -> {s['to']} | {s['reached']} | {s['bored_quits']} | {round(100 * s['rate'], 1)}% | "
                   f"{round(100 * s['baseline_rate'], 1) if 'baseline_rate' in s else '-'}% | "
                   f"{s['median_gap_min'] if s['median_gap_min'] is not None else '-'} min | {'YES' if s.get('wall') else ''} |")
    if report["challenges"]:
        out += ["", "## Challenges", "", "| Challenge | Players | Attempts | Fail % | Frustrated quits | Rate | Spike |",
                "|---|---|---|---|---|---|---|"]
        for c in report["challenges"]:
            out.append(f"| {c['id']} | {c['players']} | {c['attempts']} | {c['fail_pct']} | {c['frustrated_quits']} | "
                       f"{round(100 * c['rate'], 1)}% | {'YES' if c.get('spike') else ''} |")
    out += ["", "## Time to each milestone (play time, all sessions)", "", "| Milestone | Reached | % | Median | p90 |",
            "|---|---|---|---|---|"]
    for ms in report["milestones"]:
        out.append(f"| {ms['id']} | {ms['reached']} | {ms['pct']} | {ms['median_min'] if ms['median_min'] is not None else '-'} min | "
                   f"{ms['p90_min'] if ms['p90_min'] is not None else '-'} min |")
    e = report["economy"]
    out += ["", "## Economy", "",
            f"Earned {e['earned_total']:.4g}, sunk {e['sunk_total']:.4g} (sink ratio {e['sink_ratio']}). Median peak income "
            f"{(e['median_peak_rate_per_s'] or 0):.3g}/s, max {e['max_peak_rate_per_s']:.3g}/s. Sessions where a minute of income "
            f"buys the dearest item {INFLATION_BIND_RATIO}x over for {INFLATION_MIN_MINUTES}+ minutes: {e['inflated_sessions']} ({e['inflated_pct']}%).", "",
            "| Minute | Players | Median earned that minute |", "|---|---|---|"]
    for row in e["earned_per_active_minute"]:
        out.append(f"| {row['minute']} | {row['players']} | {row['median']:.4g} |")
    x = report["exploits"]
    out += ["", f"## Server checks under the exploiter ({x['fuzz_sessions']} fuzz sessions)", "",
            "| Remote | Problem | Severity | Sessions | Example |", "|---|---|---|---|---|"]
    for a in x["checks_broken"]:
        ex = a["examples"][0] if a["examples"] else {}
        detail = ex.get("args", "")
        if ex.get("stat"):
            detail += f" -> {ex['stat']} +{ex.get('delta')} (legit max {ex.get('legitMax')})"
        out.append(f"| {a['remote']} | {a['kind']} | {a['severity']} | {a['sessions']} | {detail} |")
    if not x["checks_broken"]:
        out.append("| - | none | - | - | - |")
    out.append("")
    out.append(f"Held (no high-severity break): {', '.join(x['checks_held']) or '-'}.")
    if x["remotes_without_legit_sample"]:
        out.append(f"Tested without a legitimate sample (gains not judged): {', '.join(x['remotes_without_legit_sample'])}.")
    out += ["", "## Personas", "",
            "| Persona | Twins | Sessions | Median session | Day-2 return | Flow / anxiety / boredom | Fail rate | Misclicks/100 | Quit reasons |",
            "|---|---|---|---|---|---|---|---|---|"]
    for name, p in report["personas"].items():
        reasons = ", ".join(f"{k} {v}" for k, v in sorted(p["quit_reasons"].items(), key=lambda kv: -kv[1]))
        out.append(f"| {name} | {p['twins']} | {p['sessions']} | {p['median_session_min']} min | {p['returned_day2_pct']}% | "
                   f"{p['flow_pct']} / {p['anxiety_pct']} / {p['boredom_pct']}% | {p['challenge_fail_pct']}% | "
                   f"{p['misclicks_per_100_clicks']} | {reasons} |")
    out += ["", "## Progression curve (median currency earned, day 1)", ""]
    minutes = sorted({pt["minute"] for pts in report["progression_curve"].values() for pt in pts})
    out.append("| Persona | " + " | ".join(f"{mm} min" for mm in minutes) + " |")
    out.append("|---|" + "---|" * len(minutes))
    for name, pts in report["progression_curve"].items():
        by = {pt["minute"]: pt for pt in pts}
        out.append(f"| {name} | " + " | ".join(f"{by[mm]['median_earned']:.4g} ({by[mm]['players']})" if mm in by else "-"
                                               for mm in minutes) + " |")
    d = report["data"]
    out += ["", "## Errors and data", "",
            f"DataStore calls {d['datastore_calls']}, injected failures {d['injected_failures']}, rejoin sessions "
            f"{d['rejoin_sessions']}, sessions with lost progress {d['progress_lost_sessions']}."]
    for err in report["errors"][:10]:
        out.append(f"- error in {err['sessions']} sessions: `{err['msg'][:300]}`")
    for w in report["warnings"][:10]:
        out.append(f"- warning in {w['sessions']} sessions: {w['msg'][:200]}")
    for h in report["harness_errors"]:
        out.append(f"- harness error in {h['sessions']} sessions: `{h['msg'][:300]}`")
    return "\n".join(out) + "\n"
