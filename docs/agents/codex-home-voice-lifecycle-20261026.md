# Home voice cancellation and call handoff, 2026-10-26

Game and watch remarks previously had no cancellation path: delayed TTS could
enqueue audio after STOP or after a private call started. `VoiceCall.stop()` also
waited for the capture thread before closing its source; a source waiting for its
next frame could therefore keep the session and output alive indefinitely.

`HomeVoice` now accepts a trusted host STOP check through
`set_stop_check(check)`. `stop()` invalidates pending work, flushes the old line's
speaker and ends the current call. A line checks that predicate before opening
output and before each PCM enqueue. Cancellation closes its generator when it
next yields and prevents a false completed-line record. Ordinary HomeVoice speech
still serves game/watch remarks and private conversation; it is not connected to
the public stream-chat speech hook.

Call startup reserves one transition and checks its generation after a slow
factory returns. STOP invalidates that generation; an unpublished candidate is
closed without starting. Flushing the old line happens before publishing a new
call, under the handoff lock. A late old TTS chunk only drops: it cannot clear the
new call's speaker. Cleanup of an old call also checks identity before detaching
anything. Game context and adult-peer transcript handling remain in their
existing paths.

`VoiceCall.stop()` flushes its own speaker, then stops its session once before closing owned capture/output resources,
and uses a half-second bounded worker join. Stopping an unstarted candidate is
supported. Each closer is attempted even if another raises. Session stopping
still includes the existing `CallSession.stop()` reply wait, up to three seconds;
the half-second join is not a claim that all shutdown work always finishes in
half a second.

`DiscordCalls.stop()` clears active friend, timer, presence and departure state
without a goodbye, Discord click or friend-departure emotion. Navigation and
button-location paths check STOP again after waits before a later action.
Runtime owns installation of the STOP predicate and calling these stop hooks.

Verification uses 26 checks in `python scripts/verify_home_voice_lifecycle.py` with fake TTS,
speakers, capture, call sessions and app actions. No account, device, model or GPU
was opened. The checks cover delayed and queued audio, handoff isolation, slow
factories, concurrent starts, resource failures, stale cleanup, blocked capture,
and STOP during app navigation. A blocked capture closer cannot delay the prior
session/speaker cancellation; its cleanup worker can still remain blocked until
that native closer returns. Dry-run checks exercise the actual Runtime voice
binding, preserve planning, reject late TTS after a mode change and prevent camera
UI actions both initially and when preview begins during camera startup.
Existing home wiring, voice call/natural-voice
tests and the separate adult-voice verifier are also run during integration.

Python threads cannot be forcibly interrupted through the threading API; see the
[official threading reference](https://docs.python.org/3.12/library/threading.html#thread-objects).
A native inference call that does not return can still occupy its worker. This
change blocks subsequent PCM and requests cleanup; it does not promise to stop a
GPU kernel, kill threads, prove microphone routing or establish audible latency.
The dedicated PC still needs a real VB-CABLE/Discord route and STOP smoke test.
