# Independent review: computer driver recovery and verification waits

Research/review date: October 31, 2026, America/Chicago.

## Scope and conclusion

Reviewed `star/computer/driver.py` and `star/computer/settings.py` against the source baseline `a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f`. The baseline was retrieved through GitHub and compared with the modified local snapshot. Supporting reads included the input methods, action-log redaction path and existing driver tests. This review did not edit application source or existing tests.

**No remaining blocker was identified for the stated, bounded change after the three findings below were resolved.** The optional polling setting defaults to zero. Normal finite configurations retain fixed-wait scheduling when polling is disabled; STOP handling and recovery/error outcomes intentionally improve. This is not evidence of native Windows correctness or a measured hardware speedup.

## Findings identified and resolved

| Finding | Reproduction and consequence | Resolution rechecked |
|---|---|---|
| Opaque backend exception text entered the new uncertainty receipt | A post-dispatch `OSError` containing a private sentinel was retained verbatim in `StepResult.detail`. Arbitrary response bodies cannot be reliably removed by recognizable-secret redaction alone. | Post-dispatch receipt text now includes the error class and a controlled description. The same sentinel no longer appears, while `OSError` and `outcome_uncertain=True` remain. |
| Nonfinite wait configuration could keep the new sleep loop alive indefinitely | `settle_s=float('inf')` was accepted; with a progressing fake clock, the wait continued until STOP. | Construction rejects nonfinite or negative settle values. Driver waits and deadlines are validated, and the loop rejects a nonfinite current clock. Focused malformed-value checks passed. |
| STOP raised during final attempt logging could still allow recovery focus | A log callback set STOP after a failed attempt. Before the fix, a recovery `windows.focus()` call occurred before the next loop's stop check. This was an existing boundary weakness exposed during the review. | A stop check now follows the final record before success return or recovery. Reproduction now raises `Stopped` with zero recovery focus calls. |

## Independent focused checks

These checks exercised actual driver methods with in-memory observations, fake clocks and fake backends. They were run as isolated Python snippets, not native desktop tasks or a replacement for the repository's full test suite.

- Default polling disabled: one post-action observation after a 0.5-second modeled wait.
- Positive condition appearing at modeled time 0.1 seconds: with a 0.05-second polling interval, accepted after three observations at 0, 0.05 and 0.1 seconds.
- Already-satisfied positive predicates, negative predicates, and mixed positive/negative predicates: fixed wait retained, with one observation in the example.
- Observation cap: a one-second phase with a 0.01-second interval and an unmet predicate made 32 observations, reserving the final observation for the deadline.
- Observation cost: adding a modeled 0.03-second snapshot cost consumed the same phase budget; the final native-call-sized overrun was represented, rather than pretending calls could be preempted.
- STOP during the initial observation prevented dispatch. STOP during post-action observation or verification prevented a success result.
- STOP during final logging prevented a subsequent recovery focus call after the fix.
- Constructor checks rejected six malformed settle values and seven malformed polling intervals; valid interval values 0, 0.01 and 1 remained accepted. Three malformed wait values were rejected.
- A post-dispatch exception produced an uncertainty receipt without including an opaque private payload after the fix.

## Code-path assessment

The dispatch marker is set before entering `_perform`, so a backend that raises after partially applying an operation is not sent into the normal catch-and-retry path. Pre-dispatch gate behavior remains distinct. Changed click/key actions stop before trying an alternative target, and unverified typing ends after one dispatched attempt. `Stopped` continues to propagate as cancellation.

Polling is limited to new positive explicit predicates. Already-satisfied conditions and absence predicates keep their existing wait behavior. The default remains zero; this is opt-in polling, not an event subscription or a promise of immediate completion. Each phase is capped at 32 fresh observations; the existing extended-verification phase can add a second phase. The deadline limits scheduled waits and includes observed elapsed time, but cannot interrupt a blocking native snapshot call.

No additional screenshot or action-log write occurs for each individual poll; attempt records retain the existing before/after model. The new boolean receipt field itself carries no private payload. Existing user content, screenshots, target descriptions and action logs retain their preexisting privacy properties; this review does not claim a complete logging privacy audit.

## Practical limits

No Windows UI Automation, SendInput, real foreground-focus transition, Studio, Blender or packaged EXE task ran. This change does not establish exactly-once execution or general idempotence: retries after a visually unchanged click remain possible, and invisible application effects require stronger task-specific postconditions. It also does not cancel an in-flight blocking backend call. Native acceptance and broader task-level performance evaluation remain necessary before any live speed or completion-rate claim.

## Reviewed file fingerprints

- `driver.py` SHA-256: `bef8bb5ed771ad9872bc4d0c811b40ff944225e9d545809ec7faa47f66ad0db8`
- `settings.py` SHA-256: `2c4d43ea29a327b26545f80e8570f9832a39ede647dd40e2ec9109c66f9dbb1b`
