# innovation-gate-20261021 (PR #488 reworked)

Branch `star/innovation-gate-20261021` from origin/star/next 9908e36c. Replaces PR #488
(feat/innovation-gate-research-20261018).

## Changed
- `star/innovation_gate.py` rewritten as a thin layer: producer = result files from `python -m star.evals run`
  (eval_runner, which records per-task `seconds`); quality = `eval_gate.compare_paired` unchanged; time = per-task
  median seconds compared with `eval_stats.sign_test`. Own JSON format, own sign test, 40-case minimum and the
  peak-memory check (no producer records memory) dropped. Protected eval files untouched (imported only).
- Consumer: `python -m star.evals innovation --objective quality|speed --baseline ... --candidate ...`
  (star/evals.py dispatch), text or `--json`, exit 0/1/2/4.
- Research: the two docs kept in docs/research; section 5 and status lines rewritten to the wired form; server user
  names replaced by "server 1/2".

## Ran
- pytest (APPDATA=temp): tests/test_innovation_gate.py + test_eval_stats, test_eval_gate, test_eval_gate_model_change,
  test_protected_closure: 87 passed.
- ruff on changed py files: clean. pyright 1.1.414 on star/innovation_gate.py, star/evals.py: 0 errors.

## Not verified
- On real eval-runner files from a live paired session (only fixture-built result dicts).
