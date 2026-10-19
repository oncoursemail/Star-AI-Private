# Run in Windows PowerShell as MAIN\alexi. Inspection is the default; -Apply registers the task.
[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$ExpectedUser = 'MAIN\alexi',
    [string]$PythonPath = 'C:\Python315\python.exe',
    [string]$RecoveryRoot = "$env:LOCALAPPDATA\StarRecovery"
)
$ErrorActionPreference = 'Stop'
$taskName = 'STAR compact recovery backup'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$sid = $identity.User.Value
if ($identity.Name -ine $ExpectedUser -or $sid -in @('S-1-5-18','S-1-5-19','S-1-5-20')) {
    throw "Run as the intended existing owner ($ExpectedUser); no service-account substitution is supported."
}
$scriptPath = Join-Path $RecoveryRoot 'windows_recovery_push.py'
$configPath = Join-Path $RecoveryRoot 'push.json'
$arguments = '"{0}" --config "{1}"' -f $scriptPath, $configPath
$present = (Test-Path -LiteralPath $PythonPath -PathType Leaf) -and
    (Test-Path -LiteralPath $scriptPath -PathType Leaf) -and
    (Test-Path -LiteralPath $configPath -PathType Leaf)
$existing = Get-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction SilentlyContinue
if ($existing) {
    $owner = $existing.Principal.UserId
    if ($owner -notmatch '^S-1-') {
        $owner = ([Security.Principal.NTAccount]::new($owner)).Translate([Security.Principal.SecurityIdentifier]).Value
    }
    if (@($existing.Actions).Count -ne 1 -or $existing.Actions[0].Execute -ine $PythonPath -or
        $existing.Actions[0].Arguments -cne $arguments -or $owner -ne $sid -or
        $existing.Principal.LogonType -ne 'Interactive' -or $existing.Principal.RunLevel -ne 'Limited') {
        throw 'Existing task differs from this owner and exact backup action. Refusing to replace it.'
    }
    if ($existing.State -eq 'Running' -and $Apply) {
        throw 'The existing backup task is running. Wait for it to finish before updating its definition.'
    }
}
$report = [ordered]@{ applied = $false; task = $taskName; owner = $identity.Name;
    accountFilesPresent = $present; existingTask = [bool]$existing;
    scope = 'Current owner, limited interactive session; sign-in is required after boot.' }
if (-not $Apply) { $report | ConvertTo-Json -Depth 4; return }
if (-not $present) { throw 'Python, the backup exporter, or push.json is missing; task registration was not attempted.' }
if ($existing) {
    $history = Join-Path $RecoveryRoot 'task-history'
    New-Item -ItemType Directory -Path $history -Force | Out-Null
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner($identity.User)
    $rule = [Security.AccessControl.FileSystemAccessRule]::new($identity.User, 'FullControl',
        'ContainerInherit, ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $history -AclObject $acl
    $prior = Join-Path $history ('backup-task-{0}.xml' -f (Get-Date -Format 'yyyyMMddTHHmmssffff'))
    Export-ScheduledTask -TaskName $taskName -TaskPath '\' | Set-Content -LiteralPath $prior -Encoding Unicode
}
$action = New-ScheduledTaskAction -Execute $PythonPath -Argument $arguments -WorkingDirectory $RecoveryRoot
$hourly = New-ScheduledTaskTrigger -Once -At (Get-Date).AddHours(1) -RepetitionInterval (New-TimeSpan -Hours 1)
$logon = New-ScheduledTaskTrigger -AtLogOn -User $identity.Name
$principal = New-ScheduledTaskPrincipal -UserId $sid -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 15)
$definition = New-ScheduledTask -Action $action -Trigger @($hourly,$logon) -Principal $principal `
    -Settings $settings -Description 'Compact STAR backup; hourly and at owner sign-in. No system account or stored password.'
Register-ScheduledTask -TaskName $taskName -TaskPath '\' -InputObject $definition -Force | Out-Null
$after = Get-ScheduledTask -TaskName $taskName -TaskPath '\'
$info = Get-ScheduledTaskInfo -TaskName $taskName -TaskPath '\'
$intervals = @($after.Triggers | ForEach-Object { $_.Repetition.Interval } | Where-Object { $_ })
$report.applied = $true
$report['verification'] = [ordered]@{
    exactAction = ($after.Actions[0].Execute -ieq $PythonPath -and $after.Actions[0].Arguments -ceq $arguments)
    limitedInteractive = ($after.Principal.LogonType -eq 'Interactive' -and $after.Principal.RunLevel -eq 'Limited')
    hourly = ($intervals -contains 'PT1H'); logon = (@($after.Triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger' }).Count -eq 1)
    ignoreOverlap = ($after.Settings.MultipleInstances -eq 'IgnoreNew'); durationLimit = $after.Settings.ExecutionTimeLimit
    catchUp = $after.Settings.StartWhenAvailable; allowedOnBattery = (-not $after.Settings.DisallowStartIfOnBatteries -and -not $after.Settings.StopIfGoingOnBatteries)
    noNetworkPrecondition = (-not $after.Settings.RunOnlyIfNetworkAvailable)
    retryCount = $after.Settings.RestartCount; retryInterval = $after.Settings.RestartInterval
    nextRun = $info.NextRunTime; lastResult = $info.LastTaskResult
}
$report | ConvertTo-Json -Depth 5
if (-not $report.verification.exactAction -or -not $report.verification.limitedInteractive -or
    -not $report.verification.hourly -or -not $report.verification.logon -or -not $report.verification.ignoreOverlap -or
    -not $report.verification.catchUp -or -not $report.verification.allowedOnBattery -or
    -not $report.verification.noNetworkPrecondition -or $report.verification.durationLimit -ne 'PT30M' -or
    $report.verification.retryCount -ne 3 -or $report.verification.retryInterval -ne 'PT15M') {
    throw 'Task registration completed, but one or more required verification flags failed. Inspect the task before relying on it.'
}
