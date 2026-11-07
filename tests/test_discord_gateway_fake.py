"""Offline gateway fake for the owner's 'talk to STAR on Discord' experience.

Real discord.py objects (bot, command tree, views) are built, but every interaction,
channel, model and screen grab is a local stub: no token, network, model or desktop.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from star.discord_bot import digest_task
from star.discord_bot.bot import BotConfig
from star.discord_bot.core import AccessPolicy, RateLimited, RateLimiter, split_message
from star.discord_bot.local_config import load_merged_env, parse_env_text
from star.discord_bot.service import DiscordService

OWNER, STRANGER, GUILD, CHANNEL = 111, 999, 222, 333
TOKEN = "fake-token-never-sent"


# ---------------------------------------------------------------- local config

def test_local_files_supply_token_and_ids_without_exposing_them(tmp_path):
    (tmp_path / "discord.env").write_text("# secret\nDISCORD_BOT_TOKEN='%s'\n" % TOKEN, encoding="utf-8")
    (tmp_path / "discord-settings.env").write_text(
        f"DISCORD_OWNER_ID={OWNER}\nDISCORD_GUILD_ID={GUILD}\nSTAR_DISCORD_DM_CHAT=1\n", encoding="utf-8")
    env = load_merged_env({"STAR_DISCORD_CONFIG_DIR": str(tmp_path), "APPDATA": "x"})
    assert env["STAR_DISCORD_BOT_TOKEN"] == TOKEN
    assert env["STAR_DISCORD_OWNER_IDS"] == str(OWNER) and env["STAR_DISCORD_GUILD_IDS"] == str(GUILD)
    assert env["APPDATA"] == "x"
    config = BotConfig.from_env(env)
    assert config.policy.owners == frozenset({OWNER}) and config.dm.enabled
    assert TOKEN not in repr(config.policy) and TOKEN not in repr(config.dm)
    # The process environment wins over the files.
    env = load_merged_env({"STAR_DISCORD_CONFIG_DIR": str(tmp_path), "STAR_DISCORD_OWNER_IDS": "5"})
    assert env["STAR_DISCORD_OWNER_IDS"] == "5"


def test_local_files_refuse_unknown_names_and_token_in_settings_file(tmp_path):
    with pytest.raises(ValueError, match="line 2") as info:
        parse_env_text("DISCORD_OWNER_ID=1\nOPENAI_API_KEY=sk-should-not-echo\n", origin="x")
    assert "sk-should-not-echo" not in str(info.value)
    (tmp_path / "discord-settings.env").write_text(f"DISCORD_BOT_TOKEN={TOKEN}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="discord.env") as info:
        load_merged_env({"STAR_DISCORD_CONFIG_DIR": str(tmp_path)})
    assert TOKEN not in str(info.value)


# ---------------------------------------------------------------- core helpers

def test_split_message_keeps_code_blocks_valid_and_under_discord_limit():
    code = "```lua\n" + "\n".join(f"local value{i} = {i}" for i in range(400)) + "\n```"
    text = "Here is the script:\n" + code + "\nDone."
    parts, overflow = split_message(text)
    assert overflow == "" and len(parts) > 1
    assert all(len(p) <= 2000 for p in parts)
    assert all(p.count("```") % 2 == 0 for p in parts)
    assert parts[1].startswith("```lua")
    many, rest = split_message("word " * 20000, max_parts=2)
    assert len(many) == 2 and rest


def test_rate_limit_applies_to_owner_only_and_strangers_learn_nothing():
    now = [0.0]
    service = DiscordService(AccessPolicy(frozenset({OWNER}), frozenset()),
                             rate_limiter=RateLimiter(limit=2, clock=lambda: now[0]))
    service.authorized(OWNER, None, CHANNEL)
    service.authorized(OWNER, None, CHANNEL)
    with pytest.raises(RateLimited, match="Slow down"):
        service.authorized(OWNER, None, CHANNEL)
    with pytest.raises(PermissionError) as info:
        service.authorized(STRANGER, None, CHANNEL)
    assert not isinstance(info.value, RateLimited)
    now[0] += 601
    service.authorized(OWNER, None, CHANNEL)


# ---------------------------------------------------------------- gateway fake

class FakeResponse:
    def __init__(self, log):
        self.log, self.done = log, False

    def is_done(self):
        return self.done

    async def defer(self, **kwargs):
        self.done = True
        self.log.append(("defer", kwargs))

    async def send_message(self, content=None, **kwargs):
        self.done = True
        self.log.append(("send_message", {"content": content, **kwargs}))


class FakeFollowup:
    def __init__(self, log):
        self.log = log

    async def send(self, content=None, **kwargs):
        self.log.append(("followup", {"content": content, **kwargs}))


def interaction(user=OWNER, guild=GUILD, channel=CHANNEL):
    log = []
    return SimpleNamespace(
        user=SimpleNamespace(id=user, voice=None), guild_id=guild, channel_id=channel, guild=None,
        response=FakeResponse(log), followup=FakeFollowup(log), log=log,
        app_permissions=SimpleNamespace(send_messages=True, attach_files=True, send_voice_messages=True))


class Brain:
    def __init__(self, answer="Offline STAR answer"):
        self.answer, self.prompts = answer, []

    async def reply(self, prompt, history, *, evidence=""):
        self.prompts.append(prompt)
        return self.answer


def make_bot(extra=None, brain=None, tmp_path=None):
    discord = pytest.importorskip("discord")
    from star.discord_bot.bot import create_bot
    env = {"STAR_DISCORD_BOT_TOKEN": TOKEN, "STAR_DISCORD_OWNER_IDS": str(OWNER),
           "STAR_DISCORD_GUILD_IDS": str(GUILD), "STAR_DISCORD_DM_CHAT": "1",
           "STAR_DISCORD_DM_IMAGES": "1", **(extra or {})}
    config = BotConfig.from_env(env)
    brain = brain or Brain()
    service = DiscordService(config.policy, brain=brain, rate_limiter=RateLimiter(limit=config.rate_limit))
    return discord, create_bot(config, service=service), service, brain


def embeds_text(log):
    out = []
    for _, kwargs in log:
        if kwargs.get("embed") is not None:
            out.append(kwargs["embed"].description or "")
        if kwargs.get("content"):
            out.append(kwargs["content"])
    return "\n".join(out)


def png_bytes():
    out = BytesIO()
    Image.new("RGB", (64, 48), (200, 30, 30)).save(out, format="PNG")
    return out.getvalue()


def test_top_level_commands_are_registered_with_the_star_group():
    discord, bot, _, _ = make_bot()

    async def check():
        try:
            names = {cmd.name for cmd in bot.tree.get_commands(type=discord.AppCommandType.chat_input)}
            assert {"ask", "image", "status", "screen", "digest", "star"} <= names
            intents = bot.intents
            assert not intents.message_content and not intents.members and not intents.presences
            assert not intents.guild_messages and intents.dm_messages
            for name in ("ask", "image", "status", "screen", "digest", "star"):
                command = bot.tree.get_command(name)
                payload = command.to_dict(bot.tree)
                assert payload["contexts"] == [0, 1], name  # server + bot DM, never group DMs
                assert payload["integration_types"] == [0], name  # guild install only
        finally:
            await bot.close()
    asyncio.run(check())


def test_ask_defers_with_thinking_indicator_and_only_answers_the_owner():
    discord, bot, _, brain = make_bot()
    ask = bot.tree.get_command("ask")

    async def run():
        try:
            stranger = interaction(user=STRANGER)
            await ask.callback(stranger, prompt="hi", private=True)
            assert brain.prompts == []
            assert stranger.log[0][0] == "send_message" and stranger.log[0][1]["ephemeral"] is True
            owner = interaction()
            await ask.callback(owner, prompt="What is a RemoteEvent?", private=True)
            assert owner.log[0] == ("defer", {"thinking": True, "ephemeral": True})
            assert brain.prompts == ["What is a RemoteEvent?"]
            assert "Offline STAR answer" in embeds_text(owner.log)
        finally:
            await bot.close()
    asyncio.run(run())


def test_long_slash_answer_continues_in_order_and_attaches_full_text_when_huge():
    discord, bot, _, brain = make_bot(brain=Brain("paragraph " * 1500))
    ask = bot.tree.get_command("ask")

    async def run():
        try:
            owner = interaction()
            await ask.callback(owner, prompt="long please", private=True)
            follow = [kw for kind, kw in owner.log if kind == "followup"]
            assert len(follow) == 4
            assert all(len(kw["embed"].description) <= 4096 for kw in follow)
            assert "file" in follow[-1] and "view" in follow[-1]
        finally:
            await bot.close()
    asyncio.run(run())


def test_image_command_normalizes_upload_and_uses_vision(monkeypatch):
    discord, bot, service, _ = make_bot()
    seen = []

    class Vision:
        async def reply(self, prompt, jpeg):
            seen.append((prompt, jpeg[:2]))
            return "The red panel overlaps the health bar"

    monkeypatch.setattr("star.discord_bot.dm_mode.DiscordVision", Vision)
    data = png_bytes()

    class Attachment:
        filename, content_type, size = "hud.png", "image/png", len(data)

        async def read(self):
            return data

    async def run():
        try:
            owner = interaction()
            await bot.tree.get_command("image").callback(owner, image=Attachment(), question="Check HUD",
                                                         private=True)
            assert seen == [("Check HUD", b"\xff\xd8")]
            assert "overlaps" in embeds_text(owner.log)
        finally:
            await bot.close()
    asyncio.run(run())


def test_screen_capture_is_off_by_default_and_needs_a_fresh_button_press(monkeypatch):
    discord, bot, service, _ = make_bot()

    async def off():
        try:
            owner = interaction()
            await bot.tree.get_command("screen").callback(owner, question="")
            assert "off" in embeds_text(owner.log)
        finally:
            await bot.close()
    asyncio.run(off())

    discord, bot, service, _ = make_bot({"STAR_DISCORD_SCREEN_CAPTURE": "1"})
    grabs = []

    async def fake_capture(key, prompt, *, grab=None, vision=None):
        grabs.append(prompt)
        return "Studio is open with an error in Output", b"\xff\xd8jpeg"

    monkeypatch.setattr(service, "screen_capture", fake_capture)

    async def on():
        try:
            owner = interaction()
            await bot.tree.get_command("screen").callback(owner, question="Any errors?")
            assert grabs == []  # asking is not capturing
            view = owner.log[0][1]["view"]
            assert view.timeout == 60
            stranger = interaction(user=STRANGER)
            assert await view.interaction_check(stranger) is False
            press = interaction()
            await view.confirm.callback(press)
            assert grabs == ["Any errors?"]
            assert any("file" in kw for _, kw in press.log)
            again = interaction()
            await view.confirm.callback(again)
            assert grabs == ["Any errors?"]  # one capture per confirmation
            assert "already used" in embeds_text(again.log)
        finally:
            await bot.close()
    asyncio.run(on())


def test_status_lists_switches_without_ids_or_token(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    discord, bot, _, _ = make_bot()

    async def run():
        try:
            owner = interaction()
            await bot.tree.get_command("status").callback(owner)
            text = embeds_text(owner.log)
            assert "DM chat:** on" in text and "PC screenshots:** off" in text
            assert TOKEN not in text and str(OWNER) not in text and str(GUILD) not in text
        finally:
            await bot.close()
    asyncio.run(run())


class Typing:
    def __init__(self, log):
        self.log = log

    async def __aenter__(self):
        self.log.append("typing")

    async def __aexit__(self, *args):
        return False


class DMChannel:
    def __init__(self, discord):
        self.type, self.id, self.sent, self.events = discord.ChannelType.private, CHANNEL, [], []

    def typing(self):
        return Typing(self.events)

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


def dm(discord, channel, text, user=OWNER):
    return SimpleNamespace(guild=None, author=SimpleNamespace(id=user, bot=False), channel=channel,
                           attachments=[], content=text, id=42)


def test_dm_chat_shows_typing_splits_long_replies_and_rate_limits():
    discord, bot, service, brain = make_bot({"STAR_DISCORD_RATE_LIMIT": "3"},
                                            brain=Brain("line of text\n" * 600))

    async def run():
        try:
            channel = DMChannel(discord)
            await bot.on_message(dm(discord, channel, "Explain everything"))
            assert channel.events == ["typing"]
            assert len(channel.sent) >= 3 and all(len(c) <= 2000 for c, _ in channel.sent)
            channel.sent.clear()
            await bot.on_message(dm(discord, channel, "help"))
            assert "normal chat" in channel.sent[0][0]
            channel.sent.clear()
            await bot.on_message(dm(discord, channel, "one more"))
            await bot.on_message(dm(discord, channel, "and another"))
            assert "Slow down" in channel.sent[-1][0]
            stranger = DMChannel(discord)
            await bot.on_message(dm(discord, stranger, "hello", user=STRANGER))
            assert stranger.sent == []
        finally:
            await bot.close()
    asyncio.run(run())


# ---------------------------------------------------------------- night school digest

def report(now, examples=137):
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    base = (now - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return ("# STAR night school: latest numbers\n"
            f"written {stamp} | started 2026-10-12T01:31:54Z | batches 38\n"
            "task attempts: 193 on 168 different tasks\npassed first time: 114\nfixed by a lesson: 23\n"
            "tasks by their latest attempt: failed 31, fixed 23, passed first 114\n"
            f"verified worked examples stored: {examples}\n"
            "proposed by the model: 73 | kept as candidate (fixed its task): 19 | discarded (task still failed): 54\n"
            "promoted to active: 1 | held back by validation: 3 | retired later: 1\n"
            "## Validation slice over time (tasks never used to write lessons)\n"
            f"- {base}: 6/12 with 0 lesson(s) (first baseline)\n")


def test_digest_is_opt_in_and_dms_once_per_real_change(tmp_path):
    assert not digest_task.DigestConfig.from_env({"STAR_DISCORD_OWNER_IDS": str(OWNER)}).enabled
    with pytest.raises(ValueError, match="exactly one"):
        digest_task.DigestConfig.from_env({"STAR_DISCORD_OWNER_IDS": str(OWNER),
                                           "STAR_DISCORD_LEARNING_DM_OPT_IN": "1"})
    with pytest.raises(ValueError, match="user@host"):
        digest_task.DigestConfig.from_env({"STAR_DISCORD_OWNER_IDS": str(OWNER),
                                           "STAR_DISCORD_LEARNING_DM_OPT_IN": "1",
                                           "STAR_DISCORD_LEARNING_REPORT_SSH": "x; rm -rf /"})
    config = digest_task.DigestConfig.from_env({
        "STAR_DISCORD_OWNER_IDS": str(OWNER), "STAR_DISCORD_LEARNING_DM_OPT_IN": "1",
        "STAR_DISCORD_LEARNING_REPORT_SSH": "star@brain.invalid",
        "STAR_DISCORD_LEARNING_STATE": str(tmp_path / "state" / "dms.sqlite3"),
        "STAR_DISCORD_LEARNING_DM_COOLDOWN_HOURS": "1"})
    assert config.owner_id == OWNER
    now = datetime.now(timezone.utc).replace(microsecond=0)
    current = {"text": report(now)}
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        if argv[-1] == digest_task.REMOTE_WATCHDOG_COMMAND:   # no knowledge watchdog on this fake server
            return SimpleNamespace(returncode=1, stdout=b"")
        assert argv[-1] == digest_task.REMOTE_REPORT_COMMAND and "BatchMode=yes" in argv
        return SimpleNamespace(returncode=0, stdout=current["text"].encode("utf-8"))

    sent = []

    async def send(body, visual):
        sent.append(body)

    async def run():
        if not digest_task.shutil.which("ssh"):
            pytest.skip("ssh client not installed")
        first = await digest_task.check_and_send(config, send, runner=runner, now=now)
        assert first["sent"] and "not Roblox Studio" in sent[0] and "137" in sent[0]
        again = await digest_task.check_and_send(config, send, runner=runner, now=now + timedelta(hours=2))
        assert not again["sent"] and len(sent) == 1  # same numbers: no DM
        current["text"] = report(now + timedelta(hours=2), examples=140)
        third = await digest_task.check_and_send(config, send, runner=runner, now=now + timedelta(hours=3))
        assert third["sent"] and "+3" in sent[1]
        assert "last digest: sent" in digest_task.ledger_state(config)
    asyncio.run(run())


def test_capture_screen_normalizes_a_stub_grab_and_reports_missing_desktop():
    from star.discord_bot.dm_mode import capture_screen
    jpeg = capture_screen(lambda: Image.new("RGB", (3840, 2160), (10, 20, 30)))
    assert jpeg.startswith(b"\xff\xd8")
    with Image.open(BytesIO(jpeg)) as shot:
        assert max(shot.size) <= 1536

    def no_desktop():
        raise OSError("screen grab failed")

    with pytest.raises(ValueError, match="no desktop session"):
        capture_screen(no_desktop)



def test_lab_readonly_screenshot_checksum_in_existing_discord_workflow(tmp_path):
    """The dedicated Discord workflow must exercise the new Lab artifact gate."""
    import hashlib
    import json
    from star.discord_bot.lab_status import LabSettings, read_receipt, read_capture, format_receipt

    image_out = BytesIO()
    Image.new("RGB", (35, 24), (5, 15, 45)).save(image_out, format="PNG")
    blob = image_out.getvalue()
    photo = tmp_path / "studio-frame.png"
    photo.write_bytes(blob)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    manifest = tmp_path / "latest.json"
    manifest.write_text(json.dumps({
        "version": 1, "job_id": "testplace-42",
        "engine": "roblox-studio", "state": "running",
        "phase": "playtesting", "task": "Verify map obstacle",
        "next_step": "Inspect the jump with four cameras",
        "checked": 2, "total": 5, "evidence": "native-studio",
        "updated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "capture_kind": "studio-viewport", "capture_file": photo.name,
        "capture_sha256": hashlib.sha256(blob).hexdigest(),
    }), encoding="utf-8")
    config = LabSettings.from_env({"STAR_DISCORD_LAB_STATUS": "1",
                                   "STAR_DISCORD_LAB_REPORT": str(manifest)})
    receipt = read_receipt(config)
    assert "**Status:** running" in format_receipt(receipt, now=now)
    filename, jpeg = read_capture(config, now=now)
    assert filename == "star-lab.jpg" and jpeg.startswith(b"\xff\xd8")
    photo.write_bytes(blob + b"corruption")
    with pytest.raises(ValueError, match="matches"):
        read_capture(config, now=now)
    assert not LabSettings.from_env({}).enabled


def test_reference_compare_and_lab_slash_are_in_discord_workflow(tmp_path):
    """Owner permissions, command availability and visual critique classifier."""
    from star.discord_bot.dm_mode import DMSettings, classify_owner_dm, is_visual_critique

    assert classify_owner_dm(
        "Not what I wanted", attachments=2, options=DMSettings(True, True)
    ).kind == "compare"
    assert is_visual_critique("I don't like that")
    assert is_visual_critique("I don’t like the animation")
    assert not is_visual_critique("Tell me about Roblox particle emitters")
    discord, bot, _, _ = make_bot(extra={
        "STAR_DISCORD_LAB_STATUS": "1",
        "STAR_DISCORD_LAB_REPORT": str(tmp_path / "latest.json"),
    })
    try:
        compare_command = bot.tree.get_command("compare")
        assert compare_command is not None
        assert compare_command.to_dict(bot.tree)["integration_types"] == [0]
        group = bot.tree.get_command("star")
        assert group.get_command("lab") is not None
        assert group.get_command("labshot") is not None
        assert not bot.intents.message_content and not bot.intents.guild_messages
        assert not bot.intents.presences
    finally:
        asyncio.run(bot.close())


def test_lab_and_work_phrases_stay_normal_chat_when_reports_are_off():
    """Default-off Lab and Work Pulse must not change DM behaviour: 'what is star working on' goes to the brain."""
    discord, bot, _, brain = make_bot()

    async def run():
        try:
            channel = DMChannel(discord)
            await bot.on_message(dm(discord, channel, "What is STAR working on?"))
            assert brain.prompts and "working on" in brain.prompts[-1]
            assert not any("Lab reports are disabled" in (c or "") for c, _ in channel.sent)
            assert not any("no live multi-worker report" in (c or "") for c, _ in channel.sent)
        finally:
            await bot.close()
    asyncio.run(run())


def test_private_work_command_and_dm_read_real_report_and_reject_strangers(tmp_path):
    import json
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = tmp_path / "work.json"
    report.write_text(json.dumps({
        "version": 1, "updated_at": now,
        "workers": [{"id": "coder-1", "kind": "coding", "state": "working",
                     "task": "Fix Studio network stress-test bottleneck",
                     "last_step": "Measured the queue", "next_step": "Rerun the benchmark",
                     "done": 2, "total": 4, "updated_at": now}],
    }), encoding="utf-8")
    discord, bot, _, brain = make_bot({
        "STAR_DISCORD_WORK_STATUS": "1", "STAR_DISCORD_WORK_REPORT": str(report)
    })

    async def run():
        try:
            direct = bot.tree.get_command("working")
            nested = bot.tree.get_command("star").get_command("working")
            assert direct is not None and nested is not None
            owner = interaction()
            await direct.callback(owner)
            assert owner.log[0] == ("defer", {"thinking": True, "ephemeral": True})
            answer = embeds_text(owner.log)
            assert "Coding" in answer and "checks 2/4" in answer
            assert "Fix Studio network stress-test bottleneck" in answer
            stranger = interaction(user=STRANGER)
            await nested.callback(stranger)
            assert "Fix Studio" not in embeds_text(stranger.log)
            channel = DMChannel(discord)
            await bot.on_message(dm(discord, channel, "Hey Star, what are you working on?"))
            assert "Fix Studio" in channel.sent[0][0] and brain.prompts == []
        finally:
            await bot.close()
    asyncio.run(run())
