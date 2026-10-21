# Linux service recovery: administrator handoff

`linux_recovery_admin.py` is a conservative installer for explicit, observed system services. The script and host configurations are prepared; this handoff does not claim they have been applied on the servers.

## Review and apply

Run the review command on the matching host from the directory containing these files:

```bash
python3 linux_recovery_admin.py linux_recovery_starai.json
```

On Brain 2, copy `linux_recovery_brain2.example.json` to `linux_recovery_brain2.json`, put in the real hostname, and substitute it. The default is a read-only plan, apart from temporary syntax-validation files. Inspect the service names, proposed contents, skipped units, and any proposed linger changes. The configuration must match the host's exact hostname.

After reviewing the plan, an administrator in an existing root session may apply it:

```bash
python3 linux_recovery_admin.py linux_recovery_starai.json --apply
```

The installer does not invoke `sudo` or provide an alternate path around privilege restrictions. `--apply` refuses a non-root process before host inspection. This matters because `starai` currently requires a password for `sudo -n`, while Brain 2 blocks elevation using `no-new-privileges`.

## What the installer changes

Only explicitly configured, currently running, persistently enabled services are eligible. Failed, stopped, disabled, static, remaining-active, and one-shot units are skipped. Custom restart policies other than `no`, `on-failure`, or `always` also require individual review.

For each eligible service, it writes one owned drop-in at:

```text
/etc/systemd/system/SERVICE.service.d/90-star-recovery.conf
```

The drop-in sets `Restart=on-failure` while preserving an existing `Restart=always`; sets the restart delay to at least 15 seconds while preserving a longer existing delay; and sets `StartLimitIntervalSec=0` so a long outage cannot leave the service permanently rate-limited. Explicitly marked network clients also get `Wants=network-online.target` and `After=network-online.target`.

This produces indefinitely retried failure recovery with a controlled delay. `network-online.target` provides boot ordering; it does not continuously monitor internet connectivity. The services' existing code must reconnect or exit with a failure status when an established connection becomes unusable. This installer adds no hung-process watchdog and does not restart healthy services to exercise failure paths.

Every selected service's current unit text plus the proposed directives is checked using `systemd-analyze verify` before changes. Existing owned drop-ins are copied to a separate timestamp directory under `/var/backups/star-recovery-systemd/`, alongside the exact plan. Unowned files with the same drop-in name and symlinks in managed paths are refused. Base units, execution commands, users, groups, and permission controls are not edited.

Application performs `systemctl daemon-reload`, then checks the resulting restart policy, retry delay, start-limit interval, network dependencies, and service identity. A later override that defeats the proposed settings causes rollback. Application failure restores prior managed files and reloads the manager; any rollback failure is reported for administrator attention. A successful second application makes no duplicate changes. The installer never invokes service `start`, `stop`, `restart`, `enable`, or `disable`, and does not change firewalls, reboot a host, or reconfigure Docker workloads.

`linger_users` is separate and explicit. Enabling linger can start that user's service manager and allows their enabled user services to run after boot without an interactive login. The supplied `starai` configuration proposes it only for the existing `star` account. Brain 2's backup user already has linger enabled, so its configuration requests no linger changes.

## Inventory used for the supplied plans

These observations were collected by the parent task through the authorized remote connection. They are not runtime assumptions: the installer inspects each host again when run.

| Host | Service | Observed state | Observed retry | Proposed retry |
| --- | --- | --- | --- | --- |
| `starai` | `star-brain.service` | Active, enabled | `on-failure`, 5 s | `on-failure`, 15 s |
| `starai` | `star-knowledge.service` | Active, enabled | `on-failure`, 5 s | `on-failure`, 15 s |
| `starai` | `star-search-gateway.service` | Active, enabled | `on-failure`, 5 s | `on-failure`, 15 s |
| `starai` | `star-night-school.service` | Active, enabled | `on-failure`, 120 s | `on-failure`, 120 s |
| Brain 2 | `docker.service` | Active, enabled | `always`, 2 s | `always`, 15 s |
| Brain 2 | `containerd.service` | Active, enabled | `always`, 5 s | `always`, 15 s |
| Brain 2 | `wings.service` | Active, enabled | `on-failure`, 5 s | `on-failure`, 15 s |

All proposed eligible services get the unlimited retry window. The existing 5-second STAR retry delays already limit restart frequency; the material change is avoiding an eventual permanent start-limit failure and preserving explicit boot supervision. The longer 120-second night-school delay is retained.

The supplied configurations deliberately exclude these observed workloads:

- `star-knowledge-refresh.service`: failed, static; likely a timer-triggered job requiring separate diagnosis.
- `star-night-conductor.service`: inactive, static.
- `star-training-gen.service`: inactive, disabled.

No deployed Metallic/Minecraft Java, Velocity, or Geyser service units were found in this inventory. Docker and Wings supervision does not prove that an individual game server is configured to restart after host boot. Each actual managed server's lifecycle and persistent-volume configuration still need independent verification.

The Brain 2 user services `star-desktop-commander.service` (`on-failure`, 15 s) and `star-egress.service` (`always`, 3 s) were already active and enabled, with user linger enabled. They are intentionally excluded from this system-level installer. On `starai`, the remote agent was running outside an observed persistent system/user unit and `star` linger was disabled; the parent task is handling that connector separately.

## Validation completed for this handoff

Seven local tests pass: default dry-run behavior; root-only apply; safe refusal of wildcard/wrong-host configurations; skipped disabled/failed/one-shot workloads; pre-mutation validation rejection; preservation of `always` and the 120-second delay; idempotence; and rollback on an effective-setting mismatch. Some tests cover multiple related guarantees. A real, offline `systemd-analyze verify` run accepted a representative merged unit with the proposed network and recovery directives. No remote service was restarted or power-cycled by these checks.

An enabled service can restart after the operating system boots, but firmware or hypervisor settings must still restore power to the machine itself after an outage. Those settings and recovery from damaged storage are outside this installer.
