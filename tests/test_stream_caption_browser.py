"""Local HTTP/PCM tests. Does not start OBS, stream, record or access a mic."""
from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit

import pytest

from star.stream_audible_captions import AudibleCaptionLane, CaptionSegment
from star.stream_audio_sample_host import DeviceAudibleSampleHost
from star.stream_caption_browser import CaptionBrowserOverlay
from star.stream_director import StreamSignal
from star.stream_motion import AudioLevel
from star.stream_playout_clock import StarPlayoutClock
from star.stream_stage import StarStage


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def step(self, amount):
        self.now += amount


def fresh_audio():
    clock = Clock()
    stage = StarStage(clock=clock)
    stage.enable(owner_approved=True)
    assert stage.offer(
        StreamSignal("overlay-test", "game_success", clock.now,
                     "A real event", evidence="observed"), now=clock.now,
    )
    plan = stage.prepare(now=clock.now)
    assert plan is not None
    assert stage.queue_audio(plan, now=clock.now)
    assert stage.acknowledge_audible(plan, now=clock.now)
    play = StarPlayoutClock(stage, clock=clock)
    play.enable(owner_approved=True)
    assert play.arm(plan, duration_s=1.0, audio_levels=(
        AudioLevel(0, .3), AudioLevel(.3, .1),
    ))
    device = DeviceAudibleSampleHost(play)
    device.enable(owner_approved=True)
    epoch = device.bind(plan, sample_rate_hz=48000, total_samples=48000)
    assert epoch is not None
    lane = AudibleCaptionLane(stage, device)
    lane.enable(owner_approved=True)
    assert lane.bind(
        plan, epoch, (
            CaptionSegment("I finally got it!", 0, 12000),
            CaptionSegment("One more try?", 12000, 42000),
        ), text_approved_for_broadcast=True,
    )
    return clock, stage, device, epoch, lane


def played_frame(clock, device, epoch, lane, samples=2400):
    assert device.report_played(epoch, played_samples=samples, sampled_at=clock.now)
    render = lane.sample(epoch, device.sample(epoch))
    assert render is not None
    return render


def read(url):
    with urllib.request.urlopen(url, timeout=2) as response:
        return response.status, response.headers, response.read()


@pytest.fixture
def running():
    clock, stage, device, epoch, lane = fresh_audio()
    overlay = CaptionBrowserOverlay(lane, clock=clock)
    url = overlay.start(owner_approved=True)
    try:
        yield clock, stage, device, epoch, lane, overlay, url
    finally:
        overlay.stop()


def state(url):
    code, headers, raw = read(url + "state")
    assert code == 200
    assert headers["Cache-Control"].startswith("no-store")
    return json.loads(raw)


def test_owner_opt_in_and_bounded_parameters():
    _, _, _, _, lane = fresh_audio()
    overlay = CaptionBrowserOverlay(lane)
    assert overlay.url is None
    with pytest.raises(PermissionError):
        overlay.start()
    with pytest.raises(PermissionError):
        overlay.start(owner_approved=1)
    with pytest.raises(TypeError):
        CaptionBrowserOverlay(object())
    for bad in (-1, 0, .01, 1, True, float("nan"), float("inf"), "1"):
        with pytest.raises(ValueError):
            CaptionBrowserOverlay(lane, freshness_seconds=bad)
    with pytest.raises(TypeError):
        CaptionBrowserOverlay(lane, clock=5)


def test_invalid_trusted_clock_prevents_server():
    _, _, _, _, lane = fresh_audio()
    overlay = CaptionBrowserOverlay(lane, clock=lambda: float("nan"))
    with pytest.raises(ValueError):
        overlay.start(owner_approved=True)
    assert overlay.url is None


def test_empty_by_default_binds_only_loopback(running):
    *_, overlay, url = running
    assert state(url) == {"text": ""}
    assert url.startswith("http://127.0.0.1:")
    assert overlay._server.server_address[0] == "127.0.0.1"
    assert overlay.metrics()["caption_visible"] is False


def test_html_nonced_local_script_and_watchdog(running):
    *_, overlay, url = running
    status, headers, body = read(url)
    html = body.decode("utf-8")
    assert status == 200
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert "no-store" in headers["Cache-Control"]
    assert "default-src 'none'" in headers["Content-Security-Policy"]
    assert "script-src 'nonce-" in headers["Content-Security-Policy"]
    assert "style-src 'nonce-" in headers["Content-Security-Policy"]
    assert "<script nonce=" in html
    assert "caption.textContent" in html
    assert "innerHTML" not in html
    assert "performance.now()" in html
    assert 'setTimeout(() => controller.abort(), 300)' in html
    assert "fetch(\"state\"" in html
    assert 'credentials:"omit"' in html
    assert "I finally got it!" not in html
    assert "http://" not in html and "https://" not in html
    assert overlay.metrics()["published"] == 0


def test_audio_playback_updates_http_text(running):
    clock, _, device, epoch, lane, overlay, url = running
    assert not overlay.publish(epoch, None)
    assert state(url) == {"text": ""}
    first = played_frame(clock, device, epoch, lane)
    assert overlay.publish(epoch, first)
    assert state(url) == {"text": "I finally got it!"}
    clock.step(.35)
    second = played_frame(clock, device, epoch, lane, samples=18000)
    assert not lane.current(epoch, first)
    assert overlay.publish(epoch, second)
    assert state(url) == {"text": "One more try?"}
    assert overlay.metrics()["published"] == 2


def test_revocation_of_stage_blanks_without_another_publish(running):
    clock, stage, device, epoch, lane, overlay, url = running
    assert overlay.publish(epoch, played_frame(clock, device, epoch, lane))
    assert state(url)["text"]
    stage.disable()
    assert state(url) == {"text": ""}
    assert overlay.metrics()["blanked"] == 1


def test_revocation_of_pcm_device_blanks_immediately(running):
    clock, _, device, epoch, lane, overlay, url = running
    assert overlay.publish(epoch, played_frame(clock, device, epoch, lane))
    device.stop(epoch, output_stopped_and_flushed=True)
    assert state(url) == {"text": ""}


def test_audio_pause_blanks_without_new_valid_sample(running):
    clock, _, device, epoch, lane, overlay, url = running
    assert overlay.publish(epoch, played_frame(clock, device, epoch, lane))
    clock.step(.04)
    assert device.report_played(
        epoch, played_samples=2400, sampled_at=clock.now, playing=False,
    )
    assert state(url) == {"text": ""}


def test_server_side_heartbeat_expiry_independent_of_pcm(running):
    clock, _, device, epoch, lane, overlay, url = running
    render = played_frame(clock, device, epoch, lane)
    assert overlay.publish(epoch, render)
    clock.step(.46)
    assert state(url) == {"text": ""}
    # A stolen old cue cannot be reauthenticated by this expired host pulse.
    assert not overlay.publish(epoch, render)
    assert state(url) == {"text": ""}


def test_repeated_identical_render_does_not_extend_deadline(running):
    clock, _, device, epoch, lane, overlay, url = running
    render = played_frame(clock, device, epoch, lane)
    assert overlay.publish(epoch, render)
    clock.step(.04)
    assert overlay.publish(epoch, render)
    clock.step(.45)
    assert state(url) == {"text": ""}


def test_reverse_playback_sample_fails_closed(running):
    clock, _, device, epoch, lane, overlay, url = running
    first = played_frame(clock, device, epoch, lane)
    assert overlay.publish(epoch, first)
    clock.step(.35)
    second = played_frame(clock, device, epoch, lane, samples=18000)
    assert overlay.publish(epoch, second)
    # Cannot re-publish an old audio generation after a newer phrase.
    assert not overlay.publish(epoch, first)
    assert state(url) == {"text": ""}


def test_clear_and_invalid_publish_blanks_output(running):
    clock, _, device, epoch, lane, overlay, url = running
    valid = played_frame(clock, device, epoch, lane)
    assert overlay.publish(epoch, valid)
    overlay.clear()
    assert state(url) == {"text": ""}
    assert overlay.publish(epoch, valid)
    assert not overlay.publish(epoch, "raw model text")
    assert state(url) == {"text": ""}
    assert not overlay.publish(None, valid)
    assert state(url) == {"text": ""}


def test_new_epoch_identity_required(running):
    clock, _, device, epoch, lane, overlay, url = running
    render = played_frame(clock, device, epoch, lane)
    forged = type(epoch)(epoch.sequence, epoch.generation,
                         epoch.sample_rate_hz, epoch.total_samples)
    assert not overlay.publish(forged, render)
    assert state(url) == {"text": ""}
    assert overlay.publish(epoch, render)
    assert state(url)["text"]


def test_no_unknown_paths_or_query_leaks(running):
    *_, overlay, url = running
    for target in ("not-the-token", url + "../state", url + "?x=1",
                   url + "state?x=1", url + "states"):
        address = target if target.startswith("http") else (
            "http://127.0.0.1:" + urlsplit(url).port.__str__() + "/" + target
        )
        with pytest.raises(urllib.error.HTTPError) as err:
            read(address)
        assert err.value.code == 404
    assert overlay.metrics()["rejected"] >= 5


def test_host_header_does_not_allow_rebinding(running):
    *_, overlay, url = running
    parsed = urlsplit(url)
    connection = http.client.HTTPConnection("127.0.0.1", parsed.port, timeout=2)
    try:
        connection.putrequest("GET", parsed.path + "state", skip_host=True)
        connection.putheader("Host", "malicious.example")
        connection.endheaders()
        reply = connection.getresponse()
        assert reply.status == 404
    finally:
        connection.close()


def test_head_post_are_disabled(running):
    *_, overlay, url = running
    for method in ("HEAD", "POST"):
        req = urllib.request.Request(url, method=method)
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=2)
        assert err.value.code == 405


def test_stopped_url_dies_and_restart_rotates_capability(running):
    clock, _, device, epoch, lane, overlay, url = running
    assert overlay.publish(epoch, played_frame(clock, device, epoch, lane))
    overlay.stop()
    assert overlay.url is None
    assert overlay.metrics()["caption_visible"] is False
    other = overlay.start(owner_approved=True)
    assert other != url
    assert state(other) == {"text": ""}
    # Old source URL on the new listener must never revive prior text.
    old_token = urlsplit(url).path
    new_parsed = urlsplit(other)
    with pytest.raises(urllib.error.HTTPError) as err:
        read(f"http://127.0.0.1:{new_parsed.port}{old_token}state")
    assert err.value.code == 404


def test_no_sensitive_text_in_metrics(running):
    clock, _, device, epoch, lane, overlay, url = running
    assert overlay.publish(epoch, played_frame(clock, device, epoch, lane))
    fields = overlay.metrics()
    assert fields["caption_visible"] is True
    assert "I finally got it!" not in repr(fields)
    assert url not in repr(fields)
    assert "port" not in fields


def test_disabling_caption_lane_clears_http_state(running):
    clock, _, device, epoch, lane, overlay, url = running
    assert overlay.publish(epoch, played_frame(clock, device, epoch, lane))
    lane.disable()
    assert state(url) == {"text": ""}


def test_browser_never_receives_model_generated_html(running):
    clock, _, device, epoch, lane, overlay, url = running
    render = played_frame(clock, device, epoch, lane)
    assert overlay.publish(epoch, render)
    status, _, html = read(url)
    assert status == 200
    assert b"I finally got it!" not in html
    # Approved spoken phrase exists only in a bounded JSON field.
    assert state(url) == {"text": "I finally got it!"}
