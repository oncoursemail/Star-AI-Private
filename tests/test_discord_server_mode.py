"""The Discord bot on a STAR server (STAR_DISCORD_HOST=server, server/discord/deploy.sh) and the PC GPU worker.

The worker and the bot's RemoteDrawer meet over a loopback TCP pair here (a Unix socket plus SSH in real use).
Fakes only: no token, network, SSH, ComfyUI or model.
"""
import asyncio
import os
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from star.discord_bot import __main__ as bot_main
from star.discord_bot import gpu_link, gpu_worker
from star.discord_bot.bot import BotConfig
from star.discord_bot.core import RateLimiter
from star.discord_bot.draw import Drawing, DrawSettings
from star.discord_bot.gpu_link import (MAX_LINE, NO_KEY, OFFLINE, RemoteDrawer, decode, drawing_from_result, encode,
                                       sign, verify)
from star.discord_bot.local_config import SERVER_MARKER, bot_host, load_merged_env, parse_env_text
from star.discord_bot.service import DiscordService
from star.server_key_file import read_key_file

OWNER, GUILD, CHANNEL = 111, 222, 333
TOKEN = "fake-token-never-sent"
ROOT = Path(__file__).resolve().parents[1]
KEY = bytes(range(32))
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


def env(**extra):
    return {"STAR_DISCORD_BOT_TOKEN": TOKEN, "STAR_DISCORD_OWNER_IDS": str(OWNER),
            "STAR_DISCORD_GUILD_IDS": str(GUILD), "STAR_DISCORD_DM_CHAT": "1", **extra}


# ---------------------------------------------------------------- server mode settings

def test_host_setting_defaults_to_pc_and_is_checked():
    assert bot_host({}) == "pc"
    assert bot_host({"STAR_DISCORD_HOST": " Server "}) == "server"
    with pytest.raises(ValueError, match="pc or server"):
        bot_host({"STAR_DISCORD_HOST": "cloud"})
    assert parse_env_text("STAR_DISCORD_HOST=server", origin="x") == {"STAR_DISCORD_HOST": "server"}
    assert BotConfig.from_env(env()).host == "pc"
    config = BotConfig.from_env(env(STAR_DISCORD_HOST="server"))
    assert config.host == "server" and config.draw.on_pc is False
    assert DrawSettings.from_env({}).on_pc is True


def test_brain_key_comes_from_the_bot_settings_folder(tmp_path, monkeypatch):
    (tmp_path / "server_api_key").write_text("abc123key\n", encoding="utf-8")
    assert read_key_file(path=tmp_path / "server_api_key") == "abc123key"
    monkeypatch.delenv("STAR_SERVER_API_KEY", raising=False)
    monkeypatch.setattr("star.providers.get_api_key", lambda name: None)
    bot_main._server_key_fallback(tmp_path)
    assert os.environ.pop("STAR_SERVER_API_KEY") == "abc123key"


def test_pc_refuses_a_second_copy_while_the_server_marker_is_there(tmp_path, capsys):
    (tmp_path / SERVER_MARKER).write_text("brain 2\n", encoding="utf-8")
    settings = {**env(), "STAR_DISCORD_CONFIG_DIR": str(tmp_path)}
    config = BotConfig.from_env(settings)
    assert bot_main._run(config, settings) == bot_main.EXIT_CONFIG
    assert "runs on a STAR server now" in capsys.readouterr().err
    assert not (tmp_path / "discord-bot.lock").exists()        # stopped before taking the lock


def test_settings_folder_override_reads_the_server_secrets(tmp_path):
    (tmp_path / "discord.env").write_text(f"DISCORD_BOT_TOKEN={TOKEN}\n", encoding="utf-8")
    (tmp_path / "discord-settings.env").write_text(f"DISCORD_OWNER_ID={OWNER}\n", encoding="utf-8")
    merged = load_merged_env({"STAR_DISCORD_CONFIG_DIR": str(tmp_path), "STAR_DISCORD_HOST": "server"})
    assert merged["STAR_DISCORD_BOT_TOKEN"] == TOKEN and merged["STAR_DISCORD_HOST"] == "server"


# ---------------------------------------------------------------- signed jobs

def test_jobs_are_signed_fresh_and_well_formed():
    job = {"id": "a" * 32, "prompt": "a dragon", "ts": 1_000_000}
    message = {"type": "job", "job": job, "sig": sign(job, KEY)}
    assert verify(message, KEY, now=1_000_010) == job
    for bad, why in [({**message, "sig": sign(job, b"x" * 32)}, "bad signature"),
                     ({**message, "job": {**job, "prompt": "a cat"}}, "bad signature"),
                     ({"type": "job", "job": job}, "unsigned"),
                     (message, "stale")]:
        with pytest.raises(ValueError, match=why):
            verify(bad, KEY, now=1_000_000 + (10_000 if why == "stale" else 0))
    odd = {"id": "a" * 32, "prompt": "a dragon", "ts": 1_000_000, "extra": 1}
    with pytest.raises(ValueError, match="bad job"):
        verify({"job": odd, "sig": sign(odd, KEY)}, KEY, now=1_000_000)
    with pytest.raises(ValueError):
        verify(message, b"", now=1_000_000)                       # no key: nothing is accepted


def test_results_are_checked_before_they_reach_discord():
    import base64
    good = {"type": "result", "ok": True, "filename": "star-drawing.png", "image": base64.b64encode(PNG).decode(),
            "prompt": "p", "seconds": 1, "seed": 2, "width": 3, "height": 4, "model": "m"}
    assert drawing_from_result(good).png == PNG
    for change in [{"filename": "evil.exe"}, {"image": base64.b64encode(b"GIF89a").decode()},
                   {"image": "A" * (9 * 1024 * 1024)}, {"image": "not base64!"}]:
        with pytest.raises(ValueError):
            drawing_from_result({**good, **change})


# ---------------------------------------------------------------- bot <-> worker

class FakeDrawer:
    def __init__(self, gate=None):
        self.prompts, self.gate, self.busy = [], gate, False

    async def draw(self, prompt, *, on_status=None):
        self.prompts.append(prompt)
        await on_status("Starting the image engine on the PC…")
        if self.gate is not None:
            await self.gate.wait()
        return Drawing(PNG, "star-drawing.png", prompt, 1.5, 7, 64, 64, "fake-model")


async def wire(remote, worker):
    """Bot side listening, worker connected over loopback; returns (server, worker session task)."""
    server = await asyncio.start_server(remote.handle, "127.0.0.1", 0, limit=MAX_LINE + 4096)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port, limit=MAX_LINE + 4096)
    session = asyncio.ensure_future(worker.session(reader, writer))
    for _ in range(100):
        if remote.connected:
            break
        await asyncio.sleep(0.01)
    return server, session, writer


def test_worker_draws_a_signed_job_and_the_picture_comes_back():
    async def run():
        remote = RemoteDrawer(DrawSettings(on_pc=False), key=KEY, wait_seconds=5)
        worker = gpu_worker.Worker(FakeDrawer(), KEY)
        server, session, writer = await wire(remote, worker)
        assert remote.connected and "connected" in remote.describe()
        statuses = []

        async def on_status(text):
            statuses.append(text)
        picture = await remote.draw("a red   dragon", on_status=on_status)
        assert picture.png == PNG and picture.prompt == "a red dragon" and picture.model == "fake-model"
        assert worker.drawer.prompts == ["a red dragon"] and statuses == ["Starting the image engine on the PC…"]
        writer.close()
        await session
        server.close()
        for _ in range(100):
            if not remote.connected:
                break
            await asyncio.sleep(0.01)
        assert not remote.connected
    asyncio.run(run())


def test_offline_or_unconfigured_worker_answers_at_once():
    async def run():
        offline = RemoteDrawer(DrawSettings(on_pc=False), key=KEY)
        with pytest.raises(ValueError) as info:
            await asyncio.wait_for(offline.draw("a cat"), timeout=1)
        assert str(info.value) == OFFLINE and "offline" in offline.describe()
        with pytest.raises(ValueError) as info:
            await RemoteDrawer(DrawSettings(on_pc=False)).draw("a cat")
        assert str(info.value) == NO_KEY
        with pytest.raises(ValueError, match="switched off"):
            await RemoteDrawer(DrawSettings(enabled=False, on_pc=False), key=KEY).draw("a cat")
    asyncio.run(run())


def test_a_silent_worker_counts_as_offline(monkeypatch):
    async def run():
        remote = RemoteDrawer(DrawSettings(on_pc=False), key=KEY, wait_seconds=5)
        server, session, writer = await wire(remote, gpu_worker.Worker(FakeDrawer(), KEY))
        remote._link.last_seen -= gpu_link.STALE_SECONDS + 1        # the PC went to sleep: no "alive" for 45 s
        with pytest.raises(ValueError) as info:
            await remote.draw("a cat")
        assert str(info.value) == OFFLINE
        writer.close()
        await session
        server.close()
    asyncio.run(run())


def test_worker_dropping_mid_picture_is_reported_not_hung():
    async def run():
        gate = asyncio.Event()
        remote = RemoteDrawer(DrawSettings(on_pc=False), key=KEY, wait_seconds=5)
        server, session, writer = await wire(remote, gpu_worker.Worker(FakeDrawer(gate), KEY))
        job = asyncio.ensure_future(remote.draw("a cat"))
        await asyncio.sleep(0.1)
        writer.close()                                           # network gone
        with pytest.raises(ValueError, match="went offline"):
            await asyncio.wait_for(job, timeout=3)
        gate.set()
        await session
        server.close()
    asyncio.run(run())


class Collect:
    def __init__(self):
        self.lines = []

    def write(self, data):
        self.lines += [decode(line) for line in data.splitlines()]

    async def drain(self):
        return None

    def is_closing(self):
        return False


def test_worker_refuses_forged_and_repeated_jobs():
    import time

    async def run():
        drawer = FakeDrawer()
        worker = gpu_worker.Worker(drawer, KEY)
        job = {"id": "b" * 32, "prompt": "a dragon", "ts": int(time.time())}
        forged = {"id": "c" * 32, "prompt": "something else", "ts": int(time.time())}
        reader = asyncio.StreamReader()
        reader.feed_data(encode({"type": "job", "job": forged, "sig": sign(forged, b"z" * 32)}))
        reader.feed_data(encode({"type": "job", "job": job, "sig": sign(job, KEY)}))
        reader.feed_data(b"not json\n")
        reader.feed_eof()
        out = Collect()
        await worker.session(reader, out)
        await worker.current
        replay = asyncio.StreamReader()
        replay.feed_data(encode({"type": "job", "job": job, "sig": sign(job, KEY)}))
        replay.feed_eof()
        await worker.session(replay, out)
        assert drawer.prompts == ["a dragon"]                    # forged and replayed jobs never drawn
        results = [m for m in out.lines if m["type"] == "result"]
        assert len(results) == 1 and results[0]["ok"] is True and results[0]["id"] == "b" * 32
        assert out.lines[0] == {"type": "hello", "version": 1}
    asyncio.run(run())


def test_worker_reconnects_with_backoff():
    delays, calls = [], []

    async def connect(settings):
        calls.append(1)
        if len(calls) < 3:
            raise OSError("network unreachable")
        reader = asyncio.StreamReader()
        reader.feed_eof()                                        # server closed at once
        return reader, Collect(), None

    async def sleep(seconds):
        delays.append(seconds)

    asyncio.run(gpu_worker.run_forever(gpu_worker.Worker(FakeDrawer(), KEY), {}, connect=connect, sleep=sleep,
                                       rounds=5))
    assert len(calls) == 5 and delays == [5, 10, 20, 40, 60]


def test_worker_settings_ssh_command_and_hidden_logon_task(tmp_path):
    with pytest.raises(ValueError, match="STAR_GPU_WORKER_SSH"):
        gpu_worker.load_settings(tmp_path)
    (tmp_path / "gpu-worker.env").write_text("STAR_GPU_WORKER_SSH=star@brain.example\n", encoding="utf-8")
    settings = gpu_worker.load_settings(tmp_path)
    assert settings == {"target": "star@brain.example", "container": "starai", "socket": gpu_worker.DEFAULT_SOCKET,
                        "feed_root": ""}
    (tmp_path / "gpu-worker.env").write_text("STAR_GPU_WORKER_SSH=x@y\nSTAR_GPU_WORKER_CONTAINER=a;rm\n",
                                             encoding="utf-8")
    with pytest.raises(ValueError):
        gpu_worker.load_settings(tmp_path)
    command = gpu_worker.ssh_command(settings)
    assert "BatchMode=yes" in command and "ServerAliveInterval=15" in command and "-R" not in command
    assert command[-1].endswith("gpu_link relay /opt/star/discord/state/gpu-worker.sock")
    xml = gpu_worker.task_xml(user="PC\\owner", python=r"C:\venv\Scripts\pythonw.exe", checkout=Path(r"C:\star"))
    for part in ("<Hidden>true</Hidden>", "<RunLevel>LeastPrivilege</RunLevel>", "<LogonType>InteractiveToken",
                 "-m star.discord_bot.gpu_worker run", "pythonw.exe", "<LogonTrigger>"):
        assert part in xml
    ran = []
    assert gpu_worker.main(["remove"], runner=lambda args, text: ran.append(args) or SimpleNamespace(returncode=0)) == 0
    assert ran == [["schtasks", "/Delete", "/TN", "STAR GPU worker", "/F"]]


# ---------------------------------------------------------------- the server bot's commands

def interaction():
    log = []

    async def send_message(content=None, **kwargs):
        log.append(("send_message", {"content": content, **kwargs}))

    async def edit_original_response(**kwargs):
        log.append(("edit", kwargs))

    async def defer(**kwargs):
        log.append(("defer", kwargs))
    response = SimpleNamespace(send_message=send_message, is_done=lambda: False, defer=defer)
    return SimpleNamespace(user=SimpleNamespace(id=OWNER, voice=None), guild_id=GUILD, channel_id=CHANNEL,
                           guild=None, response=response, log=log, edit_original_response=edit_original_response,
                           followup=SimpleNamespace(send=send_message))


def test_server_bot_screen_needs_the_pc_and_draw_says_the_gpu_is_offline(tmp_path, monkeypatch):
    pytest.importorskip("discord")
    from star.discord_bot.bot import create_bot
    (tmp_path / "gpu-worker.key").write_text(KEY.hex(), encoding="utf-8")
    monkeypatch.setenv("STAR_DISCORD_CONFIG_DIR", str(tmp_path))
    config = BotConfig.from_env(env(STAR_DISCORD_HOST="server", STAR_DISCORD_SCREEN_CAPTURE="1"))
    bot = create_bot(config, service=DiscordService(config.policy, brain=SimpleNamespace(),
                                                    rate_limiter=RateLimiter(limit=30)))

    async def run():
        try:
            screen = interaction()
            await bot.tree.get_command("screen").callback(screen, question="what is open?")
            sent = screen.log[0][1]
            assert "needs the STAR app on your PC" in sent["embed"].description and "view" not in sent
            draw = interaction()
            await bot.tree.get_command("draw").callback(draw, prompt="a dragon", private=False)
            assert draw.log[-1][1]["content"] == "⚠️ " + OFFLINE
        finally:
            await bot.close()
    asyncio.run(run())


def test_unit_and_deploy_script_keep_the_bot_light_and_hold_no_addresses():
    unit = (ROOT / "server/discord/star-discord.service").read_text(encoding="utf-8")
    for line in ("Restart=on-failure", "MemoryMax=512M", "User=star-discord", "WantedBy=multi-user.target",
                 "KillSignal=SIGINT", "STAR_DISCORD_HOST=server", "STAR_DISCORD_CONFIG_DIR=/opt/star/discord/secrets",
                 "STAR_DISCORD_GPU_SOCKET=/opt/star/discord/state/gpu-worker.sock"):
        assert line in unit
    script = (ROOT / "server/discord/deploy.sh").read_text(encoding="utf-8")
    for text in (unit, script, (ROOT / "star/discord_bot/gpu_worker.py").read_text(encoding="utf-8")):
        assert not re.search(r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d+\.\d+", text)
    assert "chmod 600" in script and "-m 700" in script and "gpu-worker.key" in script
