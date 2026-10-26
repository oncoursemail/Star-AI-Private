# Own-PC release preparation follow-up, 2026-10-26

This is a reviewed source preview for supervised native testing, not a deployed or fully autonomous release. The dedicated Windows PC remains unconnected at the time of this validation. A separate reviewed SSH bootstrap file is local-only under ignored build output; its private client key is outside this repository and was not committed. No accounts, messages, broadcast, payment, cleanup or sealed evaluation were touched.

Three concrete defects were addressed:

- Home created sound outputs without starting their PortAudio streams. Both voice factories now start owned output before publishing it, transfer ownership on success and clean up failures. Monitor selection is validated before allocation. Fake callbacks verify queued PCM can drain; this is not proof of audible/native routing or capture readiness.
- A scheduled Home loop and a manual `run`/`once` could both control the same data folder. They now share the existing operating-system lock. Duplicate starts exit before setup. One-shot cleanup must finish before releasing ownership; uncertain partial startup and long-running processes retain their lease until process exit. A permanent shutdown latch prevents an old runtime reopening admission. This guards one canonical Home folder, not every possible installation on the PC, and does not terminate all background threads.
- The brain loop accepted truthy strings as successful finish/goal flags and checked interruption too late for a returned tool batch. It now validates finish/host results, checks STOP/deadlines between operations, refuses premature model goal completion, and reports uncertain action outcomes without automatically replaying them.

## Evidence

**58 new offline checks pass**: audio startup 16, instance/shutdown 19, primary brain boundaries 13 and independent brain review 10. The instance verifier uses real verifier-owned subprocesses for lock races and crash recovery. Audio checks use the actual buffer and output class over fake PortAudio; no real device or model was opened.

The existing combined selection passed **145 tests**:

```text
python -m pytest -q tests/test_star_home.py tests/test_home_wiring.py tests/test_senses_voice.py tests/test_voice_call.py tests/test_voice_natural.py
```

An existing inert stop-callback fixture initially exposed an assumption that every fake executor had a Home path. The production guard now checks that path when supplied, preserving immediate callback-only cancellation. The affected case was rerun and passed. Existing test and evaluation sources were not edited.

Independent source reviews passed for the workflow/goal guard, ownership/shutdown and audio changes. Ruff, compilation and whitespace checks passed. Full package-free Pyright 1.1.414 remains at 570 pre-existing errors with no increased per-file/per-rule error counts. Full repository typing and remote queued CI are not described as green.

Detailed contracts: [brain boundaries](codex-home-brain-boundaries-20261026.md), [instance ownership](codex-home-instance-20261026.md), [audio startup](codex-home-audio-startup-20261026.md).

## Native boundary

Windows interactive tasks require the intended user to be logged on; an SSH shell is not that desktop. Setup should run the existing interactive `STAR Home` task, with exactly one runtime and STOP available. The first real call still needs device routing, capture/model startup, incoming-call recognition, interruption, delayed speech and two-way audible delivery checked on the actual PC.

Emotion and recall quality gates remain unchanged. Production rigging, automatic friendship delivery, public Twitch speech, generalized computer competence and human feelings are not established by this update.
