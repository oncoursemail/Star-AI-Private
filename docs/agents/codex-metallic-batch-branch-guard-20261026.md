# Preserve generator context in batch checks

The optimistic merge-queue batch used `metallic-queue` as its check branch. `check_protected` recognizes generators through configured branch patterns, so that synthetic label could turn a protected-path failure into a pass. A pure fake context reproduced the difference for the same `evals/fake.json` change: `star/gen-example` failed; `metallic-queue` passed.

The proposed queue-only fix passes the original batch source names to `_check`. After loading the **combined tree's configuration**, `_check` selects a matching generator source as its check context. Non-generator batches keep the existing label. A mixed batch can fail conservatively when a non-generator contributed a protected change; the existing per-branch fallback then checks each actual branch's delta and can accept the legitimate changes.

No protection patterns, thresholds, fixtures, evaluation files, `checks.py` or engine behaviour are changed by this fix. The existing full-tree checks, fail-fast setting, cache scope, branch fallback and compare-and-swap apply path are preserved. This corrects lost branch context; it does not establish trustworthy authorship from a branch name or solve independent configuration-trust concerns.

Read-only overlap review found no active original-worktree edits to `queue.py`/`checks.py`. Of 13 open GitHub PRs inspected, only the broad `star/next` to `main` integration PR #514 included these modules; no competing feature PR was found. This is a snapshot, not merge authorization.

The new standalone verifier replaces every Git, lock, filesystem mutation and check-execution primitive before exercising production queue control flow. It runs real `check_protected` only against fake contexts and proves generator ordering, conservative mixed-batch rejection and individual fallback, new combined-tree patterns, ordinary batches, single branches and unchanged check options. It never creates a worktree, invokes Git, applies a merge, changes a protected fixture or starts a model/server.

```text
python scripts/verify_metallic_batch_branch_guard.py
```

Validation completed on the isolated candidate:

- **9 standalone fake-context/control-flow tests passed**, including conservative mixed-batch failure followed by correct individual acceptance/rejection.
- Targeted Ruff, compilation, Pyright 1.1.414 (**0 errors, 0 warnings**) and `git diff --check` passed. The verifier imports the repository package explicitly, without modifying type-checker configuration.
- Existing `metallic/tests/test_metallic_queue.py` was read but not executed: those fixtures create temporary Git worktrees and include `apply=True`; this review stayed within the requested fake-only execution scope. No claim is made that those integration tests passed for this candidate.

An independent reviewer inspected the queue source and verifier, reran all **9** cases plus Ruff/diff checks, and approved this scoped change. The reviewer also reported two existing built-in check tests passing; that review did not execute queue integration tests. Branch-name trust, configuration authority and verdict authenticity remain outside this patch. The integrator controls its commit and integration.

After independent review, root ran the unchanged existing `metallic/tests/test_metallic_queue.py` suite: **7 passed in 129.88 seconds**. These integration tests create and merge only disposable fixture repositories, exercising the existing batch, conflict handling, fallback and moved-target refusal. They do not operate the owner's queue, branch targets or source installation. No harness source was edited and no production queue was activated.
