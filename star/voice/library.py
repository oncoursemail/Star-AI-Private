"""Character voices for role-play: a small library of named voices, plus multi-voice scripts (narrator + characters).

Kinds of voice:
  designed  made from a written description ("a gruff old sea captain, deep and slow"). Original, so always allowed.
  own       one of Star's own voices (a catalog voice or a Kokoro recipe). Always allowed.
  clone     copied from a recording of a real person. ONLY with that person's recorded consent: a ConsentRecord with
            the person's name, their consent statement in their own words, and a recording of them saying it. Without
            a valid record the clone is refused, and a revoked consent deletes the clone.

Designed voices are also refused when the description asks to imitate a named real person ("sound like <Name>",
"Morgan Freeman's voice") or describes a child's voice (role-play voices are adults, as in the voice catalog).

Pure Python (JSON file). The engine that renders a designed voice is chosen at speak time: Qwen3-TTS VoiceDesign when
it is loaded (the description is its instruction), otherwise a Kokoro stand-in picked from the description
(kokoro_fallback), so a character always has some distinct voice.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

KINDS = ("designed", "own", "clone")
MAX_CHARACTERS = 200
MAX_DESCRIPTION = 400
_NAME = re.compile(r"^[\w .'\-]{1,40}$", re.U)
CONSENT_PHRASE = re.compile(r"\b(?:consent|agree|give (?:my |you )?(?:permission|consent)|(?:may|can) (?:use|copy|clone))\b",
                            re.I)
_NO_CONSENT = re.compile(r"\b(?:do not|don'?t|never|not|no longer|withdraw|revoke)\b[^.]{0,20}\b(?:consent|agree|permission)\b",
                         re.I)
_IMITATE = re.compile(
    r"\b(?i:sound(?:s|ing)? (?:exactly |just )?like|voice of|imitat\w*|impersonat\w*|mimic\w*|clone of|in the style of)\s+"
    r"(?:the\s+)?[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?|\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?'s voice\b")
_CHILD = re.compile(r"\b(child|kid|toddler|little (?:girl|boy)|baby voice|(?:[1-9]|1[0-2])[- ]year[- ]old|"
                    r"young (?:girl|boy)|schoolgirl|schoolboy|preteen)\b", re.I)


class Refused(ValueError):
    """A voice the library will not make (no consent, real-person imitation, child voice)."""


@dataclass
class ConsentRecord:
    speaker_name: str            # the real person whose voice is cloned
    statement: str               # their consent in their own words, e.g. "I, Sam Lee, consent to Star using my voice"
    recording: str               # path to a recording of them saying the statement
    granted_at: float = field(default_factory=time.time)
    scope: str = "role-play voice inside STAR only"
    recorded_by: str = "owner"
    revoked: bool = False

    def problems(self) -> list[str]:
        out = []
        if not self.speaker_name.strip():
            out.append("no speaker name")
        statement = self.statement or ""
        if not CONSENT_PHRASE.search(statement) or "voice" not in statement.lower() or _NO_CONSENT.search(statement):
            out.append("the statement does not say they consent to the use of their voice")
        first = self.speaker_name.strip().split()[0].lower() if self.speaker_name.strip() else ""
        if first and first not in (self.statement or "").lower():
            out.append("the statement does not name the speaker")
        path = Path(self.recording) if self.recording else None
        if path is None or not path.is_file() or path.stat().st_size < 8000:
            out.append("no consent recording (at least a few seconds of audio)")
        if self.revoked:
            out.append("consent was revoked")
        return out


@dataclass
class Character:
    id: str
    name: str
    kind: str
    description: str = ""        # designed: the voice description (also the VoiceDesign instruction)
    voice: str = ""              # own: catalog voice id or Kokoro recipe
    reference_clip: str = ""     # designed (after first render) or clone: the clip that locks the voice
    style: str = "neutral"       # default speaking style (star.voice.styles)
    pitch_semitones: float = 0.0
    speed: float = 1.0
    consent: dict | None = None  # clone only: ConsentRecord as a dict
    created_at: float = field(default_factory=time.time)
    notes: str = ""


def check_description(description: str) -> None:
    text = (description or "").strip()
    if not text:
        raise Refused("A designed voice needs a description.")
    if len(text) > MAX_DESCRIPTION:
        raise Refused(f"Keep the description under {MAX_DESCRIPTION} characters.")
    if _IMITATE.search(text):
        raise Refused("I can't copy a real person's voice. Describe the sound instead (age, pitch, accent, mood).")
    if _CHILD.search(text):
        raise Refused("Role-play voices are adults. Describe an adult voice instead.")


def kokoro_fallback(description: str) -> tuple[str, float, float]:
    """(Kokoro recipe, pitch semitones, speed) that roughly fits a description when no voice-design model is loaded."""
    d = (description or "").lower()
    male = bool(re.search(r"\b(man|male|guy|gentleman|boy|king|captain|father|dad|grandfather|wizard|he)\b", d))
    old = bool(re.search(r"\b(old|elderly|aged|ancient|grand(?:father|mother)|granny)\b", d))
    deep = bool(re.search(r"\b(deep|low|gruff|gravel|booming|bass)\b", d))
    bright = bool(re.search(r"\b(bright|high|squeaky|cheerful|bubbly|energetic|perky)\b", d))
    british = bool(re.search(r"\b(british|english accent|london|posh|uk)\b", d))
    slow = bool(re.search(r"\b(slow|calm|wise|sleepy|gentle|soothing)\b", d))
    fast = bool(re.search(r"\b(fast|quick|nervous|excited|hyper)\b", d))
    if male:
        recipe = "bm_george:1.0" if british else ("am_onyx:0.6+am_michael:0.4" if deep else "am_michael:1.0")
    else:
        recipe = "bf_emma:1.0" if british else ("af_nicole:0.6+af_sarah:0.4" if deep else
                                                 ("af_bella:0.6+af_heart:0.4" if bright else "af_sarah:1.0"))
    pitch = (-2.0 if deep else 0.0) + (-1.0 if old else 0.0) + (1.5 if bright else 0.0)
    speed = 0.85 if (slow or old) else (1.1 if fast else 1.0)
    return recipe, max(-4.0, min(4.0, pitch)), speed


class CharacterLibrary:
    """CRUD over a JSON file. Thread-safe within one process; writes are atomic (temp file + replace)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    # -- storage --
    def _read(self) -> dict:
        if not self.path.is_file():
            return {"version": 1, "characters": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    # -- reading --
    def list(self) -> list[Character]:
        with self._lock:
            return [Character(**c) for c in self._read()["characters"]]

    def get(self, key: str) -> Character | None:
        """By id or by name (case-insensitive)."""
        low = (key or "").strip().lower()
        return next((c for c in self.list() if c.id == key or c.name.lower() == low), None)

    # -- writing --
    def _add(self, character: Character) -> Character:
        if not _NAME.match(character.name or ""):
            raise ValueError("A character name is 1-40 letters, digits, spaces or .'-")
        with self._lock:
            data = self._read()
            if any(c["name"].lower() == character.name.lower() for c in data["characters"]):
                raise ValueError(f"There is already a voice called {character.name}.")
            if len(data["characters"]) >= MAX_CHARACTERS:
                raise ValueError("The character library is full.")
            data["characters"].append(asdict(character))
            self._write(data)
        return character

    def create_designed(self, name: str, description: str, style: str = "neutral") -> Character:
        check_description(description)
        recipe, pitch, speed = kokoro_fallback(description)
        return self._add(Character(id=uuid.uuid4().hex[:12], name=name.strip(), kind="designed",
                                   description=description.strip(), voice=recipe, style=style,
                                   pitch_semitones=pitch, speed=speed))

    def create_own(self, name: str, voice: str, style: str = "neutral", pitch_semitones: float = 0.0,
                   speed: float = 1.0) -> Character:
        return self._add(Character(id=uuid.uuid4().hex[:12], name=name.strip(), kind="own", voice=voice, style=style,
                                   pitch_semitones=pitch_semitones, speed=speed))

    def create_clone(self, name: str, reference_clip: str, consent: ConsentRecord | None) -> Character:
        """Clone a real person's voice. Refused unless `consent` is a complete, unrevoked record."""
        if consent is None:
            raise Refused("I only copy a real person's voice with their recorded consent.")
        problems = consent.problems()
        if problems:
            raise Refused("Consent is not complete: " + "; ".join(problems) + ".")
        clip = Path(reference_clip)
        if not clip.is_file():
            raise ValueError("The reference recording is missing.")
        return self._add(Character(id=uuid.uuid4().hex[:12], name=name.strip(), kind="clone",
                                   reference_clip=str(clip), consent=asdict(consent),
                                   notes=f"clone of {consent.speaker_name}, consent recorded"))

    def update(self, key: str, **changes) -> Character:
        allowed = {"name", "description", "style", "pitch_semitones", "speed", "reference_clip", "notes", "voice"}
        bad = set(changes) - allowed
        if bad:
            raise ValueError(f"Cannot change {', '.join(sorted(bad))}.")
        with self._lock:
            data = self._read()
            for item in data["characters"]:
                if item["id"] == key or item["name"].lower() == (key or "").lower():
                    if "description" in changes and item["kind"] == "designed":
                        check_description(changes["description"])
                    if "reference_clip" in changes and item["kind"] == "clone":
                        raise Refused("A clone's recording can only be replaced by a new clone with new consent.")
                    if "name" in changes:
                        if not _NAME.match(changes["name"] or ""):
                            raise ValueError("Bad name.")
                        if any(c["name"].lower() == changes["name"].lower() and c["id"] != item["id"]
                               for c in data["characters"]):
                            raise ValueError(f"There is already a voice called {changes['name']}.")
                    item.update(changes)
                    self._write(data)
                    return Character(**item)
        raise KeyError(key)

    def delete(self, key: str) -> bool:
        with self._lock:
            data = self._read()
            keep = [c for c in data["characters"] if not (c["id"] == key or c["name"].lower() == (key or "").lower())]
            if len(keep) == len(data["characters"]):
                return False
            data["characters"] = keep
            self._write(data)
            return True

    def revoke_consent(self, speaker_name: str) -> int:
        """The person withdrew consent: every clone of their voice is deleted. Returns how many."""
        low = speaker_name.strip().lower()
        with self._lock:
            data = self._read()
            keep = [c for c in data["characters"]
                    if not (c["kind"] == "clone" and (c.get("consent") or {}).get("speaker_name", "").lower() == low)]
            removed = len(data["characters"]) - len(keep)
            if removed:
                data["characters"] = keep
                self._write(data)
            return removed


# -- multi-voice role-play ----------------------------------------------------------------------------------------
_LINE = re.compile(r"^\s*(?:\[([^\]]{1,40})\]|([A-Z][\w .'\-]{0,39}?))\s*:\s*(.+)$")
_VOICE_TAG = re.compile(r'<voice\s+name="([^"]{1,40})"\s*>(.*?)</voice>', re.S | re.I)
NARRATOR = "narrator"


@dataclass(frozen=True)
class Line:
    speaker: str                 # "narrator", "star" or a character name
    text: str


def parse_script(script: str, known: set | None = None) -> list[Line]:
    """Role-play text into lines. Accepts `Name: words` lines (or `[Name]: words`) and <voice name="X">..</voice>
    spans; anything else is the narrator. With `known`, only those names (plus Narrator/Star) count as speakers,
    so "Note: ..." in plain prose stays narration."""
    names = {n.lower() for n in (known or set())} | {NARRATOR, "star"}
    lines: list[Line] = []
    for raw in (script or "").splitlines():
        if not raw.strip():
            continue
        position = 0
        for m in _VOICE_TAG.finditer(raw):
            if raw[position:m.start()].strip():
                lines.append(Line(NARRATOR, raw[position:m.start()].strip()))
            lines.append(Line(m.group(1).strip(), m.group(2).strip()))
            position = m.end()
        rest = raw[position:].strip()
        if not rest:
            continue
        m = _LINE.match(rest)
        speaker = (m.group(1) or m.group(2)).strip() if m else ""
        if m and (known is None or speaker.lower() in names):
            lines.append(Line(NARRATOR if speaker.lower() == NARRATOR else speaker, m.group(3).strip()))
        else:
            lines.append(Line(NARRATOR, rest))
    return lines
