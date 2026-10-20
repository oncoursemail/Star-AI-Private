"""Star on Discord: live self-awareness, allow-listed actions, proactive DMs and her persona.

Everything external is faked: the brain gates (fake facts), the PC feed, Discord channels and the model.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from star.discord_bot import actions, awareness, embeds, gate_client, pc_feed, proactive
from star.discord_bot.actions import ActionRunner, parse_request, pr_status
from star.discord_bot.awareness import Awareness, Snapshot, Source
from star.discord_bot.core import AccessPolicy
from star.discord_bot.prefs import OwnerPrefs, prefs_request
from star.discord_bot.proactive import Ledger, Proactive, ProactiveConfig, invented_numbers, quiet_request
from star.discord_bot.service import DiscordService
from star.persona import CORE, DESKTOP_LINE, check_reply

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("star_gate", ROOT / "server" / "discord" / "gate" / "star_gate.py")
star_gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(star_gate)

NOW = datetime(2026, 10, 20, 15, 30, tzinfo=timezone.utc)
OWNER = 111


# ------------------------------------------------------------------ a fake brain container for star_gate

def fake_brain_root(tmp_path: Path) -> Path:
    learning = tmp_path / "opt/star/learning"
    (learning / "data").mkdir(parents=True)
    (learning / "report").mkdir()
    (learning / "conductor").mkdir()
    (learning / "docs-recent").mkdir()
    (learning / "report/latest.md").write_text(
        "# STAR night school: latest numbers\nwritten 2026-10-20T15:20:00Z | started x | batches 9\n"
        "status: brain idle, working\n\ntask attempts: 855 on 509 different tasks\npassed first time: 319\n"
        "fixed by a lesson: 104\nverified worked examples stored: 423\n"
        "speed: 2586 answers in 109.61 h of answer time = 23.6 answers per active hour\n"
        "proposed by the model: 477 | kept as candidate (fixed its task): 59 | discarded (task still failed): 418\n"
        "promoted to active: 1 | held back by validation: 3 | retired later: 1\n", encoding="utf-8")
    rows = [{"ts": "2026-10-20T14:10:00Z", "purpose": "first", "passed": True, "error": ""},
            {"ts": "2026-10-20T14:20:00Z", "purpose": "first", "passed": False, "error": ""},
            {"ts": "2026-10-20T15:05:00Z", "purpose": "new lesson", "passed": True, "error": ""},
            {"ts": "2026-10-20T15:06:00Z", "purpose": "validation trial 1/2", "passed": False, "error": ""},
            {"ts": "2026-10-20T15:07:00Z", "purpose": "first", "passed": False, "error": "APIConnectionError"},
            {"ts": "2026-10-17T15:07:00Z", "purpose": "first", "passed": True, "error": ""}]   # too old
    (learning / "data/attempts.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    events = [{"ts": "2026-10-20T15:01:00Z", "event": "lesson discarded", "lesson": {"id": "L480", "text": "x"}},
              {"ts": "2026-10-20T15:02:00Z", "event": "lesson gate INCONCLUSIVE",
               "lesson": {"id": "L109", "text": "Ensure formatting   functions handle grouping."}}]
    (learning / "data/events.jsonl").write_text("\n".join(json.dumps(r) for r in events) + "\n", encoding="utf-8")
    (learning / "conductor/report-20261019.md").write_text(
        "# STAR night conductor: night of 20261019\nwritten 2026-10-20T09:44:08Z | cycles 12 | model calls 60\n"
        "created (proposed by the model): 186\naccepted into pool/conductor-20261019.json: 30 (cap 80 a night)\n"
        "rejected: 151\n", encoding="utf-8")
    (tmp_path / "opt/star/knowledge/data").mkdir(parents=True)
    (tmp_path / "opt/star/knowledge/data/watchdog.json").write_text(json.dumps(
        {"ok": True, "checked_at": "2026-10-20T15:29:00Z", "failures": 0,
         "restarts": [{"at": "2026-10-20T13:44:37Z", "reason": "TimeoutError: timed out", "failures": 2, "done": True}]}))
    return tmp_path


def systemctl_runner(units):
    """A fake `run` for star_gate: list-units / show / is-active / cat / start / stop / restart."""
    calls = []

    def run(args, timeout=20):
        calls.append(list(args))
        out, code = "", 0
        if args[:2] == ["systemctl", "list-units"]:
            out = "\n".join(f"{u} loaded {s[0]} {s[1]} desc" for u, s in units.items())
        elif args[:2] == ["systemctl", "show"]:
            out = "\n\n".join(f"Id={u}\nActiveState={s[0]}\nSubState={s[1]}\nActiveEnterTimestamp=@1792509000\n"
                              f"NRestarts=0\nResult=success" for u, s in units.items() if u in args)
        elif args[:2] == ["systemctl", "cat"]:
            code = 0 if args[2] in units else 1
        elif args[:2] == ["systemctl", "is-active"]:
            out = units.get(args[2], ("inactive",))[0]
        elif args[0] == "id":
            code, out = 1, ""
        return SimpleNamespace(returncode=code, stdout=out, stderr="")
    run.calls = calls
    return run


UNITS = {"star-brain.service": ("active", "running"), "star-night-school.service": ("active", "running"),
         "star-knowledge-refresh.timer": ("active", "waiting")}


def test_gate_facts_read_real_files_and_count_today_by_hour(tmp_path):
    root = fake_brain_root(tmp_path)
    facts = star_gate.facts(root, systemctl_runner(UNITS), now=NOW)
    assert {s["unit"] for s in facts["services"]} == set(UNITS)
    assert facts["services"][0]["since"] == "2026-10-20T15:10:00Z"
    ns = facts["night_school"]
    assert ns["report"]["attempts_total"] == 855 and ns["report"]["answers_per_active_hour"] == 23.6
    assert ns["report"]["status"] == "brain idle, working" and ns["paused"] is False
    assert ns["hours"]["2026-10-20T14"] == {"first": 2, "first_pass": 1}
    assert ns["hours"]["2026-10-20T15"] == {"lesson": 1, "lesson_pass": 1, "validation": 1, "error": 1, "discarded": 1}
    assert "2026-10-17T15" not in ns["hours"]
    assert ns["gates"] == [{"ts": "2026-10-20T15:02:00Z", "event": "lesson gate INCONCLUSIVE", "lesson": "L109",
                            "text": "Ensure formatting functions handle grouping."}]
    assert facts["conductor"] == {"night": "20261019", "written": "2026-10-20T09:44:08Z", "cycles": 12,
                                  "created": 186, "accepted": 30, "rejected": 151, "off": False}
    assert facts["knowledge_watchdog"]["restarts"][0]["at"] == "2026-10-20T13:44:37Z"


def test_gate_refuses_anything_off_the_list_and_runs_only_fixed_commands(tmp_path):
    root = fake_brain_root(tmp_path)
    run = systemctl_runner(UNITS)
    for verb in ("rm -rf /", "facts; reboot", "restart:sshd", "lxc exec starai -- cat /etc/shadow", ""):
        code, out = star_gate.handle(verb, root=root, run=run)
        assert code == 2 and "refused" in out
    assert run.calls == []
    code, out = star_gate.handle("lxc exec starai -- cat /opt/star/knowledge/data/watchdog.json", root=root, run=run)
    assert code == 0 and json.loads(out)["ok"] is True                 # the legacy digest command still works
    code, out = star_gate.handle("restart:star-brain", root=root, run=run)
    assert code == 0 and ["systemctl", "restart", "star-brain.service"] in run.calls
    code, out = star_gate.handle("restart:star-ns-brain", root=root, run=run)
    assert code == 1 and "not installed" in json.loads(out)["text"]    # allowed name, but not on this brain


def test_gate_pause_resume_and_idea_files(tmp_path):
    root = fake_brain_root(tmp_path)
    hold = root / "opt/star/learning/data/HOLD"
    assert star_gate.handle("ns-pause", root=root)[0] == 0 and hold.exists()
    assert star_gate.handle("ns-resume", root=root)[0] == 0 and not hold.exists()
    code, out = star_gate.handle("idea", "A round timer that\x07 pauses when all players leave", root=root)
    assert code == 0 and "conductor" in json.loads(out)["text"]
    saved = list((root / "opt/star/learning/docs-recent").glob("owner-idea-*.md"))
    assert len(saved) == 1 and "\x07" not in saved[0].read_text() and "round timer" in saved[0].read_text()
    assert star_gate.handle("idea", "hi", root=root)[0] == 1


def test_gate_client_checks_verbs_and_builds_a_strict_ssh_command(tmp_path):
    (tmp_path / "gate_ed25519").write_text("k")
    (tmp_path / "gate_known_hosts").write_text("h")
    gate = gate_client.Gate.parse("brain 1", "ssh:star@brain1.example", folder=tmp_path)
    command = gate.ssh_command("facts")
    assert command[-2:] == ["star@brain1.example", "facts"]
    assert "BatchMode=yes" in command and "StrictHostKeyChecking=yes" in command and "IdentitiesOnly=yes" in command
    assert f"UserKnownHostsFile={tmp_path / 'gate_known_hosts'}" in command
    assert gate_client.allowed("restart:star-brain") and not gate_client.allowed("restart:sshd")
    with pytest.raises(ValueError, match="not an allowed"):
        asyncio.run(gate.call("cat /etc/passwd"))
    with pytest.raises(ValueError):
        gate_client.Gate.parse("brain 1", "ssh:bad host; rm", folder=tmp_path)
    gates = gate_client.gates_from_env({"STAR_DISCORD_CONFIG_DIR": str(tmp_path),
                                        "STAR_DISCORD_GATE_2": "unix:/run/star-discord-gate.sock"})
    assert list(gates) == ["2"] and gates["2"].kind == "unix"


# ------------------------------------------------------------------ awareness

class FakeGate:
    def __init__(self, facts=None, error=None, answers=None):
        self.facts, self.error, self.calls = facts, error, []
        self.answers = answers or {}

    async def call(self, verb, payload="", *, timeout=60):
        self.calls.append((verb, payload))
        if self.error:
            raise ValueError(self.error)
        if verb == "facts":
            return {"ok": True, "facts": self.facts}
        return self.answers.get(verb, {"ok": True, "text": f"{verb} done"})


def brain_facts(tmp_path, units=UNITS):
    return star_gate.facts(fake_brain_root(tmp_path), systemctl_runner(units), now=NOW)


def clock_at(moment):
    return lambda: moment.timestamp()


FEED = {"tz_offset_min": -300, "state_head": "2026-10-20 WAVE", "state_next": ["KNOWLEDGE-FIX live on brain 1"],
        "claims": [{"item": "finetune-20261020", "owner": "claude", "since": "2026-10-20T14:57:00Z"}],
        "merged_today": [{"number": 526, "title": "knowledge fix"}],
        "open_prs": [{"number": 530, "title": "a", "draft": False, "merge": "CLEAN", "checks": "passing"},
                     {"number": 531, "title": "b", "draft": True, "merge": "BLOCKED", "checks": "failing"}],
        "releases": [{"tag": "v1.0.0", "draft": False, "at": "2026-10-13"}]}


def test_summary_has_specific_numbers_and_names_missing_sources(tmp_path):
    gates = {"1": FakeGate(brain_facts(tmp_path)), "2": FakeGate(error="could not reach brain 2 (ssh exit 255)")}
    aware = Awareness(gates, pc_feed=lambda: (30.0, FEED), clock=clock_at(NOW))
    asyncio.run(aware.refresh())
    text = aware.summary()
    assert "at 10:30 owner-local" in text                        # UTC-5 from the PC feed
    assert "today 4 tries, 2 passed, 1 could not run" in text  # owner-local day = all of today's UTC buckets here
    assert "1 of 1 lesson retries fixed the task" in aware.detail("night_school")
    assert "last lesson gate L109 inconclusive (10-20)" in text
    assert "conductor night 20261019: 30 of 186 new practice tasks accepted" in text
    assert "watchdog restarted it at 13:44 UTC" in text
    assert "1 PRs merged today; 2 open, 1 with failing checks" in text and "(finetune-20261020)" in text
    assert "not visible right now" in text and "brain 2 (could not reach brain 2" in text
    assert len(text) <= 1600


def test_stale_sources_are_never_reported_as_current(tmp_path):
    later = [NOW]
    aware = Awareness({"1": FakeGate(brain_facts(tmp_path))}, pc_feed=lambda: (3600.0, FEED),
                      clock=lambda: later[0].timestamp())
    asyncio.run(aware.refresh())
    later[0] = NOW + timedelta(minutes=10)
    text = aware.summary()
    assert "night school" not in text and "brain 1 (last answer 10 min old)" in text
    assert "PC feed (60 min old)" in text
    assert "missing or stale" in aware.detail("work")


def test_detail_sections_and_unknown_section_fall_back_to_overview(tmp_path):
    aware = Awareness({"1": FakeGate(brain_facts(tmp_path))}, pc_feed=lambda: (5.0, FEED), clock=clock_at(NOW),
                      jobs=lambda: [{"label": "quick eval", "state": "running", "started": "15:20 UTC"}])
    asyncio.run(aware.refresh())
    assert "star-brain: running since" in aware.detail("services")
    assert "L109 lesson gate INCONCLUSIVE: Ensure formatting" in aware.detail("gates")
    assert "#531 b | draft | checks failing" in aware.detail("prs")
    assert "finetune-20261020" in aware.detail("work") and "KNOWLEDGE-FIX" in aware.detail("work")
    assert "quick eval: running" in aware.detail("jobs")
    assert aware.detail("nonsense").startswith("[Your live status")


def test_events_for_down_restart_gate_lab_watchdog_and_release(tmp_path):
    aware = Awareness({"1": FakeGate()}, clock=clock_at(NOW))
    before = brain_facts(tmp_path / "a")
    after = json.loads(json.dumps(before))
    after["services"][0]["since"] = "2026-10-20T15:29:00Z"                        # star-brain restarted
    after["services"][1]["active"] = "failed"                                     # night school down
    after["night_school"]["gates"].append({"ts": "2026-10-20T15:25:00Z", "event": "lesson active",
                                           "lesson": "L200", "text": "t"})
    after["knowledge_watchdog"]["restarts"].append({"at": "2026-10-20T15:28:00Z", "done": False, "reason": "x"})
    after["studio_lab"] = {"run": "nightly-1studio-20261020T153000Z", "specs": 16, "specs_ran": 16, "passed": 12}
    before["studio_lab"] = {"run": "nightly-1studio-20261019T033225Z"}
    old = Snapshot({"1": Source(before, NOW.timestamp())}, dict(FEED), 1, taken=NOW.timestamp())
    new_feed = dict(FEED, releases=[{"tag": "v2.0.0", "draft": True}] + FEED["releases"])
    new = Snapshot({"1": Source(after, NOW.timestamp())}, new_feed, 1, taken=NOW.timestamp())
    texts = dict(aware.events(old, new))
    joined = " | ".join(texts.values())
    assert "star-brain on brain 1 restarted at 15:29 UTC" in joined
    assert "star-night-school on brain 1 is DOWN (failed/running)" in joined
    assert "L200 active" in joined and "12 passed" in joined
    assert "restart FAILED" in joined and "v2.0.0 is ready as a draft" in joined
    assert aware.events(new, new) == []                                            # nothing changed, nothing to say
    after["night_school"]["report"]["status"] = "quiet lock held, waiting"           # a timing run: maintenance
    maint = dict(aware.events(old, Snapshot({"1": Source(after, NOW.timestamp())}, new_feed, 1, taken=NOW.timestamp())))
    assert any(k.startswith("maint:1:star-brain") for k in maint) and not any(k.startswith("restart:") for k in maint)


# ------------------------------------------------------------------ actions

def test_parse_request_allows_only_the_list_and_checks_arguments():
    gates = {"1": object(), "2": object()}
    assert parse_request("night_school_pause", gates=gates).brains == ("1", "2")
    assert parse_request("quick_eval", gates=gates).brains == ("1",)
    assert parse_request("restart_service", "1", "knowledge", gates=gates).text == "star-knowledge"
    assert parse_request("restart_service", "1", "star-knowledge", gates=gates).action.disruptive
    for bad in (("merge_pr", "", "526"), ("restart_service", "1", "sshd"), ("practice_idea", "", ""),
                ("studio_lab_run", "1", ""), ("pr_status", "", "drop table")):
        with pytest.raises(ValueError):
            parse_request(*bad, gates=gates)
    assert parse_request("pr_status", "", "PR 526", gates=gates).text == "526"
    with pytest.raises(ValueError, match="no control line to brain 2"):
        parse_request("night_school_stop", "2", gates={"1": object()})


def test_jobs_run_in_the_background_and_report_back():
    gates = {"1": FakeGate(answers={"knowledge-eval": {"ok": True, "text": "eval30", "summary": {"bm25": {"recall@5": 0.87}}}}),
             "2": FakeGate()}
    reports = []

    cards = []

    async def notify(text, file=None, card=None):
        reports.append(text)
        cards.append(card)

    async def run():
        runner = ActionRunner(gates, notify=notify)
        job = runner.start(parse_request("quick_eval", gates=gates))
        with pytest.raises(ValueError, match="already doing"):
            runner.start(parse_request("quick_eval", gates=gates))
        runner.start(parse_request("night_school_pause", gates=gates))
        with pytest.raises(ValueError, match="two jobs"):
            runner.start(parse_request("practice_idea", text="a timer idea", gates=gates))
        await asyncio.gather(*(j.task for j in runner.jobs))
        assert job.state == "done" and "recall@5" in job.result
        assert gates["2"].calls == [("ns-pause", "")] and ("ns-pause", "") in gates["1"].calls
        assert any(r.startswith("Done: run the quick knowledge-search eval") for r in reports)
        eval_card = next(c for c in cards if c and c["title"].startswith("Done: run the quick"))
        assert eval_card["color"] == embeds.GREEN and {"name": "bm25 recall@5", "value": "0.87", "inline": True} in eval_card["fields"]
        failing = ActionRunner({"1": FakeGate(error="could not reach brain 1")}, notify=notify)
        bad = failing.start(parse_request("quick_eval", gates={"1": 1}))
        await bad.task
        assert bad.state == "failed" and reports[-1].startswith("That didn't work")
        assert cards[-1]["color"] == embeds.RED and cards[-1]["title"].startswith("Didn't work")
    asyncio.run(run())


def test_pr_status_answers_from_the_feed_or_says_it_is_missing():
    assert "missing or stale" in pr_status(None, "")
    assert "#531 b: draft, checks failing" in pr_status((10.0, FEED), "#531")
    assert "#526 was merged today" in pr_status((10.0, FEED), "526")
    assert "Ready with green checks: #530" in pr_status((10.0, FEED), "")


# ------------------------------------------------------------------ proactive

class Sent:
    def __init__(self):
        self.texts, self.cards = [], []

    async def __call__(self, text, picture=None, card=None):
        self.texts.append(text)
        self.cards.append(card)


def make_proactive(tmp_path, aware, *, writer=None, per_hour=3, now=None, times=((8, 30), (20, 30))):
    sent = Sent()
    moment = [now or NOW]
    config = ProactiveConfig(True, times, per_hour, tmp_path / "p.sqlite3")
    bot = Proactive(config, aware, sent, writer=writer, clock=lambda: moment[0])
    return bot, sent, moment


class ScriptedAwareness:
    """Snapshots and events chosen by the test; local time = UTC-5."""

    def __init__(self, events=()):
        self.queue = list(events)

    def snapshot(self):
        return Snapshot(taken=NOW.timestamp())

    def events(self, old, new):
        return self.queue.pop(0) if self.queue else []

    def local(self, moment, snap=None):
        return moment.astimezone(timezone(timedelta(hours=-5)))

    def summary(self, snap=None):
        return "LIVE STATUS:\n- brain 1: night school today 41 attempts, 9 passed\n- brain 2: 3 services running"

    def detail(self, section, snap=None):
        return "brain 1 lesson gate results (last 36 h):\n- 2026-10-20T15:02:00Z L109 lesson gate INCONCLUSIVE: t"


def test_events_are_merged_deduplicated_rate_limited_and_held_when_quiet(tmp_path):
    batch = [("maint:1:star-brain.service:z", "restarted during a timing run"),
             ("restart:1:star-brain.service:a", "star-brain on brain 1 restarted at 15:11 UTC."),
             ("gate:1:t:L109", "Lesson gate on brain 1: L109 gate INCONCLUSIVE.")]
    aware = ScriptedAwareness([batch, batch, [("restart:1:star-brain.service:b", "again")],
                               [("down:2:x.service:c", "x DOWN")], [("down:2:y.service:d", "y DOWN")],
                               [("down:2:z.service:e", "z DOWN")]])
    bot, sent, moment = make_proactive(tmp_path, aware, per_hour=2, now=NOW.replace(hour=17))

    async def run():
        await bot.tick()                                    # first look: nothing to compare with
        await bot.tick()
        assert sent.texts == ["Heads up, a few things just happened:\n- star-brain on brain 1 restarted at 15:11 UTC.\n"
                              "- Lesson gate on brain 1: L109 gate INCONCLUSIVE."]
        await bot.tick()                                    # the same events again: never resent
        await bot.tick()                                    # same unit within 30 min: held
        assert len(sent.texts) == 1
        await bot.tick()
        assert sent.texts[-1] == "Heads up: x DOWN"
        assert sent.cards[-1]["color"] == embeds.RED and sent.cards[-1]["title"] == "Something's down"
        assert sent.cards[0]["color"] == embeds.AMBER and "restarted" in sent.cards[0]["description"]
        await bot.tick()                                    # third DM in the hour: over the limit, held
        assert len(sent.texts) == 2
        bot.set_quiet(2)
        moment[0] += timedelta(hours=1, minutes=5)
        await bot.tick()
        assert len(sent.texts) == 2 and bot.quiet() is not None
        assert bot.ledger.held_since(NOW - timedelta(days=1)) == ["restarted during a timing run", "again", "y DOWN",
                                                                "z DOWN"]
        assert "back" in bot.set_quiet(0) and bot.quiet() is None
    asyncio.run(run())


def test_digest_once_per_slot_in_her_words_or_the_template_when_a_number_is_invented(tmp_path):
    drafts = ["Morning! I did 41 attempts and 9 passed overnight; L109 is still stuck at the gate.",
              "Morning! 500 attempts, all perfect."]
    calls = []

    async def writer(system, user):
        calls.append((system, user))
        return drafts.pop(0)
    aware = ScriptedAwareness()
    at_830_local = NOW.replace(hour=13, minute=31)                 # 08:31 at UTC-5
    bot, sent, moment = make_proactive(tmp_path, aware, writer=writer, now=at_830_local)

    async def run():
        assert (await bot.tick())["digest"] == "morning"
        assert sent.texts == ["Morning! I did 41 attempts and 9 passed overnight; L109 is still stuck at the gate."]
        assert CORE in calls[0][0] and "41 attempts" in calls[0][1]
        await bot.tick()
        assert len(sent.texts) == 1                              # once per slot
        moment[0] = NOW.replace(hour=1, minute=40) + timedelta(days=1)   # 20:40 local, evening slot
        drafts.append("Evening. 9999 lessons learned!")
        drafts.append("Evening. 9999 lessons learned!")
        await bot.tick()
        assert sent.texts[-1].startswith("Evening update from me:") and "9999" not in sent.texts[-1]
    asyncio.run(run())


def test_quiet_and_number_helpers():
    assert quiet_request("quiet for 3 hours") == 3 and quiet_request("Star, be quiet") == 8
    assert quiet_request("you can talk again") == 0 and quiet_request("quiet storm lyrics") is None
    assert invented_numbers("41 attempts at 08:30, 9 passed", "41 x 9 08:30") == []
    assert invented_numbers("500 attempts", "41 attempts") == ["500"]
    config = ProactiveConfig.from_env({"STAR_DISCORD_LEARNING_DM_OPT_IN": "1", "STAR_DISCORD_LEARNING_STATE": "/x/y.db",
                                       "STAR_DISCORD_DIGEST_TIMES": "07:00, 21:15"}, gates_configured=True)
    assert config.enabled and config.times == ((7, 0), (21, 15)) and config.state_path == Path("/x/proactive.sqlite3")
    assert not ProactiveConfig.from_env({"STAR_DISCORD_LEARNING_DM_OPT_IN": "1"}, gates_configured=False).enabled
    assert not ProactiveConfig.from_env({"STAR_DISCORD_LEARNING_DM_OPT_IN": "0"}, gates_configured=True).enabled
    with pytest.raises(ValueError):
        ProactiveConfig.from_env({"STAR_DISCORD_LEARNING_DM_OPT_IN": "1", "STAR_DISCORD_DIGEST_TIMES": "8am"},
                                 gates_configured=True)


# ------------------------------------------------------------------ brain tool rounds

def _stub_desktop(monkeypatch):
    fake = ModuleType("star.desktop_core")
    fake.Settings = object
    fake.app_data = lambda: None
    monkeypatch.setitem(sys.modules, "star.desktop_core", fake)


def chunk(content=None, calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=calls))])


def tool_delta(index, name="", arguments="", ident=None):
    return SimpleNamespace(index=index, id=ident, function=SimpleNamespace(name=name, arguments=arguments))


def test_brain_runs_a_streamed_tool_call_then_answers_in_words(monkeypatch):
    from star.discord_bot.brain import DiscordBrain
    _stub_desktop(monkeypatch)
    requests = []
    rounds = [[chunk(calls=[tool_delta(0, "star_lookup", '{"sec', "c1")]), chunk(calls=[tool_delta(0, "", 'tion": "night_school"}')])],
              [chunk("I practised "), chunk("41 tasks today.")]]

    class Stream:
        def __init__(self, items):
            self.items = items

        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            for item in self.items:
                yield item

    class Client:
        def __init__(self):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def create(self, **kwargs):
            requests.append(json.loads(json.dumps(kwargs, default=str)))
            return Stream(rounds.pop(0))
    settings = SimpleNamespace(model="mock", provider="local", endpoint="http://127.0.0.1:8080/v1", validate=lambda: None)
    brain = DiscordBrain(settings=settings, client_factory=lambda s, **k: Client())
    seen, shown = [], []

    async def handler(name, arguments):
        seen.append((name, arguments))
        return "brain 1: today 41 attempts"

    async def on_delta(text):
        shown.append(text)
    answer = asyncio.run(brain.reply("what did you do today?", [], tools=[{"type": "function"}], tool_handler=handler,
                                     on_delta=on_delta))
    assert answer == "I practised 41 tasks today."
    assert seen == [("star_lookup", {"section": "night_school"})]
    assert requests[0]["tools"] and requests[1]["messages"][-1] == {"role": "tool", "tool_call_id": "c1",
                                                                   "content": "brain 1: today 41 attempts"}
    assert requests[1]["messages"][-2]["tool_calls"][0]["function"]["name"] == "star_lookup"
    assert shown[-1] == "I practised 41 tasks today."


# ------------------------------------------------------------------ service: private turns only

class LiveBrain:
    streams = True

    def __init__(self, calls=None):
        self.calls, self.lives = calls or [], []

    async def reply(self, prompt, history, *, evidence="", live="", on_delta=None, on_status=None, tools=None,
                    tool_handler=None):
        self.lives.append((live, tools))
        out = []
        for name, args in self.calls:
            out.append(await tool_handler(name, args))
        return "ok " + " | ".join(out)


def make_service(brain, gates, tmp_path):
    service = DiscordService(AccessPolicy(frozenset({OWNER}), frozenset()), brain=brain)
    service.runner = ActionRunner(gates)
    service.awareness = Awareness(gates, pc_feed=lambda: (5.0, FEED), jobs=service.runner.views, clock=clock_at(NOW))
    service.prefs = OwnerPrefs(tmp_path / "mem.sqlite3")
    return service


def test_private_turns_carry_status_prefs_and_tools_public_ones_do_not(tmp_path, monkeypatch):
    import star.live_context as live_context

    async def no_web(question, **kwargs):
        return "", []
    monkeypatch.setattr(live_context, "auto_search", no_web)
    gates = {"1": FakeGate(brain_facts(tmp_path / "b"))}
    brain = LiveBrain()
    service = make_service(brain, gates, tmp_path)
    service.prefs.remember("call me boss, keep it short")

    async def run():
        await service.awareness.refresh()
        key = service.authorized(OWNER, None, 5)
        await service.ask(key, "what are you up to?", private=True)
        await service.ask(key, "hello", private=False)
    asyncio.run(run())
    private_live, private_tools = brain.lives[0]
    assert "[Your live status" in private_live and "call me boss" in private_live
    assert private_live.rstrip().splitlines()[-1].startswith("Now:")            # the clock stays last
    assert "Now: Tuesday 2026-10-20 10:" in private_live or "owner's local time (UTC-05:00" in private_live
    assert [t["function"]["name"] for t in private_tools] == ["star_lookup", "star_action"]
    public_live, public_tools = brain.lives[1]
    assert "[Your live status" not in public_live and "call me boss" not in public_live and public_tools is None
    assert all("[Your live status" not in turn["content"] for turn in service.memory.history(service.authorized(OWNER, None, 5)))


def test_tool_actions_start_jobs_and_disruptive_ones_wait_for_the_button(tmp_path, monkeypatch):
    import star.live_context as live_context

    async def no_web(question, **kwargs):
        return "", []
    monkeypatch.setattr(live_context, "auto_search", no_web)
    gates = {"1": FakeGate(brain_facts(tmp_path / "c")), "2": FakeGate()}
    brain = LiveBrain([("star_action", {"action": "restart_service", "brain": "1", "text": "star-brain"}),
                       ("star_action", {"action": "night_school_pause", "brain": "2"}),
                       ("star_lookup", {"section": "jobs"})])
    service = make_service(brain, gates, tmp_path)
    shown = []

    async def confirm(request):
        shown.append(request.label)

    async def run():
        await service.awareness.refresh()
        answer = await service.ask(service.authorized(OWNER, None, 5), "restart the brain and pause brain 2", private=True,
                                   confirm=confirm)
        await asyncio.gather(*(j.task for j in service.runner.jobs))
        return answer
    answer = asyncio.run(run())
    assert shown == ["restart a service (star-brain) on brain 1"]
    assert "confirm button" in answer and "still running" in answer and "pause night school on brain 2: running" in answer
    assert ("restart:star-brain", "") not in gates["1"].calls and ("ns-pause", "") in gates["2"].calls


# ------------------------------------------------------------------ prefs, persona, pc feed, gpu link

def test_owner_prefs_live_in_star_memory_and_refuse_secrets(tmp_path):
    prefs = OwnerPrefs(tmp_path / "m.sqlite3")
    assert prefs.items() == [] and not (tmp_path / "m.sqlite3").exists()      # reading creates nothing
    assert prefs_request("remember: I like dark UI") == ("remember", "I like dark UI")
    assert prefs_request("what do you remember about me?") == ("list", "")
    assert prefs_request("forget: dark UI") == ("forget", "dark UI") and prefs_request("hello") is None
    prefs.remember("I like dark UI")
    prefs.remember("my cat is called Pixel")
    assert "won't keep it" in prefs.remember("my password is hunter2-very-secret")
    assert prefs.items() == ["I like dark UI", "my cat is called Pixel"]
    assert prefs.forget("dark") == "Forgotten (1 item)." and prefs.items() == ["my cat is called Pixel"]
    from star.memory import Memory
    memory = Memory(tmp_path / "m.sqlite3")
    try:
        assert memory.get("discord-owner") == "my cat is called Pixel"
    finally:
        memory.close()


def test_persona_is_shared_and_the_check_catches_the_service_desk_voice():
    from star.agent import FAST_RULES, RULES
    from star.discord_bot.brain import system_prompt
    from star.voice.persona import VOICE_SYSTEM_PROMPT
    assert system_prompt().startswith(CORE) and RULES.startswith(DESKTOP_LINE) and FAST_RULES.startswith(DESKTOP_LINE)
    assert "Star (she/her)" in VOICE_SYSTEM_PROMPT
    bad = "Hello! I'm Star, an AI assistant here to help you. How can I assist you today?"
    assert any("banned phrase" in p for p in check_reply(bad))
    assert check_reply("Good! Night school's busy: 41 attempts today. You?") == []
    assert check_reply("No, I'm an AI, STAR. A hard-working one.", prompt="are you a real person?") == []
    assert any("P09" in p for p in check_reply("I'm an AI so I can't feel tired.", prompt="tired?"))
    assert check_reply("I can help you with code, images and research.", prompt="hey")


def test_pc_feed_reads_state_board_and_github_without_addresses(tmp_path):
    (tmp_path / "COLLAB").mkdir()
    (tmp_path / "STATE.md").write_text(
        "# STATE\n\n## 2026-10-20 WAVE (Claude lead)\n- x\n\n## Next actions\n- live on brain 1 (ssh star@203.0.113.7)\n"
        "- second\n\n## Other\n- not this\n", encoding="utf-8")
    (tmp_path / "COLLAB/BOARD.md").write_text(
        "- [CLAIMED] fresh item | claude | b | 2026-10-20 14:57:50Z | n\n"
        "- [CLAIMED] old item | codex | b | 2026-10-11 05:05Z | n\n- [DONE] done | claude | b | 2026-10-20 15:00Z | n\n",
        encoding="utf-8")
    gh_out = {"merged": [{"number": 526, "title": "fix", "mergedAt": "x"}],
              "open": [{"number": 530, "title": "t", "isDraft": False, "mergeStateStatus": "CLEAN",
                        "statusCheckRollup": [{"conclusion": "SUCCESS"}, {"status": "IN_PROGRESS", "conclusion": ""}]}],
              "release": [{"tagName": "v1.0.0", "isDraft": False, "createdAt": "2026-10-13T00:00:00Z"}]}
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        kind = "merged" if "merged" in args else "open" if "open" in args else "release"
        return SimpleNamespace(returncode=0, stdout=json.dumps(gh_out[kind]))
    monkey_which = pc_feed.shutil.which
    pc_feed.shutil.which = lambda name: "gh"
    try:
        feed = pc_feed.PcFeed(tmp_path, tmp_path, runner=runner, clock=lambda: 1000.0).build(NOW)
        feed2 = pc_feed.PcFeed(tmp_path, tmp_path, runner=runner, clock=lambda: 1000.0)
    finally:
        pc_feed.shutil.which = monkey_which
    assert feed["state_head"].startswith("2026-10-20 WAVE") and feed["state_next"][1] == "second"
    assert "203.0.113" not in json.dumps(feed) and "<login>" in feed["state_next"][0]
    assert [c["item"] for c in feed["claims"]] == ["fresh item"]
    assert feed["merged_today"] == [{"number": 526, "title": "fix"}] and feed["open_prs"][0]["checks"] == "pending"
    assert pc_feed.checks_state([{"conclusion": "FAILURE"}]) == "failing" and pc_feed.checks_state([]) == "none"
    assert pc_feed.default_root(Path("/w/worktrees/live")) == Path("/w").resolve()
    assert len(calls) == 3 and feed2 is not None


def test_remote_drawer_keeps_the_latest_pc_feed():
    pytest.importorskip("discord")
    from star.discord_bot.draw import DrawSettings
    from star.discord_bot.gpu_link import RemoteDrawer, encode

    class Reader:
        def __init__(self, lines):
            self.lines = list(lines)

        async def readline(self):
            return self.lines.pop(0) if self.lines else b""

    class Writer:
        def is_closing(self):
            return False

        def close(self):
            pass
    remote = RemoteDrawer(DrawSettings(), key=b"k" * 32)
    lines = [encode({"type": "hello"}), encode({"type": "pcfeed", "feed": {"tz_offset_min": -300}}),
             encode({"type": "pcfeed", "feed": "not a dict"})]
    asyncio.run(remote.handle(Reader(lines), Writer()))
    age, feed = remote.latest_feed()
    assert feed == {"tz_offset_min": -300} and age < 5


# ------------------------------------------------------------------ the bot itself (fake Discord)

class Typing:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass


class DMChannel:
    def __init__(self, discord):
        self.type, self.id, self.sent = discord.ChannelType.private, 5, []

    def typing(self):
        return Typing()

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


def test_dm_quiet_remember_and_confirm_button_through_the_real_bot(tmp_path, monkeypatch):
    discord = pytest.importorskip("discord")
    import star.live_context as live_context
    from star.discord_bot.bot import BotConfig, create_bot

    async def no_web(question, **kwargs):
        return "", []
    monkeypatch.setattr(live_context, "auto_search", no_web)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    env = {"STAR_DISCORD_BOT_TOKEN": "fake", "STAR_DISCORD_OWNER_IDS": str(OWNER), "STAR_DISCORD_DM_CHAT": "1",
           "STAR_DISCORD_LEARNING_DM_OPT_IN": "1", "STAR_DISCORD_LEARNING_REPORT_SSH": "u@brain1.example",
           "STAR_DISCORD_LEARNING_STATE": str(tmp_path / "l.sqlite3"), "STAR_DISCORD_GATE_1": "ssh:u@brain1.example",
           "STAR_DISCORD_CONFIG_DIR": str(tmp_path)}
    config = BotConfig.from_env(env)
    assert config.proactive.enabled and list(config.gates) == ["1"]
    gates = {"1": FakeGate(brain_facts(tmp_path / "g"))}
    brain = LiveBrain([("star_action", {"action": "restart_service", "brain": "1", "text": "brain"})])
    service = make_service(brain, gates, tmp_path)
    bot = create_bot(config, service=service)

    def dm(channel, text):
        return SimpleNamespace(guild=None, author=SimpleNamespace(id=OWNER, bot=False), channel=channel,
                               attachments=[], content=text, id=42)

    async def run():
        try:
            channel = DMChannel(discord)
            await bot.on_message(dm(channel, "quiet for 2 hours"))
            assert channel.sent[-1][0].startswith("Quiet until")
            await bot.on_message(dm(channel, "remember: I like short answers"))
            assert channel.sent[-1][0] == "Got it, I'll remember that."
            assert service.prefs.items() == ["I like short answers"]
            await bot.on_message(dm(channel, "restart the brain please"))     # a plain command: no model
            text, options = channel.sent[-1]
            assert text is None and options["embed"].title == "Confirm: restart a service (star-brain) on brain 1?"
            assert options["embed"].colour.value == embeds.AMBER and type(options["view"]).__name__ == "ActionConfirm"
            assert brain.lives == []
            await bot.on_message(dm(channel, "could you give the brain a fresh start"))   # chat: the model's tool
            assert "confirm button" in channel.sent[-2][0] and channel.sent[-1][1]["embed"].title.startswith("Confirm")
            assert ("restart:star-brain", "") not in gates["1"].calls
            names = {c.name for c in bot.tree.get_commands()}
            assert {"quiet", "run"} <= names
        finally:
            await bot.close()
    asyncio.run(run())


# ------------------------------------------------------------------ cards (embeds)

def test_cards_respect_discord_limits_and_fall_back_to_text():
    huge = embeds.card("t" * 400, description="d" * 5000,
                       fields=[embeds.field("n" * 300, "v" * 2000) for _ in range(30)], now=NOW)
    assert len(huge["title"]) == 256 and len(huge["description"]) <= 4096 and len(huge["fields"]) <= 25
    assert all(len(f["name"]) <= 256 and len(f["value"]) <= 1024 for f in huge["fields"])
    assert embeds.total_chars(huge) <= 6000
    assert huge["color"] == embeds.GOLD and huge["footer"]["text"] == "Star" and huge["timestamp"].startswith("2026-10-20")
    text = embeds.card_text(embeds.card("Done: x", fields=[embeds.field("Tries", 41)], now=NOW))
    assert text == "**Done: x**\nTries: 41"


def test_status_digest_alert_pr_drawing_and_confirm_cards(tmp_path):
    aware = Awareness({"1": FakeGate(brain_facts(tmp_path)), "2": FakeGate(error="could not reach brain 2")},
                      pc_feed=lambda: (5.0, FEED), clock=clock_at(NOW))
    asyncio.run(aware.refresh())
    fields, missing = aware.status_fields()
    names = [f["name"] for f in fields]
    assert names[:2] == ["Brain 1 \u00b7 night school", "Brain 1 \u00b7 lessons"] and "Work" in names
    assert "**4** tries \u00b7 **2** passed today" in fields[0]["value"]
    assert missing == ["brain 2: could not reach brain 2"]
    status = embeds.status_card(fields, missing, now=NOW)
    assert status["color"] == embeds.AMBER and status["fields"][-1]["name"] == "Can't see"
    digest = embeds.digest_card("evening", "Busy day.", fields, [], now=NOW)
    assert digest["title"] == "Evening note" and digest["description"] == "Busy day." and digest["color"] == embeds.GREEN
    failed = embeds.status_card(fields + [embeds.field("Brain 2 \u00b7 FAILED", "star-ns-brain")], [], now=NOW)
    assert failed["color"] == embeds.RED
    assert embeds.alert_card(["Lesson gate on brain 1: L200 active."], now=NOW)["color"] == embeds.GREEN
    prs = embeds.pr_card(12.0, FEED["open_prs"], FEED["merged_today"], now=NOW)
    assert [f["value"] for f in prs["fields"][:3]] == ["2", "1", "1"] and prs["color"] == embeds.RED
    one = embeds.pr_card(12.0, FEED["open_prs"], FEED["merged_today"], number=530, now=NOW)
    assert one["title"] == "PR #530" and one["color"] == embeds.GREEN and len(one["fields"]) == 1
    drawing = embeds.drawing_card("a red dragon", "star-drawing.png", seconds=14.2, now=NOW)
    assert drawing["image"] == {"url": "attachment://star-drawing.png"} and drawing["description"] == "a red dragon"
    assert embeds.confirm_card("restart a service (star-brain) on brain 1", now=NOW)["color"] == embeds.AMBER


def test_cards_become_real_discord_embeds():
    discord = pytest.importorskip("discord")
    built = discord.Embed.from_dict(embeds.status_card([embeds.field("Brain 1 \u00b7 night school", "x")], [], now=NOW))
    assert built.title == "What I'm up to" and built.colour.value == embeds.GREEN and len(built) <= 6000
    assert built.fields[0].inline is True and built.footer.text.startswith("Star")


def test_status_questions_get_the_card():
    for text in ("what are you doing?", "What did you learn today", "how's night school", "anything I should know?"):
        assert awareness.status_question(text), text
    for text in ("hey", "write me a round timer", "what is a RemoteEvent"):
        assert not awareness.status_question(text), text


def test_team_notes_come_only_from_the_private_corpus():
    from star.discord_bot.notes import NOT_SET_UP, search_notes

    class Client:
        def __init__(self, reply):
            self.reply, self.bodies = reply, []

        def _request(self, method, path, body, timeout):
            self.bodies.append((method, path, body))
            if isinstance(self.reply, Exception):
                raise self.reply
            return self.reply
    private = Client({"corpus": "private", "passages": [
        {"title": "knowledge-fix-20261020", "heading": "Watchdog", "text": "starkb/watchdog.py restarts after 2 fails"}]})
    text = asyncio.run(search_notes("what does the watchdog do", client=private))
    assert "knowledge-fix-20261020 > Watchdog: starkb/watchdog.py restarts" in text
    assert private.bodies[0] == ("POST", "/search", {"query": "what does the watchdog do", "corpus": "private",
                                                     "mode": "hybrid", "top": 4})
    # An older service ignores "corpus" and answers from the public docs: never shown as team notes.
    public = Client({"corpus": "public", "passages": [{"title": "Roblox FAQ", "text": "x"}]})
    assert asyncio.run(search_notes("night school", client=public)) == NOT_SET_UP
    assert asyncio.run(search_notes("night school", client=Client(ValueError("404")))) == NOT_SET_UP


def test_plain_commands_skip_the_model():
    from star.discord_bot.intents import command
    assert command("pause night school on brain 1") == ("night_school_pause", "1", "")
    assert command("Star, stop night school") == ("night_school_stop", "", "")
    assert command("resume night school on both") == ("night_school_resume", "both", "")
    assert command("restart the knowledge service on brain 1") == ("restart_service", "1", "knowledge")
    assert command("what's the status of PR 526?") == ("pr_status", "", "526")
    assert command("queue a practice idea: a shop that refuses to sell when broke") == (
        "practice_idea", "", "a shop that refuses to sell when broke")
    assert command("run a quick eval") == ("quick_eval", "", "")
    assert command("start a studio lab run") == ("studio_lab_run", "", "")
    for chat in ("how's night school going?", "what did you learn today?", "I restarted my PC", "hey"):
        assert command(chat) is None, chat


def test_reasoning_leaks_are_caught_and_stripped():
    from star.persona import leaked_reasoning, strip_reasoning
    leak = ("Brain 2 had 123 tries today. The owner asks how it's going. I should answer based on the live status "
            "line. It's busy but most tries couldn't run.")
    assert leaked_reasoning(leak)
    assert strip_reasoning(leak) == "Brain 2 had 123 tries today. It's busy but most tries couldn't run."
    assert not leaked_reasoning("Brain 2 had 123 tries today, 9 passed. Rough day.")
