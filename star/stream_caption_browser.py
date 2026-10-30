"""Local-only, self-erasing OBS Browser Source for STAR's PCM-backed captions.

The owner manually adds the returned loopback URL as an OBS Browser Source.
No OBS WebSocket write, stream control, text-to-speech, mic capture or external
network access occurs here. Captions are copied only from the *current*
AudibleCaptionLane proposal, which independently validates consumed PCM.

Both sides enforce freshness: the server rechecks lane.current() on EVERY
poll, and the browser clears its DOM if requests stop (including if this
process crashes). A frozen OBS/browser compositor is outside that guarantee.
This is a local opt-in renderer, not proof of speech alignment or permission
to broadcast. The host must call publish() after each real playout sample.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
import secrets
from threading import RLock, Thread
import time
from typing import Callable

from .stream_audible_captions import AudibleCaptionLane, CaptionRender
from .stream_audio_sample_host import DevicePlayoutEpoch


# Browser Source uses native Chromium; all content stays in the local page.
# No external fonts/scripts, HTML injection, WebSocket endpoint or microphone.
_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Star captions</title>
<style nonce="__STAR_NONCE__">
html,body { margin:0; width:100%; height:100%; background:transparent; overflow:hidden; }
body { display:flex; align-items:flex-end; justify-content:center; font-family:Arial,sans-serif; }
#caption { box-sizing:border-box; margin:0 5% 5%; max-width:90%; color:#fff5da;
  text-align:center; font-size:34px; line-height:1.25; font-weight:700;
  text-shadow:0 2px 3px #000,0 0 8px #000; white-space:pre-wrap;
  overflow-wrap:anywhere; }
</style></head><body><div id="caption" aria-live="polite"></div>
<script nonce="__STAR_NONCE__">
"use strict";
const caption = document.getElementById("caption");
let expires = 0;
let busy = false;
function blank() { caption.textContent = ""; expires = 0; }
async function refresh() {
  if (busy) return;
  busy = true;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 300);
  try {
    const response = await fetch("state", {
      cache:"no-store", credentials:"omit", redirect:"error",
      signal:controller.signal
    });
    if (!response.ok) throw new Error("stale source");
    const data = await response.json();
    if (typeof data.text !== "string" || data.text.length > 100) {
      throw new Error("invalid source");
    }
    caption.textContent = data.text;
    expires = data.text ? performance.now() + 350 : 0;
  } catch (_) { blank(); }
  finally { clearTimeout(timeout); busy = false; }
}
setInterval(() => {
  if (performance.now() >= expires) blank();
  void refresh();
}, 120);
void refresh();
</script></body></html>"""


def _now(clock: Callable[[], float]) -> float:
    value = clock()
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("trusted monotonic clock unavailable")
    return float(value)


class _LoopbackHTTP(HTTPServer):
    allow_reuse_address = False

    def get_request(self):
        socket, address = super().get_request()
        socket.settimeout(0.6)  # A stalled local client must not hold the server.
        return socket, address


class CaptionBrowserOverlay:
    """An opt-in, bounded local HTTP bridge with a browser-side dead-man timer.

    Trust boundaries:
      * Trusted audio host -> AudibleCaptionLane.current -> publish -> HTTP
      * The local Browser Source may GET only a random, per-session path.
      * Only explicitly owner-approved, pre-moderated TTS phrases can enter.
      * The URL is not an authentication boundary against malware on the PC.
      * Nothing is stored to disk; the only output is volatile caption text.

    The running overlay must be on the *same machine* as OBS Browser Source.
    Stop this bridge and clear OBS's Browser Source when changing profiles.
    """

    def __init__(
        self, lane: AudibleCaptionLane, *,
        freshness_seconds: float = 0.45,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(lane, AudibleCaptionLane):
            raise TypeError("expected STAR's existing AudibleCaptionLane")
        if (type(freshness_seconds) not in (int, float)
                or not math.isfinite(freshness_seconds)
                or not 0.25 <= freshness_seconds <= 0.8):
            raise ValueError("freshness_seconds must be 0.25..0.8")
        if not callable(clock):
            raise TypeError("clock must be host-owned callable")
        self._lane = lane
        self._freshness = float(freshness_seconds)
        self._clock = clock
        self._lock = RLock()
        self._server: _LoopbackHTTP | None = None
        self._thread: Thread | None = None
        self._secret: str | None = None
        self._live: tuple[DevicePlayoutEpoch, CaptionRender, float] | None = None
        self._metrics = {"published": 0, "blanked": 0, "served": 0, "rejected": 0}

    def _blank_locked(self) -> None:
        if self._live is not None:
            self._metrics["blanked"] += 1
        self._live = None

    @property
    def url(self) -> str | None:
        """Local OBS Browser Source URL. Do not log it or expose over chat."""
        with self._lock:
            if self._server is None or self._secret is None:
                return None
            return f"http://127.0.0.1:{self._server.server_port}/{self._secret}/"

    def start(self, *, owner_approved: bool = False) -> str:
        """Open ONLY the loopback listener, never launch OBS or go live."""
        if owner_approved is not True:
            raise PermissionError("owner approval is required for caption overlay")
        with self._lock:
            if self._server is not None:
                raise RuntimeError("overlay already started")
            _now(self._clock)
            owner = self
            secret = secrets.token_urlsafe(24)

            class Handler(BaseHTTPRequestHandler):
                protocol_version = "HTTP/1.0"

                def log_message(self, *_args):
                    # Neither the random URL nor approved spoken text is logged.
                    return

                def do_HEAD(self):
                    self.send_error(405, "Method Not Allowed")

                def do_POST(self):
                    self.send_error(405, "Method Not Allowed")

                def do_GET(self):
                    # BaseServer lacks this attribute in its protocol type;
                    # a missing listener port must reject the request.
                    expected_host = f"127.0.0.1:{getattr(self.server, 'server_port', None)}"
                    if self.headers.get("Host") != expected_host:
                        owner._rejected()
                        self.send_error(404, "Not Found")
                        return
                    path = self.path
                    if path == f"/{secret}/":
                        nonce = secrets.token_urlsafe(20)
                        html = _HTML.replace("__STAR_NONCE__", nonce).encode("utf-8")
                        policy = (
                            "default-src 'none'; base-uri 'none'; object-src 'none'; "
                            "form-action 'none'; connect-src 'self'; "
                            f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'"
                        )
                        self._send_payload(200, html, "text/html; charset=utf-8", policy)
                    elif path == f"/{secret}/state":
                        body = json.dumps(
                            {"text": owner._current_text()},
                            ensure_ascii=True, separators=(",", ":"),
                        ).encode("ascii")
                        self._send_payload(200, body, "application/json; charset=utf-8")
                    else:
                        owner._rejected()
                        self.send_error(404, "Not Found")

                def _send_payload(self, code, body, content_type, csp=None):
                    self.send_response(code)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store, max-age=0")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Referrer-Policy", "no-referrer")
                    self.send_header("Cross-Origin-Resource-Policy", "same-origin")
                    if csp is not None:
                        self.send_header("Content-Security-Policy", csp)
                    self.end_headers()
                    self.wfile.write(body)

            server = _LoopbackHTTP(("127.0.0.1", 0), Handler)
            self._server = server
            self._secret = secret
            self._live = None
            thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                            name="star-caption-local", daemon=True)
            self._thread = thread
            thread.start()
            url = self.url
            assert url is not None
            return url

    def _rejected(self) -> None:
        with self._lock:
            self._metrics["rejected"] += 1

    def _current_text(self, *, count_request: bool = True) -> str:
        with self._lock:
            if count_request:
                self._metrics["served"] += 1
            if self._server is None or self._live is None:
                return ""
            epoch, render, at = self._live
            try:
                age = _now(self._clock) - at
                if age < 0 or age > self._freshness or not self._lane.current(epoch, render):
                    self._blank_locked()
                    return ""
            except Exception:
                self._blank_locked()
                return ""
            return render.text

    def publish(
        self, epoch: DevicePlayoutEpoch | None,
        render: CaptionRender | None,
    ) -> bool:
        """Refresh the visible text from a newly sampled, still-current PCM cue.

        The host should call this every time it obtains a new playout frame,
        passing None to immediately clear on silence, interruption or pause.
        A previously sampled render is not an indefinitely renewable heartbeat.
        """
        with self._lock:
            if self._server is None or epoch is None or render is None:
                self._blank_locked()
                return False
            if not isinstance(epoch, DevicePlayoutEpoch) or not isinstance(render, CaptionRender):
                self._blank_locked()
                return False
            try:
                now = _now(self._clock)
                if not self._lane.current(epoch, render):
                    self._blank_locked()
                    return False
            except Exception:
                self._blank_locked()
                return False
            if self._live is not None:
                old_epoch, old_render, first_seen = self._live
                if (old_render is render and old_epoch is epoch
                        and now - first_seen > self._freshness):
                    self._blank_locked()
                    return False
                if (old_epoch is epoch and render.sampled_at < old_render.sampled_at):
                    self._blank_locked()
                    return False
                if old_render is render:
                    now = first_seen
            self._live = (epoch, render, now)
            self._metrics["published"] += 1
            return True

    def clear(self) -> None:
        """Revoke the next HTTP result; the browser also enforces expiry."""
        with self._lock:
            self._blank_locked()

    def stop(self) -> None:
        """Stop HTTP and revoke the URL; do not pretend to stop audio/OBS."""
        with self._lock:
            self._blank_locked()
            server, thread = self._server, self._thread
            self._server = None
            self._thread = None
            self._secret = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=2)

    def metrics(self) -> dict[str, int | bool]:
        with self._lock:
            return {**self._metrics, "running": self._server is not None,
                    "caption_visible": self._current_text(count_request=False) != ""}


__all__ = ["CaptionBrowserOverlay"]
