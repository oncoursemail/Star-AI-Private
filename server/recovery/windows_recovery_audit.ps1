# Read-only metadata inspection. No credentials, configuration values or task arguments are printed.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$pattern = 'Star|Commander|Conductor|Metallic|Minecraft|Roblox'
$os = Get-CimInstance Win32_OperatingSystem
$tasks = @(Get-ScheduledTask | Where-Object { $_.TaskName -match $pattern } | ForEach-Object {
    $task = $_
    $info = Get-ScheduledTaskInfo -TaskName $task.TaskName -TaskPath $task.TaskPath -ErrorAction SilentlyContinue
    [ordered]@{
        name = $task.TaskName; path = $task.TaskPath; state = [string]$task.State
        principal = [ordered]@{ user = $task.Principal.UserId; logon = [string]$task.Principal.LogonType; level = [string]$task.Principal.RunLevel }
        actions = @($task.Actions | ForEach-Object {
            # Only the executable and separately identified -File script path are emitted.
            $scriptPath = $null
            if ($_.Arguments -match '(?i)(?:^|\s)-File\s+(?:"([^"]+)"|(\S+))') {
                $scriptPath = if ($Matches[1]) { $Matches[1] } else { $Matches[2] }
            }
            [ordered]@{ executable = $_.Execute; script = $scriptPath; workingDirectory = $_.WorkingDirectory }
        })
        triggers = @($task.Triggers | ForEach-Object { [ordered]@{
            kind = $_.CimClass.CimClassName; enabled = $_.Enabled; start = $_.StartBoundary
            repetition = $_.Repetition.Interval; duration = $_.Repetition.Duration
        } })
        settings = [ordered]@{
            retryCount = $task.Settings.RestartCount; retryInterval = $task.Settings.RestartInterval
            executionLimit = $task.Settings.ExecutionTimeLimit; instances = [string]$task.Settings.MultipleInstances
            catchUp = $task.Settings.StartWhenAvailable; disallowBattery = $task.Settings.DisallowStartIfOnBatteries
            stopOnBattery = $task.Settings.StopIfGoingOnBatteries; networkRequired = $task.Settings.RunOnlyIfNetworkAvailable
        }
        lastResult = $info.LastTaskResult; lastRun = $info.LastRunTime; nextRun = $info.NextRunTime
    }
})
$services = @(Get-CimInstance Win32_Service | Where-Object {
    $_.Name -match $pattern -or $_.DisplayName -match $pattern
} | ForEach-Object {
    [ordered]@{ name = $_.Name; displayName = $_.DisplayName; state = $_.State; startup = $_.StartMode; user = $_.StartName; pid = $_.ProcessId }
})
$paths = @("$env:USERPROFILE\.star", "$env:APPDATA\Star", "$env:USERPROFILE\Documents\starai", "$env:LOCALAPPDATA\StarRecovery")
$storage = @($paths | ForEach-Object {
    $path = $_
    $exists = Test-Path -LiteralPath $path -PathType Container
    $files = @(); $readErrors = @()
    # Avoid recursively enumerating the source repository and its dependencies.
    if ($exists -and $path -notlike '*\Documents\starai') {
        $files = @(Get-ChildItem -LiteralPath $path -File -Recurse -ErrorAction SilentlyContinue -ErrorVariable +readErrors)
    }
    [ordered]@{ path = $path; exists = $exists; files = $files.Count
        bytes = [long](($files | Measure-Object -Property Length -Sum).Sum); unreadableEntries = $readErrors.Count }
})
[ordered]@{
    observedAt = (Get-Date).ToUniversalTime().ToString('o'); computer = $env:COMPUTERNAME; user = $identity.Name
    administratorToken = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    os = $os.Caption; lastBoot = $os.LastBootUpTime; uptimeSeconds = [long]((Get-Date) - $os.LastBootUpTime).TotalSeconds
    python315 = (Test-Path -LiteralPath 'C:\Python315\python.exe' -PathType Leaf)
    tasks = $tasks; services = $services; stateDirectories = $storage
} | ConvertTo-Json -Depth 8
