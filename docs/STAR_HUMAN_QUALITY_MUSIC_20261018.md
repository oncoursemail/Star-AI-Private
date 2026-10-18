# STAR Human Quality + Music ID: Research and Pilot (2026-10-18)

**Status:** Review branch, Python backend / CLI pilot, not a public STAR release. Does not enable automatic listening, unrestricted data access, a React music button, Discord voice capture, human-level intelligence, or guaranteed flawless results. Separate from PR #478 and PR #479.

## Why human-quality verification must be evidence based

STAR already has a paired evaluation gate, visual approvals, a failure ledger, repair tools, game playtest planning, and Blender animation tests. Reuse them, do not give an LLM an independent authority to approve its own work.

**New: star/human_quality.py**

- Offline, deterministic rubrics: software, interface, animation, game, music, research. Every criterion is linked to an immutable artifact revision SHA-256.
- Validated receipts may represent genuine unit/integration tests, native playtests, visual captures, source checks, audio identification, accessibility, security and performance checks. Unexecuted checks and agent-generated pseudo-receipts never count.
- Native requirements do not count static/simulated checks as proof. Source hash, evidence hash and host-authenticated origin prevent stale/irrelevant reports from being reused as native success (hashes by themselves are not cryptographic attestation).
- Distinct outcomes: blocked, needs_evidence, needs_owner, qualified, qualified_with_advisories. A qualified rubric establishes only its defined checks, never "perfect".
- Owner approval is separately required for aesthetic/gameplay tasks. A bounded next-action preview suggests what to fix/retest; after three attempts on one criterion, escalate rather than spin forever.
- Learning proposals stay disallowed without owner authorization and the existing independent promotion/holdout gate. The CLI cannot grant training permission.

**Real execution plan:** Owner requirements and exact reference → generate one candidate → deterministic static checks → native tests and screenshots/frames → independent fact/visual checks → targeted repair + regression retest → owner signoff for subjective quality → separately gated project-scoped learning candidate. Never let the model modify tests or forge evidence.

Primary methods: https://github.com/UKGovernmentBEIS/inspect_evals/blob/main/EVALUATION_CHECKLIST.md and https://github.com/UKGovernmentBEIS/inspect_ai
STAR architecture: star/eval_gate.py, star/creative_review.py, star/failure_ledger.py.

Example:

    python -m star.human_quality --template game
    python -m star.human_quality --template interface --manifest quality.json

The manifest must come from trusted actual test results; writing "passed" in JSON is **not proof** of a real run.

## What song is this? Provider comparison

Audio fingerprint databases match recordings, not general "music understanding." A singing voice, cover, remix, unreleased game track, multiple overlapping songs, noisy party chat, humming or an unfamiliar sound may yield no match or a wrong match. Showing a convincing title is not proof it was correct.

| Provider | Capability | Limits, privacy and STAR status |
| --- | --- | --- |
| AudD | Official short-sample identification; standard endpoint checks about 12 seconds | Sends selected waveform with approved token. Free trial where eligible, possible paid plan/overages. Adapter implemented and offline-mocked; not yet live/provider-tested |
| AcoustID + Chromaprint | Locally compute fingerprint, look up recording metadata | Only fingerprint sent. Free web service **noncommercial only** and max 3 req/s; separately installed fpcalc + client key required. Adapter implemented and offline-mocked |
| Apple ShazamKit | Match to official large Shazam or custom catalog | Apple platform and Android SDK, developer enrollment/auth required. **No unrestricted native Windows/Python catalog API**; not implemented |
| ACRCloud | Official signed audio/fingerprint matching | Project authorization, cost, terms, region; candidate for later approved adapter |
| MusicBrainz | Recording/release metadata and identifiers | Useful for enriching a successful match, not a waveform recognizer by itself; ~1 request/s restriction |

Official references:
- https://docs.audd.io/ and https://s2.audd.io/pricing/
- https://acoustid.org/webservice and https://github.com/acoustid/chromaprint
- https://developer.apple.com/documentation/shazamkit and https://developer.apple.com/shazamkit/android/
- https://docs.acrcloud.com/reference/identification-api/identification-api
- https://musicbrainz.org/doc/MusicBrainz_API

## Added STAR module: star/music_recognition.py

- Reuses STAR's validated native PCM16 WAV AudioSource, without asking an LLM to infer a song from a transcript.
- AudD sends only an explicitly selected 4–12-second local snippet to one fixed HTTPS endpoint. Two booleans require explicit audio-upload and possible-provider-billing consent. No redirects, secrets in URLs, automatic provider fallback, unapproved domains, or recording history.
- AcoustID uses user-installed local Chromaprint fpcalc for 4–30 seconds, deletes the temporary WAV, and sends fingerprint/duration only after a separate explicit consent and noncommercial-usage assertion.
- Returns one or several sanitized candidates, bounded provenance hashes, actual clip offsets, provider identity, and human_verified=false. The fingerprint similarity score is uncalibrated and is **not** a percentage probability of being right; AudD usually gives no score.
- A microphone can be recorded by explicit one-shot command when optional voice dependencies are installed. The user can select a Stereo Mix or virtual mic device carrying game sound. Direct system-wide loopback is not yet integrated; the app never silently listens to another process or call.
- Unknown, silent, unmatched, refused, malformed or quota-limited results fail closed; no song is invented.

## How to try on Windows from a development checkout

Store keys in the environment or approved local secret store; never paste them in repo files or command arguments:

    $env:STAR_AUDD_API_TOKEN = "(approved provider token)"
    python -m star.music_recognition --file "song-sample.wav" --provider audd --seconds 12 --allow-upload --accept-billing

One-shot microphone:

    python -m star.music_recognition --mic --seconds 12 --provider audd --allow-upload --accept-billing

For game audio saved to a local OBS/Medal video, user chooses the clip and uses locally installed FFmpeg to extract PCM16 WAV:

    ffmpeg -ss 20 -i "recorded-gameplay.mp4" -t 12 -vn -ac 1 -ar 16000 -c:a pcm_s16le "song-sample.wav"

Noncommercial fingerprint-only lookup with user-installed Chromaprint (20–30 seconds is often preferable):

    $env:STAR_ACOUSTID_CLIENT_KEY = "(registered client key)"
    python -m star.music_recognition --file "long-sample.wav" --provider acoustid --seconds 30 --fpcalc "C:\Apps\Chromaprint\fpcalc.exe" --allow-fingerprint --noncommercial

Only capture audio and other people's voices with appropriate consent and privacy notice. AudD pricing/quotas can change and are not presumed free. AcoustID's free endpoint must not be used as a commercial catalog without agreement. The module does not enable background monitoring.

## Verification

    python -m compileall -q star
    python -m pytest -q tests/test_music_recognition.py tests/test_human_quality.py
    python -m pytest -q

Mock HTTP responses and synthetic/harness tests prove only validation and contracts; **no real AudD/AcoustID song was identified or paid request made**. Live Windows microphone tests, actual provider matches on licensed reference recordings, noise/false-match studies, actual screenshots, and privacy/owner acceptance are needed before release.

## Next independently reviewed integrations

1. Add "Identify song" to STAR's existing React attachment/audio composer with explicit source selection, recording indicator, privacy/cost consent, and a clear "not found" state.
2. Add user-initiated Windows system-output capture where OS APIs permit it, with visible consent, cancellation, short retention, and no default Discord party-chat recording.
3. Add reference-based native checkpoints: Playwright animation traces, Blender animation and rig frames, real Roblox Studio test receipts, latency/fps/memory profiles, vision/audio quality comparisons. Use independently validated receipts, not merely generated text.
4. Add a reviewer dashboard with real failure evidence, attempted repairs, owner notes, uncertainty and rollback. Measure validated work/minute and changes in first-pass correctness, not raw agent count.
5. Use only rights-cleared, owner-approved failure examples and sealed held-out evaluation to propose skills, routing adjustments or model tuning. Never treat self-generated answers as automatically trusted training labels.

**Outcome:** This PR creates new opt-in tools and a practical evidence contract. It does not magically increase inference speed or transform a local assistant into AGI. Any advertised improvements must first pass the independent gates on actual hardware and user-selected artifacts.
