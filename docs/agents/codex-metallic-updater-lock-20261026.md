# Updater staging ownership

Based on PR #687 at `3c2a09ff227704be2e182f4cf409be681ab8724b`. The constructor deleted the shared staging directory before acquiring the updater lock. A second client opened for status could therefore delete an active updater's partially built files.

The constructor now attempts the existing exclusive lock before cleaning abandoned staging. If another owner holds the lock, construction skips cleanup and status remains readable. Successful exclusive construction retains the earlier abandoned-staging cleanup behavior. Only the dedicated `UpdateBusy` error is suppressed; other cleanup and filesystem failures remain visible, and the acquired lock is released on failure.

Existing locks are refused regardless of their age. A timestamp alone cannot prove a long download or installation has stopped. After a crash, the owner must first close all updater/launcher processes and independently establish that no updater still owns the installation before recovering its abandoned `.lock`. This patch does not automatically remove such a lock or grant another agent recovery authority.

Run `python scripts/verify_metallic_updater_lock.py`. The standalone verifier uses temporary directories, synthetic state/staging and an empty trust store. It covers fresh and old locks, a second instance while the first holds its lock, status availability, orphan cleanup and backup-read compatibility, exclusive cleanup, cleanup/body failure release, acquisition failures and the existing `UpdateError` catch contract. No existing tests, graders, fixtures or baselines were changed. No signing, key generation, network reads, downloads, update application, rollback, bootstrap or installation is exercised.

Local results: all **8 standalone tests** and **14 existing pure path/version tests** passed. Scoped Ruff, the diff check and pinned Pyright 1.1.414 with a package-free Python interpreter passed (zero type errors or warnings). The original signing/update/rollback tests were not executed for this scoped candidate.

This is a staging-ownership correction, not release approval. Packaging, shipped trust configuration, authenticated manifests and native installed-launcher behavior require their separate checks. Independent review and integrator-controlled commits remain required.
