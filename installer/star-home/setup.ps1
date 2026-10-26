# STAR Home setup: run ONCE on STAR's own PC, signed in as STAR's Windows account (an administrator).
# Start it with setup.cmd (it asks for administrator rights and bypasses the script block for this one file).
#   setup.cmd              install or update
#   setup.cmd -Root D:\STAR  install into that folder (default: the first fixed drive that is not the Windows drive,
#                          else C:\STAR). All of STAR lives under the root: app, venv, home (config, STOP, action
#                          log, acceptance reports), models, tools, workspace, logs.
#   setup.cmd -Uninstall   remove the scheduled task and desktop files (keeps her data and workspace)
# What it does: Python 3.12 (if missing) -> <root>\app + <root>\venv -> config in <root>\home ->
# scheduled task "STAR Home" (at her logon, highest privileges, in her desktop session) -> STOP/RESUME files on the
# desktop -> OpenSSH server (local network only) with a slot for the lead's PUBLIC key -> optional automatic sign-in
# after restarts (Microsoft Autologon; the owner types the password into its window) -> prints this PC's address.
# It never creates, asks for or stores a password or a private key.
param([switch]$Uninstall, [string]$Root = '')
$ErrorActionPreference = 'Stop'

$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not $Root) { $Root = [Environment]::GetEnvironmentVariable('STAR_ROOT', 'Machine') }
if (-not $Root) {
    $second = Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | Where-Object { $_.DeviceID -ne $env:SystemDrive } |
        Sort-Object DeviceID | Select-Object -First 1
    $Root = if ($second) { "$($second.DeviceID)\STAR" } else { 'C:\STAR' }
}
$Root = $Root.TrimEnd('\')
$App = Join-Path $Root 'app'
$Venv = Join-Path $Root 'venv'
$Data = Join-Path $Root 'home'
$Workspace = Join-Path $Root 'workspace'
$Task = 'STAR Home'
$Desktop = [Environment]::GetFolderPath('Desktop')

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw 'Run setup.cmd (it asks for administrator rights).' }

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $Task -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $Desktop 'STAR STOP.cmd'), (Join-Path $Desktop 'STAR RESUME.cmd') -ErrorAction SilentlyContinue
    Write-Host "Removed the task and desktop files. Data kept in $Data and $Workspace."
    exit 0
}
Write-Host "STAR install root: $Root"
if (-not (Test-Path (Join-Path $Repo 'star\home\__main__.py'))) { throw "STAR source not found next to this script ($Repo\star)." }

Step 'Python 3.12'
$Python = $null
foreach ($candidate in @("$env:ProgramFiles\Python312\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe")) {
    if (Test-Path $candidate) { $Python = $candidate; break }
}
if (-not $Python) {
    winget install --id Python.Python.3.12 --exact --scope machine --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) { throw "winget could not install Python (exit $LASTEXITCODE)." }
    $Python = "$env:ProgramFiles\Python312\python.exe"
    if (-not (Test-Path $Python)) { throw "Python installed but not found at $Python." }
}
& $Python --version

Step "STAR Home files -> $App"
New-Item -ItemType Directory -Force -Path $App, (Join-Path $Root 'models\voice'), (Join-Path $Root 'models\hf'),
    (Join-Path $Root 'tools'), (Join-Path $Root 'logs'), (Join-Path $Root 'cache\pip') | Out-Null
# One folder for everything: the root, and the model and cache folders other packages read (star/home/paths.py).
$env:STAR_ROOT = $Root
$env:STAR_VOICE_MODELS = Join-Path $Root 'models\voice'
$env:HF_HOME = Join-Path $Root 'models\hf'
$env:PIP_CACHE_DIR = Join-Path $Root 'cache\pip'
foreach ($name in 'STAR_ROOT', 'STAR_VOICE_MODELS', 'HF_HOME', 'PIP_CACHE_DIR') {
    [Environment]::SetEnvironmentVariable($name, (Get-Item "env:$name").Value, 'Machine')
}
robocopy (Join-Path $Repo 'star') (Join-Path $App 'star') /MIR /XD __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "copying the STAR source failed (robocopy $LASTEXITCODE)." }
if (-not (Test-Path "$Venv\Scripts\python.exe")) { & $Python -m venv $Venv }
& "$Venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check pillow pyautogui comtypes numpy
if ($LASTEXITCODE -ne 0) { throw 'pip install failed.' }

Step "Config -> $Data\config.json"
New-Item -ItemType Directory -Force -Path $Data, $Workspace | Out-Null
$ConfigFile = Join-Path $Data 'config.json'
if (-not (Test-Path $ConfigFile)) {
    $brain = Read-Host 'Brain address, e.g. http://<server-1-address>:8080 (Enter = the lead sets it later)'
    $dry = Read-Host 'Start in dry-run mode (actions logged, not run) until the log looks right? [Y/n]'
    $config = [ordered]@{ brain_url = $brain.Trim(); model = 'star-fast'; dry_run = ($dry -notmatch '^[nN]') }
    $config | ConvertTo-Json | Set-Content -Path $ConfigFile -Encoding utf8
} else { Write-Host 'kept the existing config.json' }

Step "Scheduled task '$Task' (at logon of $env:USERDOMAIN\$env:USERNAME, highest privileges)"
$action = New-ScheduledTaskAction -Execute "$Venv\Scripts\pythonw.exe" -Argument '-m star.home run' -WorkingDirectory $App
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0 `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $Task -Description 'STAR Home: her own loop and host agent (star/home)' -Action $action `
    -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null

Step 'Owner controls on the desktop'
"@echo off`r`ncd /d `"$App`"`r`n`"$Venv\Scripts\python.exe`" -m star.home stop`r`npause" |
    Set-Content -Path (Join-Path $Desktop 'STAR STOP.cmd') -Encoding ascii
"@echo off`r`ncd /d `"$App`"`r`n`"$Venv\Scripts\python.exe`" -m star.home resume`r`npause" |
    Set-Content -Path (Join-Path $Desktop 'STAR RESUME.cmd') -Encoding ascii
Write-Host 'STAR STOP.cmd / STAR RESUME.cmd created; the hotkey Ctrl+Alt+Shift+F12 also stops her.'

Step 'OpenSSH server (for the lead to deploy updates; local network only, key login only)'
$cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server*' | Select-Object -First 1
if ($cap.State -ne 'Installed') { Add-WindowsCapability -Online -Name $cap.Name | Out-Null }
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd
$rule = Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue
if ($rule) { Set-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -RemoteAddress LocalSubnet -Profile Private, Domain }
else { New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Direction Inbound `
        -Protocol TCP -LocalPort 22 -Action Allow -RemoteAddress LocalSubnet -Profile Private, Domain | Out-Null }
$Keys = Join-Path $env:ProgramData 'ssh\administrators_authorized_keys'
Write-Host 'Paste the lead''s PUBLIC key: ONE line starting with ssh-ed25519 (from the lead''s PC:'
Write-Host '  type %USERPROFILE%\.ssh\id_ed25519.pub ). Never paste a private key. Enter = skip.'
$pub = (Read-Host 'Public key').Trim()
if ($pub) {
    if ($pub -notmatch '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp\d+) [A-Za-z0-9+/=]+( .*)?$' -or $pub -match 'PRIVATE') {
        throw 'That is not a single public key line; nothing was written. Run setup.cmd again.'
    }
    $existing = if (Test-Path $Keys) { Get-Content $Keys } else { @() }
    if ($existing -notcontains $pub) { Add-Content -Path $Keys -Value $pub -Encoding ascii }
    icacls $Keys /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F' | Out-Null
    $sshd = Join-Path $env:ProgramData 'ssh\sshd_config'
    (Get-Content $sshd) -replace '^#?\s*PasswordAuthentication\s+\w+', 'PasswordAuthentication no' | Set-Content $sshd -Encoding ascii
    Restart-Service sshd
    Write-Host 'key installed; password login over ssh is off'
} else { Write-Host 'skipped: run setup.cmd again to add the key later' }

Step 'Local voice and hearing stack (star/senses, optional)'
if (Test-Path (Join-Path $App 'star\senses\setup.py')) {
    Push-Location $App
    & "$Venv\Scripts\python.exe" -m star.senses.setup
    $senses = $LASTEXITCODE
    Pop-Location
    if ($senses -ne 0) { Write-Warning "star.senses.setup exited $senses; STAR Home works without it. Run setup.cmd again later." }
} else { Write-Host 'skipped: star/senses is not in this copy yet' }

Step "Sign in as $env:USERNAME automatically after a restart"
# Microsoft Sysinternals Autologon: the owner types her password into Autologon's own window; Windows keeps it
# encrypted as an LSA secret. This script never sees, asks for or stores the password.
$auto = Read-Host 'Set up automatic sign-in after restarts (opens Microsoft Autologon)? [Y/n]'
if ($auto -notmatch '^[nN]') {
    $tool = Join-Path $Root 'tools\Autologon'
    New-Item -ItemType Directory -Force -Path $tool | Out-Null
    $zip = Join-Path $tool 'AutoLogon.zip'
    Invoke-WebRequest -UseBasicParsing 'https://download.sysinternals.com/files/AutoLogon.zip' -OutFile $zip
    Expand-Archive -Force $zip $tool
    $exe = Join-Path $tool 'Autologon64.exe'
    $sig = Get-AuthenticodeSignature $exe
    if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
        throw "Autologon64.exe is not signed by Microsoft ($($sig.Status)); not running it."
    }
    Write-Host "In the Autologon window: Username $env:USERNAME, Domain $env:USERDOMAIN, type her password, press Enable."
    Start-Process -FilePath $exe -ArgumentList '/accepteula' -Wait
    # Stay awake so she is reachable; the screen may still turn off.
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    Write-Host 'done (also set "Restore on AC power loss" = On in the BIOS so the PC starts after a power cut)'
} else { Write-Host 'skipped: run setup.cmd again to set it up later' }

Step 'Never ask her for the password (her own PC)'
# She never types her password: no lock on wake or idle, and admin rights without the consent prompt (UAC stays
# enabled, so Store apps keep working). Her model never knows the password, so nobody can talk it out of her.
$open = Read-Host 'No lock screen on wake/idle and no admin Yes/No prompts for her account? [Y/n]'
if ($open -notmatch '^[nN]') {
    # The GUID form works on every build; the CONSOLELOCK alias is missing on some, and the setting can be hidden.
    $consoleLock = '0e796bdb-100d-47d6-a2d5-f7d2daa51f51'
    powercfg -attributes SUB_NONE $consoleLock -ATTRIB_HIDE
    powercfg /setacvalueindex SCHEME_CURRENT SUB_NONE $consoleLock 0
    powercfg /setdcvalueindex SCHEME_CURRENT SUB_NONE $consoleLock 0
    powercfg /setactive SCHEME_CURRENT
    Set-ItemProperty 'HKCU:\Control Panel\Desktop' -Name ScreenSaverIsSecure -Value '0'
    $policy = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System'
    Set-ItemProperty $policy -Name ConsentPromptBehaviorAdmin -Value 0 -Type DWord
    Set-ItemProperty $policy -Name PromptOnSecureDesktop -Value 0 -Type DWord
    Write-Host 'done: no sign-in on wake, no secure screen saver, admin actions without a prompt'
} else { Write-Host 'skipped' }

Step 'Self-test (dry run: nothing is executed)'
Push-Location $App
& "$Venv\Scripts\python.exe" -m star.home check
Pop-Location
Start-ScheduledTask -TaskName $Task

Step 'This PC'
$ips = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' } |
    Select-Object -ExpandProperty IPAddress
Write-Host "Computer: $env:COMPUTERNAME   User: $env:USERNAME"
Write-Host "Address(es): $($ips -join ', ')"
Write-Host "Tell the lead: ssh $env:USERNAME@$($ips | Select-Object -First 1)"
Write-Host "Her loop is running (task '$Task'). Stop: 'STAR STOP.cmd' on the desktop or Ctrl+Alt+Shift+F12."
Write-Host "Check every ability on this PC:  cd /d $App ; $Venv\Scripts\python.exe -m star.home acceptance   (--quick = no audio/GPU loads; report in $Data\acceptance)"
