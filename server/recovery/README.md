# STAR automatic recovery and compact backups

Deployment date: 19 October 2026. This kit contains the code, tests, configuration examples, restore instructions, and administrator handoffs used for the live work. It contains no production data or private credentials.

## Working now

| Machine / workload | Deployed behavior | Verification |
| --- | --- | --- |
| Brain 1, `starai` | Persistent remote-agent runtime; exact detection of the actual `remote` process; retry loop; existing reboot/minute cron supervision; bounded logs | Its connector was restarted and reconnected with the new persistent runtime |
| Brain 2, `alexbuz1` | Corrected remote-agent supervisor; its remote and egress user services retry without a permanent start-rate limit, with 15-second service retry delay; existing user linger retained | Its connector was restarted and reconnected; effective unit settings checked |
| STAR data on Brain 1 | Brain 2 pulls an hourly encrypted, compressed, deduplicated backup using an export-only SSH key | Multiple live hourly backups succeeded; first restore verified 11,211 files and 1 SQLite database |
| STAR data on Main | Hourly and owner-sign-in Windows task submits a compact archive to a fixed SSH receiver on Brain 2; three failure retries 15 minutes apart | First off-host backup succeeded; restore verified 479 files and 7 SQLite databases; scheduled-task definition verified |
| Baselines | Each workload has a separate encrypted baseline repository and password; rolling cleanup cannot rotate it; recorded baseline identity cannot be silently replaced | Both baselines passed full repository reads, per-file hashes, and SQLite integrity checks |
| Ongoing checks | Brain 2 verifies the latest rolling restore and the original baseline daily, and runs guarded retention daily | Five Linux timers are enabled; Linux retention was also run successfully |

The connector tests exercised process restart and reconnection. They were not physical power-loss or network-saturation tests. Main's existing Desktop Commander supervisor was inspected and preserved; it requires the owner to sign in after Windows boots.

## Storage and history

Measurements after deployment, in decimal bytes:

| Repository | Stored bytes | Approximate size |
| --- | ---: | ---: |
| STAR rolling history | 512,923,619 | 513 MB |
| STAR separate baseline | 525,019,352 | 525 MB |
| Main rolling history | 8,968,886 | 9.0 MB |
| Main separate baseline | 9,406,199 | 9.4 MB |
| **Total** | **1,056,318,056** | **1.06 GB** |

The first STAR archive was approximately 1.09 GB before storage compression. Observed subsequent backups added approximately 1.8–2.2 MB each. Actual growth depends on changed data. Main's selected payload was 20,643,824 bytes; its initial packed backup added 8,966,479 bytes.

Rolling history keeps every available snapshot from the latest **two days**, plus **seven daily, four weekly, and two monthly** selections. Those groups overlap. Baselines are outside this rotation. The hourly schedule targets about one hour of recoverable data loss while the relevant machines and connections are available; the last successful snapshot is the actual recovery point.

Models, downloadable engines, package caches, disposable logs, and explicitly identified reproducible reference bundles are excluded. Required selected files cannot disappear or fail to read silently. Transfers, temporary staging, disk reserves, and repository size budgets are checked. The repository budget is a preflight guard, not an exact filesystem quota; growth can cross the budget within one bounded backup before another backup is refused. Existing snapshots and baselines are retained when a guard fails.

## Protection boundary

Brain 1 has no credential to delete its backup repository. Main's dedicated key is restricted by source IP and a fixed receiving command; it cannot open a shell or read, overwrite, or delete the baseline through that key. Both restrictions were tested by accepting `health` and rejecting `id` with exit 126. The receiver checks the complete archive before it can become a snapshot, bounds upload size/runtime, and limits repeated upload attempts.

A successfully restored baseline proves readable saved bytes and valid SQLite databases. It does not prove the content was already free of griefing, nor that the application boots from that data. The Brain 2 account and administrators still control its disk. A compromise of that account, disk failure, or loss of the site can affect both repositories. An independently administered storage-locked or disconnected copy remains necessary for stronger protection. Preserve the encrypted repositories and their separate passwords together through an owner-controlled process.

Network outages never trigger automatic replacement of production data. DDoS mitigation must act before an attack overwhelms the available upstream connection; these backups support recovery from data loss and do not prevent network saturation.

## Remaining administrator work

| Area | Exact current limit | Prepared next step |
| --- | --- | --- |
| Brain 1 system services | `star` cannot use passwordless sudo | Review/apply the hostname-pinned four-service installer from an existing root session |
| Brain 2 Docker/containerd/Wings | Remote account has `no-new-privileges`; protected units/binaries and container volumes are unreadable | Administrator reviews/applies the three-service installer and identifies actual workloads/volumes |
| Minecraft / Metallic | `mc-ubuntu` at `10.17.0.106:22` timed out; no production world or game-database backup was possible | Restore access, identify exact services/worlds/databases, coordinate consistent snapshots, then test an isolated world restore |
| Main unattended startup | Tasks use the existing limited interactive user | Administrator/owner must establish a supported pre-sign-in service/task if required; do not substitute SYSTEM or copy credentials blindly |
| Physical power restoration | BIOS, hypervisor autostart, UPS shutdown, and cold boot were not inspected | Verify AC restoration and guest autostart from the host/firmware console |
| Independent last copy / DDoS | No offline/WORM destination or upstream filtering service was configured | Choose an owner-controlled destination and the actual game/HTTP network protection path |

The system installer is conservative: dry-run by default, explicit host and service allowlist, existing enabled/running services only, syntax checks before writes, backup and rollback of its own drop-ins. It preserves existing service identities and longer retry delays, including night school's 120 seconds. It does not restart workloads as part of applying the policy.

## Files to use

- `RECOVERY_RUNBOOK.md`: exact installed paths, current health commands, snapshot selection, and restoration into a new private review folder.
- `WINDOWS_RECOVERY.md`: Main's schedule, sign-in limitations, and state paths.
- `LINUX_RECOVERY_ADMIN.md`: review/apply behavior and precise limits for administrator changes.
- `MC_METALLIC_RECOVERY.md`: actual game-server coverage gaps and the consistency/restore acceptance steps.
- `DEPLOYMENT_STATUS.json`: recorded successes, verified snapshot IDs, measured storage, and explicit untested conditions.
- `*.example.json`: configuration structure and installed path examples; these are not repository passwords or private SSH keys.

## Validation

The local suite passed **111 tests**. On the actual Main Windows machine, **28 tests ran: 26 passed and 2 POSIX-symlink fixtures were skipped**; portable Windows reparse-point tests passed. Windows-specific fixes handle active SQLite sidecars, file metadata differences, private temporary directories, single-flight locking, and durable pending status after interruption.

The live work also checked both Linux connector reconnections, the scheduled Linux backup context, real incremental storage reuse, both source-key restrictions, full baseline restores for both workloads, retention preserving the baseline identity, enabled Linux timers, and the Windows task's exact action/principal/triggers/retries. The Windows backup action was run successfully manually before scheduling; its future hourly invocation is not reported as already executed.

Run the portable suite from this directory or its parent:

```bash
python -m unittest discover -s . -p 'test_*.py' -q
```

On Windows, run only `test_windows_recovery_*.py`; Linux-only modules use `/proc`, file descriptors, and `fcntl`.

## Technical references

- [SQLite online backup](https://sqlite.org/backup.html)
- [restic backup and producer exit status](https://restic.readthedocs.io/en/stable/040_backup.html)
- [restic retention](https://restic.readthedocs.io/en/stable/060_forget.html)
- [restic repository checks and copy](https://restic.readthedocs.io/en/stable/045_working_with_repos.html)
- [systemd service restart policies](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html)
- [systemd timer persistence](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html)
- [Windows task logon types](https://learn.microsoft.com/en-us/windows/win32/taskschd/principal-logontype)
- [Why upstream capacity matters for DDoS mitigation](https://www.cloudflare.com/learning/ddos/ddos-mitigation/)
