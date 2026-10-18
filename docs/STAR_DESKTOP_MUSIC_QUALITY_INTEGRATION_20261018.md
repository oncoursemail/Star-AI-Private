# STAR desktop music and quality integration (18 Oct 2026)

**Status:** Review-only stacked PR built on star/music-human-quality-20261018 (PR #481).
This adds the desktop integration for the existing Python quality/music pilot.
It does not deploy a public release, create a better foundation model, guarantee
any song match, silently record game audio, or certify that any output is perfect.

## Implemented in code

- A music-note action in the chat composer launches a native STAR song-identification dialog.
- The owner can select one local, bounded PCM16 WAV through the native Qt file picker,
  or deliberately capture one short sample from a microphone or configured virtual game input.
- AudD access requires explicit audio-upload consent and separate possible-billing acknowledgment.
  AcoustID access requires explicit fingerprint lookup consent and confirmation of noncommercial use.
- All secret tokens remain in the desktop environment and never go to React or the public repository.
- AcoustID uses an owner-selected installed Chromaprint fpcalc, deletes temporary WAV bytes,
  and sends only a fingerprint signature (not the full recording).
- Provider results display candidate tracks or no match, source/time provenance and
  clear uncertainty: not human-verified ground truth.
- No model tool can invoke the Qt-only file pickers or grant recording/network consent.
- Quality verification now has an actual Tools panel: choose a local artifact with a
  native file picker, hash its exact bytes and display the existing software,
  interface, animation, game, research and music checklist requirements.
- Python/JSON files receive a cheap, non-executing static parse. Syntax success
  never counts as a unit test, native playtest, human art approval or release gate.
- No AI-generated receipt can mark itself passed or authorize its own training.
  Actual native evidence, authenticated owner review, independent evaluation
  and ordinary repo CI are still required.

## How to use after this stack has been approved and released

Configure at least one approved provider token in the local environment:

    $env:STAR_AUDD_API_TOKEN = "(private approved token)"

Or, for eligible noncommercial AcoustID use:

    $env:STAR_ACOUSTID_CLIENT_KEY = "(registered client key)"

Open the desktop composer and select Identify song. Choose WAV or Microphone,
then choose a catalog and read the consent options. For music from a recording,
extract a short PCM16 WAV with locally installed FFmpeg, for example:

    ffmpeg -ss 20 -i "my-gameplay.mp4" -t 12 -vn -ac 1 -ar 16000 -c:a pcm_s16le song.wav

For AcoustID you must additionally choose your separately installed Chromaprint
fpcalc executable. External providers can have usage quotas or billing. A microphone
may include other people's speech: obtain consent before recording and uploading.
System-wide audio loopback or always-on recognition is not implemented.

Open Tools -> Quality verification. Choose a real artifact and view the
revision-bound checks that must be independently completed. A checklist is a
plan, not a substitute for tests and human design/animation judgment.

## What can make STAR faster and more accurate next

| Goal | Practical measurement and next implementation |
| --- | --- |
| Lower reply latency | Benchmark llama.cpp prefix cache, continuous batching, parallel slots and speculative decoding on owner hardware with frozen prompts and model weights |
| Higher throughput | Use existing resource leases and the resource planner; compare verified work per hour while preserving foreground chat p95 |
| Faster fixes | Classify concrete failures from actual logs, run affected tests first, run complete regression before approval, cap repeated repairs |
| Better UI/animation | Native Playwright screenshots/trace videos, real Blender frames, Roblox Studio multiplayer acceptance and user-reviewed design evidence |
| Better knowledge | Scoped, timestamped and licensed sources, calibrated abstention, evidence-carrying claims and deduplicated retrieval |
| Safer learning | Rights-cleared successful fixes promoted only after independent paired holdouts and rollback, never self-reported success |
| Better music | Opt-in Windows loopback, offline acoustic analysis, additional licensed providers, and rights-cleared false-match benchmarks |

STAR already has many of these foundations: do not install duplicate schedulers,
arbitrary community MCP servers, or uncontrolled AI swarms. Increasing agent
count on one memory-constrained host can make latency worse. The optimum is
measured verified quality per unit of time and compute, not marketing claims.

## Source documents

- llama.cpp server batching, cache and metrics: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- Harness engineering and agent feedback loops: https://openai.com/index/harness-engineering/
- Official Playwright trace docs: https://playwright.dev/docs/api/class-tracing
- Qt native file dialog contract: https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QFileDialog.html
- AudD: https://docs.audd.io/ and https://s2.audd.io/pricing/
- AcoustID noncommercial service and 3 req/s limit: https://acoustid.org/webservice
- Chromaprint: https://github.com/acoustid/chromaprint

## Developer verification

    python -m compileall -q star
    python -m pytest -q tests/test_desktop_music_quality.py tests/test_music_quality_bridge_contract.py
    python -m pytest -q tests/test_music_recognition.py tests/test_human_quality.py
    python -m pytest -q
    cd frontend
    npm run typecheck
    npm run test
    npm run build

These runs do NOT identify real music, access a live microphone, prove a Windows
install launched, or perform a human subjective-quality assessment. Browser
preview without a Qt desktop host must never show a fake catalog match.

The stacked branch cannot be merged ahead of PR #481. Its existing base
night-conductor CI regression must be independently fixed, not bypassed.
Release only through STAR's official reviewed GitHub Actions pipeline, never
by auto-merging research.
