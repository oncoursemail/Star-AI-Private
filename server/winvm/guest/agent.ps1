# winvm guest agent: started at logon of `ci`. Polls the host for exactly one task, runs it, reports, shuts down.
# The golden state is saved while this loop polls, so every resumed clone continues right here within a second.
$ErrorActionPreference = 'Continue'
$H = 'http://10.0.2.100'  # star:allow QEMU user-mode net address (winvm.py GUEST_IP), not a LAN host
function Report($m) { try { Invoke-RestMethod "$H/log?m=$([uri]::EscapeDataString($m))" -TimeoutSec 3 | Out-Null } catch { } }

while ($true) {
    try { $t = Invoke-RestMethod "$H/task" -TimeoutSec 2 } catch { Start-Sleep -Milliseconds 300; continue }
    if ($t.kind -eq 'wait') { Start-Sleep -Milliseconds 700; continue }
    break
}
# The saved state's clock is stale: take the host's time first (TLS and the runner need it).
try { Set-Date -Date ([DateTimeOffset]::FromUnixTimeSeconds([int64]$t.epoch).UtcDateTime) | Out-Null } catch { Report "set-date: $_" }
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
$rc = 1
switch ($t.kind) {
    'github' {
        Report 'github runner starting'
        Push-Location C:\runner
        & .\run.cmd --jitconfig $t.jit
        $rc = $LASTEXITCODE
        Pop-Location
    }
    'shell' {
        # Host-supplied PowerShell (timing runs, smoke checks). Output goes to C:\a\task.log and back to the host.
        Report 'shell task starting'
        Set-Content C:\a\task.ps1 $t.script
        & C:\tools\pwsh\pwsh.exe -NoProfile -ExecutionPolicy Bypass -File C:\a\task.ps1 *> C:\a\task.log
        $rc = $LASTEXITCODE
        Get-Content C:\a\task.log -Tail 40 | ForEach-Object { Report $_ }
    }
    default { Report "unknown task kind $($t.kind)" }
}
try { Invoke-RestMethod "$H/done?rc=$rc" -TimeoutSec 5 | Out-Null } catch { }
Stop-Computer -Force
