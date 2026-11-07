"""What a chat turn's attachments become before the model sees them.

Pictures go as they are; documents are handed to the document tools. A video becomes sampled frames plus a transcript of its sound
(`star.video_understanding`), sent only to the place chosen for video understanding. An audio
file becomes its transcript. A project's pinned visual references join a turn that is about
how something looks. A message that only links to a video gets the rule that STAR has not
watched it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Callable

from . import media_places, references, video_understanding

IMAGE_CAP = 4           # pictures per model request (star.brain_router.select_route allows 0..4)


@dataclass
class TurnMedia:
    pictures: list[Path] = field(default_factory=list)
    documents: list[Path] = field(default_factory=list)  # text, PDF, Office and data files (star/documents.py)
    extras: list[str] = field(default_factory=list)     # lines added after the owner's words
    footer: str = ''                                    # added to the answer by STAR itself
    video: video_understanding.Evidence | None = None
    references: int = 0

    def prompt(self, owner_text: str) -> str:
        return owner_text + ('\n\n' + '\n'.join(self.extras) if self.extras else '')


def prepare_turn(settings, home: Path, prompt: str, selected: list[Path], workdir: Path, *,
                 cancelled: Callable[[], bool] | None = None, asr=None,
                 transcribe_audio: Callable[[Path], str] | None = None) -> TurnMedia:
    from .documents import DOCUMENT_EXTENSIONS
    from .media_features import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS
    turn = TurnMedia()
    videos = [path for path in selected if path.suffix.lower() in VIDEO_EXTENSIONS]
    audio = [path for path in selected if path.suffix.lower() in AUDIO_EXTENSIONS]
    # Documents are read by the document tools, never sent as pictures.
    turn.documents = [path for path in selected if path.suffix.lower() in DOCUMENT_EXTENSIONS]
    turn.pictures = [path for path in selected
                     if path not in videos and path not in audio and path not in turn.documents]
    if len(videos) > 1:
        raise ValueError('Attach one video at a time: STAR samples a few frames per message.')
    if len(turn.pictures) > IMAGE_CAP:
        turn.pictures = turn.pictures[:IMAGE_CAP]
        turn.extras.append(f'Only the first {IMAGE_CAP} pictures were sent to respect context limits.')
    for path in audio:
        if transcribe_audio is None:
            from .media_features import transcribe_audio as transcribe_audio
        turn.extras.append(f'Audio transcript from {path.name}: {transcribe_audio(path)}')
    if videos:
        # Frames of the owner's video go only where Settings says video understanding runs.
        media_places.require_video_provider(settings, home)
        room = IMAGE_CAP - len(turn.pictures)
        if room < 1:
            raise ValueError(f'Attach the video with at most {IMAGE_CAP - 1} pictures, so there is room for its frames.')
        # Explicit local opt-in: never let a model-selected prompt change the sampling mode.
        sampling = ('adaptive' if os.environ.get('STAR_VIDEO_FRAME_SAMPLING') == 'adaptive'
                    else 'uniform')
        evidence = video_understanding.prepare(videos[0], workdir / 'video', frames=room,
                                               ffmpeg_dir=getattr(settings, 'ffmpeg_dir', ''),
                                               asr=asr, cancelled=cancelled,
                                               frame_sampling=sampling)
        turn.video = evidence
        turn.pictures.extend(evidence.frames)
        turn.extras.append(video_understanding.evidence_text(evidence))
        turn.footer = video_understanding.footer(evidence)
        return turn
    rule = video_understanding.link_only_note(prompt, False)
    if rule:
        turn.extras.append(rule)
    pinned, line = references.for_turn(home, settings.project, prompt, already=len(turn.pictures),
                                       cap=IMAGE_CAP, enabled=bool(getattr(settings, 'media_use_references', True))
                                       and _can_read_images(settings))
    if pinned:
        turn.pictures.extend(pinned)
        turn.extras.append(line)
        turn.references = len(pinned)
    return turn


def _can_read_images(settings) -> bool:
    """Only add pictures on our own initiative when the model that will get them reads images.

    The owner's own attachments are always sent (their choice); references are STAR's addition,
    so they are added only for the STAR Server with a vision model or an explicit vision model.
    """
    from . import server_roles
    from .providers import provider_kind
    if str(getattr(settings, 'vision_model', '') or '').strip():
        return True
    if provider_kind(settings) != 'lan':
        return False
    return 'vision' in server_roles.discovered_roles(settings)
