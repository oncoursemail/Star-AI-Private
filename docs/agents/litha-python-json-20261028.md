# Litha engine: Python and JSON verification

This change adds a capability to the real `server/mesh/verify` engine. It does not modify the launcher or ship a dormant source patch. It starts from `star/next` at `36bcf15d`, with `main` freshly inspected at `d9b0876d`.

## Runtime behavior

- Python, `py` and `python3` fenced or explicitly labelled source now receive compiler diagnostics with source line/column positions. Before this change Python blocks were unsupported and could return `ok=True, checked=False` even for broken syntax. The host Python interpreter compiles in memory; the generated code is never executed, imported or written as bytecode.
- Ordinary JSON blocks now receive syntax checks. NaN and Infinity literals fail; duplicate decoded object keys produce warnings because a later value can overwrite an earlier one. Both errors and warnings feed Litha's existing repair loop, followed by rechecking.
- Reports expose `syntax_checked` for completed Python/JSON parsing, including syntax failures. Hard refusals set it false. The legacy JSON `checked` field retains domain/schema coverage, so ordinary JSON can have `checked=False, syntax_checked=True`; this does not claim Minecraft tag/config schema validation. The repair loop accepts either completed-check field. Existing aggregate coverage denominators retain their legacy meaning.
- The existing mesh answer-cache verifier now rejects these errors/warnings rather than treating unsupported Python/general JSON as clean. A retained check exercises `Router.verify_ok` with actual verifier reports and injected transport.
- Minecraft `pack.mcmeta` validation remains after JSON syntax checking. Root member names are identified during the same parse regardless of key order. A filename label belongs to its own code fence: `tick.json` beside `pack.mcmeta` is checked as ordinary JSON. The same local context is retained while comparing proposed repairs.
- Hard source/complexity limits return an error with `checked=False`. The repair loop does not spend a model call attempting to fix an input the checker could not examine.

The existing `POST /mesh/verify` and `POST /mesh/verify?fix=1` paths use these checkers automatically. For example, `{"code":"def broken(:\n    pass","language":"python"}` returns `ok=False`, `checked=True` and a syntax diagnostic. The fix route passes the diagnostic to the already configured model and checks the returned code again. No new tools, credentials, arbitrary execution, file writes or model endpoint are granted.

## Scope and limits

Each block is limited to 64 KiB of UTF-8 source; JSON nesting is limited to 128 levels. Diagnostics are capped at 240 characters and duplicate warnings at 16 distinct keys. Syntax-error `name` remains `None`, so the inherited placeholder policy cannot demote an error for identifiers such as `X_POS`. Syntax failures use the existing `kind="syntax"` vocabulary; report consumers count them without changing evaluation code.

Python success means the host interpreter accepts its grammar and compiler context. It does not prove imports, names, types, dependencies, runtime behavior or safety. SyntaxWarning behavior follows host policy; this checker does not mutate global warning filters. Interpreter-specific limits are reported as unchecked failures rather than universal syntax judgements.

JSON checking validates its grammar and duplicate-key ambiguity, not application schemas, number representability or Unicode interoperability. Numeric lexemes are not converted to host floats/integers, so valid JSON such as `1e9999` or a long integer is not rejected merely because of Python numeric limits. An escaped lone surrogate is admitted by JSON's grammar; raw unencodable request text is refused. Duplicate keys are warnings, not claims of invalid grammar. Minecraft's existing format check remains heuristic, based on root members and local filename labels.

Sources: [Python compile](https://docs.python.org/3.12/library/functions.html#compile), [Python JSON decoding](https://docs.python.org/3.12/library/json.html#json.JSONDecoder), [RFC 8259](https://www.rfc-editor.org/rfc/rfc8259). These define the compiler/JSON behavior, not an intelligence or benchmark score.

## Validation and integration

`python scripts/verify_litha_languages.py` passes 21 new groups, including the actual HTTP handler, injected-model repair, cache admission, aliases, source coordinates, no code execution, hard-limit refusal, explicit check coverage, canonical report kinds, duplicate members, nonfinite literals, large numeric lexemes and mixed pack/tick files. The HTTP test uses an ephemeral loopback listener and synthetic key; it contacts no model/provider. Independent reviewers also ran the existing verifier tests and extra edge probes.

The branch incorporates `star/next` at `b88377fc`, including the recall lane's tests unchanged. Run all existing `tests/test_mesh_*.py` files for wider router/cache/node compatibility. Scoped Ruff, new-module Pyright and compileall passed. Existing tests, graders, fixtures, stored results and active evaluations were not edited. This is static verification and synthetic repair evidence, not a live-model quality score.

Claude's active lanes were inspected before editing. The docs lane changes lower `core.py` repair/docs signatures; this branch preserves that ownership. The recall lane's mixed-file JSON intent is retained with stronger local-file detection. Integration must preserve those hooks; no router, instant cache, node settings or other agent worktree was changed. The existing deploy tar includes the entire verifier directory, so the new modules require no deployment-script permission change. No live restart or deployment has been performed; the runtime PR needs independent integration review.
