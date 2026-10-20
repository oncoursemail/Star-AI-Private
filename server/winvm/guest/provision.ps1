# First-logon provisioning of the golden Windows CI image (runs once, elevated, as the local user `ci`).
# Everything comes from the config ISO (tools already SHA-256 checked by winvm.py fetch). Ends with a power-off;
# winvm.py boots it again without the ISOs, autologon starts agent.ps1, whose first poll lets the host save the state.
param([Parameter(Mandatory = $true)][string]$Source)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force C:\winvm, C:\tools, C:\a, C:\cache | Out-Null
Start-Transcript -Path C:\winvm\provision.log -Append
$T = Join-Path $Source 'tools'
$TC = 'C:\hostedtoolcache\windows'
# Fixed cache folders: the workflow points APPDATA/LOCALAPPDATA at a throwaway profile, which would hide the default ones.
$env:PIP_CACHE_DIR = 'C:\cache\pip'
$env:npm_config_cache = 'C:\cache\npm'

function Step($name, [scriptblock]$block) {
    $t0 = Get-Date
    try { & $block; Write-Output ("STEP ok   {0} {1:n0}s" -f $name, ((Get-Date) - $t0).TotalSeconds) }
    catch { Write-Output ("STEP FAIL {0}: {1}" -f $name, $_) ; throw }
}

Step 'quiet machine' {
    powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c
    powercfg /hibernate off
    $au = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU'
    New-Item -Force $au | Out-Null
    Set-ItemProperty $au NoAutoUpdate 1 -Type DWord
    foreach ($s in 'wuauserv', 'UsoSvc', 'WSearch', 'SysMain', 'DiagTrack', 'MapsBroker', 'dmwappushservice') {
        Stop-Service $s -Force -ErrorAction SilentlyContinue
        Set-Service $s -StartupType Disabled -ErrorAction SilentlyContinue
    }
    foreach ($t in '\Microsoft\Windows\Defrag\', '\Microsoft\Windows\Application Experience\',
                   '\Microsoft\Windows\Customer Experience Improvement Program\', '\Microsoft\Windows\UpdateOrchestrator\',
                   '\Microsoft\Windows\WindowsUpdate\', '\Microsoft\Windows\Maintenance\') {
        Get-ScheduledTask -TaskPath $t -ErrorAction SilentlyContinue | Disable-ScheduledTask -ErrorAction SilentlyContinue | Out-Null
    }
    $cd = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\CloudContent'
    New-Item -Force $cd | Out-Null
    Set-ItemProperty $cd DisableWindowsConsumerFeatures 1 -Type DWord
    # Defender stays on (real users have it); only the CI work folders are excluded, inside this throwaway VM.
    Add-MpPreference -ExclusionPath 'C:\a', 'C:\runner', $TC, 'C:\cache', "$env:TEMP"
}

Step 'pwsh + git' {
    Expand-Archive (Join-Path $T 'PowerShell-7.6.6-win-x64.zip') C:\tools\pwsh -Force
    Expand-Archive (Join-Path $T 'MinGit-2.56.0.2-64-bit.zip') C:\tools\git -Force
}

Step 'python 3.11.9 (tool cache)' {
    $z = Join-Path $env:TEMP 'python.zip'
    Copy-Item (Join-Path $T 'python.3.11.9.nupkg') $z
    Expand-Archive $z (Join-Path $env:TEMP 'py') -Force
    $dst = Join-Path $TC 'Python\3.11.9\x64'
    New-Item -ItemType Directory -Force $dst | Out-Null
    Copy-Item (Join-Path $env:TEMP 'py\tools\*') $dst -Recurse -Force
    New-Item -ItemType File -Force "$dst.complete" | Out-Null
    # The nuget package has pip but no Scripts\pip.exe; setup-python runs `pip cache dir` (failed run 39481758008).
    & (Join-Path $dst 'python.exe') -m ensurepip --upgrade
    if (-not (Test-Path (Join-Path $dst 'Scripts\pip.exe'))) { throw 'pip.exe missing after ensurepip' }
}

Step 'node 22.23.3 (tool cache)' {
    Expand-Archive (Join-Path $T 'node-v22.23.3-win-x64.zip') (Join-Path $env:TEMP 'node') -Force
    $dst = Join-Path $TC 'node\22.23.3\x64'
    New-Item -ItemType Directory -Force $dst | Out-Null
    Copy-Item (Join-Path $env:TEMP 'node\node-v22.23.3-win-x64\*') $dst -Recurse -Force
    New-Item -ItemType File -Force "$dst.complete" | Out-Null
}

Step 'inno setup 6.7.3' {
    $p = Start-Process (Join-Path $T 'innosetup-6.7.3.exe') -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/ALLUSERS', '/SP-' -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "Inno Setup installer exit $($p.ExitCode)" }
    if (-not (Test-Path 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe')) { throw 'ISCC.exe missing' }
}

Step 'actions runner 2.338.0' {
    Expand-Archive (Join-Path $T 'actions-runner-win-x64-2.338.0.zip') C:\runner -Force
    Set-Content C:\runner\.env -Encoding ascii -Value @("RUNNER_TOOL_CACHE=$TC", "AGENT_TOOLSDIRECTORY=$TC",
        "PIP_CACHE_DIR=$env:PIP_CACHE_DIR", "npm_config_cache=$env:npm_config_cache")
}

Step 'machine environment' {
    [Environment]::SetEnvironmentVariable('RUNNER_TOOL_CACHE', $TC, 'Machine')
    [Environment]::SetEnvironmentVariable('AGENT_TOOLSDIRECTORY', $TC, 'Machine')
    [Environment]::SetEnvironmentVariable('PIP_CACHE_DIR', $env:PIP_CACHE_DIR, 'Machine')
    [Environment]::SetEnvironmentVariable('npm_config_cache', $env:npm_config_cache, 'Machine')
    $path = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    [Environment]::SetEnvironmentVariable('Path', "C:\tools\pwsh;C:\tools\git\cmd;$path", 'Machine')
    New-Item -ItemType Directory -Force C:\ProgramData\STAR-CI | Out-Null
    Set-Content C:\ProgramData\STAR-CI\disposable-vm.txt 'Throwaway CI VM (server/winvm). Destroyed after every job.'
}

# Warm the pip and npm caches with STAR's own dependency lists, so a job downloads almost nothing. Not fatal.
try {
    Step 'warm pip cache' {
        $py = Join-Path $TC 'Python\3.11.9\x64\python.exe'
        & $py -m venv C:\winvm\warm
        $reqs = Get-ChildItem (Join-Path $Source 'repo') -Filter 'requirements-*.txt' | Where-Object { $_.Name -in 'requirements-desktop.txt', 'requirements-dev.txt' }
        $argsList = @('-m', 'pip', 'install', '--disable-pip-version-check', 'pyinstaller>=6.10,<7')
        foreach ($r in $reqs) { $argsList += @('-r', $r.FullName) }
        Push-Location (Join-Path $Source 'repo')
        & C:\winvm\warm\Scripts\python.exe @argsList
        Pop-Location
        Remove-Item C:\winvm\warm -Recurse -Force
    }
    Step 'warm npm cache' {
        $env:Path = (Join-Path $TC 'node\22.23.3\x64') + ";$env:Path"
        Copy-Item (Join-Path $Source 'repo\frontend') C:\winvm\fe -Recurse -Force
        Push-Location C:\winvm\fe
        npm install --no-audit --no-fund
        Pop-Location
        Remove-Item C:\winvm\fe -Recurse -Force
    }
} catch { Write-Output "cache warm-up incomplete: $_" }

Step 'agent at logon' {
    Copy-Item (Join-Path $Source 'agent.ps1') C:\winvm\agent.ps1 -Force
    $a = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\winvm\agent.ps1'
    $tr = New-ScheduledTaskTrigger -AtLogOn -User "$env:COMPUTERNAME\ci"
    $pr = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\ci" -LogonType Interactive -RunLevel Highest
    $st = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries
    Register-ScheduledTask -TaskName 'winvm-agent' -Action $a -Trigger $tr -Principal $pr -Settings $st -Force | Out-Null
}

Step 'trim free space' { Optimize-Volume -DriveLetter C -ReTrim }
Stop-Transcript
shutdown /s /t 5  # winvm.py then boots it without the ISOs and saves the running state
