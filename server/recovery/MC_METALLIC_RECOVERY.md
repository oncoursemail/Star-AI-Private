# Minecraft and Metallic recovery readiness

## Present coverage and access

**The Minecraft and Metallic production worlds and databases have not been backed up or restore-tested by this job.** The generic exporter and backup runner have not been pointed at live game worlds. The STAR backups described elsewhere in this kit do not establish game-server coverage.

The following are observations reported by the parent session on 19 October 2026:

| Host or component | Observed fact | Recovery implication |
| --- | --- | --- |
| `mc-ubuntu` | SSH to `10.17.0.106:22` timed out from Brain 1. | Its services, persistent data and backup state could not be inspected. A timeout does not establish whether the machine is powered off. |
| Brain 2, `alexbuz1` | `docker.service`, `containerd.service` and `wings.service` were active and enabled. | Their availability does not prove that a particular game container restarts or that its persistent data is protected. |
| Brain 2 storage | `/var/lib/pterodactyl` and `/var/lib/docker/volumes` were unreadable to the available account. | Game-server IDs, world paths, mount mappings and retained snapshots remain unverified. Their contents were not copied. |
| Observed Linux service inventory | No live Java, Velocity or Geyser system service units were observed. | Games may be managed elsewhere or inside containers. This is not evidence that those services do not exist. |

## Concrete administrator operations already prepared

The existing installer handles only explicitly allowlisted, currently running and persistently enabled system services. It preserves service accounts, writes reversible retry drop-ins, validates them, reloads unit definitions and verifies the result. It does **not** start, enable or restart services, change container policies, or create game backups. See `LINUX_RECOVERY_ADMIN.md` for its rollback and privilege requirements.

On Brain 1 (`starai`), review the exact deployed files:

```bash
/usr/bin/python3 /home/star/.local/share/star-recovery/linux_recovery_admin.py \
  /home/star/.local/share/star-recovery/linux_recovery_starai.json
```

That read-only review passed for four existing STAR services. An administrator in an existing root session can apply the reviewed configuration:

```bash
/usr/bin/python3 /home/star/.local/share/star-recovery/linux_recovery_admin.py \
  /home/star/.local/share/star-recovery/linux_recovery_starai.json --apply
```

On Brain 2 (`alexbuz1`), an administrator must perform the review from an existing root session:

```bash
/usr/bin/python3 /home/alexbuz1/.local/share/star-recovery/linux_recovery_admin.py \
  /home/alexbuz1/.local/share/star-recovery/linux_recovery_alexbuz1.json
```

The limited-account review stopped during `systemd-analyze verify`: access to `netplan-ovs-cleanup` unit material was denied and `/usr/local/bin/wings` was not executable by that account. It did not apply changes. After a successful administrator review, apply only that host's explicit Docker, containerd and Wings configuration:

```bash
/usr/bin/python3 /home/alexbuz1/.local/share/star-recovery/linux_recovery_admin.py \
  /home/alexbuz1/.local/share/star-recovery/linux_recovery_alexbuz1.json --apply
```

These are prepared operations, not claims of completed privileged changes. Brain 1 requires an administrator's normal authentication, while the present Brain 2 session has `no-new-privileges`; the installer does not bypass either boundary. In an administrator review, also check the ownership and contents of these user-directory scripts before executing them with root privileges.

## Inventory required before protecting a game server

Record one explicit entry for each production server. Required facts are:

- The actual host, supported access route, service or panel/server ID, container ID where applicable, existing restart policy, runtime versions, and the controller that owns startup and shutdown. Preserve deliberately stopped workloads.
- Absolute persistent host paths and container mount mappings, filesystem ownership and permissions, free space, quotas and measured data size. Confirm that every world and dimension, region/entity/POI data, player data, datapacks, configuration, plugin data and custom assets is included or has a documented reconstruction source.
- Each database and its owning application, its supported consistent backup mechanism, and the relationship between database state and world files. Include economies, inventories, permissions, bans, identities and account links where the actual deployment uses them. Keep credentials out of the inventory report.
- Proxy, forwarding and authentication settings, network dependencies, plugin/mod versions and checksums, resource packs, and any Java/Bedrock compatibility layer actually deployed. Identify startup readiness and reconnect behavior; an open port alone is not a complete gameplay check.

Inspect the panel/controller's documented startup settings before changing any container restart policy. A managed container's policy must agree with its controller and intended stopped state. Approve individual existing workloads after identifying them; do not bulk-enable all containers or services.

## Consistent compact snapshots

Treat a two-hour recovery interval as a proposed production schedule until the actual inventory and first verified restore exist. Measure changed data and backup duration before choosing retention and resource limits. Compression and deduplication can reduce storage, but cannot make an arbitrary changing world consume no additional space.

A live file copy can mix world data from different save points, omit cached changes, or split plugin transactions across databases and files. Use the actual server version's documented save/flush and snapshot procedure, including plugin and database requirements. If a coordinated online snapshot cannot be established, take a short controlled maintenance window, stop the identified game workload gracefully, verify that shutdown completed, capture its persistent data, then restore its prior intended running state. A filesystem snapshot of actively changing files alone does not establish application consistency.

All quiescing must have bounded waits and recovery handling. If flush or shutdown fails, mark the attempted backup unsuccessful; do not silently publish an incomplete checkpoint. If a save pause is used, reliably resume it even if export fails. Keep the protected baseline outside automatic rolling-retention deletion. Do not interpret connection failure, a DDoS event or a failed health probe as permission to roll a live world back.

## Baseline and isolated restore acceptance

Create a baseline only after the owner reviews the actual game state. A valid hash or readable database proves technical integrity, not the absence of griefing already present at capture time. Retain a reviewed baseline and enough older versions to cover delayed discovery.

Protect that baseline in administrator-controlled offline storage or correctly configured retention-locked/WORM storage, independently of game-server credentials. A compromised source should be unable to delete or overwrite it. A separate writable repository on a second local machine improves isolation but is not a verified immutable or off-site copy. No single snapshot can honestly be guaranteed "100% grief-proof" in every circumstance.

For acceptance, restore an archived snapshot into a new quarantine directory or test host. Verify the manifest, file hashes and database integrity before startup; preserve the original archive. Run the restored game with production endpoints, public admission, scheduled jobs and external write integrations isolated. Check representative worlds, player state, builds, inventories/economies where present, permissions, plugins and the actual supported client paths. Record the checkpoint time, contents, restoration duration and owner review. A later production rollback requires an explicit checkpoint choice, a fresh preservation copy of the current state, and a controlled maintenance operation.

## Network and power recovery boundary

DDoS mitigation must act upstream of a saturated internet connection. A reverse proxy or tunnel can form part of that design only when the public ingress is protected and origin exposure is controlled; backup files do not filter traffic. Select protection for the protocols actually deployed, including UDP if required. After a network outage, services should reconnect with bounded backoff without restoring older game data.

Unattended recovery from a power loss additionally depends on host firmware or hypervisor power restoration, working storage and the operating system booting. Those conditions and a real game-server cold-boot test remain unverified here. Once access and inventory are resolved, validate each layer separately: host startup, controller readiness, intended game workload startup, client connection, a completed scheduled backup and an isolated restore.
