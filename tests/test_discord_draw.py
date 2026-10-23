"""Discord image making (/draw, "draw a dragon" DMs and mentions), phone-photo uploads, and the honest persona.

Scripted fakes only: no token, network, ComfyUI, GPU or model. Real discord.py objects are built
for the gateway tests (skipped when discord.py is not installed).
"""
import asyncio
from io import BytesIO
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
from PIL import Image

from star.discord_bot.bot import BotConfig
from star.discord_bot.brain import DiscordBrain, system_prompt
from star.discord_bot.core import AccessPolicy, RateLimiter
from star.discord_bot.dm_mode import (HEIC_HELP, MAX_UPLOAD_EDGE, download_attachment, prepare_discord_image)
from star.discord_bot.draw import (NO_SUBJECT, Drawer, DrawSettings, draw_authorized, draw_intent, prompt_problem)
from star.discord_bot.local_config import parse_env_text
from star.discord_bot.service import DiscordService

OWNER, MEMBER, GUILD, CHANNEL = 111, 555, 222, 333
TOKEN = "fake-token-never-sent"


# ---------------------------------------------------------------- intent routing

@pytest.mark.parametrize("text,prompt", [
    ("draw a dragon", "a dragon"),
    ("Draw me a red dragon over a castle at sunset", "a red dragon over a castle at sunset"),
    ("<@987654321> draw a cat wearing a hat", "a cat wearing a hat"),
    ("generate an image of a cat in space", "a cat in space"),
    ("Please create a picture of a forest at night", "a forest at night"),
    ("make me a logo for my game", "a logo for my game"),
    ("show me a picture of a waterfall", "a waterfall"),
    ("I need a poster of a racing car", "a poster of a racing car"),
    ("Generate me a image", ""),          # the owner's own message: a picture, subject still to ask
    ("create a picture", ""),
])
def test_picture_requests_are_routed_to_drawing(text, prompt):
    assert draw_intent(text).prompt == prompt


@pytest.mark.parametrize("text", [
    "Can you create images?", "Can you make a logo?", "What is a RemoteEvent?",
    "draw a conclusion from these numbers", "write a luau script that draws a line",
    "make a flowchart of my game loop", "make an image label in code", "I want a picture", "",
])
def test_questions_code_and_diagrams_stay_with_the_chat_model(text):
    assert draw_intent(text) is None


def test_prompt_checks_match_the_desktop_limits_plus_one_hard_line():
    assert prompt_problem("a dragon") == ""
    assert "1 to 1500" in prompt_problem("")
    assert "1 to 1500" in prompt_problem("x" * 1501)
    assert prompt_problem("a kid flying a kite") == ""
    assert prompt_problem("a naked child") == "STAR will not draw that."


def test_draw_settings_parse_and_are_allowed_in_the_local_settings_file():
    assert DrawSettings.from_env({}) == DrawSettings(True, False, 240, False)
    parsed = parse_env_text("STAR_DISCORD_DRAW=0\nSTAR_DISCORD_DRAW_ANYONE=1\nSTAR_DISCORD_DRAW_TIMEOUT=120\n"
                            "STAR_DISCORD_MENTIONS=1\n", origin="x")
    assert DrawSettings.from_env(parsed) == DrawSettings(False, True, 120, True)
    with pytest.raises(ValueError, match="30 to 900"):
        DrawSettings.from_env({"STAR_DISCORD_DRAW_TIMEOUT": "5"})
    with pytest.raises(ValueError, match="0 or 1"):
        DrawSettings.from_env({"STAR_DISCORD_DRAW": "yes"})


def test_owner_only_by_default_and_anyone_setting_covers_approved_server_only():
    service = DiscordService(AccessPolicy(frozenset({OWNER}), frozenset({GUILD})), brain=object())
    assert draw_authorized(service, DrawSettings(), OWNER, None, CHANNEL) == (None, CHANNEL, OWNER)
    with pytest.raises(PermissionError):
        draw_authorized(service, DrawSettings(), MEMBER, GUILD, CHANNEL)
    anyone = DrawSettings(anyone=True)
    assert draw_authorized(service, anyone, MEMBER, GUILD, CHANNEL) == (GUILD, CHANNEL, MEMBER)
    with pytest.raises(PermissionError):
        draw_authorized(service, anyone, MEMBER, None, CHANNEL)      # a stranger's DM: never
    with pytest.raises(PermissionError):
        draw_authorized(service, anyone, MEMBER, 777, CHANNEL)       # another server: never


# ---------------------------------------------------------------- the drawer (fake image backend)

def png_bytes(size=(64, 48), colour=(200, 30, 30)):
    out = BytesIO()
    Image.new("RGB", size, colour).save(out, format="PNG")
    return out.getvalue()


class Backend:
    """Stands in for image_gen.generate / image_gen.status / the ComfyUI launcher."""

    def __init__(self, *, running=True, installed=True, missing=(), block=False, fail=None):
        self.running, self.installed, self.missing, self.fail = running, installed, list(missing), fail
        self.release = threading.Event()
        if not block:
            self.release.set()
        self.prompts, self.starts, self.cancelled = [], 0, False

    def status(self, settings):
        return {"running": self.running, "missing": self.missing}

    def find(self, settings):
        return "C:/media/ComfyUI" if self.installed else ""

    def start(self, settings, home, *, wait_seconds=120.0):
        assert wait_seconds >= 120
        self.starts += 1
        self.running = True

    def is_running(self):
        return self.starts > 0

    def stop(self):
        self.running = False

    def generate(self, settings, prompt, home, *, size, use_references, cancel_event):
        assert size == "square" and use_references is False
        self.prompts.append(prompt)
        while not self.release.wait(0.02):
            if cancel_event.is_set():
                self.cancelled = True
                raise RuntimeError("STAR image generation cancelled by user")
        if self.fail:
            raise self.fail
        path = Path(home) / "generated-images" / "star-test.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png_bytes())
        return {"path": path, "note": {"seconds": 3.2, "seed": 42, "width": 1024, "height": 1024,
                                       "model": "FLUX.2 klein 4B (distilled, fp8)"}}


def drawer(tmp_path, backend, settings=DrawSettings(), **extra):
    launcher = SimpleNamespace(start=backend.start, running=backend.is_running, stop=backend.stop)
    return Drawer(settings, home=tmp_path, load_settings=lambda: SimpleNamespace(comfy_port=8188),
                  generate=backend.generate, engine_status=backend.status, find_engine=backend.find,
                  launcher=launcher, **extra)


def test_drawer_makes_a_picture_and_reports_progress(tmp_path):
    backend = Backend()
    steps = []

    async def say(text):
        steps.append(text)

    picture = asyncio.run(drawer(tmp_path, backend).draw("  a   dragon ", on_status=say))
    assert backend.prompts == ["a dragon"] and steps == ["Drawing…"]
    assert picture.png.startswith(b"\x89PNG") and picture.filename == "star-drawing.png"
    assert "**a dragon**" in picture.caption() and "seed 42" in picture.caption()


def test_drawer_starts_the_engine_on_demand_and_explains_a_missing_one(tmp_path):
    backend = Backend(running=False)
    steps = []

    async def say(text):
        steps.append(text)

    asyncio.run(drawer(tmp_path, backend, idle_seconds=0).draw("a castle", on_status=say))
    assert backend.starts == 1 and steps[0].startswith("Starting the image engine")

    for missing_engine in (Backend(running=False, installed=False),):
        with pytest.raises(ValueError, match="image engine is off") as info:
            asyncio.run(drawer(tmp_path, missing_engine).draw("a castle"))
        assert "setup_comfyui.sh" in str(info.value) and missing_engine.prompts == []
    with pytest.raises(ValueError, match="model files are missing"):
        asyncio.run(drawer(tmp_path, Backend(missing=["models/vae/flux2-vae.safetensors"])).draw("a castle"))


def test_drawer_turns_comfy_errors_into_owner_messages(tmp_path):
    from star.comfy import ComfyError
    backend = Backend(fail=ComfyError("out_of_memory", "The graphics card ran out of memory while making the image."))
    with pytest.raises(ValueError, match="ran out of memory"):
        asyncio.run(drawer(tmp_path, backend).draw("a castle"))


def test_drawer_switched_off_says_how_to_turn_it_on(tmp_path):
    backend = Backend()
    with pytest.raises(ValueError, match="STAR_DISCORD_DRAW=1"):
        asyncio.run(drawer(tmp_path, backend, DrawSettings(enabled=False)).draw("a castle"))
    assert backend.prompts == []


def test_one_picture_at_a_time(tmp_path):
    backend = Backend(block=True)
    draw = drawer(tmp_path, backend)

    async def run():
        first = asyncio.create_task(draw.draw("first"))
        while not backend.prompts:
            await asyncio.sleep(0.01)
        assert draw.busy
        with pytest.raises(ValueError, match="already drawing"):
            await draw.draw("second")
        backend.release.set()
        await first
        assert not draw.busy
        await draw.draw("third")                 # free again afterwards
    asyncio.run(run())
    assert backend.prompts == ["first", "third"]


def test_timeout_cancels_the_job_and_frees_the_lock(tmp_path):
    backend = Backend(block=True)
    draw = drawer(tmp_path, backend, DrawSettings(timeout_seconds=1))
    with pytest.raises(ValueError, match="not finished after 1 seconds"):
        asyncio.run(draw.draw("slow"))
    assert backend.cancelled and not draw.busy


# ---------------------------------------------------------------- persona

def test_system_prompt_never_claims_star_is_text_only():
    for prompt in (system_prompt(), system_prompt(draw=False, vision=False)):
        lowered = prompt.lower()
        assert "text-based" not in lowered and "text-only" not in lowered and "text based" not in lowered
        assert "web search" in lowered and "date and time" in lowered
    assert "Making images: ON" in system_prompt() and "/draw" in system_prompt()
    off = system_prompt(draw=False, vision=False)
    assert "STAR_DISCORD_DRAW=1" in off and "STAR_DISCORD_DM_IMAGES=1" in off
    assert system_prompt() == system_prompt()            # byte-stable (prompt cache)
    assert DiscordBrain(system=off)._system == off


# ---------------------------------------------------------------- phone photos

class Upload:
    def __init__(self, data, filename="IMG_0001.JPG", content_type="image/jpeg", reads=None, size=None):
        self.data, self.filename, self.content_type = data, filename, content_type
        self.size = len(data) if size is None else size
        self.reads = list(reads or [])
        self.calls = 0

    async def read(self):
        self.calls += 1
        return self.reads.pop(0) if self.reads else self.data


def big_photo_bytes(target=10 * 1024 * 1024):
    """A noisy 12 MP JPEG of roughly `target` bytes (noise does not compress, like a real photo's detail)."""
    import os
    width, height = 4032, 3024
    noise = Image.frombytes("RGB", (width, height), os.urandom(width * height * 3))
    for quality in (95, 90, 85, 75):
        out = BytesIO()
        noise.save(out, format="JPEG", quality=quality)
        if out.tell() <= 24 * 1024 * 1024:
            data = out.getvalue()
            if len(data) >= min(target, 6 * 1024 * 1024 + 1):
                return data
    return data


def test_a_10_mb_phone_photo_is_downscaled_on_the_pc():
    data = big_photo_bytes()
    assert len(data) > 6 * 1024 * 1024                    # bigger than the old limit that refused the owner
    jpeg = prepare_discord_image("IMG_0001.JPG", "image/jpeg", len(data), data)
    assert jpeg.startswith(b"\xff\xd8") and len(jpeg) < 2 * 1024 * 1024
    with Image.open(BytesIO(jpeg)) as shown:
        assert max(shown.size) == MAX_UPLOAD_EDGE and shown.size[0] > shown.size[1]


def test_exif_rotation_is_applied():
    out = BytesIO()
    exif = Image.Exif()
    exif[0x0112] = 6                                      # "rotate 90 degrees clockwise to display"
    Image.new("RGB", (80, 40), (10, 200, 10)).save(out, format="JPEG", exif=exif)
    data = out.getvalue()
    jpeg = prepare_discord_image("photo.jpg", "image/jpeg", len(data), data)
    with Image.open(BytesIO(jpeg)) as shown:
        assert shown.size == (40, 80) and "exif" not in shown.info


def test_heic_without_pillow_heif_gives_a_clear_message(monkeypatch):
    monkeypatch.setattr("star.discord_bot.dm_mode._heif_ready", lambda: False)
    with pytest.raises(ValueError) as info:
        prepare_discord_image("IMG_0002.HEIC", "image/heic", 10, b"0123456789")
    assert str(info.value) == HEIC_HELP


def test_download_retries_a_short_read_once_then_explains():
    data = png_bytes()
    flaky = Upload(data, reads=[data[:10]])
    assert asyncio.run(download_attachment(flaky)) == data and flaky.calls == 2
    broken = Upload(data, reads=[data[:10], data[:20]])
    with pytest.raises(ValueError, match="did not download completely"):
        asyncio.run(download_attachment(broken))
    huge = Upload(b"x", size=30 * 1024 * 1024)
    with pytest.raises(ValueError, match="up to 25 MB"):
        asyncio.run(download_attachment(huge))
    assert huge.calls == 0                                 # never downloaded


# ---------------------------------------------------------------- gateway fakes

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

    async def edit_original_response(**kwargs):
        log.append(("edit", kwargs))

    return SimpleNamespace(user=SimpleNamespace(id=user, voice=None), guild_id=guild, channel_id=channel,
                           guild=None, response=FakeResponse(log), followup=FakeFollowup(log), log=log,
                           edit_original_response=edit_original_response)


class Brain:
    def __init__(self):
        self.prompts = []

    async def reply(self, prompt, history, *, evidence=""):
        self.prompts.append(prompt)
        return "chat answer"


def make_bot(tmp_path, backend, extra=None):
    pytest.importorskip("discord")
    from star.discord_bot.bot import create_bot
    env = {"STAR_DISCORD_BOT_TOKEN": TOKEN, "STAR_DISCORD_OWNER_IDS": str(OWNER),
           "STAR_DISCORD_GUILD_IDS": str(GUILD), "STAR_DISCORD_DM_CHAT": "1", "STAR_DISCORD_DM_IMAGES": "1",
           **(extra or {})}
    config = BotConfig.from_env(env)
    brain = Brain()
    service = DiscordService(config.policy, brain=brain, rate_limiter=RateLimiter(limit=config.rate_limit))
    bot = create_bot(config, service=service, drawer=drawer(tmp_path, backend, config.draw))
    return bot, brain


class Sent:
    def __init__(self, channel, content, kwargs):
        self.channel, self.content, self.kwargs, self.deleted = channel, content, kwargs, False

    async def edit(self, content=None, **kwargs):
        self.channel.edits.append(content)
        self.content = content

    async def delete(self):
        self.deleted = True


class Typing:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *args):
        return False


class Channel:
    def __init__(self, kind):
        self.type, self.id, self.sent, self.edits = kind, CHANNEL, [], []

    def typing(self):
        return Typing()

    async def send(self, content=None, **kwargs):
        message = Sent(self, content, kwargs)
        self.sent.append(message)
        return message


def message(channel, text, *, user=OWNER, guild=None, attachments=(), mentions=()):
    return SimpleNamespace(guild=guild, author=SimpleNamespace(id=user, bot=False), channel=channel,
                           attachments=list(attachments), content=text, id=42, mentions=list(mentions))


def test_draw_command_is_registered_and_help_names_both_image_commands(tmp_path):
    bot, _ = make_bot(tmp_path, Backend())
    discord = pytest.importorskip("discord")

    async def run():
        try:
            names = {cmd.name for cmd in bot.tree.get_commands(type=discord.AppCommandType.chat_input)}
            assert {"draw", "image", "ask"} <= names
            payload = bot.tree.get_command("draw").to_dict(bot.tree)
            assert payload["contexts"] == [0, 1] and payload["integration_types"] == [0]
            assert not bot.intents.guild_messages and not bot.intents.message_content
            owner = interaction()
            await bot.tree.get_command("star").get_command("help").callback(owner)
            text = owner.log[0][1]["embed"].description
            assert "`/draw` — make an image" in text and "`/image` — look at an image" in text
        finally:
            await bot.close()
    asyncio.run(run())


def test_slash_draw_posts_the_png_with_its_prompt(tmp_path):
    backend = Backend()
    bot, _ = make_bot(tmp_path, backend)
    draw = bot.tree.get_command("draw")

    async def run():
        try:
            owner = interaction()
            await draw.callback(owner, prompt="a dragon over a castle", private=False)
            assert owner.log[0] == ("defer", {"thinking": True, "ephemeral": False})
            edits = [kw for kind, kw in owner.log if kind == "edit"]
            assert edits[0]["content"] == "🎨 Drawing…"
            final = edits[-1]
            # The picture arrives inside Star's drawing card (embeds.drawing_card), prompt as the description.
            assert final["content"] is None and final["embed"].description == "a dragon over a castle"
            assert final["embed"].image.url == "attachment://star-drawing.png"
            assert final["attachments"][0].filename == "star-drawing.png"
            stranger = interaction(user=MEMBER)
            await draw.callback(stranger, prompt="a cat", private=False)
            assert stranger.log[0][0] == "send_message" and stranger.log[0][1]["ephemeral"] is True
            assert backend.prompts == ["a dragon over a castle"]
        finally:
            await bot.close()
    asyncio.run(run())


def test_slash_draw_when_the_gpu_backend_is_off(tmp_path):
    backend = Backend(running=False, installed=False)
    bot, _ = make_bot(tmp_path, backend)

    async def run():
        try:
            owner = interaction()
            await bot.tree.get_command("draw").callback(owner, prompt="a cat", private=True)
            final = [kw for kind, kw in owner.log if kind == "edit"][-1]
            assert final["content"].startswith("⚠️ The image engine is off") and "attachments" not in final
        finally:
            await bot.close()
    asyncio.run(run())


def test_owner_dm_draw_request_shows_drawing_then_the_picture(tmp_path):
    discord = pytest.importorskip("discord")
    backend = Backend()
    bot, brain = make_bot(tmp_path, backend)

    async def run():
        try:
            dm = Channel(discord.ChannelType.private)
            await bot.on_message(message(dm, "draw a dragon"))
            assert dm.sent[0].content == "🎨 Drawing…" and dm.sent[0].deleted
            picture = dm.sent[1]
            assert picture.kwargs["embed"].description == "a dragon" and picture.kwargs["file"].filename == "star-drawing.png"
            assert brain.prompts == []                        # not sent to the chat model
            dm.sent.clear()
            await bot.on_message(message(dm, "Generate me a image"))
            assert [m.content for m in dm.sent] == [NO_SUBJECT]
            dm.sent.clear()
            await bot.on_message(message(dm, "Can you create images?"))
            assert brain.prompts == ["Can you create images?"]   # a question goes to the chat model
        finally:
            await bot.close()
    asyncio.run(run())


def test_owner_dm_draw_while_busy_and_when_switched_off(tmp_path):
    discord = pytest.importorskip("discord")
    backend = Backend(block=True)
    bot, _ = make_bot(tmp_path, backend)

    async def run():
        try:
            dm = Channel(discord.ChannelType.private)
            first = asyncio.create_task(bot.on_message(message(dm, "draw a slow dragon")))
            while not backend.prompts:
                await asyncio.sleep(0.01)
            await bot.on_message(message(dm, "draw a second dragon"))
            assert any("already drawing" in (text or "") for text in dm.edits)
            backend.release.set()
            await first
        finally:
            await bot.close()
    asyncio.run(run())

    bot, _ = make_bot(tmp_path, Backend(), {"STAR_DISCORD_DRAW": "0"})

    async def off():
        try:
            dm = Channel(discord.ChannelType.private)
            await bot.on_message(message(dm, "draw a dragon"))
            assert "STAR_DISCORD_DRAW=1" in dm.edits[-1]
        finally:
            await bot.close()
    asyncio.run(off())


def test_mentions_are_opt_in_and_draw_in_the_approved_server(tmp_path):
    discord = pytest.importorskip("discord")
    backend = Backend()
    bot, _ = make_bot(tmp_path, backend, {"STAR_DISCORD_MENTIONS": "1", "STAR_DISCORD_DRAW_ANYONE": "1"})
    assert bot.intents.guild_messages and not bot.intents.message_content
    me = SimpleNamespace(id=4242)

    async def run():
        try:
            bot._connection.user = me
            room = Channel(discord.ChannelType.text)
            guild = SimpleNamespace(id=GUILD)
            await bot.on_message(message(room, "<@4242> draw a lighthouse", user=MEMBER, guild=guild, mentions=[me]))
            assert room.sent[-1].kwargs["file"].filename == "star-drawing.png"
            room.sent.clear()
            await bot.on_message(message(room, "draw a lighthouse", user=MEMBER, guild=guild))   # no mention
            other = SimpleNamespace(id=999)
            await bot.on_message(message(room, "<@4242> draw a cat", user=MEMBER, guild=other, mentions=[me]))
            assert room.sent == [] and backend.prompts == ["a lighthouse"]
        finally:
            await bot.close()
    asyncio.run(run())


def test_dm_photo_over_the_old_6_mib_limit_reaches_the_vision_model(tmp_path, monkeypatch):
    discord = pytest.importorskip("discord")
    seen = []

    class Vision:
        async def reply(self, prompt, jpeg):
            seen.append((prompt, len(jpeg)))
            return "A cat on a sofa"

    monkeypatch.setattr("star.discord_bot.dm_mode.DiscordVision", Vision)
    bot, _ = make_bot(tmp_path, Backend())
    data = big_photo_bytes()

    async def run():
        try:
            dm = Channel(discord.ChannelType.private)
            await bot.on_message(message(dm, "Look at this", attachments=[Upload(data)]))
            assert seen and seen[0][0] == "Look at this" and seen[0][1] < 2 * 1024 * 1024
            assert "A cat on a sofa" in dm.sent[-1].content
        finally:
            await bot.close()
    asyncio.run(run())


def test_heic_photo_is_converted_when_pillow_heif_is_installed():
    pillow_heif = pytest.importorskip("pillow_heif")
    pillow_heif.register_heif_opener()
    out = BytesIO()
    Image.new("RGB", (320, 240), (30, 60, 200)).save(out, format="HEIF")
    data = out.getvalue()
    jpeg = prepare_discord_image("IMG_0003.HEIC", "image/heic", len(data), data)
    with Image.open(BytesIO(jpeg)) as shown:
        assert shown.format == "JPEG" and shown.size == (320, 240)


def _photo_48mp(fmt):
    """An 8000 x 6000 (48 MP) picture: a smooth gradient, so the file stays small enough to build quickly."""
    gradient = Image.linear_gradient("L").resize((8000, 6000))
    picture = Image.merge("RGB", (gradient, gradient.transpose(Image.Transpose.FLIP_LEFT_RIGHT), gradient))
    out = BytesIO()
    if fmt == "JPEG":
        exif = Image.Exif()
        exif[0x0112] = 6                                  # portrait phone photo
        picture.save(out, format="JPEG", quality=90, exif=exif)
    else:
        picture.save(out, format=fmt)
    return out.getvalue()


@pytest.mark.parametrize("name,kind,fmt", [("IMG_48MP.JPG", "image/jpeg", "JPEG"),
                                           ("IMG_48MP.PNG", "image/png", "PNG"),
                                           ("IMG_48MP.HEIC", "image/heic", "HEIF")])
def test_a_48_mp_phone_photo_is_shrunk_despite_star_global_pixel_limit(name, kind, fmt):
    from star.pil_safe import Image as SafeImage           # sets STAR's global limit (20 MP, error above 40 MP)
    assert SafeImage.MAX_IMAGE_PIXELS == 20_000_000
    if fmt == "HEIF":
        pillow_heif = pytest.importorskip("pillow_heif")
        pillow_heif.register_heif_opener()
    data = _photo_48mp(fmt)
    with pytest.raises(SafeImage.DecompressionBombError):
        SafeImage.open(BytesIO(data))                        # the global limit still applies everywhere else
    jpeg = prepare_discord_image(name, kind, len(data), data)
    with Image.open(BytesIO(jpeg)) as shown:
        expected = (1176, 1568) if fmt == "JPEG" else (1568, 1176)
        assert shown.size == expected
    assert SafeImage.MAX_IMAGE_PIXELS == 20_000_000         # unchanged


def test_oversized_uploads_are_still_refused_on_the_discord_path():
    from star.pil_safe import Image as SafeImage  # noqa: F401  (global limit active)
    out = BytesIO()
    Image.new("L", (9000, 7000)).save(out, format="PNG")    # 63 MP: above the 60 MP Discord limit for non-JPEG
    data = out.getvalue()
    with pytest.raises(ValueError, match="too large"):
        prepare_discord_image("huge.png", "image/png", len(data), data)
