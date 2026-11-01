"""Safe generated-image chat previews. Full-size images stay in STAR user data."""
from __future__ import annotations
import base64
import io
from functools import lru_cache
from pathlib import Path
import re
from ._lazy import lazy_attr, lazy_module
Image = lazy_attr("star.pil_safe", "Image")   # Pillow loads on first use, with the pixel limit set
ImageOps = lazy_module("PIL.ImageOps")

PREFIX = "STAR_GENERATED_IMAGE:"
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,190}$")

# A text model has no picture tool, so when it answers a "make me a ..." message with "I can't create or show images"
# the message was a picture request the chat's own detector (frontend/src/imageIntent.ts) did not recognise.
_REFUSAL = re.compile(
    r"\b(?:can(?:['’]t|not)|can not|unable to|not able to|(?:do not|don['’]t) have (?:the )?(?:ability|capability))\b"
    r"[^.!?\n]{0,60}?\b(?:create|generate|make|draw|produce|render|show|display)\b[^.!?\n]{0,40}?"
    r"\b(?:images?|pictures?|photos?|drawings?|illustrations?|artwork|visuals?)\b", re.I)
_MAKE_VERB = re.compile(
    r"^(?:(?:please|kindly|can you|could you|would you|will you|go ahead and|i want you to|i need you to|i'd like you to)\s+){0,2}"
    r"(?:generate|create|make|draw|render|paint|sketch|illustrate|design|produce|doodle|show|give|send|get)\b", re.I)
_FILLER = re.compile(r"\b(?:please|kindly|can|could|would|will|you|to|generate|create|make|draw|render|paint|sketch|illustrate|"
                     r"design|produce|doodle|show|give|send|get|me|an?|the|some|images?|pictures?|photos?|pics?|drawings?)\b", re.I)


def refused_to_make_picture(prompt: str, answer: str) -> bool:
    """True when a short text answer says STAR cannot make pictures to a message that asked for one to be made.

    "Can you create images?" (nothing left to draw once the filler words go) and a long answer that only
    mentions the limit while doing the work are not picture requests.
    """
    if len(answer or "") > 600 or not _REFUSAL.search(answer):
        return False
    request = (prompt or "").replace("’", "'").strip()
    return bool(_MAKE_VERB.match(request) and re.search(r"\w", _FILLER.sub(" ", request)))


def preview_image(path: Path) -> str:
    """Return a small thumbnail for Qt WebChannel, cached across chat refreshes."""
    path = path.resolve(strict=True)
    stat = path.stat()
    if stat.st_size > 25_000_000:
        raise ValueError("Generated image is too large for a chat preview")
    return _cached_preview(str(path), stat.st_mtime_ns, stat.st_size)

@lru_cache(maxsize=24)
def _cached_preview(filename: str, modified_ns: int, file_size: int) -> str:
    # Cache only encoded thumbnails; key includes mtime/size for invalidation.
    with Image.open(filename) as opened:
        if opened.width * opened.height > 55_000_000:
            raise ValueError("Generated image dimensions exceed safety limit")
        im = ImageOps.exif_transpose(opened)
        im.thumbnail((960, 960), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        im.convert("RGB").save(out, format="WEBP", quality=76, method=4)
    return "data:image/webp;base64," + base64.b64encode(out.getvalue()).decode("ascii")

def chat_image(home: Path, body: str) -> dict | None:
    if not body.startswith(PREFIX):
        return None
    name = body[len(PREFIX):]
    if not NAME.fullmatch(name) or name in (".", ".."):
        return {"text": "Generated image unavailable (invalid reference)."}
    directory = (home / "generated-images").resolve()
    path = (directory / name).resolve()
    if not path.is_relative_to(directory) or not path.is_file():
        return {"text": "Generated image unavailable (file missing)."}
    try:
        return {"text": _saved_answer(path), "image": preview_image(path)}
    except (OSError, ValueError):
        return {"text": "Generated image saved; preview unavailable. Open STAR data folder to view."}

def _saved_answer(path: Path) -> str:
    """The line written when the picture was made (time, model, size, seed), kept beside it."""
    import json
    try:
        note = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        answer = note.get("answer")
        if isinstance(answer, str) and 0 < len(answer) <= 600:
            return answer
    except (OSError, ValueError, AttributeError):
        pass
    return "Image generated locally · original saved in STAR/generated-images"

def generate_chat_image(settings, prompt: str, home: Path, cancel_event=None, *, size: str = "square",
                        source: Path | None = None, mask: Path | None = None) -> dict:
    """Make or edit a picture for the chat, on the place chosen in Settings.

    The built-in path is ComfyUI on this PC with FLUX.2 klein 4B (star/image_gen.py): text to
    image, edit an attached picture, or change only a masked area. An owner who configured
    their own API-format workflow keeps it for text to image; it never downloads custom nodes.
    """
    if not 1 <= len(prompt.strip()) <= 1500:
        raise ValueError("Image prompt must be 1–1500 characters")
    if source is None and not settings.comfy_workflow.strip():
        from . import image_quality
        if image_quality.enabled(settings):
            made = image_quality.generate_best(settings, prompt, home, size=size, cancel_event=cancel_event)
            return _on_disk(home, {"answer": made["answer"], "image": made["image"], "message": made["message"]})
    if source is not None or not settings.comfy_workflow.strip():
        from .image_gen import generate as generate_built_in
        made = generate_built_in(settings, prompt, home, size=size, source=source, mask=mask,
                                 cancel_event=cancel_event)
        return _on_disk(home, {"answer": made["answer"], "image": made["image"], "message": made["message"]})
    from . import media_places
    media_places.require(settings, "images", home)
    from .comfy import generate
    output = home / "generated-images"
    images = generate(Path(settings.comfy_workflow), prompt=prompt,
                      node_id=settings.comfy_prompt_node, output=output,
                      port=settings.comfy_port, timeout_seconds=240, cancel_event=cancel_event)
    first = images[0]
    if not NAME.fullmatch(first.name):
        raise RuntimeError("Unexpected generated image filename")
    return _on_disk(home, {"answer": "Image generated locally · original saved in STAR/generated-images",
                           "image": preview_image(first), "message": PREFIX + first.name})


def _on_disk(home: Path, result: dict) -> dict:
    """Refuse to hand the chat a reference to a file that is not in the generated-images folder."""
    name = result["message"][len(PREFIX):]
    if not (home / "generated-images" / name).is_file():
        raise RuntimeError("The picture was made but its file is not in the STAR data folder, so it was not added to the chat")
    return result


def latest_generated_path(home: Path, project: str, chat_id: str) -> Path | None:
    """The picture a follow-up such as "make it brown" refers to: the newest answer of this chat, if it is one.

    Only the newest answer counts. After a text answer there is no "it" to change, so an earlier
    picture is never picked up by a follow-up that is really about something else.
    """
    from .desktop_core import Conversations
    chats = Conversations(home / 'conversations.sqlite3')
    try:
        records = chats.recent_records(project, limit=80, chat_id=chat_id)
    finally:
        chats.close()
    directory = (home / 'generated-images').resolve()
    for row in reversed(records):
        if row['role'] != 'assistant':
            continue
        body = row['body']
        if not body.startswith(PREFIX):
            return None
        name = body[len(PREFIX):]
        if not NAME.fullmatch(name) or name in ('.', '..'):
            return None
        path = (directory / name).resolve()
        return path if path.is_relative_to(directory) and path.is_file() else None
    return None
