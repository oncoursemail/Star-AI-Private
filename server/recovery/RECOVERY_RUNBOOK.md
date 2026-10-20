# STAR backup and recovery runbook

## What this installation protects

Brain 2 pulls the configured STAR application, configuration, and data paths from Brain 1 (container `starai`). The source exporter makes a consistent SQLite snapshot and checks file stability before sending an archive. Brain 2 stores encrypted, compressed, deduplicated restic snapshots. The SSH credential on Brain 2 is restricted to the source export command; Brain 1 does not hold the destination repository passwords.

The Brain 1 scope is the 16 source roots below. Minecraft/Metallic world data is **not covered by these jobs**. A separate Main Windows upload job is enabled and its baseline has been verified; its exact scope and restore substitutions appear below. Models, engines, and other paths outside the source lists, plus explicitly excluded reproducible document bundles and disposable files, need their own reconstruction or backup plan. The exporters reject unreadable required paths, unapproved symlinks, unstable files, and inconsistent databases instead of treating a partial export as success.

| Archive source name | Required path on Brain 1 |
| --- | --- |
| `learning-app` | `/opt/star/learning/app` |
| `learning-data` | `/opt/star/learning/data` |
| `learning-outbox` | `/opt/star/learning/outbox` |
| `learning-conductor` | `/opt/star/learning/conductor` |
| `learning-env` | `/opt/star/learning/env` |
| `learning-docs` | `/opt/star/learning/docs-recent` |
| `learning-pool` | `/opt/star/learning/pool` |
| `knowledge-app` | `/opt/star/knowledge/app` |
| `knowledge-data` | `/opt/star/knowledge/data` |
| `knowledge-sources` | `/opt/star/knowledge/sources` |
| `training` | `/opt/star/training` |
| `model-config` | `/opt/star/config` |
| `search-gateway` | `/opt/star/search-gateway` |
| `runtime-secrets` | `/opt/star/secrets` |
| `recovery-source` | `/home/star/.local/share/star-recovery` |
| `recovery-config` | `/home/star/.config/star-recovery` |

The exact exclusion patterns are recorded in `starai_export.example.json`: Python bytecode caches, `.pyc`, `.log`, `.bak-*`, and 11 named raw-document symlinks under `knowledge-sources`. Those excluded bundles include the OpenStax bundles, Blender and Godot manuals, ebook, SimpleWiki, and Wikipedia topics. The archive manifest records the source paths and configured exclusions for restoration review.

The knowledge database `knowledge-data/kb.sqlite3` (with its `-wal`/`-shm` files) is excluded from the hourly job since 2026-10-20: it is about 1.9 GB, can be rebuilt from the sources plus embeddings, and while it was being rewritten each hourly copy added about 1 GB. It has its own daily workload `starai-kb` (source name `knowledge-kb`; `starai_kb_export.example.json` on Brain 1, `starai_kb_backup.example.json` on Brain 2, SSH command `export-kb` through the same restricted gate). Budgets: 12 GiB for `starai` and 8 GiB for `starai-kb`, 20 GiB together.

The baseline below has passed a full repository data read, extraction, file hashes, and SQLite integrity checks. These checks establish that the saved bytes can be recovered. They do not establish that the application boots, that a Minecraft world is clean, or that the original content was free of griefing or compromise. A DDoS can still prevent access while the network is under attack.

### Recorded first verified checkpoint

The deployment record supplied on 2026-10-19 contains:

| Item | Recorded value |
| --- | --- |
| Baseline snapshot | `bde340de2a6f82917c31d5c74edeff8e0ab6b1e12b46e9c69171e92f923817d4` |
| Original rolling snapshot | `64f42440b079d746894e6332e9f5c27a424a60262f1dc7d95933a8af8b7d0621` |
| Verified payload | 11,211 files, including 1 SQLite database; 1,072,465,406 source bytes |
| Initial storage | About 505 MB for the first rolling snapshot and 525 MB for the independently encrypted baseline; later rolling usage varies with changed data |

Use the live status command below for the latest rolling snapshot and verification time. A new successful backup does not replace the baseline.

## Installed paths

Run the following commands on Brain 2 as the Brain 2 backup user.

| Purpose | Absolute path |
| --- | --- |
| Backup runner | `~/.local/share/star-recovery/bin/recovery_backup.py` |
| Pinned restic binary | `~/.local/share/star-recovery/bin/restic` |
| Backup configuration | `~/.config/star-recovery/starai.json` |
| Operation status | `~/.local/state/star-recovery/starai-status.json` |
| Rolling repository | `~/.local/share/star-recovery/repositories/starai` |
| Protected baseline repository | `~/.local/share/star-recovery/repositories/starai-baseline` |
| Rolling password file | `~/.config/star-recovery/starai-password` |
| Baseline password file | `~/.config/star-recovery/starai-baseline-password` |
| kb workload: configuration, status | `~/.config/star-recovery/starai-kb.json`, `~/.local/state/star-recovery/kb/status.json` (its own folder: every operation clears abandoned `restore-check-*` staging in its state folder, so two workloads must not share one) |
| kb workload: repositories | `~/.local/share/star-recovery/repositories/starai-kb`, `starai-kb-baseline` |
| kb workload: password files | `~/.config/star-recovery/starai-kb-password`, `starai-kb-baseline-password` |
| Temporary export staging, on Brain 1 | `/data/star-re/knowledge/.star-recovery-staging` |

Keep the two password files private. Arrange an owner-controlled, offline copy of **both passwords and the corresponding encrypted repositories**. The passwords are different, and losing a repository's password makes that repository unusable. A password copy alone cannot recover a failed disk. Do not put these passwords on Brain 1 or publish them in logs or support messages.

The baseline is in a separate repository and the automatic job never prunes or replaces it. This protects it from rolling retention and from deletion using the source's restricted SSH access. The Brain 2 account can still delete it, and both repositories currently depend on Brain 2's storage. The baseline is not an offline or storage-enforced immutable copy and cannot be described as 100% grief-proof.

## Schedule, retention, and health

The configured user timers are:

| Timer | Schedule, UTC | Work |
| --- | --- | --- |
| `star-recovery-backup.timer` | Every hour at minute 10, with a boot trigger after about 3 minutes | Pull a fresh encrypted snapshot |
| `star-recovery-verify.timer` | Daily at 07:35 | Verify the latest rolling restore, then the fixed original baseline, in disposable private staging |
| `star-recovery-retention.timer` | Daily at 00:40 | Apply rolling retention and compact unused data |
| `star-recovery-kb.timer` | Daily at 04:00 America/Chicago | Back up `kb.sqlite3`, verify the latest restore, verify (first run: create) its baseline, apply the same retention |

All three timers were enabled during deployment, and a service-triggered backup completed at 19:52:01 UTC on 2026-10-19. That incremental backup added 1,895,144 packed bytes; future growth depends on changed data. Check the current timer state and next run:

```bash
systemctl --user list-timers --all 'star-recovery-*'
/usr/bin/python3 ~/.local/share/star-recovery/bin/recovery_backup.py \
  --config ~/.config/star-recovery/starai.json status
journalctl --user -u star-recovery-backup.service -n 40 --no-pager
```

Rolling retention keeps all snapshots within the latest **2 days**, plus **7 daily, 4 weekly, and 2 monthly** selections. These groups overlap; they do not promise a distinct snapshot for every period when a backup failed or the machine was offline. Hourly scheduling targets approximately an hour of data loss during healthy operation. The actual recovery point is the latest successful snapshot shown in status.

Retention requires a verified baseline with the expected identity and a successful latest backup less than three hours old. A failed latest attempt or stale success suspends retention. Export size, disk reserve, and repository budget limits also cause a safe failure while preserving existing recovery points; investigate the reported limit before changing it.

`latest_complete: true`, `in_progress: false`, and a recent `last_success_utc` identify a completed latest backup. `last_restore_verification` records the separate extraction test; its snapshot may precede the latest hourly backup. `baseline_verification` records the protected checkpoint test. `application_boot_tested` and `clean_world_validated` remain false unless those additional checks are performed separately. A message that another recovery operation is running means the operation lock is occupied; check the service journal and retry after that operation finishes.

To request an immediate scheduled-style backup, run:

```bash
systemctl --user start star-recovery-backup.service
```

The runner's available actions are `init`, `backup`, `verify`, `baseline`, `retention`, and `status`. `verify` tests the latest recorded rolling snapshot. `baseline` checks the existing baseline; it refuses a missing or changed previously recorded baseline rather than silently replacing it. No action automatically restores over production.

## After an outage or suspected incident

1. Confirm that both machines have power, their operating systems have booted, and the connection is available. Service supervision runs only once the machine itself is running; firmware power recovery, boot failures, damaged disks, and network filtering need separate attention.
2. Check the user timers, status, and service journal above. Restore network access and required source paths, then request one backup if a scheduled attempt failed. A dropped connection is handled as a failed attempt; it must not advance the last successful recovery point.
3. Following an interrupted process, the next locked operation clears only its own abandoned staging directories. Source staging and verification staging may contain sensitive plaintext until this cleanup completes. Ordinary successful verification removes its temporary archive and extracted files.
4. For confirmed corruption, missing data, or griefing, select a snapshot from before the incident and recover it into a new review folder using the procedure below. Preserve the protected baseline and current repository during the investigation. Automatic service restart and data rollback are separate operations.

## Recover the baseline into a new review folder

This uses the installed restic `dump` operation through the runner's command wrapper and its actual archive validator. It acquires the normal operation lock, checks the baseline repository, downloads the fixed snapshot, verifies every restored file, and checks SQLite integrity. It creates a new private folder under the Brain 2 backup user's home folder and never writes to production paths.

Ensure Brain 2 has room for both an archive and its extracted files. For the recorded baseline, allow at least 3 GB of working space in addition to normal operating reserves. Restoring a later, larger snapshot needs more space. Run this on Brain 2 as the Brain 2 backup user:

```bash
/usr/bin/python3 - <<'PY'
import fcntl
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile

os.umask(0o077)
sys.path.insert(0, str(Path.home() / ".local/share/star-recovery/bin"))
from recovery_backup import Backup, validate_archive

cfg = json.loads((Path.home() / ".config/star-recovery/starai.json").read_text())  # star-main.json for the PC
worker = Backup(cfg)
snapshot = "bde340de2a6f82917c31d5c74edeff8e0ab6b1e12b46e9c69171e92f923817d4"
use_baseline = True

with worker.state_path.with_suffix(".lock").open("a") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    worker.call("unlock", baseline=use_baseline)
    worker.call("check", "--read-data", baseline=use_baseline)
    review = Path(tempfile.mkdtemp(prefix="star-recovery-review-", dir=Path.home()))
    archive = review / "recovery.tar"
    print("Private recovery folder:", review, flush=True)
    try:
        with archive.open("xb") as output:
            worker.call("dump", snapshot, "recovery.tar", baseline=use_baseline, output=output)
        result = validate_archive(archive, review / "files", cfg["max_export_bytes"], cfg["expected_sources"])
        with tarfile.open(archive, "r:") as saved:
            manifest = saved.extractfile("RECOVERY_MANIFEST.json").read()
        (review / "RECOVERY_MANIFEST.json").write_bytes(manifest)
        print(json.dumps(result, indent=2))
        print("Verified files:", review / "files")
    finally:
        archive.unlink(missing_ok=True)
PY
```

A nonzero exit means the restore is not verified. The review folder may contain incomplete files for investigation; it has not changed production. The temporary tar is removed on normal completion or an ordinary exception. A hard kill or power failure can leave this manually created review folder behind; it is deliberately outside the automatic verification-cleanup namespace.

The verified files are placed under their source names. The saved manifest records original paths, modes, sizes, and hashes. The validator deliberately writes private file permissions (`0600`, directories `0700`), so this is a review copy, not a bootable installation. Review the source mapping and content, restore the necessary ownership and executable modes, and test the application in isolation before deciding which production files to replace. Keep the working installation and current data intact during that review.

### Choose a rolling recovery point instead

List available rolling snapshots using the installed CLI:

```bash
~/.local/share/star-recovery/bin/restic \
  --repo ~/.local/share/star-recovery/repositories/starai \
  --password-file ~/.config/star-recovery/starai-password snapshots
```

Select the full snapshot ID from before the incident. In the Python recovery block, set `snapshot` to that ID and `use_baseline = False`. Run the block again to create another new review folder. Do not mix the baseline repository with the rolling password file.

## Main Windows backup and restoration

Main's task **STAR compact recovery backup** runs hourly and when `<COMPUTER>\<WIN_USER>` signs in, with three failure retries 15 minutes apart. It was registered and its exact action, limited interactive principal, triggers, overlap exclusion, timeout, and battery behavior were verified. A manual run of the same backup action succeeded before scheduling. The first scheduled run is one hour after registration; future scheduled execution is not claimed as already tested. Main must be powered on and its owner signed in for this task.

| Archive root | Windows source |
| --- | --- |
| `star-state` | `%USERPROFILE%\.star` |
| `star-roaming` | `%APPDATA%\Star` |

Top-level downloaded engines/models/downloads/updates/caches and disposable logs, lock files, and `.bak` copies are excluded. User-generated assets, settings, skills, runs, selected `.star` state, and databases are included. The initial restore verified **479 files, 7 SQLite databases, and 20,643,824 bytes**. This is STAR desktop state, not all files on the Windows PC or any Minecraft world.

| Purpose | Path on Brain 2 |
| --- | --- |
| Main configuration | `~/.config/star-recovery/star-main.json` |
| Main status and isolated temporary staging parent | `~/.local/state/star-recovery/main/status.json` |
| Rolling repository | `~/.local/share/star-recovery/repositories/star-main` |
| Fixed baseline repository | `~/.local/share/star-recovery/repositories/star-main-baseline` |
| Rolling password file | `~/.config/star-recovery/star-main-password` |
| Baseline password file | `~/.config/star-recovery/star-main-baseline-password` |

Main holds only a restricted upload SSH key. The receiver accepts a complete bounded archive, validates all paths/hashes/databases and the expected two source names, then commits an encrypted snapshot. It provides a successful receipt only for an actual new snapshot. Upload failures cannot replace the last successful receipt. Source-side and receiver-side operation locks and exact orphan-cleanup namespaces prevent concurrent backup attempts or interrupted plaintext stages from accumulating unchecked.

The initial rolling snapshot is `4384b2c9e01eacc78a002fc017ac628de3a21c3334af5ca3365b55aac6bfb3fb`; the fixed baseline is `caf972b65d9272c887e8288370eb70fd48ef6fbe97003cc4ec4b70a453b0e982`, verified at 22:06:59 UTC on 19 October 2026. Brain 2's `star-main-recovery-verify.timer` checks its latest restore and original baseline daily at 07:45 UTC; `star-main-recovery-retention.timer` runs the same guarded retention policy at 00:50 UTC. Both are enabled.

To restore Main's baseline, use the earlier Python restore block on Brain 2, substituting the Main configuration path and its baseline snapshot ID. The restored private `star-state` and `star-roaming` folders can then be reviewed and mapped to the two Windows source directories. Close the owning STAR application before any separately approved production replacement, preserve the current state, and restore the appropriate owner permissions. The automatic routine does not overwrite Windows data.

Main's local receipt is `%LOCALAPPDATA%\StarRecovery\status.json`. To request a new backup after any current operation and the ten-minute receiver rate window have finished:

```powershell
& C:\Python315\python.exe "$env:LOCALAPPDATA\StarRecovery\windows_recovery_push.py" --config "$env:LOCALAPPDATA\StarRecovery\push.json"
```

All four repository passwords and the four encrypted repositories are needed for a complete independent copy. None of the passwords or production payloads are contained in this kit.

## Implementation and reference sources

Operational behavior and paths above come from the installed deployment record and this kit's `recovery_backup.py`, `recovery_export.py`, and `bounded_export.py`. The scripts' tests cover WAL consistency, path/symlink rejection, required-source failure, archive checksums, bounded streams, interrupted producers, and the protection gates around retention. They do not simulate a physical power loss or establish that every application boots from a restore.

- [restic: backup, compression, and producer exit status](https://restic.readthedocs.io/en/stable/040_backup.html)
- [restic: retention and pruning](https://restic.readthedocs.io/en/stable/060_forget.html)
- [restic: repository checking](https://restic.readthedocs.io/en/stable/045_working_with_repos.html)
- [restic: repository password requirements](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html)
- [SQLite: online backup API](https://sqlite.org/backup.html)
