# Dedicated STAR PC: audit and reversible startup cleanup

`installer/star-home/optimize-star-pc.ps1` prepares an evidence-based optimization
pass for STAR's dedicated RTX 4060 Windows PC. It previews by default and makes no
performance-gain claim. No optimization was applied to the development PC.

## Run on STAR's PC as STAR's Windows account

From PowerShell, with the actual installation root:

```powershell
.\installer\star-home\optimize-star-pc.ps1 -Root D:\STAR
.\installer\star-home\optimize-star-pc.ps1 -Root D:\STAR -DisableStartupId steam,spotify
.\installer\star-home\optimize-star-pc.ps1 -Root D:\STAR -DisableStartupId steam,spotify -Apply
```

The first command is a read-only audit. The second previews selected startup
changes. Only the third changes the chosen registrations. `-WhatIf` also keeps
an apply request in preview mode. Comma-separated IDs work when launching with
`powershell.exe -File` as well.

Exact startup IDs: `spotify`, `steam`, `epic-games`, `teams-classic`, `skype`.
These map to five vetted names in the **current user's Run key**. No patterns,
all-user keys, services, scheduled tasks or other startup locations are edited.
Discord, STAR, game dependencies, the browser, OneDrive and security components
are outside the cleanup allowlist. A registered value may already be disabled
in Windows Startup settings; registration is not proof that it actually runs.

Cleanup removes only those selected launch registrations for the next sign-in.
It leaves the app installed, leaves running programs alone, and does not touch
app files or data. The app can still be launched manually. An application update
may register itself again; no persistent blocking policy is installed.

## Restore

Before the first change, the tool writes an exclusive new backup under
`<root>\home\optimization\startup-<random-id>.json`. Original unexpanded values
and registry types are protected with Windows DPAPI **CurrentUser**, bound to
that account and installation root. The report includes the backup's path but
never the original command lines. Keep this folder with STAR's local data;
backups are not committed, uploaded or copied into public releases.

```powershell
.\installer\star-home\optimize-star-pc.ps1 -Root D:\STAR -RestoreManifest 'D:\STAR\home\optimization\startup-<id>.json'
.\installer\star-home\optimize-star-pc.ps1 -Root D:\STAR -RestoreManifest 'D:\STAR\home\optimization\startup-<id>.json' -Apply
```

The first command previews restoration. The second restores missing values.
An existing original value is a no-op; a changed value is preserved as a conflict.
Current values are checked immediately before removal or restoration. Restore
validates the exact ID/name/type, account/root binding, size, file location and
encrypted payload. Absolute local paths are required; traversal, device/UNC
paths, alternate streams, wildcard paths and reparse-point ancestors are refused.
DPAPI does not isolate data from other programs running as STAR's same account.

## What the audit measures

- Windows build and a current free/total memory snapshot.
- The active power-plan GUID through read-only `powercfg /getactivescheme`.
- One NVIDIA snapshot of GPU name, driver version, VRAM use, utilization,
  temperature and reported power. Missing/unsupported counters stay unknown.
  A snapshot is not a frame-time benchmark or a thermal stability test.
- Whether OBS is installed at its standard location and its file version.
- With `-ObsLogPath 'C:\absolute\selected.log'`, the last reported rendering-lag,
  encoding-lag and network-drop percentages from that selected log. Other log
  text is discarded. No OBS stream profile, stream key, account or browser data
  is read. Counters may refer to different sessions in a reused log; use a fresh
  log for comparisons. Portable/custom OBS installations need manual checking.
- Presence of five optional AppX package names for review. AppX availability
  failures are unknown, not fabricated success.

Use the same five-minute game scene, avatar, call and OBS workload before/after
one change. Inspect OBS Stats for rendering, encoding and network problems
separately, plus game frame times and voice interruptions. Keep a change only
when that comparison improves the intended metric without regressions. For an
overloaded GPU, first test a game FPS cap and simpler OBS/avatar scenes. NVENC
uses dedicated encoding hardware, while compositing, local inference and avatar
rendering still need GPU resources. Select a codec supported by the destination.

Power plans, GPU clocks/power limits, drivers, Defender, Windows Update, UAC,
privacy/telemetry settings and Windows services are not changed. Balanced versus
Best performance is a manual workload comparison including temperature/power.
No benchmark model or game is started by the audit.

## Why this tool does not uninstall apps

Normal packaged-app uninstall can remove application data. Microsoft's
`-PreserveApplicationData` option applies to loose development packages and does
not establish a reversible uninstall for ordinary Store apps. Optional app
inventory therefore leads to Windows Settings recommendations, where the owner
can back up needed app data first. No provisioned packages or app files are
deleted by this tool.

## Verification

`python scripts/verify_pc_optimization.py` runs Windows PowerShell with fake
registry operations and fake hardware probes. It uses real DPAPI only for
synthetic temporary backup files. Checks cover preview/no writes, exact IDs,
path/junction guards, backup-before-change, encrypted payloads, restore/conflict
handling, races, malformed counters, OBS separation and honest unknown states.
No harness-owned tests were edited. Target-PC observations and before/after
streaming performance remain pending.

## Primary sources checked 2026-10-25 (America/Chicago)

- [Microsoft startup-app guidance](https://support.microsoft.com/en-us/windows/experience/startup-boot/configure-startup-applications-in-windows)
  and [Run keys](https://learn.microsoft.com/windows/win32/setupapi/run-and-runonce-registry-keys):
  current-user startup registration is distinct from uninstalling an app.
- [Microsoft power modes](https://support.microsoft.com/en-us/windows/change-the-power-mode-for-your-windows-pc-c2aff038-22c9-f46d-5ca0-78696fdf2de8):
  available modes depend on the device and selected plan.
- [Remove-AppxPackage](https://learn.microsoft.com/en-us/powershell/module/appx/remove-appxpackage):
  the data-preservation limitations inform the decision to avoid app removal.
- [DPAPI scope](https://learn.microsoft.com/en-us/dotnet/api/system.security.cryptography.dataprotectionscope):
  CurrentUser limits unprotection to the user's context.
- [NVIDIA nvidia-smi](https://docs.nvidia.com/deploy/nvidia-smi/): reported metrics
  have hardware/driver-dependent availability and sampling behavior.
- [NVIDIA OBS guide](https://www.nvidia.com/en-us/geforce/guides/broadcasting-guide/)
  and [OBS performance troubleshooting](https://obsproject.com/kb/encoding-performance-troubleshooting):
  codec/preset choices and GPU workload compete within the overall streaming setup.
