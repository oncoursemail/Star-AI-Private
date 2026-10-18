"""STAR opt-in song identification from an approved PCM16 WAV or selected microphone.

Two independent provider paths:
- AudD: user-approved 4..12s audio snippet upload, token and billing consent.
- AcoustID: local optional fpcalc / Chromaprint, send fingerprint *only* with a
  non-commercial client key and explicit network/terms confirmation.

No always-on listening, automatic microphone permissions, OS/game audio spying,
site scraping, undocumented Shazam endpoints, key persistence, audio archives,
account rotation, hidden billing, or hallucinated matches. Provider results are
untrusted candidates, not human-verified truth. WAV/PCM limits reuse STAR's
existing audio_understanding.AudioSource.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import wave

import httpx

from .audio_understanding import AudioSource

AUDD_ENDPOINT = "https://api.audd.io/"
ACOUSTID_ENDPOINT = "https://api.acoustid.org/v2/lookup"
MAX_RESPONSE_BYTES = 96 * 1024
MIN_CLIP_SECONDS = 4
AUDD_MAX_SECONDS = 12
ACOUSTID_MAX_SECONDS = 30
_FINGERPRINT = re.compile(r"[A-Za-z0-9_-]{12,32000}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}\Z")


class MusicRecognitionUnavailable(RuntimeError):
    """An approved identification provider or local fingerprint tool is unavailable."""


def _text(value: object, limit: int = 180) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(" " if ord(x) < 32 else x for x in value).strip()[:limit]


def _secret(value: object, label: str) -> str:
    if not isinstance(value, str) or not 4 <= len(value) <= 500 or any(ord(x) <= 32 for x in value):
        raise ValueError(f"{label} must come from the owner's approved credential store or environment")
    return value


def clip_wav(source: AudioSource, *, begin_seconds: int = 0, seconds: int = AUDD_MAX_SECONDS,
             max_seconds: int = AUDD_MAX_SECONDS) -> tuple[bytes, dict]:
    """Prepare only bounded, explicitly selected input; never crop without provenance."""
    if not isinstance(source, AudioSource):
        raise ValueError("Host-verified AudioSource required")
    if (type(begin_seconds) is not int or type(seconds) is not int or type(max_seconds) is not int
            or begin_seconds < 0 or begin_seconds > 120
            or not MIN_CLIP_SECONDS <= seconds <= max_seconds <= ACOUSTID_MAX_SECONDS):
        raise ValueError("Clip start/duration exceeds approved music-identification limits")
    start = begin_seconds * source.sample_rate
    stop = min(source.frames, (begin_seconds + seconds) * source.sample_rate)
    if start >= source.frames or stop - start < MIN_CLIP_SECONDS * source.sample_rate:
        raise ValueError("At least four seconds of selected audio are needed")
    pcm = source.pcm[start * source.channels * 2:stop * source.channels * 2]
    if not pcm or pcm.count(0) == len(pcm):
        raise ValueError("Selected audio is silent; no song can be fingerprinted")
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setsampwidth(2)
        handle.setframerate(source.sample_rate)
        handle.setnchannels(source.channels)
        handle.writeframes(pcm)
    raw = output.getvalue()
    info = {
        "source_id": source.source_id,
        "source_sha256": source.source_sha256,
        "clip_sha256": hashlib.sha256(raw).hexdigest(),
        "start_seconds": begin_seconds,
        "duration_seconds": round((stop - start) / source.sample_rate, 3),
        "sample_rate": source.sample_rate, "channels": source.channels,
        "bytes": len(raw),
    }
    return raw, info


def _normalize_audd(body: object) -> list[dict]:
    if not isinstance(body, dict) or body.get("status") != "success":
        raise MusicRecognitionUnavailable("Audio-recognition provider returned an unsuccessful response")
    result = body.get("result")
    if result is None:
        return []
    if not isinstance(result, dict):
        raise MusicRecognitionUnavailable("Audio-recognition provider returned malformed match metadata")
    title, artist = _text(result.get("title")), _text(result.get("artist"))
    if not title or not artist:
        return []  # Never fabricate a song name from a partial provider reply.
    return [{
        "title": title, "artist": artist, "album": _text(result.get("album")),
        "release_date": _text(result.get("release_date"), 30),
        "score": None, "score_meaning": "Provider did not report a calibrated match confidence",
        "provider": "audd",
    }]


def _normalize_acoustid(body: object) -> list[dict]:
    if not isinstance(body, dict) or body.get("status") != "ok" or not isinstance(body.get("results"), list):
        raise MusicRecognitionUnavailable("Fingerprint provider returned an unsuccessful or malformed response")
    tracks = []
    for item in body["results"][:12]:
        if not isinstance(item, dict):
            continue
        score = item.get("score")
        if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
            continue
        for recording in (item.get("recordings") or [])[:6] if isinstance(item.get("recordings"), list) else []:
            if not isinstance(recording, dict):
                continue
            title = _text(recording.get("title"))
            artists = recording.get("artists") if isinstance(recording.get("artists"), list) else []
            artist = _text("".join(_text(person.get("name")) + _text(person.get("joinphrase"), 12)
                                   for person in artists if isinstance(person, dict)))
            if not title or not artist:
                continue
            tracks.append({
                "title": title, "artist": artist, "recording_id": _text(recording.get("id"), 80),
                "score": round(float(score), 3),
                "score_meaning": "Uncalibrated AcoustID fingerprint similarity, not a probability",
                "provider": "acoustid",
            })
    tracks.sort(key=lambda x: (-x["score"], x["title"], x["artist"]))
    dedup: list[dict] = []
    seen = set()
    for track in tracks:
        key = (track["title"].casefold(), track["artist"].casefold(), track["recording_id"])
        if key not in seen:
            dedup.append(track)
            seen.add(key)
        if len(dedup) == 3:
            break
    return dedup


async def _request_json(url: str, form: dict[str, str], *,
                        audio_file: bytes | None = None,
                        transport: httpx.AsyncBaseTransport | None = None) -> object:
    """No redirects or proxy, fixed endpoint, body caps and no provider error echo."""
    if url not in (AUDD_ENDPOINT, ACOUSTID_ENDPOINT):
        raise ValueError("Unapproved music lookup host")
    files = {"file": ("star-selected-clip.wav", audio_file, "audio/wav")} if audio_file is not None else None
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(18.0, connect=4.0), trust_env=False,
            follow_redirects=False, transport=transport,
        ) as client:
            async with client.stream(
                "POST", url, data=form, files=files,
                headers={"Accept": "application/json", "User-Agent": "STAR-music-identification/1.0"},
            ) as reply:
                if reply.status_code == 429:
                    raise MusicRecognitionUnavailable("Recognition provider is rate limiting requests")
                if reply.status_code in (401, 402, 403):
                    raise MusicRecognitionUnavailable("Recognition provider rejected credentials, terms or billing status")
                if reply.status_code != 200:
                    raise MusicRecognitionUnavailable(f"Recognition provider unavailable (HTTP {reply.status_code})")
                size = reply.headers.get("content-length", "")
                if size.isdecimal() and int(size) > MAX_RESPONSE_BYTES:
                    raise MusicRecognitionUnavailable("Recognition reply exceeded safety limit")
                buffer = bytearray()
                async for chunk in reply.aiter_bytes():
                    buffer.extend(chunk)
                    if len(buffer) > MAX_RESPONSE_BYTES:
                        raise MusicRecognitionUnavailable("Recognition reply exceeded safety limit")
                data = json.loads(buffer)
                return data
    except (httpx.HTTPError, ValueError, json.JSONDecodeError):
        raise MusicRecognitionUnavailable("Recognition request failed or returned invalid metadata") from None


def _report(info: dict, *, provider: str, candidates: list[dict], transferred: str) -> dict:
    return {
        "status": "candidate_matches" if candidates else "no_match",
        "provider": provider,
        "candidates": candidates,
        "source_id": info["source_id"],
        "source_sha256": info["source_sha256"],
        "clip_sha256": info["clip_sha256"],
        "start_seconds": info["start_seconds"],
        "duration_seconds": info["duration_seconds"],
        "transferred": transferred,
        "human_verified": False,
        "raw_audio_retained_by_star": False,
        "note": ("Provider matches are suggestions, not proof. Covers, remix edits, live game audio, "
                 "multiple tracks, speech/music mixtures and uncatalogued songs can be missed or mislabeled."),
    }


async def recognize_audd(source: AudioSource, *, token: str, allow_audio_upload: bool = False,
                         accept_possible_billing: bool = False,
                         begin_seconds: int = 0, seconds: int = 12,
                         transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """Upload a bounded WAV snippet only after separate privacy and billing consent."""
    if allow_audio_upload is not True or accept_possible_billing is not True:
        raise PermissionError("AudD needs explicit audio-upload consent and possible-billing acknowledgement")
    token = _secret(token, "AudD token")
    audio, info = clip_wav(source, begin_seconds=begin_seconds, seconds=seconds)
    body = await _request_json(AUDD_ENDPOINT, {"api_token": token}, audio_file=audio, transport=transport)
    return _report(info, provider="audd", candidates=_normalize_audd(body),
                   transferred="Short selected WAV audio and provider token over HTTPS")


def fingerprint_fpcalc(source: AudioSource, fpcalc_executable: Path,
                       *, begin_seconds: int = 0, seconds: int = 30) -> tuple[str, int, dict]:
    """Run owner-installed, trusted fpcalc locally and delete its temporary WAV.

    Must never accept an LLM-supplied executable path. The invoking host/owner
    selects and verifies the installed executable. Does not download anything.
    """
    if not isinstance(fpcalc_executable, Path) or fpcalc_executable.name.lower() not in ("fpcalc", "fpcalc.exe"):
        raise ValueError("Choose an installed Chromaprint fpcalc binary")
    if fpcalc_executable.is_symlink() or not fpcalc_executable.is_file():
        raise ValueError("fpcalc executable missing or linked")
    wav, info = clip_wav(source, begin_seconds=begin_seconds, seconds=seconds, max_seconds=ACOUSTID_MAX_SECONDS)
    with tempfile.TemporaryDirectory(prefix="star-fingerprint-") as folder:
        path = Path(folder) / "selected.wav"
        path.write_bytes(wav)
        try:
            process = subprocess.run(
                [str(fpcalc_executable.resolve(strict=True)), "-length", str(seconds), "-json", str(path)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=15, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            raise MusicRecognitionUnavailable("Local Chromaprint fingerprint generation failed") from None
        if process.returncode or len(process.stdout) > 64000:
            raise MusicRecognitionUnavailable("Local Chromaprint fingerprint output invalid")
        try:
            data = json.loads(process.stdout)
        except (ValueError, UnicodeError):
            raise MusicRecognitionUnavailable("Local Chromaprint returned invalid JSON") from None
    fingerprint = data.get("fingerprint") if isinstance(data, dict) else None
    duration = data.get("duration") if isinstance(data, dict) else None
    if not isinstance(fingerprint, str) or not _FINGERPRINT.fullmatch(fingerprint):
        raise MusicRecognitionUnavailable("Local Chromaprint returned no valid fingerprint")
    if type(duration) not in (int, float) or not math.isfinite(duration) or not MIN_CLIP_SECONDS <= duration <= 120:
        raise MusicRecognitionUnavailable("Local Chromaprint returned invalid duration")
    return fingerprint, round(duration), info


async def recognize_acoustid(fingerprint: str, duration: int, info: dict, *,
                             client_key: str, allow_fingerprint_lookup: bool = False,
                             noncommercial_usage_confirmed: bool = False,
                             transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """Send a fingerprint only; AcoustID's free API is non-commercial and rate limited."""
    if allow_fingerprint_lookup is not True or noncommercial_usage_confirmed is not True:
        raise PermissionError("AcoustID requires explicit network and non-commercial-use confirmation")
    key = _secret(client_key, "AcoustID client key")
    if not isinstance(fingerprint, str) or not _FINGERPRINT.fullmatch(fingerprint):
        raise ValueError("Invalid Chromaprint fingerprint")
    if type(duration) is not int or not 4 <= duration <= 120:
        raise ValueError("Invalid fingerprint duration")
    if not isinstance(info, dict) or not all(isinstance(info.get(x), str) for x in (
        "source_id", "source_sha256", "clip_sha256"
    )) or not _IDENTIFIER.fullmatch(info["source_id"]) or not all(
        re.fullmatch(r"[0-9a-f]{64}", info[x]) for x in ("source_sha256", "clip_sha256")
    ) or type(info.get("start_seconds")) is not int or type(info.get("duration_seconds")) not in (int, float):
        raise ValueError("Invalid approved audio provenance")
    body = await _request_json(ACOUSTID_ENDPOINT, {
        "client": key, "duration": str(duration), "fingerprint": fingerprint,
        "meta": "recordings", "format": "json",
    }, transport=transport)
    return _report(info, provider="acoustid", candidates=_normalize_acoustid(body),
                   transferred="Only Chromaprint signature, duration and AcoustID client key over HTTPS")


def capture_microphone(*, seconds: int, device_index: int | None = None) -> AudioSource:
    """Explicit user-triggered capture, never an always-on background recorder.

    Selected mic may be Stereo Mix or a consented virtual game-audio input. Does
    not claim privileged or universal Windows WASAPI loopback support.
    """
    if type(seconds) is not int or not 4 <= seconds <= 30:
        raise ValueError("Record 4..30 seconds only")
    if device_index is not None and (type(device_index) is not int or not 0 <= device_index <= 1024):
        raise ValueError("Select a valid local microphone input index")
    try:
        import sounddevice as sd
    except (ImportError, OSError):
        raise MusicRecognitionUnavailable("Install STAR's optional voice requirements to capture a microphone") from None
    try:
        pcm = sd.rec(seconds * 16000, samplerate=16000, channels=1, dtype="int16", device=device_index)
        sd.wait()
    except Exception:
        raise MusicRecognitionUnavailable("Microphone capture failed; check input permissions/device") from None
    if len(pcm) != seconds * 16000:
        raise MusicRecognitionUnavailable("Microphone capture was incomplete")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(pcm.tobytes())
    return AudioSource("explicit_microphone", buf.getvalue())


async def _cli(args: argparse.Namespace) -> dict:
    if bool(args.file) == bool(args.mic):
        raise ValueError("Select exactly one source: --file or --mic")
    if args.mic:
        source = capture_microphone(seconds=args.seconds, device_index=args.device)
    else:
        path = args.file
        if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".wav" or not 44 <= path.stat().st_size <= 8 * 1024 * 1024:
            raise ValueError("Choose a local, ordinary PCM16 WAV file up to 8 MiB")
        source = AudioSource("selected_file", path.read_bytes())
    if args.provider == "audd":
        return await recognize_audd(
            source, token=os.environ.get("STAR_AUDD_API_TOKEN", ""),
            allow_audio_upload=args.allow_upload, accept_possible_billing=args.accept_billing,
            begin_seconds=args.start, seconds=min(args.seconds, AUDD_MAX_SECONDS),
        )
    if args.fpcalc is None:
        raise ValueError("Install Chromaprint fpcalc and provide --fpcalc path")
    fp, duration, info = fingerprint_fpcalc(
        source, args.fpcalc, begin_seconds=args.start, seconds=min(args.seconds, ACOUSTID_MAX_SECONDS))
    return await recognize_acoustid(
        fp, duration, info, client_key=os.environ.get("STAR_ACOUSTID_CLIENT_KEY", ""),
        allow_fingerprint_lookup=args.allow_fingerprint, noncommercial_usage_confirmed=args.noncommercial,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Opt-in STAR song identification from WAV or explicitly recorded mic")
    choose = parser.add_mutually_exclusive_group(required=True)
    choose.add_argument("--file", type=Path, help="Local, user-selected PCM16 WAV; NEVER a URL")
    choose.add_argument("--mic", action="store_true", help="Explicitly record the microphone once")
    parser.add_argument("--device", type=int, help="Mic input index (Stereo Mix/virtual input if user configured)")
    parser.add_argument("--provider", choices=("audd", "acoustid"), default="audd")
    parser.add_argument("--start", type=int, default=0, help="Seconds into the selected WAV, default 0")
    parser.add_argument("--seconds", type=int, default=12, help="Clip/recording duration, 4..12 AudD, 4..30 AcoustID")
    parser.add_argument("--allow-upload", action="store_true", help="Send selected WAV snippet to AudD")
    parser.add_argument("--accept-billing", action="store_true", help="Acknowledge possible AudD provider charges")
    parser.add_argument("--fpcalc", type=Path, help="Owner-installed Chromaprint executable")
    parser.add_argument("--allow-fingerprint", action="store_true", help="Send only local fingerprint to AcoustID")
    parser.add_argument("--noncommercial", action="store_true", help="Confirm non-commercial AcoustID service use")
    args = parser.parse_args(argv)
    try:
        answer = asyncio.run(_cli(args))
    except (ValueError, PermissionError, MusicRecognitionUnavailable, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(answer, indent=2, ensure_ascii=False))
    return 0 if answer["status"] == "candidate_matches" else 1


if __name__ == "__main__":
    raise SystemExit(main())
