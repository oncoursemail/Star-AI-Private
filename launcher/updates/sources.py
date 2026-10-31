"""Where bytes come from: an HTTP(S) base URL (own server, forge release assets, any static host) or a folder.

Nothing here is trusted: every byte is checked against the signed manifest by the client. A source only has to
return the bytes it was asked for, and `stream` supports an offset so interrupted downloads resume.
"""
from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterator

MAX_SMALL = 8 * 1024 * 1024  # manifest and signature files
CHUNK = 256 * 1024


class FetchError(OSError):
    """The source could not deliver the bytes (network down, 404, truncated)."""


class DirSource:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if self.root not in p.parents:
            raise FetchError(f"path escapes the source folder: {rel}")
        return p

    def read(self, rel: str) -> bytes:
        try:
            p = self._path(rel)
            if p.stat().st_size > MAX_SMALL:
                raise FetchError(f"{rel} is too large for a metadata file")
            return p.read_bytes()
        except FileNotFoundError as exc:
            raise FetchError(f"not found: {rel}") from exc

    def stream(self, rel: str, offset: int = 0) -> Iterator[bytes]:
        try:
            with open(self._path(rel), "rb") as fh:
                fh.seek(offset)
                while block := fh.read(CHUNK):
                    yield block
        except FileNotFoundError as exc:
            raise FetchError(f"not found: {rel}") from exc


class HttpSource:
    def __init__(self, base_url: str, timeout: float = 20.0, user_agent: str = "Metallic-Updater/1"):
        parts = urllib.parse.urlsplit(base_url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("the update address must be an http(s) URL")
        self.base = base_url.rstrip("/") + "/"
        self.timeout, self.ua = timeout, user_agent

    def _open(self, rel: str, offset: int = 0):
        url = self.base + urllib.parse.quote(rel, safe="/")
        headers = {"User-Agent": self.ua, "Accept-Encoding": "identity"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 416:  # asked for the part past the end: nothing left to send
                return None
            raise FetchError(f"{exc.code} for {rel}") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise FetchError(f"cannot reach {self.base}: {getattr(exc, 'reason', exc)}") from exc

    def read(self, rel: str) -> bytes:
        resp = self._open(rel)
        if resp is None:
            raise FetchError(f"empty reply for {rel}")
        try:
            with resp:
                data = resp.read(MAX_SMALL + 1)
        except OSError as exc:
            raise FetchError(f"download of {rel} was cut off: {exc}") from exc
        if len(data) > MAX_SMALL:
            raise FetchError(f"{rel} is too large for a metadata file")
        return data

    def stream(self, rel: str, offset: int = 0) -> Iterator[bytes]:
        resp = self._open(rel, offset)
        if resp is None:
            return
        with resp:
            skip = 0
            if offset and getattr(resp, "status", 200) == 200:  # server ignored Range: drop what we already have
                skip = offset
            try:
                while block := resp.read(CHUNK):
                    if skip:
                        if len(block) <= skip:
                            skip -= len(block)
                            continue
                        block, skip = block[skip:], 0
                    yield block
            except OSError as exc:
                raise FetchError(f"download of {rel} was cut off: {exc}") from exc
