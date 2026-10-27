# Home audio output startup, 2026-10-26

Home's standalone and call factories constructed `SoundOutput` without entering
its context. Construction creates an inactive PortAudio stream; `__enter__`
starts it. `CallSession.start()` and `build_pc_session()` do not start that
speaker. TTS could therefore fill the buffer while no audio callback consumed it.
This affected both game/watch remarks and the native call speaker.

The factories now start the raw owned output before wrapping or publishing it.
An output-start exception propagates to the existing call-failure result, with
no call-state or camera-success side effect. Construction uses an ExitStack:
subsequent wrapper, brain, session, capture or call-object failure attempts to
close each resource already returned to the factory. Successful construction
transfers ownership to the returned speaker or VoiceCall; it does not close the
stream early. Shared cached TTS/ASR engines are not closed.

`routes.open_voice_output()` also validates a named monitor before allocating
the cable output. Failure while constructing that monitor closes the cable
already allocated. No monitor is added by default, and a missing cable or
configured monitor still fails rather than falling back to physical speakers.

`python scripts/verify_home_audio_startup.py` runs 16 hardware-free checks using
the actual SoundOutput, routing and PlaybackBuffer with fake PortAudio streams.
It verifies exactly one start per output, fake TTS reaching the callback and
draining the queue, explicit monitor behavior, ownership transfer and failure
cleanup. A fake output-start failure through DiscordCalls does not report a
connected voice session or start a camera. No model, device, account, network
request or real call is used by the verifier.

The [sounddevice stream documentation](https://python-sounddevice.readthedocs.io/en/0.5.1/api/streams.html)
confirms that a newly created stream is inactive and that context entry starts
it. It also cautions that simultaneous streams on one device depend on the host
API. The fake callback check is not proof of audible output, VB-CABLE routing,
microphone capture, latency, cancellation on a real driver or sustained calls.
Native close operations can fail; resource cleanup is attempted, not certified.
Resources that a nested factory fails to return remain that factory's
responsibility. Lazy capture startup still requires separate native verification.

## First supervised call on STAR's PC

The installer registers Home for the chosen Windows user's interactive logon.
[Microsoft's Task Scheduler documentation](https://learn.microsoft.com/en-us/windows/win32/taskschd/principal-logontype)
says interactive-token tasks require an already logged-on user and run in an
existing interactive session. An SSH connection alone does not establish those
conditions or prove that Discord and audio work. Do not start a second Home loop
from an SSH shell.

Use the existing first-session guide on the dedicated PC. Confirm the intended
Windows account is logged on to the usable desktop, Discord is signed in, one
Home process is running, and preview is disabled only for the supervised test.
Select STAR Microphone as Discord's input. The current call factory captures
Windows' default playback output, so Discord's selected output must be the route
that capture is actually hearing. Verify both directions with a willing partner,
including a delayed reply, interruption and STOP. A visible Discord connection,
factory return or locally queued PCM alone does not prove a working conversation.
