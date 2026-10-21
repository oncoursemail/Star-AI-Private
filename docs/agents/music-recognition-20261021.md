# music-recognition-20261021: song recognition as one opt-in STAR feature

Folds PR #481 (star/music-human-quality-20261018) and PR #483 (star/desktop-music-quality-integration-20261018)
into one feature on `star/music-recognition-20261021`, from origin/star/next 9908e36c.

## What it does
- Settings > Images, voice & 3D > Song recognition: switch `music_recognition_enabled` (off by default), the AudD
  token and AcoustID client key (OS keyring through `saveProviderKey`, `star/providers.py` MUSIC_KEYS, like the
  Brave/Tavily keys), `fpcalc_path` ('' = PATH). Key fields appear only once the switch is on.
- Composer (only while on): an "Identify a song" button opens a dialog (a WAV chosen in the native picker, or one
  4-30 s recording from a chosen input: microphone, Stereo Mix or a virtual cable). A WAV attached to a message gets
  a line "Identify the song. <what is sent where>" with a catalog choice; ticking it approves one lookup.
- Chat: that approval (`songLookup` in `sendMessage`, checked by `react_shell.song_lookup_request`) attaches the
  `star_identify_song` tool (`music_recognition.ChatSongLookup`) for that turn only, one call. The model cannot set
  the flag. The approved WAV skips speech-to-text. The tool is in `agent.UNTRUSTED_SOURCE_TOOLS`.
- `music_recognition.identify`: refuses without the setting or `consent is True`; returns `not_configured` (no key)
  or `not_installed` (no fpcalc) without sending; runs as a registered backend of
  `audio_understanding.inspect_audio` (its first real caller); HTTP via the new `web_fetch.post_form` (same
  public-address checks and pinning as fetch_page, no redirects, no proxy, 96 KB JSON cap).
  AudD gets the WAV clip (4-12 s); AcoustID gets only the fpcalc fingerprint and length (4-30 s).
- Keys never reach the bridge payload, results or logs (status returns booleans only; tests assert it).

## Dropped from the PRs, and why
- `star/human_quality.py`, `QualityChecklistPanel.tsx`, quality bridge actions, `desktop_music_quality.py`: the panel
  called `review()` with no receipts, and nothing in STAR produces receipts, so every output was the constant
  "needs evidence" list. No real caller: trimmed per the brief. The music session part moved into
  `music_recognition.DesktopSession`.
- The argparse CLI (read keys from environment variables) and the separate httpx client (second HTTP path).
- The fpcalc file chooser (Settings path or PATH instead), the AcoustID "noncommercial" and AudD "billing" extra
  checkboxes (one consent line per lookup that names the service and what it receives), both PR docs.

## Tests run (2026-10-21)
- `pytest tests/test_music_recognition.py` + web_fetch, audio_understanding, bridge exec, agent, settings, provider,
  chat-path suites: 597 passed. `tests/test_server_first_flow.py` fails only when run after
  `tests/test_server_provider.py`; the same pair fails on clean origin/star/next (pre-existing, not this branch).
- `ruff check` on changed Python: clean. Pyright 1.1.414: `star/music_recognition.py` no errors; the baseline
  check reports overages in files this branch does not change in those lines (providers.py:227, vision.py,
  image_gen.py, desktop_core instant-route lines): the local venv's package versions differ from CI.
- Frontend: `npm run typecheck` clean, `npm test` 67 files / 628 tests passed, `npm run build` OK.
- `tests/test_night_conductor.py` (the #481 review failure): 31 passed on current star/next.

## Not verified
- No live AudD/AcoustID call, no real fpcalc run, no real microphone recording (all faked in tests).
- The dialog and composer line were not looked at in a running desktop (DOM tests only).
- WAV only (PCM16, up to 8 MB / 120 s, the audio_understanding limits); MP3 etc. would need decoding first.
