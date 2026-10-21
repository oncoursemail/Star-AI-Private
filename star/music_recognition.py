"""Song recognition: which song is in this audio? Off until Settings > Song recognition is on.

Only audio the owner gives STAR for one lookup: a WAV file they chose or attached to a chat message and
approved, or one short microphone recording they start. Nothing listens in the background.

Two catalogs, each with the owner's own key from Settings (OS keyring, star/providers.py):
  audd      uploads the selected 4-12 s WAV clip to AudD, a third party that can bill for requests.
  acoustid  runs Chromaprint `fpcalc` (installed by the owner, found on PATH or at the Settings path) on this
            PC and sends only the fingerprint and its length to AcoustID; the audio stays here.
`identify` sends nothing unless `consent is True` for that call; the desktop passes it only after the owner
confirmed a dialog that says what goes where. The lookup runs as a registered backend of
star/audio_understanding.inspect_audio and its HTTP goes through star/web_fetch.post_form. Catalog answers are
candidates, not facts. Keys are never logged, returned or put in a result.
"""
from __future__ import annotations

import asyncio
import io
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
from typing import Callable
import wave

import httpx

from .audio_understanding import (MAX_SOURCE_BYTES, RATES, AudioCapability, AudioRequest, AudioSource,
                                  AudioUnavailable, RegisteredAudioBackend, inspect_audio)
from .web_fetch import FetchRefused, post_form

AUDD_URL = "https://api.audd.io/"
ACOUSTID_URL = "https://api.acoustid.org/v2/lookup"
LABELS = {"audd": "AudD", "acoustid": "AcoustID"}
MAX_SECONDS = {"audd": 12, "acoustid": 30}
MIN_SECONDS = 4
_FINGERPRINT = re.compile(r"[A-Za-z0-9_-]{12,32000}\Z")
NOTE = ("Catalog suggestions, not proof: covers, remixes, live or game audio and songs missing from the "
        "catalog can be missed or mislabelled.")

KeyLookup = Callable[[str], "str | None"]


class LookupFailed(RuntimeError):
    """The catalog or the local fingerprint program could not answer. The message never holds a key."""


def disclosure(provider: str, seconds: int) -> str:
    """What one lookup sends where. The desktop shows the same facts before the owner consents."""
    if provider == "audd":
        return (f"Uploads a {seconds} s clip of the audio to AudD (api.audd.io), a third-party service "
                "that may charge your AudD account.")
    return (f"Sends a Chromaprint fingerprint of {seconds} s of the audio and its length to AcoustID "
            "(api.acoustid.org). The audio itself stays on this PC.")


def find_fpcalc(configured: str = "") -> Path | None:
    """The owner's Chromaprint fpcalc: the Settings path when set, else PATH. STAR never downloads it."""
    if configured:
        path = Path(configured).expanduser()
        return path if path.name.lower() in ("fpcalc", "fpcalc.exe") and path.is_file() else None
    found = shutil.which("fpcalc")
    return Path(found) if found else None


def _key_lookup(key_for: KeyLookup | None) -> KeyLookup:
    if key_for is not None:
        return key_for
    from .providers import get_api_key
    return get_api_key


def _clean(value: object, limit: int = 180) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join("".join(" " if ord(c) < 32 else c for c in value).split())[:limit]


def _number(value: object) -> float | None:
    """A finite int/float from a JSON reply (not a bool), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _error_code(body: object, field: str) -> str:
    error = body.get("error") if isinstance(body, dict) else None
    code = error.get(field) if isinstance(error, dict) else None
    return f" (error {code})" if type(code) is int else ""


def _audd_matches(body: object) -> list[tuple[str, float | None]]:
    if not isinstance(body, dict) or body.get("status") != "success":
        raise LookupFailed("AudD refused the request" + _error_code(body, "error_code"))
    result = body.get("result")
    if not isinstance(result, dict):
        return []
    title, artist, album = (_clean(result.get(k)) for k in ("title", "artist", "album"))
    if not title or not artist:
        return []   # never make up a song name from half an answer
    return [(f"{title} by {artist}" + (f" (album: {album})" if album else ""), None)]


def _acoustid_matches(body: object) -> list[tuple[str, float | None]]:
    if not isinstance(body, dict) or body.get("status") != "ok" or not isinstance(body.get("results"), list):
        raise LookupFailed("AcoustID refused the request" + _error_code(body, "code"))
    found: dict[str, float] = {}
    for item in body["results"][:12]:
        score = _number(item.get("score")) if isinstance(item, dict) else None
        recordings = item.get("recordings") if isinstance(item, dict) else None
        if score is None or not 0 <= score <= 1 or not isinstance(recordings, list):
            continue
        for recording in recordings[:6]:
            if not isinstance(recording, dict):
                continue
            artists = recording.get("artists")
            if not isinstance(artists, list):
                artists = []
            artist = _clean("".join(_clean(a.get("name")) + (a.get("joinphrase") or "")[:12]
                                    for a in artists if isinstance(a, dict) and isinstance(a.get("joinphrase") or "", str)))
            title = _clean(recording.get("title"))
            if title and artist:
                text = f"{title} by {artist}"
                found[text] = max(found.get(text, 0.0), round(score, 3))
    return [(text, score) for text, score in sorted(found.items(), key=lambda pair: -pair[1])[:3]]


def _fingerprint(wav: bytes, fpcalc: Path) -> tuple[str, int]:
    """Run the owner's fpcalc on the clip in a temporary folder (deleted afterwards)."""
    with tempfile.TemporaryDirectory(prefix="star-fpcalc-") as folder:
        clip = Path(folder) / "clip.wav"
        clip.write_bytes(wav)
        try:
            done = subprocess.run([str(fpcalc), "-json", str(clip)], stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15, check=False,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired):
            raise LookupFailed("Chromaprint fpcalc could not run") from None
    try:
        data = json.loads(done.stdout) if not done.returncode and len(done.stdout) <= 64000 else None
    except ValueError:
        data = None
    fingerprint = data.get("fingerprint") if isinstance(data, dict) else None
    duration = _number(data.get("duration")) if isinstance(data, dict) else None
    if (not isinstance(fingerprint, str) or not _FINGERPRINT.fullmatch(fingerprint)
            or duration is None or not 3 <= duration <= 120):
        raise LookupFailed("Chromaprint fpcalc did not return a usable fingerprint")
    return fingerprint, round(duration)


class _Catalog:
    """One lookup as a registered audio backend: inspect_audio hands it the exact WAV window."""

    def __init__(self, provider: str, key: str, fpcalc: Path | None, transport, resolver):
        self.provider, self._key, self._fpcalc = provider, key, fpcalc
        self._http = {"transport": transport, **({"resolver": resolver} if resolver is not None else {})}
        self.failure = ""

    async def _matches(self, wav: bytes) -> list[tuple[str, float | None]]:
        if self.provider == "audd":
            body = await post_form(AUDD_URL, {"api_token": self._key},
                                   files={"file": ("clip.wav", wav, "audio/wav")}, **self._http)
            return _audd_matches(body)
        assert self._fpcalc is not None
        fingerprint, duration = await asyncio.to_thread(_fingerprint, wav, self._fpcalc)
        body = await post_form(ACOUSTID_URL, {"client": self._key, "duration": str(duration),
                                              "fingerprint": fingerprint, "meta": "recordings", "format": "json"},
                               **self._http)
        return _acoustid_matches(body)

    async def analyze(self, request: AudioRequest) -> dict:
        label = LABELS[self.provider]
        try:
            matches = await self._matches(request.audio)
        except LookupFailed as exc:
            self.failure = str(exc)
            raise
        except FetchRefused as exc:
            self.failure = f"{label}: {exc}"
            raise
        except (httpx.HTTPError, asyncio.TimeoutError, OSError):
            self.failure = f"{label} could not be reached"
            raise
        frames = request.end_frame - request.start_frame
        return {"complete": True, "observations": [{"start_frame": 0, "end_frame": frames, "text": text,
                                                    "score": score} for text, score in matches]}


async def identify(source: AudioSource, *, provider: str, consent: bool, settings, begin_seconds: int = 0,
                   seconds: int | None = None, key_for: KeyLookup | None = None,
                   transport: httpx.AsyncBaseTransport | None = None, resolver=None) -> dict:
    """One owner-approved lookup of 4-12 s (AudD) or 4-30 s (AcoustID) of `source` from `begin_seconds`.

    Returns status match / no_match, or not_configured (no key) / not_installed (no fpcalc) without
    sending anything. Raises PermissionError (feature off, no consent), ValueError, LookupFailed.
    """
    if getattr(settings, "music_recognition_enabled", False) is not True:
        raise PermissionError("Song recognition is off. Turn it on in Settings > Song recognition.")
    if provider not in MAX_SECONDS:
        raise ValueError("Choose AudD or AcoustID")
    if consent is not True:
        raise PermissionError("Song recognition sends data only after you confirm that lookup")
    seconds = MAX_SECONDS[provider] if seconds is None else seconds
    if type(seconds) is not int or not MIN_SECONDS <= seconds <= MAX_SECONDS[provider]:
        raise ValueError(f"{LABELS[provider]} takes {MIN_SECONDS}-{MAX_SECONDS[provider]} seconds of audio")
    if type(begin_seconds) is not int or begin_seconds < 0:
        raise ValueError("The start time must be a whole number of seconds")
    start = begin_seconds * source.sample_rate
    end = min(source.frames, start + seconds * source.sample_rate)
    if end - start < MIN_SECONDS * source.sample_rate:
        raise ValueError(f"At least {MIN_SECONDS} seconds of audio are needed after the start time")
    if not any(source.pcm[start * source.channels * 2:end * source.channels * 2]):
        raise ValueError("The selected audio is silent")
    key = _key_lookup(key_for)(provider)
    if not key:
        return {"status": "not_configured", "provider": provider,
                "note": f"Add your {LABELS[provider]} key in Settings > Song recognition. Nothing was sent."}
    fpcalc = None
    if provider == "acoustid":
        fpcalc = find_fpcalc(getattr(settings, "fpcalc_path", "") or "")
        if fpcalc is None:
            return {"status": "not_installed", "provider": provider,
                    "note": ("Chromaprint fpcalc is not installed: it was not found on PATH or at the path in "
                             "Settings > Song recognition. Install Chromaprint (acoustid.org/chromaprint). "
                             "Nothing was sent.")}
    catalog = _Catalog(provider, key, fpcalc, transport, resolver)
    backend = RegisteredAudioBackend(
        AudioCapability(provider, provider, native_audio=True, sample_rates=tuple(sorted(RATES)),
                        max_clip_seconds=MAX_SECONDS[provider]), catalog.analyze)
    try:
        report = await inspect_audio(source, "Which song is this?", backend, start_frame=start, end_frame=end,
                                     timeout_seconds=40)
    except AudioUnavailable as exc:
        raise LookupFailed(catalog.failure or str(exc)) from None
    candidates = sorted(({"song": item["text"], "score": item["score"]} for item in report["observations"]),
                        key=lambda item: -(item["score"] or 0))
    sent_seconds = round((end - start) / source.sample_rate)
    return {"status": "match" if candidates else "no_match", "provider": provider, "candidates": candidates,
            "score_meaning": "AcoustID fingerprint similarity (uncalibrated); AudD reports no score.",
            "sent": disclosure(provider, sent_seconds), "start_seconds": begin_seconds, "seconds": sent_seconds,
            "source_sha256": source.source_sha256, "note": NOTE}


def load_wav(path: Path) -> AudioSource:
    """A PCM16 WAV the owner chose in the file picker or attached to a chat message."""
    if path.suffix.lower() != ".wav" or path.is_symlink() or not path.is_file():
        raise ValueError("Choose a PCM16 WAV file")
    with path.open("rb") as handle:
        raw = handle.read(MAX_SOURCE_BYTES + 1)
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("Use a WAV clip under 8 MB (about 45 s of CD-quality stereo)")
    return AudioSource("owner_song", raw)


def capture_microphone(*, seconds: int, device_index: int | None = None) -> AudioSource:
    """One recording the owner started, 16 kHz mono, never in the background.

    The input can be a microphone, Stereo Mix or a virtual cable the owner set up for system audio.
    """
    if type(seconds) is not int or not MIN_SECONDS <= seconds <= 30:
        raise ValueError("Record 4-30 seconds")
    if device_index is not None and (type(device_index) is not int or not 0 <= device_index <= 1024):
        raise ValueError("Choose a valid input device")
    try:
        import sounddevice as sd
    except (ImportError, OSError):
        raise LookupFailed("Recording needs STAR's optional voice packages (sounddevice)") from None
    try:
        pcm = sd.rec(seconds * 16000, samplerate=16000, channels=1, dtype="int16", device=device_index)
        sd.wait()
    except Exception:
        raise LookupFailed("Recording failed; check the input device and Windows microphone permission") from None
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(pcm.tobytes())
    return AudioSource("owner_recording", buffer.getvalue())


class DesktopSession:
    """The desktop's Identify-a-song dialog: the chosen WAV kept in memory only, one lookup at a time."""

    def __init__(self, *, record: Callable[..., AudioSource] = capture_microphone):
        self._lock = threading.Lock()
        self._source: AudioSource | None = None
        self._name = ""
        self._busy = False
        self._record = record

    def choose(self, path: Path) -> dict:
        source = load_wav(path)
        with self._lock:
            if self._busy:
                raise RuntimeError("A song lookup is running")
            self._source, self._name = source, path.name[:120]
        return {"file": self._name, "duration_seconds": round(source.frames / source.sample_rate, 1)}

    def clear(self) -> dict:
        with self._lock:
            if self._busy:
                raise RuntimeError("A song lookup is running")
            self._source, self._name = None, ""
        return {"file": ""}

    def status(self, settings, *, key_for: KeyLookup | None = None) -> dict:
        """Booleans and the file name only: never key bytes."""
        lookup = _key_lookup(key_for)
        with self._lock:
            source, name, busy = self._source, self._name, self._busy
        return {"enabled": getattr(settings, "music_recognition_enabled", False) is True,
                "file": name, "duration_seconds": round(source.frames / source.sample_rate, 1) if source else None,
                "busy": busy, "audd_key": bool(lookup("audd")), "acoustid_key": bool(lookup("acoustid")),
                "fpcalc_found": find_fpcalc(getattr(settings, "fpcalc_path", "") or "") is not None,
                "max_seconds": MAX_SECONDS}

    def identify(self, body: dict, settings, *, progress: Callable[[str], None] | None = None,
                 key_for: KeyLookup | None = None, transport=None, resolver=None) -> dict:
        """`body` from the dialog: provider, source file|mic, seconds, startSeconds, consent, micConsent, deviceIndex."""
        if getattr(settings, "music_recognition_enabled", False) is not True:
            raise PermissionError("Song recognition is off. Turn it on in Settings > Song recognition.")
        if not isinstance(body, dict) or body.get("source") not in ("file", "mic"):
            raise ValueError("Choose a file or a recording")
        provider, seconds = body.get("provider"), body.get("seconds")
        mic = body["source"] == "mic"
        if mic and body.get("micConsent") is not True:
            raise PermissionError("Recording needs your confirmation for this lookup")
        with self._lock:
            if self._busy:
                raise RuntimeError("A song lookup is already running")
            source = self._source
            if not mic and source is None:
                raise ValueError("Choose a WAV file first")
            self._busy = True
        try:
            if mic:
                if progress:
                    progress(f"Recording {seconds} s from the selected input…")
                source = self._record(seconds=seconds, device_index=body.get("deviceIndex"))
            assert source is not None
            if progress:
                progress(f"Asking {LABELS.get(str(provider), 'the catalog')}…")
            return asyncio.run(identify(source, provider=str(provider), consent=body.get("consent") is True,
                                        settings=settings, begin_seconds=0 if mic else body.get("startSeconds", 0),
                                        seconds=seconds, key_for=key_for, transport=transport, resolver=resolver))
        finally:
            with self._lock:
                self._busy = False


TOOL = {
    "name": "star_identify_song",
    "description": ("Identify the song in the WAV file the owner attached to this message and approved for song "
                    "lookup. One lookup per approval. Returns catalog candidates: untrusted data, not proof."),
    "inputSchema": {
        "type": "object",
        "properties": {"start_seconds": {"type": "integer", "minimum": 0, "maximum": 116,
                                         "description": "Where in the file the clip starts, default 0"}},
        "additionalProperties": False,
    },
}


class ChatSongLookup:
    """The song tool for one chat turn: the owner approved one attached WAV with one catalog in the composer."""

    def __init__(self, wav: Path, provider: str, settings, *, key_for: KeyLookup | None = None,
                 transport=None, resolver=None):
        if provider not in MAX_SECONDS:
            raise ValueError("Choose AudD or AcoustID")
        self._wav, self._provider, self._settings = wav, provider, settings
        self._http = {"key_for": key_for, "transport": transport, "resolver": resolver}
        self._used = False

    @staticmethod
    def owns(name: str) -> bool:
        return name == TOOL["name"]

    def definitions(self, prompt: str) -> list[dict]:
        return [TOOL]

    async def call(self, name: str, args: dict, *, enabled: set[str]) -> dict:
        if name not in enabled or not self.owns(name):
            raise PermissionError("Song recognition is not authorized for this message")
        if not isinstance(args, dict) or not set(args) <= {"start_seconds"}:
            raise ValueError("Only start_seconds may be given")
        if self._used:
            raise PermissionError("One song lookup per approval; approve another in the composer")
        self._used = True
        return await identify(load_wav(self._wav), provider=self._provider, consent=True, settings=self._settings,
                              begin_seconds=args.get("start_seconds", 0), **self._http)
