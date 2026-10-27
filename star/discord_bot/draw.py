"""Make an image from Discord: "draw a dragon" in a DM or mention, or `/draw prompt:`.

The picture is made exactly the way STAR Desktop's chat makes it (`make_picture` below: the careful pipeline of
`star.image_quality` when it is on in Settings, otherwise the single shot of `star.image_gen`; both on ComfyUI at
127.0.0.1 on this PC's graphics card), with the same checks and the same Settings. When
ComfyUI is not running, STAR starts the install it finds (the desktop's own launcher and search) and
stops it again after a quiet spell, so the graphics memory goes back to games.

Limits: one picture at a time (a second request is told to wait, not queued), the configured
owner only unless STAR_DISCORD_DRAW_ANYONE=1 (then members of the approved server too, never
strangers' DMs), and a timeout after which the job is cancelled in ComfyUI.
Pictures and ComfyUI's log go to ~/.star/discord-images, never into STAR Desktop's data folder.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import io
import logging
import os
from pathlib import Path
import re
import threading
from typing import Awaitable, Callable

from .core import RateLimited, clean_text, session_key

_LOG = logging.getLogger(__name__)

MAX_DRAW_PROMPT = 1500          # the desktop's limit (image_gen.generate)
MAX_DISCORD_FILE = 8 * 1024 * 1024
IDLE_STOP_SECONDS = 600         # stop a ComfyUI that the bot started after 10 quiet minutes
DEFAULT_TIMEOUT = 420           # the careful pipeline (rewrite, draw, judge, maybe a repair) takes 1.5 to 4 minutes
START_WAIT_SECONDS = 240        # a cold start on a busy PC took over 120 s (2026-10-14); 25-28 s when warm
TURN_ON_HINT = "Set STAR_DISCORD_DRAW=1 in ~/.star/discord-settings.env and restart the bot."
NO_SUBJECT = ("What should I draw? Say what you want to see, for example "
              "`draw a dragon over a castle at sunset` (or use `/draw`).")


def _flag(source, name: str, default: str) -> bool:
    raw = str(source.get(name, default)).strip() or default
    if raw not in {"0", "1"}:
        raise ValueError(f"{name} must be 0 or 1")
    return raw == "1"


@dataclass(frozen=True)
class DrawSettings:
    enabled: bool = True            # owner-only by default, local GPU only
    anyone: bool = False            # also members of the approved server (never strangers' DMs)
    timeout_seconds: int = DEFAULT_TIMEOUT
    mentions: bool = False          # answer @STAR mentions in the approved server (needs guild messages)
    on_pc: bool = True              # False on a server (STAR_DISCORD_HOST=server): the PC GPU worker draws

    @classmethod
    def from_env(cls, env=None) -> "DrawSettings":
        from .local_config import bot_host
        source = os.environ if env is None else env
        raw = str(source.get("STAR_DISCORD_DRAW_TIMEOUT", str(DEFAULT_TIMEOUT))).strip() or str(DEFAULT_TIMEOUT)
        if not raw.isdecimal() or not 30 <= int(raw) <= 900:
            raise ValueError("STAR_DISCORD_DRAW_TIMEOUT must be a number of seconds from 30 to 900")
        return cls(_flag(source, "STAR_DISCORD_DRAW", "1"), _flag(source, "STAR_DISCORD_DRAW_ANYONE", "0"),
                   int(raw), _flag(source, "STAR_DISCORD_MENTIONS", "0"), on_pc=bot_host(source) == "pc")


# ---- Which messages are picture requests (a port of the desktop's frontend/src/imageIntent.ts) ----
# Deliberately an order and not a guess: "draw a cat", "generate an image of ...", "make me a logo for ...",
# never "Can you create images?" (a question about STAR), code, diagrams or charts.

_TECHNICAL = re.compile(
    r"```|\b(?:code|script|luau|python|typescript|javascript|html|css|json|sql|regex|react|api|function|module|"
    r"component|plugin|programmatically|in code|ImageLabel|ImageButton|Decal|SurfaceAppearance|diagram|flowchart|"
    r"chart|graph|ascii|mermaid|uml|spreadsheet|schema|database|algorithm|repository|stack trace)\b", re.I)
_NOUN = (r"(?:image|picture|pic|photo|photograph|drawing|illustration|logo|icon|wallpaper|sprite|texture|artwork|"
         r"poster|portrait|graphic|sketch|render)")
_ART = rf"(?=(?:an?\s+)?{_NOUN}\b|{_NOUN}s\s+(?:of|showing|depicting)\b)"
_LEAD = (r"^(?:(?:please|pls|kindly|can you|could you|would you|will you|i want you to|i need you to|"
         r"i would like you to|i'd like you to|go ahead and)\s+){0,2}")
_NOT_A_PICTURE = (r"(?:conclusion|comparison|parallel|distinction|analogy|line|lesson|breath|plan|schedule|list|"
                  r"summary|table|timeline|outline)")
_COMMAND = re.compile(rf"{_LEAD}(?:generate|draw|make|create|render|paint|design|produce|sketch|illustrate|doodle)"
                      rf"\s+(?:me\s+)?{_ART}", re.I)
_DRAW = re.compile(rf"{_LEAD}(?:draw|paint|sketch|illustrate|doodle)\s+(?:me\s+)?"
                   rf"(?=(?:an?|some|the)\s+(?!{_NOT_A_PICTURE}\b)[a-z])", re.I)
_SHOW = re.compile(rf"{_LEAD}(?:show|give|send|get)\s+me\s+{_ART}", re.I)
_NEED = re.compile(rf"^(?:(?:i|we)\s+(?:really\s+)?(?:need|want|would\s+like)|(?:i|we)'d\s+like|"
                   rf"(?:can|could)\s+i\s+(?:have|get))\s+{_ART}", re.I)
_DESCRIBED = re.compile(rf"^(?:an?\s+)?{_NOUN}s?\s+(?:of|showing|depicting|for|with|featuring|about)\b", re.I)
_JUST_THE_WORD = re.compile(rf"^(?:an?\s+)?{_NOUN}s?[\s.!?]*$", re.I)
_ASKS_ABILITY = re.compile(r"^(?:please\s+)?(?:can|could|would|will)\s+you\b", re.I)
_GENERIC = re.compile(r"^(?:an?\s+)?(?:images?|pictures?|pics?)\s*(?:(?:of|showing|depicting)\s+|$)", re.I)
_MENTION = re.compile(r"<@!?\d{1,20}>")


def strip_mentions(text: str) -> str:
    """The message without Discord user mentions (`<@123>`), spaces tidied."""
    return " ".join(_MENTION.sub(" ", str(text or "")).split())


@dataclass(frozen=True)
class DrawIntent:
    prompt: str          # what the picture model gets; '' = the owner asked for a picture but said not what


def draw_intent(text: str) -> DrawIntent | None:
    """The picture request in a chat message, or None for an ordinary question."""
    request = strip_mentions(text).replace("‘", "'").replace("’", "'")
    if not request or len(request) > MAX_DRAW_PROMPT or _TECHNICAL.search(request):
        return None

    def ordered(match: re.Match, needs_description: bool = False) -> DrawIntent | None:
        rest = request[match.end():].strip()
        if needs_description and not _DESCRIBED.match(rest):
            return None
        # "Can you make a logo?" and "Can you create an image?" ask what STAR can do; they say nothing to draw.
        if _ASKS_ABILITY.match(request) and _JUST_THE_WORD.match(rest):
            return None
        # "Generate me a image": a picture, but of nothing yet (the bot asks what to draw).
        subject = re.sub(r"[\s.!?]+$", "", _GENERIC.sub("", rest)).strip()
        return DrawIntent(subject)

    command = _COMMAND.match(request) or _DRAW.match(request)
    if command:
        return ordered(command)
    described = _SHOW.match(request) or _NEED.match(request)
    if described:
        return ordered(described, True)
    return None


# ---- Prompt checks: the desktop's (1-1500 characters, checked again inside image_gen.generate), plus one
# hard line for a bot whose pictures can land in a server channel.
_MINOR = re.compile(r"\b(?:child|children|kid|kids|minor|minors|underage|toddler|infant|baby|preteen|teen|teenage|"
                    r"schoolgirl|schoolboy|loli|shota|\d{1,2}[- ]?(?:yo|year[- ]?old))\b", re.I)
_SEXUAL = re.compile(r"\b(?:nude|naked|nsfw|sex|sexual|sexy|porn|erotic|lewd|topless|undress(?:ed|ing)?|"
                     r"lingerie|hentai)\b", re.I)


def prompt_problem(prompt: str) -> str:
    """'' when the prompt may be drawn, otherwise the reason (shown to the requester)."""
    text = (prompt or "").strip()
    if not 1 <= len(text) <= MAX_DRAW_PROMPT:
        return f"An image prompt must be 1 to {MAX_DRAW_PROMPT} characters."
    if _MINOR.search(text) and _SEXUAL.search(text):
        return "STAR will not draw that."
    return ""


def draw_authorized(service, settings: DrawSettings, user_id: int, guild_id: int | None,
                    channel_id: int) -> tuple:
    """The owner as everywhere else; with STAR_DISCORD_DRAW_ANYONE=1 also anyone in an approved server
    channel (rate-limited per person). Strangers' DMs never reach the image engine."""
    try:
        return service.authorized(user_id, guild_id, channel_id)
    except RateLimited:
        raise
    except PermissionError:
        policy = service.policy
        if not (settings.anyone and guild_id is not None and guild_id in policy.guilds
                and (not policy.channels or channel_id in policy.channels)):
            raise
    service.rate_limiter.hit(user_id)
    return session_key(guild_id, channel_id, user_id)


@dataclass(frozen=True)
class Drawing:
    png: bytes
    filename: str
    prompt: str
    seconds: float
    seed: int
    width: int
    height: int
    model: str

    def caption(self) -> str:
        shown = re.sub(r"([\\*_~`|>])", r"\\\1", self.prompt[:1500])     # Discord markdown shown as typed
        return clean_text(f"**{shown}**\n-# Drawn on this PC in {self.seconds} s · {self.model} · "
                          f"{self.width} x {self.height} · seed {self.seed}", max_chars=1900)


def make_picture(settings, prompt: str, home: Path, *, size: str = "square", use_references: bool = False,
                 cancel_event=None) -> dict:
    """One text-to-image picture, the way the desktop chat makes it: the careful pipeline (rewrite, drafts, blind judge,
    repair, exact text) when `image_quality` is on and the owner has no workflow of their own, else the single shot."""
    from .. import image_gen, image_quality
    if image_quality.enabled(settings) and not str(getattr(settings, "comfy_workflow", "") or "").strip():
        return image_quality.generate_best(settings, prompt, home, size=size, use_references=use_references,
                                           cancel_event=cancel_event)
    return image_gen.generate(settings, prompt, home, size=size, use_references=use_references,
                              cancel_event=cancel_event)


def default_home() -> Path:
    return Path.home() / ".star" / "discord-images"


def _load_settings():
    from ..desktop_core import Settings, app_data
    settings = Settings.load(app_data() / "settings.json")      # read only
    settings.validate()
    return settings


def _fit_for_discord(png: bytes) -> tuple[bytes, str]:
    if len(png) <= MAX_DISCORD_FILE:
        return png, "png"
    from PIL import Image
    with Image.open(io.BytesIO(png)) as picture:
        out = io.BytesIO()
        picture.convert("RGB").save(out, format="JPEG", quality=90)
    return out.getvalue(), "jpg"


class Drawer:
    """One picture at a time on this PC's graphics card."""

    def __init__(self, config: DrawSettings, *, home: Path | None = None,
                 load_settings: Callable | None = None, generate: Callable | None = None,
                 engine_status: Callable | None = None, find_engine: Callable | None = None,
                 launcher=None, idle_seconds: float = IDLE_STOP_SECONDS) -> None:
        self.config = config
        self.home = Path(home) if home is not None else default_home()
        self._load_settings = load_settings or _load_settings
        self._generate = generate
        self._engine_status = engine_status
        self._find_engine = find_engine
        self._launcher = launcher
        self._idle_seconds = idle_seconds
        self._idle: asyncio.TimerHandle | None = None
        self._lock = asyncio.Lock()

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    def _parts(self):
        from .. import image_gen, media_actions
        if self._launcher is None:
            self._launcher = media_actions.ComfyLauncher()
        return (self._generate or make_picture, self._engine_status or image_gen.status,
                self._find_engine or media_actions.effective_comfy_home)

    async def _ensure_engine(self, settings, find, status, say) -> None:
        state = await asyncio.to_thread(status, settings)
        if state.get("running"):
            if state.get("missing"):
                raise ValueError("The image engine (ComfyUI) is running on the PC but its model files are missing: "
                                 + ", ".join(state["missing"])[:300] + ". Run scripts/media/setup_comfyui.sh models.")
            return
        if not find(settings):
            raise ValueError("The image engine is off: pictures are made by ComfyUI on the PC, it is not running, "
                             "and STAR found no ComfyUI install to start. Set it up with "
                             "scripts/media/setup_comfyui.sh (see docs/STAR_DISCORD_SETUP.md), or start ComfyUI "
                             "from STAR Desktop → Settings → Where STAR generates, then ask again.")
        await say("Starting the image engine on the PC (30 seconds to a few minutes)…")
        launcher = self._launcher
        assert launcher is not None  # _parts() creates it before an engine is started
        try:
            await asyncio.to_thread(launcher.start, settings, self.home, wait_seconds=START_WAIT_SECONDS)
        except (OSError, RuntimeError, ValueError) as exc:     # TimeoutError is an OSError
            raise ValueError("The image engine (ComfyUI) did not start: " + str(exc)[:400]
                             + " (The bot's copy of that log is ~/.star/discord-images/logs/comfyui.log.)") from exc

    async def draw(self, prompt: str, *, on_status: Callable[[str], Awaitable] | None = None) -> Drawing:
        if not self.config.enabled:
            raise ValueError("Making images is switched off for the Discord bot. " + TURN_ON_HINT)
        prompt = " ".join(str(prompt or "").split())
        problem = prompt_problem(prompt)
        if problem:
            raise ValueError(problem)
        if self._lock.locked():
            raise ValueError("STAR is already drawing a picture. Try again when it is done (about a minute).")

        async def say(text: str) -> None:
            if on_status is not None:
                try:
                    await on_status(text)
                except Exception as exc:     # a status edit must never stop the picture
                    _LOG.info("Draw status update failed (%s)", type(exc).__name__)

        async with self._lock:
            if self._idle is not None:
                self._idle.cancel()
                self._idle = None
            try:
                generate, status, find = self._parts()
                from ..comfy import ComfyError
                settings = await asyncio.to_thread(self._load_settings)
                try:
                    await self._ensure_engine(settings, find, status, say)
                    await say("Drawing…")
                    cancel = threading.Event()
                    job = asyncio.ensure_future(asyncio.to_thread(
                        generate, settings, prompt, self.home, size="square", use_references=False,
                        cancel_event=cancel))
                    done, _ = await asyncio.wait({job}, timeout=self.config.timeout_seconds)
                    if not done:
                        cancel.set()                         # image_gen stops the ComfyUI job at its next check
                        await asyncio.wait({job}, timeout=20)
                        if job.done() and not job.cancelled():
                            job.exception()                  # consumed: the timeout is the answer
                        raise ValueError(f"The picture was not finished after {self.config.timeout_seconds} "
                                         "seconds, so STAR cancelled it. The first picture after the engine "
                                         "starts is the slowest; try again.")
                    result = job.result()
                except ComfyError as exc:
                    raise ValueError(str(exc)) from exc
                note = result["note"]
                png, kind = _fit_for_discord(Path(result["path"]).read_bytes())
                return Drawing(png, f"star-drawing.{kind}", prompt, float(note["seconds"]), int(note["seed"]),
                               int(note["width"]), int(note["height"]), str(note["model"]))
            finally:
                self._schedule_idle_stop()

    def _schedule_idle_stop(self) -> None:
        launcher = self._launcher
        if launcher is None or not getattr(launcher, "running", lambda: False)() or self._idle_seconds <= 0:
            return
        loop = asyncio.get_running_loop()

        def stop() -> None:
            self._idle = None
            if not self._lock.locked():
                # Only a ComfyUI that this bot started (ComfyLauncher never stops one started by hand).
                loop.create_task(asyncio.to_thread(launcher.stop))
        self._idle = loop.call_later(self._idle_seconds, stop)

    def describe(self) -> str:
        if not self.config.enabled:
            return "off"
        who = "owner + approved server" if self.config.anyone else "owner only"
        return f"on ({who}, one at a time, {self.config.timeout_seconds} s limit)"
