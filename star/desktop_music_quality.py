"""Owner-only STAR desktop bridge for music lookup and human-quality checklists.

No arbitrary paths are accepted from React or from agents. The native Qt picker
supplies candidate files; this service checks them and stores only a bounded
waveform snapshot or a content hash. Credentials come from the owner's
environment, never from the UI and never back to it.

All provider calls are initiated by a separate explicit owner action. This
module is *not* a model tool, a privileged learning receipt signer, or an
unattended recording service.
"""
from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Callable

from .audio_understanding import AudioSource, MAX_SOURCE_BYTES
from . import human_quality, music_recognition

OWNER_ACTIONS = frozenset({
    "musicStatus", "musicChooseWav", "musicChooseFpcalc", "musicClear",
    "musicIdentify", "qualityChooseFile", "qualityPreview", "qualityClear",
})
MAX_QUALITY_BYTES = 8 * 1024 * 1024
QUALITY_TYPES = frozenset({".py", ".json", ".js", ".jsx", ".ts", ".tsx",
                            ".lua", ".luau", ".md", ".txt", ".glb", ".blend", ".fbx"})


def _ordinary(path: Path, *, suffixes: frozenset[str], size: int) -> Path:
    """Check a file from a *trusted native picker*, not a model-supplied path."""
    if not isinstance(path, Path) or path.is_symlink() or path.suffix.lower() not in suffixes:
        raise ValueError("Choose an ordinary supported local file")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or not 0 < resolved.stat().st_size <= size:
        raise ValueError("Selected file missing or exceeds the size limit")
    return resolved


def _bytes(path: Path, limit: int) -> bytes:
    """Bound both the on-disk size and the actual bytes read."""
    with path.open("rb") as source:
        data = source.read(limit + 1)
    if not data or len(data) > limit:
        raise ValueError("Selected file exceeds its size limit")
    return data


def _syntax_report(path: Path, raw: bytes) -> dict:
    """No execution, lint assertion, script import or aesthetic approval."""
    suffix = path.suffix.lower()
    if suffix not in (".py", ".json"):
        return {"status": "not_checked", "kind": "syntax",
                "note": "Use a real project compiler or runtime test for this file type"}
    try:
        decoded = raw.decode("utf-8")
        if suffix == ".py":
            ast.parse(decoded, filename=path.name)
        else:
            json.loads(decoded)
    except (SyntaxError, UnicodeError, ValueError) as exc:
        line = getattr(exc, "lineno", None)
        return {"status": "failed", "kind": "syntax", "line": line,
                "note": "Python syntax" if suffix == ".py" else "JSON syntax"}
    return {"status": "passed_static_only", "kind": "syntax",
            "note": "Parsed without execution; not a unit test, native run or release approval"}


class DesktopMusicQuality:
    """One local UI session. All state is ephemeral; nothing is saved or uploaded."""

    def __init__(self):
        self._lock = threading.RLock()
        self._audio: AudioSource | None = None
        self._file_name: str = ""
        self._fpcalc: Path | None = None
        self._quality: dict | None = None
        self._busy = False

    def select_wav(self, chosen: Path) -> dict:
        path = _ordinary(chosen, suffixes=frozenset({".wav"}), size=MAX_SOURCE_BYTES)
        raw = _bytes(path, MAX_SOURCE_BYTES)
        source = AudioSource("owner_selected_song", raw)
        with self._lock:
            if self._busy:
                raise RuntimeError("A song lookup is running; finish it before changing the source")
            self._audio, self._file_name = source, path.name[:120]
        return self.status()

    def select_fpcalc(self, chosen: Path) -> dict:
        path = _ordinary(chosen, suffixes=frozenset({".exe", ""}), size=32 * 1024 * 1024)
        if path.name.lower() not in ("fpcalc", "fpcalc.exe"):
            raise ValueError("Choose an installed Chromaprint fpcalc executable")
        with self._lock:
            if self._busy:
                raise RuntimeError("Finish the song lookup before changing Chromaprint")
            self._fpcalc = path
        return self.status()

    def clear_music(self) -> dict:
        with self._lock:
            if self._busy:
                raise RuntimeError("Finish the running lookup before clearing its source")
            self._audio, self._file_name = None, ""
        return self.status()

    def select_quality_file(self, chosen: Path) -> dict:
        path = _ordinary(chosen, suffixes=QUALITY_TYPES, size=MAX_QUALITY_BYTES)
        raw = _bytes(path, MAX_QUALITY_BYTES)
        report = {
            "name": path.name[:120], "bytes": len(raw),
            "artifact_sha256": hashlib.sha256(raw).hexdigest(),
            "syntax": _syntax_report(path, raw),
        }
        with self._lock:
            self._quality = report
        return {"selected": True, **report}

    def clear_quality(self) -> dict:
        with self._lock:
            self._quality = None
        return {"selected": False}

    def quality_preview(self, kind: str) -> dict:
        if kind not in {"software", "interface", "animation", "game", "music", "research"}:
            raise ValueError("Select a supported quality checklist")
        with self._lock:
            selected = dict(self._quality) if self._quality is not None else None
        criteria = human_quality.template(kind)
        if selected is None:
            return {
                "selected": False, "category": kind,
                "requirements": [
                    {"id": c.id, "accepted_kinds": list(c.accepted_kinds), "critical": c.critical,
                     "native_required": c.require_native, "owner_review": c.require_owner_review}
                    for c in criteria
                ],
                "state": "unverified",
                "note": "Choose an actual artifact to bind this rubric to a revision. No checks have run.",
            }
        report = human_quality.review(selected["artifact_sha256"], criteria)
        return {
            "selected": True, "category": kind, "artifact": selected,
            "state": report["state"], "checks_passed": report["checks_passed"],
            "checks_total": report["checks_total"], "criteria": report["criteria"],
            "next_actions": report["next_actions"],
            "note": "This is a requirements preview. Only independently run tests and authenticated owner reviews may clear checks; static parsing cannot mark a quality gate passed.",
        }

    def status(self) -> dict:
        with self._lock:
            src = self._audio
            fingerprint_ready = self._fpcalc is not None and self._fpcalc.is_file()
            return {
                "selected": src is not None,
                "file": self._file_name if src else "",
                "duration_seconds": round(src.frames / src.sample_rate, 2) if src else None,
                "sha256": src.source_sha256 if src else None,
                "audd_configured": bool(os.environ.get("STAR_AUDD_API_TOKEN")),
                "acoustid_configured": bool(os.environ.get("STAR_ACOUSTID_CLIENT_KEY")),
                "fpcalc_selected": fingerprint_ready,
                "busy": self._busy,
                "microphone_supported": "optional_voice_package",
            }

    def identify(self, args: dict, *, progress: Callable[[str], None] | None = None) -> dict:
        """One owner-initiated, bounded synchronous operation (runs on Qt pool)."""
        if not isinstance(args, dict):
            raise ValueError("Music identification request must be an object")
        provider, source_kind = args.get("provider"), args.get("source")
        if provider not in ("audd", "acoustid") or source_kind not in ("file", "mic"):
            raise ValueError("Select a supported provider and recording source")
        begin, seconds = args.get("startSeconds", 0), args.get("seconds")
        if type(begin) is not int or not 0 <= begin <= 120:
            raise ValueError("Audio start must be a non-negative whole second")
        max_seconds = 12 if provider == "audd" else 30
        if type(seconds) is not int or not 4 <= seconds <= max_seconds:
            raise ValueError("Audio length is outside the provider's 4–12s / 4–30s limit")
        if source_kind == "mic" and (args.get("micConsent") is not True or begin != 0):
            raise PermissionError("A new microphone capture needs explicit consent and begins at zero")
        if provider == "audd":
            if args.get("uploadConsent") is not True or args.get("billingConsent") is not True:
                raise PermissionError("Audio upload and possible provider charges require separate approvals")
            key = os.environ.get("STAR_AUDD_API_TOKEN", "")
            if not key:
                raise RuntimeError("Configure STAR_AUDD_API_TOKEN outside the app before using AudD")
        else:
            if args.get("fingerprintConsent") is not True or args.get("noncommercialConsent") is not True:
                raise PermissionError("AcoustID lookup and noncommercial-use approval are required")
            key = os.environ.get("STAR_ACOUSTID_CLIENT_KEY", "")
            if not key:
                raise RuntimeError("Configure STAR_ACOUSTID_CLIENT_KEY outside the app before using AcoustID")

        with self._lock:
            if self._busy:
                raise RuntimeError("Another music lookup is already running")
            if source_kind == "file" and self._audio is None:
                raise ValueError("Choose a WAV file with the local file picker first")
            fpcalc = self._fpcalc
            if provider == "acoustid" and fpcalc is None:
                raise ValueError("Choose the installed Chromaprint fpcalc executable first")
            chosen_source = self._audio
            self._busy = True
        try:
            if source_kind == "mic":
                if progress:
                    progress("Recording the microphone once (never in the background)")
                index = args.get("deviceIndex")
                if index is not None and (type(index) is not int or not 0 <= index <= 1024):
                    raise ValueError("Invalid microphone input selection")
                chosen_source = music_recognition.capture_microphone(seconds=seconds, device_index=index)
            if chosen_source is None:
                raise ValueError("No approved audio source selected")
            if progress:
                progress("Checking fingerprint metadata" if provider == "acoustid" else "Uploading the selected snippet")
            if provider == "audd":
                return asyncio.run(music_recognition.recognize_audd(
                    chosen_source, token=key,
                    allow_audio_upload=True, accept_possible_billing=True,
                    begin_seconds=begin, seconds=seconds,
                ))
            if fpcalc is None:
                raise ValueError("Chromaprint executable is not selected")
            fingerprint, duration, info = music_recognition.fingerprint_fpcalc(
                chosen_source, fpcalc, begin_seconds=begin, seconds=seconds,
            )
            return asyncio.run(music_recognition.recognize_acoustid(
                fingerprint, duration, info, client_key=key,
                allow_fingerprint_lookup=True, noncommercial_usage_confirmed=True,
            ))
        finally:
            with self._lock:
                self._busy = False
