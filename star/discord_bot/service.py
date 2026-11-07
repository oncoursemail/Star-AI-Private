"""STAR Discord chat, opt-in speech, and opt-in transcription services.

This service never dispatches desktop tools and never writes conversation memory.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
import json
from hashlib import sha256
from dataclasses import dataclass
from typing import Any

from .audio import decode_attachment, ffmpeg_path, synthesize_pcm, validate_attachment, voice_message
from .brain import DiscordBrain
from .core import (AccessPolicy, RateLimiter, SessionMemory, MAX_AUDIO_TEXT, MAX_PROMPT, clean_text,
                   session_key)


@dataclass(frozen=True)
class ResearchAnswer:
    text: str
    sources: tuple[dict, ...]


@dataclass(frozen=True)
class SpokenAnswer:
    transcript: str
    text: str
    audio: object


def source_lines(sources) -> str:
    """'Sources:' with up to five links (angle brackets: Discord shows no preview cards)."""
    lines = []
    for item in list(sources or [])[:5]:
        url = str(item.get("url", "")) if isinstance(item, dict) else ""
        if url.startswith("https://") and not any(c in url for c in " <>"):
            title = " ".join(str(item.get("title", "")).split())[:90]
            if item.get("stored"):          # from research memory: when STAR read it
                title = f"{title} (STAR's research notes, fetched {str(item.get('fetched', ''))[:10]})".strip()
            lines.append(f"- {title}: <{url}>" if title else f"- <{url}>")
    return ("\n\nSources:\n" + "\n".join(lines)) if lines else ""


def _accepts(brain, name: str) -> bool:
    """True when the brain's reply() takes the keyword `name` (DiscordBrain does; test doubles may not)."""
    import inspect
    try:
        return name in inspect.signature(brain.reply).parameters
    except (TypeError, ValueError):
        return False


def _accepts_live(brain) -> bool:
    return _accepts(brain, "live")


def lookup_schema() -> dict:
    from .awareness import SECTIONS
    return {"type": "function", "function": {
        "name": "star_lookup",
        "description": ("Only when your live status lines do not already answer him: look up one part of your "
                        "live status in detail (services, night school hours, lesson gate results, conductor, Studio "
                        "Lab, knowledge search, his work board, PRs, jobs he started, speed), or section 'notes' with "
                        "a query to search the team's private notes (what changed today, how a part of STAR works)."),
        "parameters": {"type": "object", "properties": {"section": {"type": "string", "enum": list(SECTIONS) + ["notes"]},
                                                        "query": {"type": "string", "description": "for notes: what to look for"}},
                       "required": ["section"]}}}


class DiscordService:
    def __init__(self, policy: AccessPolicy, *, brain=None, memory: SessionMemory | None = None,
                 ffmpeg_dir: str = "", searcher=None, rate_limiter: RateLimiter | None = None,
                 queue_seconds: float = 60.0, awareness: Any = None, runner: Any = None, prefs: Any = None,
                 research_store_path: Any = None) -> None:
        self.policy = policy
        # Research memory (star/research_store.py, the bot's own state folder): verified web answers with source and
        # fetch date; None (tests, a bare service) = search every time and keep nothing.
        self.research_store_path = research_store_path
        # Owner-private turns only: live status (awareness.Awareness), allow-listed actions (actions.ActionRunner)
        # and what he asked Star to remember (prefs.OwnerPrefs). All optional; without them chat is as before.
        self.awareness, self.runner, self.prefs = awareness, runner, prefs
        self.brain = brain or DiscordBrain()
        self.memory = memory or SessionMemory()
        self.ffmpeg_dir = ffmpeg_dir
        self._searcher = searcher
        self.rate_limiter = rate_limiter or RateLimiter()
        # A short queue (bounded by the rate limit) instead of refusing a quick follow-up DM.
        self.queue_seconds = queue_seconds
        # One owner conversation at a time to prevent two simultaneous answers from
        # committing out of order. CPU-heavy voice engines have their own locks.
        self._brain_lock = asyncio.Lock()
        self._tts_lock = asyncio.Lock()
        self._asr_lock = asyncio.Lock()
        self._tts = None
        self._asr = None

    def authorized(self, user_id: int, guild_id: int | None, channel_id: int) -> tuple:
        """Owner allowlist first (strangers learn nothing), then the owner's rate budget."""
        self.policy.require(user_id, guild_id, channel_id)
        self.rate_limiter.hit(user_id)
        return session_key(guild_id, channel_id, user_id)

    async def _lock_brain(self) -> None:
        # Don't queue a wall of interactions while a local model is busy.
        try:
            await asyncio.wait_for(self._brain_lock.acquire(), timeout=self.queue_seconds)
        except asyncio.TimeoutError as exc:
            raise ValueError("STAR is busy with another request. Try again shortly.") from exc

    async def ask(self, key: tuple, prompt: str, *, on_delta=None, on_status=None, private: bool = False,
                  confirm=None) -> str:
        """`on_delta(text_so_far)` / `on_status(note)`: optional async callbacks for a live reply.
        Passed only to a brain that streams (`brain.streams`); others answer in one piece.
        `private`: the owner's DM or a private slash answer. Only then does the turn carry Star's live status, his
        remembered preferences and the star_lookup / star_action tools; `confirm(request)` shows him the confirm
        button for a disruptive action."""
        question = clean_text(prompt, max_chars=MAX_PROMPT)
        if not question:
            raise ValueError("Ask STAR a question")
        await self._lock_brain()
        try:
            history = self.memory.history(key)
            live = {}
            if getattr(self.brain, "streams", False) is True and (on_delta or on_status):
                live = {"on_delta": on_delta, "on_status": on_status}
            remembered = question
            sources = []
            if _accepts_live(self.brain):
                # The time (and, for a news/"latest"/weather question, live web results) goes at the
                # very end of the message (docs/agents/clock-and-web-20261013.md).
                # Web results ride in `live`, not `evidence`: the model is chosen by the question
                # itself (a news summary does not need to queue for the main model).
                web, sources, clock_line = await self._live_context(question)
                status = self._private_context() if private else ""
                live["live"] = "\n\n".join(part for part in (web, status, clock_line) if part)
                if private and self.awareness is not None and _accepts(self.brain, "tools"):
                    from .actions import TOOL_SCHEMA
                    tools = [lookup_schema()] + ([TOOL_SCHEMA] if self.runner is not None else [])

                    async def handler(name, arguments):
                        return await self._tool(name, arguments, confirm)
                    live.update(tools=tools, tool_handler=handler)
                if not web:
                    # Stored with the time line it was sent with, so the next request starts with
                    # the bytes the server already read (prompt cache). Web results are not stored.
                    remembered = question + "\n\n" + clock_line
            answer = await self.brain.reply(question, history, **live)
            # The session keeps the answer as generated (what the server cached); the owner also sees
            # the links the answer was based on.
            self.memory.remember(key, remembered, answer)
            store_path = self._research_store_path()
            if sources and store_path is not None:
                from ..live_context import learn_later
                learn_later(store_path, question, answer, sources)
            return answer + source_lines(sources)
        finally:
            self._brain_lock.release()

    def _private_context(self) -> str:
        """Live status + remembered preferences for the owner's private turn (never stored in history)."""
        parts = []
        if self.awareness is not None:
            try:
                parts.append(self.awareness.summary())
            except Exception as exc:      # a broken status source must not break chat
                parts.append(f"[Your live status: unavailable ({type(exc).__name__})]")
        if self.prefs is not None:
            try:
                parts.append(self.prefs.context())
            except Exception:
                pass
        return "\n\n".join(p for p in parts if p)

    async def _tool(self, name: str, arguments: dict, confirm) -> str:
        if name == "star_lookup" and self.awareness is not None:
            if arguments.get("section") == "notes":
                from .notes import search_notes
                return await search_notes(str(arguments.get("query", "") or ""),
                                          settings=getattr(self.brain, "_settings", None))
            return self.awareness.detail(str(arguments.get("section", "overview")))
        if name == "star_action" and self.runner is not None:
            from .actions import parse_request
            request = parse_request(arguments.get("action", ""), str(arguments.get("brain", "") or ""),
                                    str(arguments.get("text", "") or ""), gates=self.runner.gates)
            if request.action.name == "pr_status":
                return await self.runner.run_now(request)
            if request.action.disruptive:
                if confirm is None:
                    return ("This needs his confirmation and no button can be shown here; tell him to use "
                            "/run in a DM with you.")
                await confirm(request)
                return (f"A confirm button for '{request.label}' is now shown under your reply. Nothing has started; "
                        "tell him briefly what it will do and to press it.")
            job = self.runner.start(request)
            return (f"Started '{job.label}' (job {job.id}); it is still running. Tell him you're on it and will "
                    "message him when it's done. Do not say it is done or paused yet.")
        return f"Unknown tool {name[:40]}"

    def _research_store_path(self):
        settings = getattr(self.brain, "_settings", None)
        if self.research_store_path is None or getattr(settings, "research_memory", True) is False:
            return None
        return self.research_store_path

    def speed(self) -> dict:
        stats = getattr(self.brain, "last_stats", None)
        return {} if stats is None else {"model": stats.model, "first_text_s": stats.first_text_s,
                                         "total_s": stats.total_s}

    async def _live_context(self, question: str) -> tuple[str, list, str]:
        """(web block or '', its sources, the time line). The web block is cited, untrusted results for
        a news/"latest"/weather question, or one line saying the search failed. Never raises."""
        from ..clock import now_line
        from ..live_context import auto_search, open_store
        store_path = self._research_store_path()
        store = open_store(store_path) if store_path is not None else None
        try:
            web, sources = await auto_search(question, settings=getattr(self.brain, "_settings", None),
                                             searcher=self._searcher, store=store)
        except Exception:
            web, sources = "", []
        finally:
            if store is not None:
                store.close()
        zone = self.awareness.owner_tz() if self.awareness is not None else None
        # On a server the container clock is UTC: name the owner's own time when it is known.
        return web, sources, now_line(datetime.now(zone) if zone is not None else None)

    async def inspect_image(self, key: tuple, prompt: str, jpeg: bytes, *, vision=None) -> str:
        """Owner image analysis (DM, /image or a confirmed /screen); bytes are never persisted."""
        if not isinstance(key, tuple) or len(key) != 3:
            raise PermissionError("Image analysis needs an authorized owner request")
        self.policy.require(key[2], key[0], key[1])
        from .dm_mode import DiscordVision
        await self._lock_brain()
        try:
            answer = await (vision or DiscordVision()).reply(prompt, jpeg)
            # Temporary context stores only the question and the reply, never an
            # image file, remote URL, original attachment or image bytes.
            self.memory.remember(key, "[Image discussed] " + prompt[:300], answer)
            return answer
        finally:
            self._brain_lock.release()

    async def compare_images(self, key: tuple, prompt: str, reference: bytes, rendered: bytes,
                             *, vision=None, native_receipt=None) -> str:
        """Compare exactly two owner-supplied, normalized private images.

        Only a short, text-only receipt enters temporary chat context; the
        screenshots are never stored, trained on, exported or cloud-routed.
        A future owner correction can refer to the image hashes, but still
        requires the existing desktop review and approval process.
        """
        if not isinstance(key, tuple) or len(key) != 3:
            raise PermissionError("Reference comparison requires an authorized owner")
        self.policy.require(key[2], key[0], key[1])
        from .dm_mode import DiscordVision
        question = clean_text(prompt, max_chars=MAX_PROMPT) or (
            "Compare the desired reference with STAR's result and suggest concrete fixes.")
        if native_receipt is not None and (not isinstance(prompt, str) or len(prompt) > 1000):
            raise ValueError("Keep native reference instructions within 1000 characters")
        await self._lock_brain()
        try:
            answer = await (vision or DiscordVision()).compare(question, reference, rendered)
            ref_hash = sha256(reference).hexdigest()
            render_hash = sha256(rendered).hexdigest()
            context = ""
            if native_receipt is not None:
                context = (f" [Native job={native_receipt.job_id} build={native_receipt.build_sha256}"
                           f" iteration={native_receipt.iteration} camera={native_receipt.camera}"
                           f" capture={native_receipt.capture_sha256} at={native_receipt.captured_at}]")
                answer = ("Advisory visual comparison only. Native evidence records "
                          f"{native_receipt.checked}/{native_receipt.total} checks; "
                          f"job state: {native_receipt.state}. "
                          "A visual opinion cannot override rejection, verify motion/rig/VFX behavior, "
                          "or approve a reusable lesson.\n\n" + answer)
            self.memory.remember(
                key, "[Image comparison reference=" + ref_hash + " result=" + render_hash
                + "]" + context + " " + (prompt if native_receipt is not None else question[:300]), answer)
            return answer
        finally:
            self._brain_lock.release()

    async def compare_lab_reference(self, key: tuple, prompt: str, reference: bytes, lab, *, vision=None) -> str:
        """Bind one owner reference and exact constraints to one immutable native capture.

        Later corrections use the existing pending-only CorrectionStore workflow.
        Native checks stay separate from the vision model's advisory opinions.
        """
        if not isinstance(key, tuple) or len(key) != 3:
            raise PermissionError("Native comparison requires an authorized owner")
        self.policy.require(key[2], key[0], key[1])
        from .lab_status import read_receipt, read_capture
        receipt = await asyncio.to_thread(read_receipt, lab)
        if not receipt.source:
            raise ValueError("Native comparison requires a build-bound producer receipt")
        _, rendered = await asyncio.to_thread(read_capture, lab, receipt)
        return await self.compare_images(key, prompt, reference, rendered, vision=vision, native_receipt=receipt)

    async def screen_capture(self, key: tuple, prompt: str, *, grab=None, vision=None) -> tuple[str, bytes]:
        """One capture of this PC's screen, ONLY after the owner pressed the confirm button.

        Returns (answer, jpeg) so the owner privately sees exactly what was captured.
        """
        from .dm_mode import capture_screen
        jpeg = await asyncio.to_thread(capture_screen, grab)
        question = clean_text(prompt, max_chars=MAX_PROMPT) or "Describe what is on this screen."
        answer = await self.inspect_image(key, question, jpeg, vision=vision)
        return answer, jpeg

    async def propose_dm_lesson(self, key: tuple, *, message_id: int,
                                text: str, kind: str, project: str, home=None):
        """An explicit remember request creates a reviewable local candidate.

        Even a Discord owner cannot skip desktop lesson approval or use a
        Discord conversation to grant agent or Roblox permissions.
        """
        if not isinstance(key, tuple) or len(key) != 3 or key[0] is not None:
            raise PermissionError("Lesson capture is owner-DM only")
        self.policy.require(key[2], None, key[1])
        from ..desktop_core import app_data
        from .dm_mode import capture_discord_lesson_candidate
        return await asyncio.to_thread(
            capture_discord_lesson_candidate,
            owner_id=key[2], allowed_owners=self.policy.owners,
            message_id=message_id, text=text, kind=kind, project=project,
            home=home if home is not None else app_data(),
        )

    async def propose_dm_correction(self, key: tuple, *, message_id: int, text: str, project: str, home=None):
        """The owner says STAR's last DM answer was wrong: a regression-test candidate plus a lesson candidate,
        both reviewed in STAR Desktop. The corrected question and answer come from this DM's own short memory."""
        if not isinstance(key, tuple) or len(key) != 3 or key[0] is not None:
            raise PermissionError("Corrections are owner-DM only")
        self.policy.require(key[2], None, key[1])
        turns = self.memory.history(key)
        question = next((t["content"] for t in reversed(turns) if t["role"] == "user"), "")
        answer = next((t["content"] for t in reversed(turns) if t["role"] == "assistant"), "")
        from ..desktop_core import app_data
        from .dm_mode import capture_discord_correction
        return await asyncio.to_thread(
            capture_discord_correction,
            owner_id=key[2], allowed_owners=self.policy.owners, message_id=message_id, text=text,
            question=question, answer=answer, project=project,
            home=home if home is not None else app_data(),
        )

    async def research(self, key: tuple, question: str) -> ResearchAnswer:
        """Optional cited web search; only existing STAR-configured search providers.

        Source URLs originate from the fixed Brave/Tavily gateway and must never
        grant filesystem, GitHub or Studio permissions to the bot.
        """
        from ..web_search import search_web, source_context
        query = clean_text(question, max_chars=600)
        if not query:
            raise ValueError("Give STAR a research question")
        await self._lock_brain()
        try:
            searcher = self._searcher or search_web
            sources = await asyncio.wait_for(searcher(query, limit=5), timeout=25)
            if not sources:
                raise ValueError("The configured search provider returned no usable sources")
            extra = {}
            if _accepts_live(self.brain):
                from ..clock import now_line
                extra["live"] = now_line()
            answer = await self.brain.reply(query, self.memory.history(key), evidence=source_context(sources),
                                            **extra)
            self.memory.remember(key, query, answer)
            return ResearchAnswer(answer, tuple(sources[:5]))
        finally:
            self._brain_lock.release()

    async def converse(self, key: tuple, *, filename: str, content_type: str | None,
                       data: bytes) -> SpokenAnswer:
        """Explicit voice-message question → private transcript + public spoken answer.

        This is turn-based conversation through uploaded audio, not live VC capture.
        The invoking Discord command must check permissions and communicate that
        the generated audio reply will be public before invoking this method.
        """
        transcript = await self.transcribe(filename=filename, content_type=content_type, data=data)
        answer = await self.ask(key, transcript)
        spoken = await self.voice_message(answer[:MAX_AUDIO_TEXT])
        return SpokenAnswer(transcript, answer, spoken)

    def forget(self, key: tuple) -> None:
        self.memory.forget(key)

    @staticmethod
    def _voice_settings():
        from ..desktop_core import app_data
        from ..voice.settings import VoiceSettings
        path = app_data() / "voice.json"
        if not path.is_file():
            return VoiceSettings().validate()
        try:
            return VoiceSettings.from_mapping(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return VoiceSettings().validate()

    def _speech(self, text: str) -> tuple[bytes, int]:
        from ..voice.engines import make_tts
        if self._tts is None:
            settings = self._voice_settings()
            self._tts = make_tts(settings.tts_engine, settings.voice, settings.speed, settings.device,
                                 lang=settings.tts_lang, gap_ms=settings.sentence_gap_ms,
                                 pitch_semitones=settings.pitch_semitones)
        return synthesize_pcm(self._tts, text)

    async def speak_pcm(self, text: str) -> tuple[bytes, int]:
        if len(text) > MAX_AUDIO_TEXT:
            raise ValueError("Discord speech is limited to 500 characters")
        async with self._tts_lock:
            return await asyncio.to_thread(self._speech, text)

    async def voice_message(self, text: str):
        pcm, rate = await self.speak_pcm(text)
        return await asyncio.to_thread(voice_message, pcm, rate, executable=ffmpeg_path(self.ffmpeg_dir))

    def _transcribe(self, pcm: bytes) -> str:
        from ..voice.engines import make_asr
        if self._asr is None:
            config = self._voice_settings()
            self._asr = make_asr(config.asr_engine, config.asr_model, config.device, config.asr_prompt)
        text = self._asr.transcribe(pcm, 16000)
        return clean_text(text, max_chars=MAX_PROMPT)

    async def transcribe(self, *, filename: str, content_type: str | None, data: bytes) -> str:
        validate_attachment(filename, content_type, len(data))
        async with self._asr_lock:
            pcm = await asyncio.to_thread(decode_attachment, data, executable=ffmpeg_path(self.ffmpeg_dir))
            transcript = await asyncio.to_thread(self._transcribe, pcm)
        if not transcript:
            raise ValueError("No intelligible speech was detected in the attachment")
        return transcript
