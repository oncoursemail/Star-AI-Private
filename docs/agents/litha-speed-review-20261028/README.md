# Litha source review packet

This is a review handoff for the separate Metallic Launcher repository, not a STAR runtime change. It accompanies GitHub issue #682 and the prior artwork draft #727. No model settings, active evaluation, permissions or installed application are changed by these files.

The source is pushed on Metallic Launcher branch `codex/litha-speed-quality-20261028`, final commit `44dfb8c`. It stacks on the prior isolated candidate `79489ad0d62aba4aa6323de93531a27fb3c171f2`; the earlier credential-adjacent work still needs maintainer review. Claude's checkout and branches were preserved.

`source-review.patch` is the complete incremental diff from that launcher base to this candidate. It belongs to Metallic Launcher and must not be applied to the STAR source tree. Its SHA-256 is `56416e57d45f60ff83da4d2a375c72b987f1ef47baae4fe2600e0178ba88c00e`. It uses zero-context diff formatting, retaining all changed lines; applying it requires the exact base with index checks and `--unidiff-zero`. The author verified the patch against the current candidate with a reverse check without applying it. Review the original branch when available; this copy makes the actual source and retained checks accessible on GitHub without a Forge browser session.

## What changed

- Per-view message rows retain their identity; streaming updates the changing reply and preserves drafts and reading position.
- Compact source JSON and UTF-8 transport preserve source data while reducing request bytes.
- Normal completion avoids an extra network read. Output-limit replies retain partial text with an incomplete warning and are excluded from successful model history. Unsupported terminal reasons and invalid Unicode fail visibly.

The actual old production renderer and new renderer were compared under the same 100-frame synthetic fixture: settled formatting calls 3,030 to zero, whole-list replacements 202 to zero, assigned HTML string length 4,268,940 to 78,890 UTF-16 code units. Four retained source-context cases produced 0.79% to 39.35% fewer request bytes, independently reproduced with the actual prior builder and encoder. These are operation/byte counts, not measured model latency, native FPS or coding-accuracy gains.

The launcher suite passed 354 existing Python tests with five skipped and nine existing JS checks. New checks cover completion integrity (7 groups), lossless context transport (2 groups), and incremental rendering (129 checks, 132 with the optional old-module comparison). Existing tests and evaluation fixtures are unchanged. An isolated real-browser check exercised the byte-identical chat module with synthetic events; it verified retained rows, drafts, reading position, Stop, incomplete warnings and normal completion. It did not load a model or use credentials. Windows native installation and live-model quality/latency remain unverified.

`research.md` links primary documentation and papers, distinguishes observations from proposals, and explains broader changes left for separate evidence. `independent-review.md` records exact baseline comparisons and scoped source review. The patch also contains the launcher's own integration, rendering and first-start notes.

This PR's STAR CI checks apply to the review packet's host tree; they do not execute the dormant launcher patch. No merge or release is requested automatically.
