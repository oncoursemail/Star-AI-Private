# anime-dub-research (PR #495 finish), 2026-10-21

Branch `star/anime-dub-research-20261021` from origin/star/next.

## Changed
- The four docs moved to `docs/research/STAR_ANIME_*.md` (content unchanged except the "Reviewable Star package" section, which said no reader exists). Examples stay in `examples/anime_production/`.
- New consumer `star/anime_production.py`: structural validator for `pilot.json` (contiguous half-open shots ending at `total_frames`, known characters/listeners, cue windows inside their cut, no character over themselves, SHA-256 format, unproduced plans carry no take/hash/media), `pilot_cues.csv` (exact columns; row-by-row agreement with `pilot.json` via `--plan`) and `benchmark_template.json` (take/route caps 1-3, unique screen tests, measurement groups, a `not_run` record has no runs or summary).
- Wiring: `star anime-check <file> [--plan pilot.json]` in `star/cli.py` (exit 1 on problems), and `python -m star.anime_production`. No agent tool: a validator for three example files does not justify a Settings flag plus a gateway; the CLI is the natural place.
- It reads only the local files named; no network, no downloads. Rights notes in the docs stay documentation; the validator has no content or rights logic.
- Tests: `tests/test_anime_production.py` (shipped examples valid; 12 plan mutations, CSV drift, 6 benchmark mutations, exit codes, CLI registration and output).

## Ran
- pytest: test_anime_production + test_cli passed; ruff clean on the new/changed py files.

## Remains
Provider adapters, directed voice auditions, benchmark runs: still research, as the docs say.
