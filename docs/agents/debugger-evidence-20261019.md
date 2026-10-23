# Debugger evidence upgrade — review notes

Owner: codex. Board item: 182. Branch: `star/chatgpt-debugger-evidence-20261019`.

## Request and scope

Improve STAR's debugging tools and research useful AI-assisted debugging approaches. Work starts at private-repository main `bd575de0aba344b145fe7119d23670ec9c954967` in the isolated `wt-chatgpt-debugger-evidence-20261019` worktree. Public distribution, main, running app settings, Brain services, and evaluation fixtures are outside this change.

Implemented four read-only model tools for reports, comparison, source windows, and diagnostic plans; a default-OFF Settings switch; opt-in pytest evidence; bounded trusted-program debugpy capture; and a developer Playwright reporter/runner. Optional debugger dependencies are in `requirements-debug.txt`. The research note is `docs/DEBUGGER_RESEARCH_20261019.md`.

## Evidence and review

- Original test identities survive redaction through opaque SHA-256 values. Missing legacy identities stay inconclusive.
- Test source and recorded harness hashes are compared. Retries, skips, removed IDs, incomplete runs, and changed evidence cannot silently count as a completed repair.
- Reports are untrusted data, bounded and redacted. `verified_fix` is always false. These tools do not certify a patch, enable a feature, execute code for the model, or bypass the independent evaluation gate.
- Independent review covered malformed JSON, field/key collisions, output limits, nested secret redaction, identity collisions, and process cleanup. Focused regressions cover the findings.
- Windows targeted Python/app regressions: 241 passed, one symlink test skipped. Real debugpy captures and cleanup ran successfully with a temporary Python 3.12 environment.
- Linux combined debugger/application regressions: 293 passed. Windows browser reporter/runner: 46 passed, 5 platform/symlink skips.
- Broad Windows Python run: 9,618 passed, 328 skipped, 4 failures. All four reproduced on unchanged main: three unavailable WindowsApps bash launcher cases and desktop doctor missing the separate desktop keyring dependency. The full result remains non-green.
- TypeScript checking and the production frontend build passed. Frontend unit tests: 562 passed across 63 files with process-local `NODE_OPTIONS=--no-experimental-webstorage` on Node 26.11.1. The initial host-storage incompatibility did not require source/test/configuration changes.
- Real Playwright 1.62.1 browser-free CLI runs produced actual exit 1/0, identical test source/identity, distinct run IDs, and readable comparable artifacts. No browser or live STAR acceptance run is claimed.

## Delivery requirements

Commit through the parent `star commit` guard with an explicit path list. Push only this feature branch to the private repository using its explicit URL; the shared checkout's historical origin name must not route private development to the public distribution repository. Open a draft PR against the inspected main. Do not merge, release, or enable the experiment. The final validation record is included above and in the research note.

There is overlap in `star/agent.py`, `star/desktop_core.py`, and Settings plumbing with the separate incremental-repair draft. The integration changes here are intentionally small and require ordinary conflict review if that draft lands first.
