"""Star's status cards in plain words: verdict, color from real health, problems explained, honest alert titles.

The fixtures have the shape of real `star_gate facts` answers (2026-11-03 03:55 UTC, the night the owner could not
read the old card): brain 1 practising well, brain 2 getting few answers right, a Studio Lab run where 1 of 16 tests
ran and none passed, and no PC feed.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path

from star.discord_bot import embeds, status_view
from star.discord_bot.awareness import Awareness, Snapshot, Source
from star.discord_bot.proactive import plain_digest

NOW = datetime(2026, 11, 3, 3, 55, 30, tzinfo=timezone.utc)          # 9:55 pm on Nov 2 in Chicago (CST)
CST = timezone(timedelta(hours=-6))
JARGON = ("conductor", "gate", "spec", "finetune", "pipeline", "tries", "night school", "PC feed")


def services(*rows):
    return [{"unit": u, "active": a, "sub": "running" if a == "active" else "dead", "since": "2026-10-24T06:52:25Z",
             "restarts": 0, "result": "success"} for u, a in rows]


def brain1(**extra):
    facts = {
        "v": 1, "at": "2026-11-03T03:55:22Z", "load": {"load1": 20.09, "mem_available_gb": 43.3},
        "services": services(("star-brain.service", "active"), ("star-knowledge.service", "active"),
                             ("star-night-school.service", "active"), ("star-knowledge-watchdog.service", "inactive")),
        "night_school": {
            "paused": False,
            "report": {"written": "2026-11-03T03:54:23Z", "status": "brain idle, working", "attempts_total": 3128,
                       "answers_per_active_hour": 28.0},
            "hours": {"2026-11-02T20": {"first": 215, "first_pass": 116, "lesson": 147, "lesson_pass": 16,
                                        "validation": 124, "validation_pass": 60, "discarded": 81, "error": 1}},
            "gates": [{"ts": "2026-11-02T09:28:30Z", "event": "lesson gate INCONCLUSIVE", "lesson": "L1269",
                       "text": "Always define functions inside the module and return them as part of the module table."},
                      {"ts": "2026-11-03T01:24:28Z", "event": "lesson gate INCONCLUSIVE", "lesson": "L1009",
                       "text": "Always ensure conditional return statements cover both true and false outcomes."}]},
        "conductor": {"night": "20261102", "written": "2026-11-03T03:05:18Z", "cycles": 4, "created": 102,
                      "accepted": 33, "rejected": 69, "off": False},
        "knowledge_watchdog": {"ok": True, "checked_at": "2026-11-03T03:54:41Z", "failures": 0,
                               "restarts": [{"at": "2026-10-20T13:44:37Z", "done": True, "reason": "TimeoutError"}]}}
    facts.update(extra)
    return facts


def brain2(**extra):
    facts = {
        "v": 1, "at": "2026-11-03T03:55:23Z", "load": {"load1": 10.02},
        "services": services(("star-discord.service", "active"), ("star-night-school.service", "active"),
                             ("star-ns-brain.service", "active"), ("star-brain.service", "inactive")),
        "night_school": {"paused": False, "report": {"status": "brain idle, working"},
                         "hours": {"2026-11-02T21": {"first": 63, "first_pass": 7, "lesson": 70, "lesson_pass": 2,
                                                     "discarded": 54}},
                         "gates": []},
        "studio_lab": {"run": "nightly-1studio-20261103T033434Z", "ok": True, "specs": 16, "specs_ran": 1,
                       "passed": 0, "first_pass": 0, "playtests": 0, "wall_seconds": 9.1, "running": False}}
    facts.update(extra)
    return facts


class Gate:
    def __init__(self, facts=None, error=None):
        self.facts, self.error = facts, error

    async def call(self, verb, payload="", *, timeout=60):
        if self.error:
            raise ValueError(self.error)
        return {"ok": True, "facts": self.facts}


def aware(b1=None, b2=None, *, pc=None, errors=None):
    errors = errors or {}
    gates = {"1": Gate(b1, errors.get("1")), "2": Gate(b2, errors.get("2"))}
    out = Awareness(gates, pc_feed=(lambda: pc) if pc else (lambda: None), tz=CST, clock=lambda: NOW.timestamp())
    asyncio.run(out.refresh())
    return out


def snap(b1, b2):
    return Snapshot({"1": Source(b1, NOW.timestamp()), "2": Source(b2, NOW.timestamp())}, None, None,
                    taken=NOW.timestamp())


# ------------------------------------------------------------------ the live status card

def test_tonights_real_numbers_read_as_a_plain_verdict_with_problems_explained():
    report = aware(brain1(), brain2()).status_report()
    card = embeds.status_card(report, now=NOW)
    assert card["title"] == "⚠️ Brain 2 is struggling (+1 more)" and card["color"] == embeds.AMBER
    assert card["author"] == {"name": "Star · how I'm doing"}
    assert card["description"] == (
        "⚠️ Brain 2 got only 9 of 133 practice answers right today (7%). It keeps practising and writes itself "
        "lessons from the mistakes.\n\n"
        "⚠️ My Roblox Studio test run (tonight 9:34 pm) went badly: only 1 of 16 tests got to run, and it didn't "
        "pass. The next run is tomorrow night, starting with the 15 that didn't run.")
    fields = {f["name"]: (f["value"], f["inline"]) for f in card["fields"]}
    assert len(card["fields"]) <= 6
    assert fields["Brain 1 · practice today"] == ("**192** of 486 right (40%)", True)    # 116+16+60 of 215+147+124
    assert fields["⚠️ Brain 2 · practice today"] == ("**9** of 133 right (7%)", True)
    assert fields["📚 What I'm learning"][0] == (
        "🧪 Tested 2 new lessons in the last day: for both, the test couldn't tell if it helps, so I'm not using "
        "them yet.\n✍️ Wrote 102 new practice questions for myself (night of Nov 2) and kept the 33 that passed my "
        "checks.")
    assert fields["⚠️ Studio tests"] == ("tonight 9:34 pm\n**0** of 16 passed\nonly 1 got to run", True)
    assert fields["🖥️ Systems"] == ("✅ everything running\n🔎 search ok", True)
    assert fields["💻 Your PC"][0].startswith("Not connected, so I can't see pull requests or the task board. "
                                             "Practice and chat don't need it.")
    text = embeds.card_text(card).lower()
    assert not [word for word in JARGON if word.lower() in text]


def test_all_good_is_green_with_one_warm_line():
    b2 = brain2(studio_lab=dict(brain2()["studio_lab"], specs_ran=16, passed=16))
    b2["night_school"]["hours"]["2026-11-02T21"].update(first_pass=40, lesson_pass=10)
    card = embeds.status_card(aware(brain1(), b2).status_report(), now=NOW)
    assert card["title"] == "✅ All good: I'm practising" and card["color"] == embeds.GREEN
    assert card["description"] == "I'm practising Roblox coding on brain 1 and brain 2. Nothing needs you."
    assert {"name": "🎮 Studio tests", "value": "tonight 9:34 pm\n**16** of 16 passed", "inline": True} in card["fields"]


def test_a_stopped_service_or_dead_search_is_red_and_says_what_to_do():
    b1 = brain1(services=services(("star-night-school.service", "failed"), ("star-brain.service", "active")))
    b1["knowledge_watchdog"]["ok"] = False
    report = aware(b1, brain2()).status_report()
    card = embeds.status_card(report, now=NOW)
    assert card["color"] == embeds.RED and card["title"] == "❌ Practice stopped on brain 1 (+3 more)"
    assert "❌ Practice on brain 1 has stopped. You can ask me to restart it." in card["description"]
    assert "❌ My knowledge search isn't answering" in card["description"]
    systems = next(f["value"] for f in card["fields"] if f["name"] == "🖥️ Systems")
    assert systems == "❌ stopped: practice (brain 1)\n❌ knowledge search down"


def test_paused_and_unreachable_brains_are_worth_a_look_not_alarms():
    b1 = brain1()
    b1["night_school"]["paused"] = True
    report = aware(b1, None, errors={"2": "could not reach brain 2 (ssh exit 255)"}).status_report()
    assert report.level == "warn"
    texts = [i.text for i in report.issues]
    assert "Practice on brain 1 is paused (someone switched it off for now). Say \"resume night school\" and I'll " \
           "start again." in texts
    assert "Brain 2 didn't answer my status check (it didn't answer), so its numbers are missing from this card." in texts
    assert report.fields[0]["value"] == "**192** of 486 right (40%)\npaused"


def test_pc_feed_shows_pull_requests_in_plain_words():
    feed = {"tz_offset_min": -360, "claims": [{"item": "x"}], "merged_today": [{"number": 1}],
            "open_prs": [{"number": 2, "checks": "failing"}, {"number": 3, "checks": "passing"}]}
    report = aware(brain1(), brain2(), pc=(20.0, feed)).status_report()
    assert {"name": "💻 Your PC", "value": "2 pull requests open (1 need a fix)\n1 merged today\n1 tasks being worked on",
            "inline": True} in report.fields


def test_trend_against_yesterday_only_when_the_gate_window_covers_all_of_yesterday():
    b1 = brain1()
    b1["night_school"]["hours"]["2026-11-01T20"] = {"first": 100, "first_pass": 47}      # Nov 1 in Chicago
    b1["night_school"]["hours_from"] = "2026-11-01T01:55:22Z"                           # 50 h back
    value = aware(b1, brain2()).status_report().fields[0]["value"]
    assert value == "**192** of 486 right (40%)\n↓ from 47% yesterday"
    b1["night_school"]["hours_from"] = "2026-11-01T15:55:22Z"                           # the old 36 h window
    assert aware(b1, brain2()).status_report().fields[0]["value"] == "**192** of 486 right (40%)"
    assert status_view.trend({"first": 10, "first_pass": 5}, {"first": 10, "first_pass": 5}) == "same as yesterday (50%)"
    assert status_view.trend({"first": 10, "first_pass": 6}, {"first": 10, "first_pass": 5}) == "↑ from 50% yesterday"


def test_the_gate_reports_its_window_for_the_yesterday_check(tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("star_gate_cards", root / "server/discord/gate/star_gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    (tmp_path / "opt/star/learning/data").mkdir(parents=True)
    (tmp_path / "opt/star/learning/data/attempts.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"ts": "2026-11-01T02:00:00Z", "purpose": "first", "passed": True},       # 49.9 h old: kept
        {"ts": "2026-11-01T01:00:00Z", "purpose": "first", "passed": True}]))     # 50.9 h old: dropped
    ns = gate.night_school(tmp_path, NOW)
    assert ns["hours_from"] == "2026-11-01T01:55:30Z" and list(ns["hours"]) == ["2026-11-01T02"]


# ------------------------------------------------------------------ change alerts

def lab_alert(**lab):
    before = brain2(studio_lab={"run": "nightly-1studio-20261102T033311Z", "specs": 16, "specs_ran": 16, "passed": 9})
    after = brain2(studio_lab=dict(brain2()["studio_lab"], **lab))
    events = aware().events(snap(brain1(), before), snap(brain1(), after))
    return events, embeds.alert_card(events, now=NOW)


def test_a_studio_run_with_nothing_passed_is_never_good_news():
    events, card = lab_alert()
    assert [e[2] for e in events] == ["warn"]
    assert card["title"] == "⚠️ Studio tests went badly" and card["color"] == embeds.AMBER
    assert card["description"] == ("My Roblox Studio test run (tonight 9:34 pm) went badly: only 1 of 16 tests got to "
                                   "run, and it didn't pass. The next run is tomorrow night, starting with the 15 "
                                   "that didn't run.")
    _, none_ran = lab_alert(specs_ran=0)
    assert none_ran["title"] == "⚠️ Studio tests went badly" and "didn't run at all: 0 of 16 started" in none_ran["description"]
    _, all_failed = lab_alert(specs_ran=16)
    assert "all 16 tests ran and none passed" in all_failed["description"]
    _, some = lab_alert(specs_ran=16, passed=12)
    assert some["title"] == "🎮 Studio tests finished" and some["color"] == embeds.GOLD
    _, perfect = lab_alert(specs_ran=16, passed=16)
    assert perfect["title"] == "✅ Studio tests passed" and perfect["color"] == embeds.GREEN


def test_lesson_and_service_alerts_say_what_happened_in_plain_words():
    before, after = brain1(), brain1()
    after["night_school"] = dict(after["night_school"], gates=after["night_school"]["gates"] + [
        {"ts": "2026-11-03T03:50:00Z", "event": "lesson gate PROMOTE", "lesson": "L1400", "text": "Check nil first."}])
    after["services"] = services(("star-brain.service", "active"), ("star-knowledge.service", "failed"),
                                 ("star-night-school.service", "active"))
    events = aware().events(snap(before, brain2()), snap(after, brain2()))
    texts = {e[0].split(":")[0]: (e[1], e[2]) for e in events}
    assert texts["down"] == ("Knowledge search on brain 1 stopped (failed). I'll tell you when it's back.", "bad")
    assert texts["gate"] == ("Brain 1: A new lesson (L1400) passed its test, so I use it from now on. “Check nil "
                             "first.”", "good")
    card = embeds.alert_card(events, now=NOW)
    assert card["title"] == "❌ Something needs you" and card["color"] == embeds.RED
    assert card["description"].splitlines()[0].startswith("❌ Knowledge search on brain 1 stopped")
    only_gate = embeds.alert_card([e for e in events if e[2] == "good"], now=NOW)
    assert only_gate["title"] == "✅ I learned something new" and only_gate["color"] == embeds.GREEN
    unclear = status_view.lesson_sentence("lesson gate INCONCLUSIVE", "L1009")
    assert unclear == ("info", "I tested a new lesson (L1009); the test couldn't tell if it helps, so I'm not using "
                               "it yet. I'll test it again after it fixes more tasks.")


def test_mixed_alerts_take_the_worst_title_and_good_news_needs_all_good():
    good = ("release:v1", "Release v1 is published.", "good")
    warn = ("lab:2:x", "My Roblox Studio test run went badly.", "warn")
    assert embeds.alert_card([good, warn], now=NOW)["title"] == "⚠️ A few things to know"
    assert embeds.alert_card([good, good], now=NOW)["title"] == "✅ Good news"
    mixed = embeds.alert_card([good, ("gate:1:t:L1", "I tested a new lesson.", "info")], now=NOW)
    assert mixed["title"] == "📝 A few updates" and mixed["color"] == embeds.GOLD


# ------------------------------------------------------------------ the morning/evening note

def test_the_note_card_and_its_plain_fallback_text():
    report = aware(brain1(), brain2()).status_report()
    text = plain_digest("evening", report)
    assert text.splitlines() == [
        "Evening update from me:",
        "- Brain 2 got only 9 of 133 practice answers right today (7%). It keeps practising and writes itself "
        "lessons from the mistakes.",
        "- My Roblox Studio test run (tonight 9:34 pm) went badly: only 1 of 16 tests got to run, and it didn't pass. "
        "The next run is tomorrow night, starting with the 15 that didn't run."]
    card = embeds.digest_card("evening", text, report, now=NOW)
    assert card["author"] == {"name": "Star · evening note"} and card["title"] == report.headline
    assert card["color"] == embeds.AMBER and card["fields"] == report.fields     # the text already says it
    assert embeds.total_chars(card) <= 6000
    her_words = embeds.digest_card("evening", "Busy evening! I practised a lot.", report, now=NOW)
    assert her_words["fields"][0]["name"] == "Worth a look"                      # her words skipped the problems
    calm = aware(brain1(), brain2(studio_lab=None)).status_report()
    calm.issues = []
    calm.note = "I'm practising Roblox coding on brain 1 and brain 2. Nothing needs you."
    assert plain_digest("morning", calm) == ("Morning! Here's how I'm doing:\n- I'm practising Roblox coding on "
                                             "brain 1 and brain 2. Nothing needs you.")
