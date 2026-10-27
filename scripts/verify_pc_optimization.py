"""Verify Windows optimization using fake registry/probes and temporary DPAPI backups.

No real startup registration, app, power plan, service, driver or security setting
is changed. Requires Windows PowerShell; run with the project's Python environment.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


HARNESS = r"""
param([string]$Source, [string]$FixtureRoot)
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Optimization script has syntax errors.' }
. $Source -FunctionsOnly
$script:Passed = 0
function Check([string]$Name, [bool]$Ok) {
    if (-not $Ok) { throw ('Failed check: ' + $Name) }
    $script:Passed += 1
}
function Reject([string]$Name, [scriptblock]$Body) {
    $rejected = $false
    try { & $Body | Out-Null } catch { $rejected = $true }
    Check $Name $rejected
}
$script:Fake = @{}
$script:Writes = 0; $script:Removes = 0; $script:Reads = 0
$script:RaceAtRead = 0
function Get-StarStartupValue([string]$Name) {
    $script:Reads += 1
    if ($script:RaceAtRead -eq $script:Reads) {
        $script:Fake[$Name] = @{ Present = $true; Kind = 'String'; Value = 'a changed fixture value' }
    }
    if ($script:Fake.ContainsKey($Name)) { return $script:Fake[$Name].Clone() }
    return @{ Present = $false }
}
function Remove-StarStartupValue([string]$Name) {
    Check 'encrypted backup precedes each registry removal' (@(Get-ChildItem -LiteralPath (Join-Path $FixtureRoot 'STAR\home\optimization') -File).Count -gt 0)
    $script:Removes += 1; $script:Fake.Remove($Name)
}
function Set-StarStartupValue([string]$Name, [string]$Value, [string]$Kind) {
    $script:Writes += 1
    $script:Fake[$Name] = @{ Present = $true; Kind = $Kind; Value = $Value }
}
function Invoke-StarReadOnlyProbe([string]$File, [string]$Arguments) {
    if ($File -like '*powercfg.exe') { return 'Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e (Balanced)' }
    return 'NVIDIA GeForce RTX 4060, 999.00, 8188, 6123, 92, 70, 105.25'
}
function Get-CimInstance { return [pscustomobject]@{ Caption = 'Windows fixture'; BuildNumber = 'fixture'; TotalVisibleMemorySize = 33554432; FreePhysicalMemory = 16777216 } }
function Get-AppxPackage { return $null }
$root = Join-Path $FixtureRoot 'STAR'
$script:Fake['Steam'] = @{ Present = $true; Kind = 'ExpandString'; Value = '"%ProgramFiles(x86)%\Steam\steam.exe" -silent' }
$script:Fake['Discord'] = @{ Present = $true; Kind = 'String'; Value = 'protected fixture' }
$original = $script:Fake['Steam'].Clone()
Check 'default Apply switch is false' (-not (Get-Variable Apply -ValueOnly))
Check 'ShouldProcess supports WhatIf' ($null -ne $ast.ParamBlock.Attributes.Where({ $_.TypeName.Name -eq 'CmdletBinding' }))
$commands = @($ast.FindAll({ param($node) $node -is [Management.Automation.Language.CommandAst] }, $true) | ForEach-Object { $_.GetCommandName() })
Check 'no app, service or driver removal commands' (-not @($commands | Where-Object { $_ -in 'Remove-AppxPackage', 'Remove-AppxProvisionedPackage', 'Remove-Item', 'Set-Service', 'Stop-Service', 'Remove-WindowsDriver', 'Invoke-WebRequest', 'Start-Process' }).Count)
Check 'catalog is a small exact allowlist' ((Get-StarOptionalStartup).Count -eq 5)
Check 'STAR voice and Windows components absent from cleanup allowlist' ((Get-StarOptionalStartup).Values.Name -notcontains 'Discord')
foreach ($bad in @('relative', 'C:STAR', 'C:\', '\\server\share\STAR', 'C:\STAR\..\Windows', 'C:\STAR\file:stream',
    'C:\STAR\bad*', 'C:\STAR\trailing.', 'C:\STAR\trailing ', 'C:/STAR', 'C:\STAR\\home')) {
    Reject 'ambiguous root rejected' { Resolve-StarOptimizationRoot $bad }
}
Reject 'Windows folder rejected' { Resolve-StarOptimizationRoot $env:windir }
Reject 'drive root rejected' { Resolve-StarOptimizationRoot 'C:\' }
$target = Join-Path $FixtureRoot 'junction-target'
$link = Join-Path $FixtureRoot 'junction'
[void][IO.Directory]::CreateDirectory($target)
New-Item -ItemType Junction -Path $link -Target $target | Out-Null
Reject 'junction ancestor rejected' { Resolve-StarOptimizationRoot (Join-Path $link 'STAR') }
Reject 'unknown app ID rejected' { Get-StarStartupPlan @('discord') }
Reject 'wildcard ID rejected' { Get-StarStartupPlan @('steam*') }
Reject 'duplicate IDs rejected' { Get-StarStartupPlan @('steam', 'steam') }
Reject 'noncanonical ID rejected' { Get-StarStartupPlan @('Steam') }
$preview = Invoke-StarStartupCleanup $root @('steam') $false
Check 'preview lists exact planned change' ($preview.Mode -eq 'preview' -and $preview.Changes[0].Id -eq 'steam')
Check 'preview touches no registry state' ($script:Writes -eq 0 -and $script:Removes -eq 0)
Check 'preview creates no backup folder' (-not (Test-Path -LiteralPath (Join-Path $root 'home\optimization')))
Check 'preview hides original command' (($preview | ConvertTo-Json -Depth 8) -notmatch 'steam.exe')
$plan = @(Get-StarStartupPlan @('spotify'))
Check 'missing optional startup is explicit' ($plan[0].Action -eq 'not-registered')
$script:Fake['Spotify'] = @{ Present = $true; Kind = 'DWord'; Value = 1 }
Check 'unexpected registry type skipped' (@(Get-StarStartupPlan @('spotify'))[0].Action -eq 'unsupported-value')
$applied = Invoke-StarStartupCleanup $root @('steam') $true
Check 'only selected fake startup removed' (-not $script:Fake.ContainsKey('Steam') -and $script:Fake.ContainsKey('Discord'))
Check 'explicit apply writes a backup' (Test-Path -LiteralPath $applied.Manifest -PathType Leaf)
Check 'backup never stores readable command' (-not [IO.File]::ReadAllText($applied.Manifest).Contains($original.Value))
$backup = Read-StarOptimizationManifest $root $applied.Manifest
Check 'backup preserves unexpanded registry string and type' ($backup.Entries[0].Value -ceq $original.Value -and $backup.Entries[0].Kind -eq 'ExpandString')
$restorePreview = Restore-StarStartupCleanup $root $applied.Manifest $false
Check 'restore preview writes nothing' ($restorePreview.Changes[0].Status -eq 'would-restore' -and $script:Writes -eq 0)
$restored = Restore-StarStartupCleanup $root $applied.Manifest $true
Check 'same-account restore works' ($restored.Changes[0].Status -eq 'restored' -and $script:Fake['Steam'].Value -ceq $original.Value)
Check 'repeated restore is idempotent' ((Restore-StarStartupCleanup $root $applied.Manifest $true).Changes[0].Status -eq 'already-original')
$script:Fake['Steam'] = @{ Present = $true; Kind = 'String'; Value = 'new owner configuration' }
Check 'changed owner value wins on restore' ((Restore-StarStartupCleanup $root $applied.Manifest $true).Changes[0].Status -eq 'conflict-preserved')
Check 'owner change not overwritten' ($script:Fake['Steam'].Value -eq 'new owner configuration')
Reject 'backup outside root rejected' { Read-StarOptimizationManifest $root (Join-Path $FixtureRoot 'startup-00000000000000000000000000000000.json') }
$forged = Save-StarOptimizationManifest $root @(@{ Id = 'steam'; Name = 'Discord'; Kind = 'String'; Value = 'test' })
Reject 'valid encrypted backup with wrong target rejected' { Read-StarOptimizationManifest $root $forged }
$altered = Join-Path (Join-Path $root 'home\optimization') ('startup-' + [Guid]::NewGuid().ToString('N') + '.json')
[IO.File]::WriteAllText($altered, '{"Format":"STAR startup backup v1","Protected":"broken"}')
Reject 'altered ciphertext rejected' { Read-StarOptimizationManifest $root $altered }
$movedRoot = Join-Path $FixtureRoot 'OtherSTAR'
Reject 'backup root binding rejects alternate root' { Read-StarOptimizationManifest $movedRoot $applied.Manifest }
$script:Fake['Steam'] = $original.Clone()
$script:Reads = 0; $script:RaceAtRead = 3
$race = Invoke-StarStartupCleanup $root @('steam') $true
Check 'concurrent startup edit preserved during cleanup' ($race.Changes[0].Status -eq 'conflict-preserved')
$script:RaceAtRead = 0
$csv = @(Convert-StarGpuCsv 'NVIDIA GeForce RTX 4060, 999.00, 8188, 6000, 94, 73, 111.25')
Check 'GPU numeric fields parsed' ($csv[0].TotalMB -eq 8188 -and $csv[0].PowerW -eq 111.25)
Check 'unsupported GPU fields remain unknown' ($null -eq (Convert-StarNumeric 'N/A'))
Check 'nonfinite GPU fields rejected' ($null -eq (Convert-StarNumeric 'NaN'))
Check 'blank GPU fields stay unknown' ($null -eq (Convert-StarNumeric ''))
Check 'malformed GPU CSV yields no observation' (@(Convert-StarGpuCsv 'not-a-gpu-row').Count -eq 0)
$counters = Get-StarObsCounters @'
10:00:00 Number of lagged frames due to rendering lag/stalls: 1 (0.2%)
10:00:01 Video stopped, number of skipped frames due to encoding lag: 2/100 (2.0%)
10:00:02 private-token-do-not-echo
10:00:03 Number of dropped frames due to insufficient bandwidth/connection stalls: 3 (3.0%)
'@
Check 'OBS lag types kept separate' ($counters.RenderingLagPercent -eq 0.2 -and $counters.EncodingLagPercent -eq 2 -and $counters.NetworkDropPercent -eq 3)
Check 'OBS parser discards raw log text' (($counters | ConvertTo-Json) -notmatch 'private-token-do-not-echo')
$audit = Get-StarOptimizationAudit $root
Check 'audit reports actual fixture memory' ($audit.System.FreeMemoryMB -eq 16384)
Check 'audit reports fixture GPU snapshot' ($audit.GpuSnapshot[0].TotalMB -eq 8188)
Check 'power-plan query is observation only' ($audit.ActivePowerPlanGuid -eq '381b4222-f694-41f0-9685-ff5bb260df2e')
Check 'audit never claims measured improvement' ($audit.PerformanceGainMeasured -eq $false)
Check 'audit does not expose startup commands' (($audit | ConvertTo-Json -Depth 10) -notmatch 'steam.exe|protected fixture')
Check 'only fake writes occurred' ($script:Writes -eq 1 -and $script:Removes -eq 1)
@{ Checks = $script:Passed; RealStartupWrites = 0; RealPackageRemovals = 0; ProbeCalls = 'mocked'; Status = 'passed' } | ConvertTo-Json -Compress
"""


def main() -> None:
    if os.name != "nt":
        raise SystemExit("Run this Windows-only verifier on Windows; nothing was applied.")
    executable = shutil.which("powershell.exe")
    if not executable:
        raise SystemExit("Windows PowerShell is required; nothing was applied.")
    source = Path(__file__).resolve().parents[1] / "installer" / "star-home" / "optimize-star-pc.ps1"
    with tempfile.TemporaryDirectory(prefix="star-optimization-check-") as temporary:
        folder = Path(temporary)
        harness = folder / "verify.ps1"
        harness.write_text(HARNESS, encoding="utf-8-sig")
        completed = subprocess.run(
            [
                executable,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(harness),
                "-Source",
                str(source),
                "-FixtureRoot",
                str(folder),
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
        if completed.returncode:
            raise SystemExit(completed.stderr.strip() or completed.stdout.strip() or "Verification failed.")
        result = json.loads(completed.stdout.strip())
        print(f"{result['Checks']} optimization checks passed; no real startup/app changes; probes mocked")


if __name__ == "__main__":
    main()
