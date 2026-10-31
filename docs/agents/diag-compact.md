# CLI diagnostic compaction (#411) - slice 1

Branch `star/diag-compact-20261020`, PR to `star/next`, "Refs #411".

Done: `star/diag_compact.py`, pure library (never runs a command or reads a workspace file):
- Allowlist `KINDS = pytest, vitest, ruff, tsc, cargo, luau`; anything else is refused with `ValueError`.
- `parse(kind, text, exit_code)` -> `Diagnostics`: deterministic regex parsing (no model) into `Failure(file, line,
  message, code, excerpt)`; pytest keeps the `E  assert` lines and `file:line` of the FAILURES section, vitest the
  `❯ file:line:col`, ruff/tsc/luau the per-line records, cargo the `--> file:line`. ANSI is stripped (flag kept).
  `ok` only with exit 0 and nothing parsed; non-zero exit with nothing parsed = `unparsed` (never ok).
- `compact(kind, text, exit_code, enabled=False, max_chars=12000)`: off by default (text returned unchanged); on,
  output under 6,000 chars stays whole; otherwise a preview with every parsed failure line + excerpt (identical lines
  once, `failures_total` keeps the count), the summary line, exit code, SHA-256 and length of the original, an
  "untrusted output" marker; an unparsed failure gets the exact head and tail; a cut is marked `[CUT: n more chars]`.
- Tests: `tests/test_diag_compact.py` (8: six tools, ANSI/Unicode/300 KB single line/prompt-injection text as data,
  default off, every failure kept, near-limit cut marked).

Left of #411: wire `compact` behind a setting into the agent's test/lint tool outputs (uses
`star/tool_evidence.py`'s read-back for the original), 100-scenario fixture corpus (this slice has ~12), optional
pinned `rtk-oss`/ripgrep/ast-grep adapters, the A/B measurement (fidelity, recall, tokens, CPU, p95) and the
30-repair acceptance run. Default stays off until that acceptance.
