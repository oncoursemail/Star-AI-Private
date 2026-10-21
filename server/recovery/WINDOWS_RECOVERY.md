# Main Windows recovery

## Observed configuration

The parent session inspected Main on 19 October 2026. Windows 11 runs as `<COMPUTER>\<WIN_USER>` without an elevated administrator token. `Desktop Commander Background` is running under this same user, with a limited interactive principal, sign-in and time triggers, start-when-available enabled, unlimited execution time, 255 scheduler retries one minute apart, and overlapping launches ignored. The existing hidden supervisor separately retries the actual remote node agent after exit, backing off from 10 to 60 seconds. It respects the owner's `DISABLED` switch and uses a user/session mutex. This working configuration was preserved.

The running STAR GPU night turbo task has a time trigger and a 72-hour execution limit; changing its start conditions could change when heavy GPU work runs. The other STAR GPU worker task is disabled. Neither task is modified by this recovery kit.

STAR state was observed at `%USERPROFILE%\.star` (428 files; 26,744,077 bytes) and `%APPDATA%\Star` (120 files; 3,738,766,410 bytes, predominantly models, downloads and engines). The latter also contains small root SQLite databases and `knowledge\knowledge.sqlite3`. Python is at `C:\Python315\python.exe`. The compact exporter excludes regenerable model/download/engine caches and snapshots SQLite through its backup API.

## Register the compact backup schedule

First deploy and verify the exporter, configuration and its protected receiving destination. The installer expects `windows_recovery_push.py` and `push.json` in `%LOCALAPPDATA%\StarRecovery`. Its default invocation only inspects local prerequisites and any existing task:

```powershell
powershell.exe -NoProfile -File $env:LOCALAPPDATA\StarRecovery\windows_recovery_schedule.ps1 -ExpectedUser (whoami)
```

After those prerequisites exist, run as the existing owner:

```powershell
powershell.exe -NoProfile -File $env:LOCALAPPDATA\StarRecovery\windows_recovery_schedule.ps1 -ExpectedUser (whoami) -Apply
```

This installs **STAR compact recovery backup** with one action under the same limited interactive account, an indefinite hourly trigger, a sign-in trigger, catch-up after a missed run, no overlapping runs, a 30-minute execution limit, and three retries 15 minutes apart. It permits battery operation and lets the exporter handle connection failures. It does not start an immediate extra backup or alter GPU tasks. The first scheduled attempt is one hour after registration; the initial backup is run and verified separately. A task with another owner, principal or action is refused; an existing matching task's XML is saved in an owner-only `task-history` directory before updating it. Registration does not prove a successful backup: inspect the reported flags, then confirm the scheduled run's result and receiving-side verified snapshot.

## What a power failure still requires

These interactive tasks restart once **the owner signs in**. They cannot run before sign-in. We have not enabled automatic login, stored a Windows password, substituted SYSTEM, or claimed unattended cold-boot recovery. The desktop STAR GUI also requires an interactive session.

The next concrete administrator task is to install a separately reviewed background-agent service or noninteractive startup task using a supported service identity and deliberately scoped state/network access. First establish whether the remote agent supports that identity and whether its existing authentication state is usable without an interactive profile. An S4U task is not an interchangeable replacement for the existing login: network credentials and encrypted user material may be unavailable. Do not copy an existing interactive task to SYSTEM. Any account password needed by a supported Windows setup must be entered by the owner into the native Windows credential dialog, never a script or chat.

Restoring power to a machine that is physically off depends on firmware. On Main, the owner must check the UEFI/BIOS option usually called **Restore AC Power Loss / AC Back / Power On After Power Failure**, and select **Power On** if unattended recovery is desired. Its availability and present setting were not verified. A UPS and its supported shutdown integration can reduce abrupt data loss but were not installed or tested here.

Recovery testing should first verify a completed scheduled backup and restore its data into a separate directory. A later owner-coordinated boot test must verify firmware startup, Windows startup, sign-in requirements and the remote agent; Main was not rebooted and its Windows connector was not interrupted by this work.

## Protection boundary

A snapshot with verified files and databases proves readability and integrity at capture time, not that its game state was already free from griefing. Keep an independently retained, reviewed baseline at the protected receiver plus recent compact versions. Compromising Main must not grant deletion or overwrite access to that retained baseline. Copies on another machine in the same building still share power, theft and site-loss risks. DDoS traffic must be filtered upstream; backups support restoration but do not prevent link saturation.
