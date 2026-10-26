# play-learn-20261026: STAR learns games from recorded play

Branch `star/play-learn-20261026` (from origin/star/next dff4a008), worktree `worktrees/play-learn`, board item #263.
Research: `docs/research/play-learn-20261026.md`. Code: `star/play/learn/`. Tests: `tests/test_play_learn.py`.

## What exists
- `actions.py`: GameSpec (keys, buttons, mu-law mouse bins, success/failure moment kinds, chat keys, window) with
  presets `roblox_obby` and `minecraft`; InputState turns events into per-step labels (short taps count; only game
  keys; chat pauses labels; mouse buttons use their own namespace).
- `recorder.py`: Recorder (consent note required, `[STAR rec]` lines at start, every 5 min and at stop, game window
  region only, steps dropped while the window is not in front), npz shards written on a writer thread, frame t
  stored with the input made after it, `mark()` for game moments, `cut()` for respawns. `SinkTap` and `TeeSource`
  record STAR's own play; `RawInputSource` records the owner's (Raw Input on a message-only window).
- `dataset.py`: Corpus (RAM or memmap cache), session-level split, gap-aware frame stacks, idle thinning, episode
  masks (+1 success, -1 failure).
- `policy.py`: IMPALA CNN (1.29 M params at 128x72x3 frames), 4 heads, AdamW + cosine, fp16 AMP, shift + colour
  augmentation, best/last checkpoints with spec, stats and metrics.
- `adapter.py`: FrameObserver, PolicyController (sampling, a 60 ms minimum key hold, mouse capped at the human p99),
  PolicyActor (key transitions with jitter, mouse spread with minimum jerk), `obby_signal`, and
  `reflex_session(checkpoint, source=, sink=, recorder=)`, which plugs into the existing GameSession via session._wire.
- `improve.py`: `select_steps` (success episodes plus human replay), `improve()` (fine-tune, evaluate incumbent and
  candidate, promote only if better, previous.pt kept for rollback, receipts.jsonl).
- `evaluate.py`: success rate over N attempts with a Wilson interval, `<root>/evals/<game>.jsonl`, and her Life
  history line (`star.home.life.Life.record`, activity "eval <game>"); `session_attempt` for live games.
- `synthetic.py`: DotGame plus a scripted human-like player (tests and synthetic GPU runs).
- CLI: `python -m star.play.learn {record,train,synth,bench,heavy-ok}`.
- Only change outside learn/: one docstring line in `star/play/__init__.py`.

## Verified (commands run)
- `PYTHONPATH=<scratch pytest> tools-portable/train-venv/Scripts/python.exe -m pytest -q tests/test_play_learn.py`
  -> 22 passed (torch 2.11 CPU paths). Audit venv (no torch): `tests/test_play_learn.py tests/test_play.py` -> 44
  passed, 3 skipped. `ruff check star/play/learn tests/test_play_learn.py` clean.
- CPU smoke `synth --frame 32x18 --episodes 150 --steps 400 --eval-n 40 --device cpu`: base 27/40, after one
  filtered-BC round 31/40, promoted. The intervals overlap, so this is not evidence yet.
- `bench --game roblox_obby`: CUDA fp16 p50 3.9 ms, p95 6.5 ms, 12.5 MB; CPU p50 10.5 ms.
- Raw Input: registration, two injected 1-px mouse moves seen, clean stop. Keyboard not exercised.

## GPU synthetic run
Allowed only when `python -m star.play.learn heavy-ok` exits 0 (owner idle >= 5 min, or 05:00-13:00Z). Result:
PENDING (filled in below when run).

## Not done / limits
- No real game learned and no real play recorded (not allowed on this PC). Data needed per game: 2-5 h of the
  owner's play for one obby course (estimate from the CS:GO and VPT numbers in the research doc).
- No human-likeness distribution report yet; no action chunking; no IDM.
- torch is not in requirements.txt, so CI skips the 3 torch tests. STAR's PC needs a CUDA torch in her runtime.

## Resume
Next: on STAR's PC, record the owner on one obby, `train --cache` at night, eval with `session_attempt(reflex_session)`,
then a nightly `improve()`.
