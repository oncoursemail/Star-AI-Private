# STAR Home setup: run ONCE on STAR's own PC, signed in as STAR's Windows account (an administrator).
# Start it with setup.cmd (it asks for administrator rights and bypasses the script block for this one file).
#   setup.cmd                    install or update everything (questions first, then it runs unattended)
#   setup.cmd -Root D:\STAR      install into that folder (default: the first fixed drive that is not the Windows drive,
#                                else C:\STAR). All of STAR lives under the root: app, venv, home (config, STOP, action
#                                log, acceptance reports), models, tools, workspace, logs.
#   setup.cmd -DryRun            print every step and change NOTHING (no admin rights, no download, no install)
#   setup.cmd -Yes               take every default and ask nothing (steps that need the owner are SKIPPED)
#   setup.cmd -Skip cable,camera skip those steps          setup.cmd -Only models,acceptance   run only those steps
#   setup.cmd -Grounder none     ask|ui-tars-2b|qwen3-vl-2b|ui-tars-1.5-7b|none (default: ask; Qwen is explicit opt-in)
#   setup.cmd -MinecraftLauncher modrinth  remember that choice; skip the official launcher, keep Java and Mineflayer
#   setup.cmd -DiscordAccessibility  optional shortcut setup for UI Automation; normal Discord is unchanged by default
#   setup.cmd -Uninstall         remove the scheduled task and desktop files (keeps her data and workspace)
# Steps (ids for -Skip / -Only): preflight python files venv pip torch node apps models cable camera grounder discord
#   config task controls ssh autologon nolock check optimize acceptance.
# Every step is idempotent (run setup.cmd again and finished steps do nothing), is reported as OK / SKIPPED / FAILED with the
# fix, and a failed step never stops the others. Python packages come from requirements-home.txt (exact versions with
# hashes; regenerate with installer\star-home\pin_requirements.py); other downloads are pinned in pins.json, star.senses.setup
# and install-camera.ps1. It never creates, asks for or stores a password or a private key.
param(
    [switch]$Uninstall,
    [string]$Root = '',
    [switch]$DryRun,
    [switch]$Yes,
    [string[]]$Skip = @(),
    [string[]]$Only = @(),
    [ValidateSet('ask', 'ui-tars-2b', 'qwen3-vl-2b', 'ui-tars-1.5-7b', 'none')][string]$Grounder = 'ask',
    [ValidateSet('official', 'modrinth')][string]$MinecraftLauncher,
    [switch]$DiscordAccessibility
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is very slow with the progress bar

$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Pins = Get-Content (Join-Path $PSScriptRoot 'pins.json') -Raw | ConvertFrom-Json
$StepIds = @('preflight', 'python', 'files', 'venv', 'pip', 'torch', 'node', 'apps', 'models', 'cable', 'camera', 'grounder',
    'discord', 'config', 'task', 'controls', 'ssh', 'autologon', 'nolock', 'check', 'optimize', 'acceptance')
$Skip = @($Skip | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim().ToLower() } | Where-Object { $_ })
$Only = @($Only | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim().ToLower() } | Where-Object { $_ })
foreach ($id in $Skip + $Only) { if ($StepIds -notcontains $id) { throw "Unknown step '$id'. Steps: $($StepIds -join ' ')" } }

if (-not $Root) { $Root = [Environment]::GetEnvironmentVariable('STAR_ROOT', 'Machine') }
if (-not $Root) {
    $second = Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | Where-Object { $_.DeviceID -ne $env:SystemDrive } |
        Sort-Object DeviceID | Select-Object -First 1
    $Root = if ($second) { "$($second.DeviceID)\STAR" } else { 'C:\STAR' }
}
$Root = $Root.Replace('/', '\').TrimEnd('\')
if ($Root -notmatch '^[A-Za-z]:\\.+') { throw "-Root must be a full folder path such as D:\STAR (got '$Root')." }
$App = "$Root\app"
$Venv = "$Root\venv"
$VenvPy = "$Venv\Scripts\python.exe"
$Data = "$Root\home"
$Workspace = "$Root\workspace"
$ConfigFile = "$Data\config.json"
$Task = 'STAR Home'
$Desktop = [Environment]::GetFolderPath('Desktop')
$Startup = [Environment]::GetFolderPath('Startup')
$MineflayerDir = "$App\star\games\mineflayer"
$FastServer = "$Root\models\voice\fast\llama.cpp\llama-server.exe"

# ---- small helpers ------------------------------------------------------------------------------------------------------
$script:Results = New-Object System.Collections.ArrayList
$script:Cur = $null
$script:Python = $null
$script:NeedReboot = $false
function Step-Header($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Say($text) { Write-Host "  $text" }
function Would($text) { Write-Host "  [dry-run] would: $text" -ForegroundColor DarkYellow }
function Mark($status, $detail, $fix = '') { $script:Cur = [pscustomobject]@{ Status = $status; Detail = $detail; Fix = $fix } }
function Mark-Ok($detail) { Mark 'OK' $detail }
function Mark-Skipped($detail, $fix = '') { Mark 'SKIPPED' $detail $fix }
function Mark-Failed($detail, $fix = '') { Mark 'FAILED' $detail $fix }
function Mark-DryRun($detail) { Mark 'DRY-RUN' $detail }
function Selected($id) { ((-not $Only.Count) -or ($Only -contains $id)) -and ($Skip -notcontains $id) }
function Read-SetupPreferences([string]$Path) {
    $saved = [ordered]@{}
    if (Test-Path -LiteralPath $Path) {
        $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($raw -isnot [pscustomobject]) { throw 'setup-preferences.json must contain an object.' }
        foreach ($property in $raw.PSObject.Properties) { $saved[$property.Name] = $property.Value }
    }
    return $saved
}
function Get-SetupLauncher([string]$Path, [string]$Requested) {
    if ($Requested) { return $Requested.ToLowerInvariant() }
    $saved = Read-SetupPreferences $Path
    if (-not $saved.Contains('minecraft_launcher')) { return 'official' }
    if ($saved.minecraft_launcher -isnot [string] -or $saved.minecraft_launcher -cnotin @('official', 'modrinth')) {
        throw 'Invalid minecraft_launcher in setup-preferences.json; choose -MinecraftLauncher official or modrinth.'
    }
    return $saved.minecraft_launcher
}
function Assert-SetupPreferenceDepth($Value, [int]$Depth = 0) {
    if ($Depth -gt 32) { throw 'Setup preferences are too deeply nested; existing file was kept.' }
    if ($Value -is [System.Collections.IDictionary]) {
        foreach ($item in $Value.Values) { Assert-SetupPreferenceDepth $item ($Depth + 1) }
    } elseif ($Value -is [pscustomobject]) {
        foreach ($property in $Value.PSObject.Properties) { Assert-SetupPreferenceDepth $property.Value ($Depth + 1) }
    } elseif ($Value -is [array]) {
        foreach ($item in $Value) { Assert-SetupPreferenceDepth $item ($Depth + 1) }
    }
}
function Save-SetupLauncher([string]$Path, [string]$Choice) {
    $saved = Read-SetupPreferences $Path
    if ($saved.Contains('minecraft_launcher') -and $saved.minecraft_launcher -is [string] -and
        $saved.minecraft_launcher -ceq $Choice) { return }
    $saved['minecraft_launcher'] = $Choice
    Assert-SetupPreferenceDepth $saved
    New-Item -ItemType Directory -Path (Split-Path $Path) -Force | Out-Null
    $temporary = $Path + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    try {
        [IO.File]::WriteAllText($temporary, ($saved | ConvertTo-Json -Depth 100), [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary } }
}
function Test-DiscordShortcut($Link, [string]$DiscordDir, [switch]$GeneratedOnly) {
    $target = [string]$Link.TargetPath
    $shortcutArgs = [string]$Link.Arguments
    $generated = ($target -ieq (Join-Path $DiscordDir 'Update.exe')) -and
        ($shortcutArgs -ceq '--processStart Discord.exe --process-start-args "--force-renderer-accessibility"')
    if ($GeneratedOnly) { return $generated }
    return $generated -or (($target -ieq (Join-Path $DiscordDir 'Update.exe')) -and $shortcutArgs -ceq '--processStart Discord.exe') -or
        (($target -ieq (Join-Path $DiscordDir 'Discord.exe')) -and $shortcutArgs -cin @('', '--processStart Discord.exe'))
}
function Backup-DiscordShortcut([string]$Path, [string]$BackupDir, [string]$Kind, [switch]$Preview) {
    Write-Warning "Custom Discord $Kind shortcut kept unchanged."
    if ($Preview) { Would "back up the custom $Kind shortcut under $BackupDir"; return }
    $digest = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.Substring(0, 12)
    $backup = Join-Path $BackupDir ("Discord-$Kind-$digest.lnk")
    if (-not (Test-Path -LiteralPath $backup)) {
        New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
        Copy-Item -LiteralPath $Path -Destination $backup
    }
}
function Set-DiscordShortcuts($Shell, [string]$DesktopDir, [string]$StartupDir, [string]$DiscordDir,
                              [string]$BackupDir, [switch]$Preview) {
    $desktopPath = Join-Path $DesktopDir 'Discord.lnk'
    $startupPath = Join-Path $StartupDir 'Discord (STAR).lnk'
    $legacyPath = Join-Path $DesktopDir 'Discord (STAR).lnk'
    $desktopReady = $false
    foreach ($entry in @(@{ Path = $desktopPath; Kind = 'desktop' }, @{ Path = $startupPath; Kind = 'startup' })) {
        $link = $Shell.CreateShortcut($entry.Path)
        $known = if ($entry.Kind -eq 'desktop') { Test-DiscordShortcut $link $DiscordDir }
                 else { Test-DiscordShortcut $link $DiscordDir -GeneratedOnly }
        if ((Test-Path -LiteralPath $entry.Path) -and -not $known) {
            Backup-DiscordShortcut $entry.Path $BackupDir $entry.Kind -Preview:$Preview
            continue
        }
        if ($Preview) { Would "set '$($entry.Path)' to launch Discord with accessibility" }
        else {
            $link.TargetPath = Join-Path $DiscordDir 'Update.exe'
            $link.Arguments = '--processStart Discord.exe --process-start-args "--force-renderer-accessibility"'
            $link.WorkingDirectory = $DiscordDir
            $link.Description = 'Discord with accessibility for STAR'
            $link.Save()
        }
        if ($entry.Kind -eq 'desktop') { $desktopReady = $true }
    }
    if (Test-Path -LiteralPath $legacyPath) {
        $legacy = $Shell.CreateShortcut($legacyPath)
        if (Test-DiscordShortcut $legacy $DiscordDir -GeneratedOnly) {
            if ($desktopReady) {
                if ($Preview) { Would "remove the old generated desktop alias '$legacyPath'" }
                else { Remove-Item -LiteralPath $legacyPath }
            }
        } else { Backup-DiscordShortcut $legacyPath $BackupDir 'legacy' -Preview:$Preview }
    }
}
function Format-Size([double]$bytes) {
    if ($bytes -ge 1GB) { return ('{0:N1} GB' -f ($bytes / 1GB)) }
    if ($bytes -ge 1MB) { return ('{0:N0} MB' -f ($bytes / 1MB)) }
    return ('{0:N0} KB' -f ($bytes / 1KB))
}

function Invoke-Step {
    param([string]$Id, [string]$Title, [string]$Fix, [scriptblock]$Body)
    if ($Only.Count -and ($Only -notcontains $Id)) { [void]$script:Results.Add([pscustomobject]@{ Id = $Id; Title = $Title; Status = 'SKIPPED'; Detail = 'not selected (-Only)'; Fix = '' }); return }
    if ($Skip -contains $Id) { [void]$script:Results.Add([pscustomobject]@{ Id = $Id; Title = $Title; Status = 'SKIPPED'; Detail = 'skipped (-Skip)'; Fix = "setup.cmd -Only $Id" }); return }
    Step-Header "[$Id] $Title"
    $script:Cur = $null
    try { & $Body } catch { Mark-Failed $_.Exception.Message $Fix }
    if (-not $script:Cur) { Mark-Ok 'done' }
    $color = switch ($script:Cur.Status) { 'OK' { 'Green' } 'FAILED' { 'Red' } 'SKIPPED' { 'Yellow' } default { 'DarkYellow' } }
    Write-Host ("  {0}: {1}" -f $script:Cur.Status, $script:Cur.Detail) -ForegroundColor $color
    if ($script:Cur.Fix -and $script:Cur.Status -in 'FAILED', 'SKIPPED') { Write-Host "  fix: $($script:Cur.Fix)" -ForegroundColor $color }
    [void]$script:Results.Add([pscustomobject]@{ Id = $Id; Title = $Title; Status = $script:Cur.Status; Detail = $script:Cur.Detail; Fix = $(if ($script:Cur.Fix) { $script:Cur.Fix } else { $Fix }) })
}

# Runs a program and returns { Code, Output }. Output lines are echoed (not with -Quiet). -Live leaves the console to the program (progress bars).
function Run-Native {
    param([string]$Exe, [string[]]$Arguments = @(), [switch]$Live, [switch]$Quiet)
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'   # native stderr lines must not end the script
    $lines = @()
    try {
        if ($Live) { & $Exe @Arguments; $code = $LASTEXITCODE }
        else {
            & $Exe @Arguments 2>&1 | ForEach-Object { $text = "$_"; $lines += $text; if (-not $Quiet) { Write-Host "    $text" } }
            $code = $LASTEXITCODE
        }
    } finally { $ErrorActionPreference = $old }
    [pscustomobject]@{ Code = $code; Output = ($lines -join "`n") }
}

# Downloads Url to Dest (resumable, curl.exe ships with Windows) and keeps it only when size and SHA-256 match. Returns $false
# when a correct file was already there.
function Get-Verified {
    param([string]$Url, [string]$Dest, [long]$Size = 0, [string]$Sha256 = '')
    function Test-File($path) {
        if (-not (Test-Path $path)) { return $false }
        if ($Size -and (Get-Item $path).Length -ne $Size) { return $false }
        if ($Sha256 -and ((Get-FileHash $path -Algorithm SHA256).Hash -ne $Sha256.ToUpper())) { return $false }
        return $true
    }
    if (Test-File $Dest) { return $false }
    if (Test-Path $Dest) { Remove-Item $Dest -Force }
    New-Item -ItemType Directory -Force -Path (Split-Path $Dest) | Out-Null
    $part = "$Dest.part"
    Say ("downloading {0} ({1}) ..." -f (Split-Path $Dest -Leaf), (Format-Size $Size))
    $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
    if (Test-Path $curl) {
        $r = Run-Native $curl @('-L', '--fail', '--retry', '5', '--retry-delay', '5', '-C', '-', '-o', $part, $Url) -Live
        if ($r.Code -ne 0) { throw "download failed (curl exit $($r.Code)): $Url" }
    } else { Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $part }
    if (-not (Test-File $part)) {
        Remove-Item $part -Force -ErrorAction SilentlyContinue
        throw "$(Split-Path $Dest -Leaf) does not match the pinned size or SHA-256 (the partial file was deleted; run again). Nothing was installed."
    }
    Move-Item $part $Dest -Force
    return $true
}

function Find-Python312 {
    foreach ($candidate in @("$env:ProgramFiles\Python312\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe")) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}
function Test-Winget { [bool](Get-Command winget -ErrorAction SilentlyContinue) }
function Install-WithWinget([string]$Id, [string]$Scope = '') {
    $arguments = @('install', '--id', $Id, '--exact', '--silent', '--accept-package-agreements', '--accept-source-agreements', '--disable-interactivity')
    if ($Scope) { $arguments += @('--scope', $Scope) }
    $r = Run-Native 'winget' $arguments
    if ($r.Code -ne 0 -and $r.Output -notmatch 'already installed|No available upgrade|No newer package') { throw "winget could not install $Id (exit $($r.Code))." }
}
function Test-WingetHas([string]$Id) {
    $r = Run-Native 'winget' @('list', '--id', $Id, '--exact', '--accept-source-agreements', '--disable-interactivity') -Quiet
    return ($r.Code -eq 0 -and $r.Output -match [regex]::Escape($Id))
}
function Get-FreeGB([string]$Path) {
    $letter = (Split-Path -Qualifier $Path).TrimEnd(':')
    $drive = Get-PSDrive -Name $letter -ErrorAction SilentlyContinue
    if ($drive) { return [math]::Round($drive.Free / 1GB, 1) }
    return -1
}
function Get-Nvidia {
    $card = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'NVIDIA' } | Select-Object -First 1
    $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    $driver = ''
    if ($smi) { $driver = ((& $smi.Source --query-gpu=driver_version --format=csv,noheader 2>$null) | Select-Object -First 1) }
    [pscustomobject]@{ Card = $(if ($card) { $card.Name } else { '' }); Driver = "$driver".Trim(); Smi = [bool]$smi }
}
# Hash failures stop this step. Never retry an unverified package installation.
function Install-Pinned([string]$File, [string]$Label) {
    $base = @('-m', 'pip', 'install', '--disable-pip-version-check', '--no-cache-dir', '--progress-bar', 'off', '--no-deps')
    $r = Run-Native $VenvPy ($base + @('--require-hashes', '-r', $File))
    if ($r.Code -eq 0) { return 'hashes verified' }
    throw "The verified install of $Label failed (exit $($r.Code)). No unverified retry was attempted. Check the output, connection and lock file, then rerun this step."
}

# ---- uninstall ----------------------------------------------------------------------------------------------------------
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if ($DryRun) { Write-Host "DRY RUN: nothing on this PC will be changed, downloaded or installed." -ForegroundColor DarkYellow }
elseif (-not $admin) {
    # Encode data separately from code: apostrophes/spaces in paths and arguments cannot become PowerShell source.
    $parameters = @{}
    foreach ($key in $PSBoundParameters.Keys) {
        $value = $PSBoundParameters[$key]
        if ($value -is [System.Management.Automation.SwitchParameter]) { $value = [bool]$value }
        $parameters[$key] = $value
    }
    $payload = @{ path = $PSCommandPath; parameters = $parameters } | ConvertTo-Json -Depth 8 -Compress
    $encodedPayload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($payload))
    $launch = '$p = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("' + $encodedPayload + '")) | ConvertFrom-Json; ' +
        '$a = @{}; foreach ($v in $p.parameters.PSObject.Properties) { $a[$v.Name] = $v.Value }; & $p.path @a; exit $LASTEXITCODE'
    $encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($launch))
    $child = Start-Process -FilePath "$PSHOME\powershell.exe" -Verb RunAs -Wait -PassThru -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $encodedCommand)
    exit $child.ExitCode
}

if ($Uninstall) {
    if ($DryRun) { Would 'remove the STAR scheduled task and STAR desktop/startup shortcuts; keep all data'; exit 0 }
    Unregister-ScheduledTask -TaskName $Task -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $Desktop 'STAR STOP.cmd'), (Join-Path $Desktop 'STAR RESUME.cmd'), (Join-Path $Desktop 'Discord (STAR).lnk'),
        (Join-Path $Startup 'Discord (STAR).lnk') -ErrorAction SilentlyContinue
    Write-Host "Removed the task, the desktop files and the Discord shortcuts. Data kept in $Data and $Workspace."
    exit 0
}
Write-Host "STAR install root: $Root"
if (-not (Test-Path (Join-Path $Repo 'star\home\__main__.py'))) { throw "STAR source not found next to this script ($Repo\star)." }
$PreferencesFile = Join-Path $Root 'setup-preferences.json'
$LauncherChoice = Get-SetupLauncher $PreferencesFile $MinecraftLauncher
if ($MinecraftLauncher) {
    if ($DryRun) { Would "remember Minecraft launcher preference '$LauncherChoice' in $PreferencesFile" }
    else { Save-SetupLauncher $PreferencesFile $LauncherChoice }
}
$env:STAR_ROOT = $Root
$env:STAR_VOICE_MODELS = "$Root\models\voice"
$env:HF_HOME = "$Root\models\hf"
$env:PIP_CACHE_DIR = "$Root\cache\pip"
$script:Python = Find-Python312

# ---- download sizes (MB) for the plan ------------------------------------------------------------------------------------
function Read-Mb($file, $pattern, $fallback) {
    $m = [regex]::Match("$(Get-Content (Join-Path $Repo $file) -Raw -ErrorAction SilentlyContinue)", $pattern)
    if ($m.Success) { return [double]$m.Groups[1].Value }
    return $fallback
}
$PlanMb = [ordered]@{
    python = 26; pip = (Read-Mb 'requirements-home.txt' 'about (\d+) MB' 2100); torch = (Read-Mb 'requirements-home-torch.txt' '(\d+) MB from the official' 2900)
    node = $Pins.node.mb; apps = ($Pins.apps | Measure-Object -Property mb -Sum).Sum
    models = 5866; cable = 2; camera = 1; grounder = 0
}

# ---- questions first, then it runs unattended ---------------------------------------------------------------------------
function Ask-YesNo([string]$Question, [bool]$Default = $true) {
    $hint = if ($Default) { '[Y/n]' } else { '[y/N]' }
    if ($DryRun) { Would "ask: $Question $hint (default $(if ($Default) { 'yes' } else { 'no' }))"; return $Default }
    if ($Yes) { return $Default }
    $answer = (Read-Host "$Question $hint").Trim()
    if (-not $answer) { return $Default }
    return ($answer -match '^[yY]')
}
function Ask-Text([string]$Question) {
    if ($DryRun) { Would "ask: $Question (default empty)"; return '' }
    if ($Yes) { return '' }
    return (Read-Host $Question).Trim()
}
$A = @{ Brain = ''; ConfigDry = $true; SshKey = ''; Autologon = $true; NoLock = $true; Grounder = 'none' }
$freeGB = Get-FreeGB $Root
if ((Selected 'grounder') -and $Grounder -eq 'ask') {
    $size2b = ($Pins.grounder.'ui-tars-2b'.files | Measure-Object -Property size -Sum).Sum
    $roomy = ($freeGB -lt 0) -or ($freeGB -ge 40)
    Write-Host "`nOptional: a small vision model (UI-TARS 2B, $(Format-Size $size2b)) lets her find buttons by looking when an app has no accessibility tree." -ForegroundColor Cyan
    $A.Grounder = if (Ask-YesNo 'Download it?' $roomy) { 'ui-tars-2b' } else { 'none' }
} elseif ($Grounder -ne 'ask') { $A.Grounder = $Grounder }
if ($A.Grounder -ne 'none') {
    $PlanMb.grounder = ($Pins.grounder.($A.Grounder).files | Measure-Object -Property size -Sum).Sum / 1MB
}
if (Selected 'config') {
    if (-not (Test-Path $ConfigFile)) {
        $A.Brain = Ask-Text 'Brain address, e.g. http://<server-1-address>:8080 (Enter = the lead sets it later)'
        $A.ConfigDry = Ask-YesNo 'Start in dry-run mode (actions logged, not run) until the log looks right?' $true
    }
}
if (Selected 'ssh') {
    Write-Host "`nThe lead's PUBLIC key: ONE line starting with ssh-ed25519 (from the lead's PC: type %USERPROFILE%\.ssh\id_ed25519.pub). Never paste a private key." -ForegroundColor Cyan
    $A.SshKey = Ask-Text 'Public key (Enter = skip)'
    if ($A.SshKey -and (($A.SshKey -notmatch '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp\d+) [A-Za-z0-9+/=]+( .*)?$') -or ($A.SshKey -match 'PRIVATE'))) {
        Write-Warning 'That is not a single public key line; it will be skipped. Run setup.cmd -Only ssh later.'
        $A.SshKey = ''
    }
}
if (Selected 'autologon') {
    $A.Autologon = if ($Yes) { $false } else { Ask-YesNo 'Sign in as her automatically after restarts (opens Microsoft Autologon at the end; you type her password into its window)?' $true }
}
if (Selected 'nolock') {
    $A.NoLock = Ask-YesNo 'No lock screen on wake/idle and no admin Yes/No prompts for her account?' $true
}

# ---- the steps ----------------------------------------------------------------------------------------------------------
Invoke-Step 'preflight' 'Checks: Windows, disk space, internet, graphics card' 'See the lines above, fix them, run setup.cmd again.' {
    $os = Get-CimInstance Win32_OperatingSystem
    Say "Windows: $($os.Caption) build $($os.BuildNumber), 64-bit: $([Environment]::Is64BitOperatingSystem)"
    if (-not [Environment]::Is64BitOperatingSystem) { Mark-Failed 'needs 64-bit Windows' 'STAR needs Windows 11 x64.'; return }
    $total = 0
    foreach ($id in $PlanMb.Keys) { if (Selected $id) { $total += $PlanMb[$id] } }
    $need = [math]::Round(($total / 1024) + 8, 0)
    Say ("Download size of the selected steps: {0:N1} GB (pip packages {1:N1}, PyTorch {2:N1}, voice and speech models {3:N1}, screen model {4:N1}, apps {5:N1}).  Disk needed on {6}: about {7} GB." -f
        ($total / 1024), ($PlanMb.pip / 1024), ($PlanMb.torch / 1024), ($PlanMb.models / 1024), ($PlanMb.grounder / 1024), ($PlanMb.apps / 1024), (Split-Path -Qualifier $Root), $need)
    Say "Free on $(Split-Path -Qualifier $Root): $(if ($freeGB -ge 0) { "$freeGB GB" } else { 'unknown (the drive does not exist yet)' })"
    if ($freeGB -ge 0 -and $freeGB -lt $need) {
        if ($DryRun) { Mark-DryRun "only $freeGB GB free, about $need GB needed"; return }
        if (-not (Ask-YesNo "Only $freeGB GB free on the install drive, about $need GB needed. Continue anyway?" $false)) {
            throw "Not enough disk space ($freeGB GB free, about $need GB needed). Free space or use -Root on a bigger drive, then run setup.cmd again."
        }
    }
    $gpu = Get-Nvidia
    if ($gpu.Card) { Say "Graphics card: $($gpu.Card), driver $(if ($gpu.Driver) { $gpu.Driver } else { 'not reported (nvidia-smi missing)' })" }
    else { Say 'Graphics card: no NVIDIA card found (the voice stack would run on the CPU; STAR needs the RTX 4060)' }
    if ($gpu.Card -and (-not $gpu.Smi)) { Write-Warning 'The NVIDIA driver is not installed (no nvidia-smi). Install the GeForce driver from nvidia.com, then run setup.cmd again.' }
    elseif ($gpu.Driver -and ([double]($gpu.Driver -split '\.' | Select-Object -First 1) -lt 576)) {
        Write-Warning "NVIDIA driver $($gpu.Driver) is older than 576: the CUDA 12.9 libraries pinned here may not load. Update the GeForce driver."
    }
    if ($DryRun) { Would 'check that pypi.org, github.com and huggingface.co answer'; Mark-DryRun 'plan printed'; return }
    foreach ($url in 'https://pypi.org/simple/pip/', 'https://huggingface.co', 'https://github.com') {
        try { [void](Invoke-WebRequest -UseBasicParsing -Method Head -Uri $url -TimeoutSec 20) }
        catch { Mark-Failed "cannot reach $url" 'Connect this PC to the internet (and check the firewall/VPN), then run setup.cmd again.'; return }
    }
    New-Item -ItemType Directory -Force -Path "$Root\logs" | Out-Null
    Start-Transcript -Path ("$Root\logs\setup-{0:yyyyMMdd-HHmmss}.log" -f (Get-Date)) -Append | Out-Null
    Mark-Ok "$freeGB GB free, internet reachable; log in $Root\logs"
}

Invoke-Step 'python' 'Python 3.12' 'Install Python 3.12 (all users) from python.org, then run setup.cmd again.' {
    if ($script:Python) { Mark-Ok "$(& $script:Python --version) at $script:Python"; return }
    if ($DryRun) { Would "winget install $($Pins.python.winget) (machine-wide, silent)"; Mark-DryRun 'would install Python 3.12'; return }
    if (-not (Test-Winget)) { Mark-Failed 'winget is missing' 'Update "App Installer" in the Microsoft Store, or install Python 3.12 from python.org, then run setup.cmd again.'; return }
    Install-WithWinget $Pins.python.winget 'machine'
    $script:Python = "$env:ProgramFiles\Python312\python.exe"
    if (-not (Test-Path $script:Python)) { throw "Python installed but not found at $script:Python." }
    Mark-Ok (& $script:Python --version)
}

Invoke-Step 'files' "STAR source and folders under $Root" "Check that $Root is writable and has room, then run setup.cmd again." {
    if ($DryRun) {
        Would "create $App, models\voice, models\hf, tools, logs, cache\pip under $Root"
        Would 'set the machine variables STAR_ROOT, STAR_VOICE_MODELS, HF_HOME, PIP_CACHE_DIR'
        Would "copy $Repo\star to $App\star (robocopy /MIR, keeps node_modules), plus bundled avatar art, setup tools and owner guide"
        Mark-DryRun 'would copy the source'; return
    }
    New-Item -ItemType Directory -Force -Path $App, "$Root\models\voice", "$Root\models\hf",
        "$Root\tools", "$Root\logs", "$Root\cache\pip", "$Root\cache\tmp" | Out-Null
    # One folder for everything: the root, and the model and cache folders other packages read (star/home/paths.py).
    foreach ($name in 'STAR_ROOT', 'STAR_VOICE_MODELS', 'HF_HOME', 'PIP_CACHE_DIR') {
        [Environment]::SetEnvironmentVariable($name, (Get-Item "env:$name").Value, 'Machine')
    }
    if ([IO.Path]::GetFullPath($Repo) -ne [IO.Path]::GetFullPath($App)) {
        robocopy (Join-Path $Repo 'star') "$App\star" /MIR /XD __pycache__ node_modules /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "copying the STAR source failed (robocopy $LASTEXITCODE)." }
    }
    foreach ($relative in @('assets\vtuber', 'frontend\public\assets\mascot\faces', 'installer\star-home', 'installer\star-camera')) {
        $source = Join-Path $Repo $relative
        $target = Join-Path $App $relative
        if ((Test-Path -LiteralPath $source) -and ([IO.Path]::GetFullPath($source) -ne [IO.Path]::GetFullPath($target))) {
            robocopy $source $target /E /XD __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
            if ($LASTEXITCODE -ge 8) { throw "copying bundled files failed: $relative (robocopy $LASTEXITCODE)." }
        }
    }
    if ([IO.Path]::GetFullPath($Repo) -ne [IO.Path]::GetFullPath($App)) {
        Copy-Item (Join-Path $Repo 'requirements-home*.txt') $App -Force
        foreach ($guide in @('STAR-FIRST-START.md', 'STAR-LIVE-TEST.md')) {
            if (Test-Path -LiteralPath (Join-Path $Repo $guide)) {
                Copy-Item -LiteralPath (Join-Path $Repo $guide) -Destination $App -Force
            }
        }
    }
    $global:LASTEXITCODE = 0
    Mark-Ok "source in $App, variables STAR_ROOT / STAR_VOICE_MODELS / HF_HOME / PIP_CACHE_DIR set for the machine"
}

Invoke-Step 'venv' 'Python virtual environment' 'Delete the venv folder and run setup.cmd again.' {
    if (Test-Path $VenvPy) { Mark-Ok "$(& $VenvPy --version) at $Venv"; return }
    if ($DryRun) { Would "$(if ($script:Python) { $script:Python } else { 'python 3.12' }) -m venv $Venv"; Mark-DryRun 'would create the venv'; return }
    if (-not $script:Python) { Mark-Skipped 'needs Python 3.12' 'Fix the python step first.'; return }
    & $script:Python -m venv $Venv
    if (-not (Test-Path $VenvPy)) { throw "venv was not created at $Venv." }
    Mark-Ok "$(& $VenvPy --version) at $Venv"
}

Invoke-Step 'pip' 'Python packages (requirements-home.txt: exact versions, hashes checked)' "Run: $VenvPy -m pip install --no-deps -r $Repo\requirements-home.txt  and read the error; then run setup.cmd again." {
    $lock = Join-Path $Repo 'requirements-home.txt'
    if ($DryRun) {
        $count = ([regex]::Matches((Get-Content $lock -Raw), '(?m)^[A-Za-z0-9_.-]+==')).Count
        Would "pip install --no-deps --require-hashes -r requirements-home.txt ($count pinned packages, about $([math]::Round($PlanMb.pip / 1024, 1)) GB, incl. CUDA 12 libraries for onnxruntime-gpu and faster-whisper)"
        Mark-DryRun "would install $count packages"; return
    }
    if (-not (Test-Path $VenvPy)) { Mark-Skipped 'needs the venv' 'Fix the venv step first.'; return }
    $oldTemp = $env:TEMP
    $env:TEMP = $env:TMP = "$Root\cache\tmp"   # pip unpacks big wheels here: keep them on the install drive
    try { $how = Install-Pinned $lock 'requirements-home.txt' } finally { $env:TEMP = $env:TMP = $oldTemp }
    $check = Run-Native $VenvPy @('-I', '-c', "import numpy, PIL, comtypes, pyautogui, soundcard, sounddevice, faster_whisper, kokoro_onnx, onnxruntime, pyvirtualcam, winsdk, mss, dxcam, cv2, yt_dlp, httpx, defusedxml; print('imports ok, onnxruntime', onnxruntime.__version__)")
    if ($check.Code -ne 0) { Mark-Failed "installed, but an import failed: $(($check.Output -split "`n" | Select-Object -Last 1))" "Run: $VenvPy -c ""import dxcam, soundcard, onnxruntime""  and send the error to the lead."; return }
    Mark-Ok $how
}

Invoke-Step 'torch' 'PyTorch for the RTX 4060 (CUDA build from the official index)' "Update the NVIDIA driver, then run: $VenvPy -m pip install --no-deps -r $Repo\requirements-home-torch.txt" {
    $lock = Join-Path $Repo 'requirements-home-torch.txt'
    if ($DryRun) { Would "pip install --no-deps --require-hashes -r requirements-home-torch.txt (about $([math]::Round($PlanMb.torch / 1024, 1)) GB from download.pytorch.org)"; Mark-DryRun 'would install CUDA PyTorch'; return }
    if (-not (Test-Path $VenvPy)) { Mark-Skipped 'needs the venv' 'Fix the venv step first.'; return }
    $oldTemp = $env:TEMP
    $env:TEMP = $env:TMP = "$Root\cache\tmp"
    try { $how = Install-Pinned $lock 'requirements-home-torch.txt' } finally { $env:TEMP = $env:TMP = $oldTemp }
    $gpu = Get-Nvidia
    $probe = Run-Native $VenvPy @('-I', '-c', "import torch; ok = torch.cuda.is_available(); print('torch', torch.__version__, 'cuda', ok, torch.cuda.get_device_name(0) if ok else '')")
    if ($probe.Code -ne 0) { Mark-Failed 'installed, but torch does not import' "Run: $VenvPy -c ""import torch""  and send the error to the lead."; return }
    if ($probe.Output -match 'cuda False' -and $gpu.Card) { Mark-Failed 'torch installed but cannot use the graphics card' 'Install or update the NVIDIA GeForce driver (576 or newer), restart, run setup.cmd -Only torch.'; return }
    Mark-Ok "$(($probe.Output -split "`n" | Select-Object -Last 1)); $how"
}

Invoke-Step 'node' 'Node.js LTS and the Minecraft bot (mineflayer, npm install)' "Install Node.js LTS from nodejs.org, then in $MineflayerDir run: npm install mineflayer@$($Pins.npm.mineflayer) mineflayer-pathfinder@$($Pins.npm.'mineflayer-pathfinder')" {
    function Find-Node {
        $local = "$env:ProgramFiles\nodejs\node.exe"
        if (Test-Path $local) { return $local }
        $c = Get-Command node -ErrorAction SilentlyContinue
        if ($c) { return $c.Source }
        return $null
    }
    function Get-Major($node) { try { return [int]((((& $node --version) -replace '^v', '') -split '\.')[0]) } catch { return 0 } }
    $node = Find-Node
    $have = if ($node) { Get-Major $node } else { 0 }
    if ($have -lt $Pins.node.min_major) {
        if ($DryRun) { Would "winget install $($Pins.node.winget) (Node.js LTS, $($Pins.node.why))" }
        else {
            if (-not (Test-Winget)) { Mark-Failed 'winget is missing' 'Install Node.js LTS from nodejs.org, then run setup.cmd again.'; return }
            Install-WithWinget $Pins.node.winget 'machine'
            $node = Find-Node
            if (-not $node) { throw 'Node.js installed but node.exe was not found.' }
        }
    } else { Say "Node.js $(& $node --version) already installed" }
    $mf = $Pins.npm.mineflayer; $pf = $Pins.npm.'mineflayer-pathfinder'
    if ($DryRun -and -not (Test-Path $MineflayerDir)) { Would "in star\games\mineflayer: npm install --no-save mineflayer@$mf mineflayer-pathfinder@$pf"; Mark-DryRun 'would install Node and the Minecraft bot packages'; return }
    if ($DryRun) { Would "in star\games\mineflayer: npm install --no-save mineflayer@$mf mineflayer-pathfinder@$pf (unless already there)"; Mark-DryRun 'would install the Minecraft bot packages'; return }
    if (-not (Test-Path $MineflayerDir)) { Mark-Skipped 'needs the STAR source in the app folder' 'Fix the files step first.'; return }
    $env:Path = "$(Split-Path $node);$env:Path"
    Push-Location $MineflayerDir
    try {
        $js = "try{const f=require('fs');const v=n=>JSON.parse(f.readFileSync('node_modules/'+n+'/package.json')).version;console.log(v('mineflayer')+' '+v('mineflayer-pathfinder'))}catch(e){console.log('none')}"
        $installed = ((& $node -e $js) | Select-Object -Last 1)
        if ("$installed" -eq "$mf $pf") { Say "mineflayer $mf and mineflayer-pathfinder $pf already installed" }
        else {
            $npm = Join-Path (Split-Path $node) 'npm.cmd'
            $r = Run-Native $npm @('install', '--no-save', '--no-package-lock', '--no-audit', '--no-fund', "mineflayer@$mf", "mineflayer-pathfinder@$pf")
            if ($r.Code -ne 0) { throw "npm install failed (exit $($r.Code))." }
        }
        $r = Run-Native $node @('-e', "require('mineflayer');require('mineflayer-pathfinder');console.log('mineflayer loads')")
        if ($r.Code -ne 0) { throw 'node cannot load mineflayer after the install.' }
    } finally { Pop-Location }
    Mark-Ok "Node $(& $node --version), mineflayer $mf, pathfinder $pf"
}

Invoke-Step 'apps' 'Discord, the chosen Minecraft launcher and Java' 'Install the missing app by hand, then run setup.cmd again.' {
    $missing = @()
    foreach ($app in $Pins.apps) {
        if ($app.id -eq 'Mojang.MinecraftLauncher' -and $LauncherChoice -eq 'modrinth') {
            Say 'Modrinth preference: keeping the owner-selected launcher; official Minecraft Launcher skipped'
            continue
        }
        $found = $false
        foreach ($pattern in $app.present) { if (Test-Path ([Environment]::ExpandEnvironmentVariables($pattern))) { $found = $true; break } }
        if (-not $found -and (Test-Winget)) { $found = Test-WingetHas $app.id }
        if ($found) { Say "$($app.name): already installed" } else { $missing += $app }
    }
    if (-not $missing.Count) { Mark-Ok 'all selected apps are installed'; return }
    if ($DryRun) { foreach ($app in $missing) { Would "winget install $($app.id) ($($app.name), about $($app.mb) MB)" }; Mark-DryRun "would install $($missing.Count) app(s)"; return }
    if (-not (Test-Winget)) { Mark-Failed 'winget is missing' 'Update "App Installer" in the Microsoft Store, or install the apps by hand, then run setup.cmd again.'; return }
    $failed = @()
    foreach ($app in $missing) {
        try { Install-WithWinget $app.id } catch { $failed += $app.name; Write-Warning $_.Exception.Message }
    }
    if ($failed.Count) { Mark-Failed "could not install: $($failed -join ', ')" } else { Mark-Ok "installed $(($missing | ForEach-Object { $_.name }) -join ', ')" }
}

Invoke-Step 'models' 'Voice, speech and fast-path models (pinned, SHA-256 checked, star.senses.setup)' "Run: cd /d $App && $VenvPy -m star.senses.setup  and read the FAILED line; then run setup.cmd again." {
    if ($DryRun) {
        Would 'python -m star.senses.setup: Kokoro voice + voice-activity + end-of-turn files (365 MB), speech models small.en + distil-small.en (816 MB), llama.cpp CUDA server (664 MB), Qwen3.5-4B Q4 (2741 MB) and 2B Q4 (1281 MB) into <root>\models'
        Mark-DryRun 'would download about 5.9 GB'; return
    }
    if (-not (Test-Path $VenvPy)) { Mark-Skipped 'needs the venv and packages' 'Fix the pip step first.'; return }
    Push-Location $App
    try { $r = Run-Native $VenvPy @('-m', 'star.senses.setup') } finally { Pop-Location }
    $bad = @($r.Output -split "`n" | Where-Object { $_ -match '^FAILED ' })
    if ($r.Code -ne 0 -or $bad.Count) { Mark-Failed ($bad -join '; ') ; return }
    Push-Location $App
    try { $left = Run-Native $VenvPy @('-m', 'star.senses.setup', '--list') } finally { Pop-Location }
    Mark-Ok ($left.Output -split "`n" | Select-Object -Last 1)
}

Invoke-Step 'cable' 'VB-CABLE virtual audio cable and the "STAR Microphone" device' 'See the lines above. By hand: install VB-CABLE from vb-audio.com/Cable (run VBCABLE_Setup_x64.exe as administrator), restart, run setup.cmd -Only cable.' {
    function Test-StarMic { [bool](Get-PnpDevice -Class AudioEndpoint -PresentOnly -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -match 'STAR Microphone' }) }
    function Get-Cable { @(Get-CimInstance Win32_SoundDevice -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'VB-Audio|CABLE' }) }
    $cableUrl = $Pins.vbcable
    if (Test-StarMic) { Mark-Ok '"STAR Microphone" already exists'; return }
    $installed = (Get-Cable).Count -gt 0
    if ($DryRun) {
        if (-not $installed) { Would "download VBCABLE_Driver_Pack45.zip ($(Format-Size $cableUrl.size)) from $($cableUrl.url), check the Authenticode signature of VBCABLE_Setup_x64.exe (signer must match '$($cableUrl.signer_pattern)'), run it with -i -h" }
        Would 'python -m star.senses.routes script > tools\setup-star-mic.ps1, run it (renames the cable output to "STAR Microphone", makes it the default recording and communications device), then routes verify'
        Mark-DryRun 'would install the cable and create STAR Microphone'; return
    }
    if (-not (Test-Path $VenvPy)) { Mark-Skipped 'needs the venv and packages' 'Fix the pip step first.'; return }
    if (-not $installed) {
        $dir = "$Root\tools\vbcable"
        $zip = "$dir\VBCABLE_Driver_Pack45.zip"
        [void](Get-Verified $cableUrl.url $zip $cableUrl.size $cableUrl.sha256)
        $unpacked = "$dir\pack45"
        Expand-Archive -Force $zip $unpacked
        $setup = "$unpacked\VBCABLE_Setup_x64.exe"
        if (-not (Test-Path $setup)) { throw 'VBCABLE_Setup_x64.exe is not in the downloaded zip.' }
        $sig = Get-AuthenticodeSignature $setup
        $signer = if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { '(none)' }
        if ($sig.Status -ne 'Valid' -or $signer -notmatch $cableUrl.signer_pattern) {
            Mark-Failed "VBCABLE_Setup_x64.exe was NOT run: signature $($sig.Status), signer $signer" 'If the signer is VB-Audio and the status is Valid, edit signer_pattern in installer\star-home\pins.json; otherwise download the driver from vb-audio.com/Cable by hand.'
            return
        }
        Say "signature Valid, signer $signer"
        Say 'installing the driver (Windows may ask once to allow the VB-Audio driver: click Install) ...'
        $p = Start-Process -FilePath $setup -ArgumentList '-i', '-h' -WorkingDirectory $unpacked -Wait -PassThru
        Say "VBCABLE_Setup_x64.exe exit code $($p.ExitCode)"
        if ((Get-Cable).Count -eq 0) {
            $script:NeedReboot = $true
            Mark-Skipped 'driver installed; Windows must restart before the cable appears' 'Restart Windows, then run setup.cmd again (it finishes the STAR Microphone steps).'
            return
        }
    }
    Push-Location $App
    try {
        $script1 = "$Root\tools\setup-star-mic.ps1"
        (& $VenvPy -m star.senses.routes script) | Set-Content $script1 -Encoding ascii
        $r = Run-Native 'powershell' @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $script1)
        if ($r.Code -ne 0 -and $r.Output -match 'No recording endpoint') {
            $script:NeedReboot = $true
            Mark-Skipped 'the cable is installed but Windows has not created its recording device yet' 'Restart Windows, then run setup.cmd again (it finishes the STAR Microphone steps).'
            return
        }
        if ($r.Code -ne 0) { Mark-Failed "the rename script failed (exit $($r.Code))" "Run $script1 -WhatIf in an elevated PowerShell and send the output to the lead. The cable still works under its stock name; set the default recording device by hand." ; return }
        try { Restart-Service -Name Audiosrv -Force -ErrorAction Stop } catch { Say 'could not restart the Windows audio service; the new name shows after a sign-out' }
        $v = Run-Native $VenvPy @('-m', 'star.senses.routes', 'verify')
        if ($v.Code -ne 0) { Mark-Failed 'the cable is installed but routes verify failed' 'In Sound settings > Recording > STAR Microphone (or CABLE Output) > Properties > Advanced choose 2 channel, 24 bit, 48000 Hz; then run python -m star.senses.routes verify.'; return }
    } finally { Pop-Location }
    Mark-Ok 'cable installed, renamed to STAR Microphone, default recording device, verify passed (still set 2 channel 24 bit 48000 Hz by hand in Sound settings)'
}

Invoke-Step 'camera' 'STAR Camera virtual webcam (Unity Capture, pinned hashes)' "Run: $Repo\installer\star-camera\install-camera.cmd and read the error." {
    $script2 = Join-Path $Repo 'installer\star-camera\install-camera.ps1'
    $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $script2, '-Root', $Root)
    if ($DryRun) {
        $r = Run-Native 'powershell' ($arguments + '-DryRun')
        if ($r.Code -ne 0) { Mark-Failed "the camera installer's dry run failed (exit $($r.Code))"; return }
        Mark-DryRun 'camera installer dry run printed above'; return
    }
    if (-not (Test-Path $VenvPy)) { Mark-Skipped 'needs the venv and packages' 'Fix the pip step first.'; return }
    $r = Run-Native 'powershell' $arguments
    if ($r.Code -ne 0) { Mark-Failed "install-camera.ps1 exit $($r.Code)" ; return }
    if ($r.Output -match 'WARNING') { Mark-Failed 'registered, but the camera did not start in the self-test' 'Read camera.log in the configured VTuber data folder (normally <root>\home\vtuber).' ; return }
    Mark-Ok "'STAR Camera' registered and sent frames in the self-test (Discord detection is not verified yet)"
}

Invoke-Step 'grounder' 'Optional screen-reading model for star.computer (pinned)' 'Download the files listed in installer\star-home\pins.json by hand, or run setup.cmd -Only grounder -Grounder ui-tars-2b' {
    if ($A.Grounder -eq 'none') { Mark-Skipped 'not selected (default is to skip when the disk is low or you answer no)' 'setup.cmd -Only grounder -Grounder ui-tars-2b (or explicit candidate qwen3-vl-2b); setup reports download size; measure GPU use before enabling'; return }
    $g = $Pins.grounder.($A.Grounder)
    $folder = "$Root\models\grounding\$($A.Grounder)"
    $bytes = ($g.files | Measure-Object -Property size -Sum).Sum
    if ($DryRun) {
        Would "download $($g.files.Count) files ($(Format-Size $bytes)) of $($g.repo)@$($g.revision.Substring(0, 8)) into $folder (SHA-256 checked), unpack the llama.cpp server if needed, write tools\start-grounder.cmd and home\computer.vlm.json (not switched on)"
        Mark-DryRun "would download $(Format-Size $bytes)"; return
    }
    if (-not (Test-Path $VenvPy)) { Mark-Skipped 'needs the venv and packages' 'Fix the pip step first.'; return }
    if (-not (Test-Path $FastServer)) {
        Push-Location $App
        try { $r = Run-Native $VenvPy @('-m', 'star.senses.setup', '--only', 'server') } finally { Pop-Location }
        if ($r.Code -ne 0 -or -not (Test-Path $FastServer)) { Mark-Failed 'the llama.cpp server could not be fetched'; return }
    }
    $free = Get-FreeGB $Root
    if ($free -ge 0 -and $free * 1GB -lt ($bytes + 2GB)) { Mark-Skipped "only $free GB free for $(Format-Size $bytes)" 'Free disk space, then run setup.cmd -Only grounder.'; return }
    foreach ($file in $g.files) {
        [void](Get-Verified "https://huggingface.co/$($g.repo)/resolve/$($g.revision)/$($file.name)" "$folder\$($file.name)" $file.size $file.sha256)
    }
    $model = "$folder\$($g.model_file)"
    $mmproj = "$folder\$($g.mmproj_file)"
    @('@echo off',
      "rem Starts STAR's screen-reading model ($($A.Grounder)) on 127.0.0.1:8081. Measure GPU memory on this PC before running beside voice or a game; download size is not a VRAM budget.",
      "`"$FastServer`" -m `"$model`" --mmproj `"$mmproj`" --host 127.0.0.1 --port 8081 -ngl 99 -c 4096 --no-webui") |
        Set-Content -Path "$Root\tools\start-grounder.cmd" -Encoding ascii
    New-Item -ItemType Directory -Force -Path $Data | Out-Null
    ([ordered]@{ grounder = [ordered]@{ kind = 'vlm'; url = 'http://127.0.0.1:8081/v1'; model = $A.Grounder; choice = $A.Grounder; format = 'auto' } } |
        ConvertTo-Json -Depth 4) | Set-Content -Path "$Data\computer.vlm.json" -Encoding ascii
    Mark-Ok "files verified in $folder. To switch it on: run tools\start-grounder.cmd, copy home\computer.vlm.json over home\computer.json, then python -m star.computer calibrate"
}

Invoke-Step 'discord' 'Optional Discord accessibility shortcuts' $(if ($DiscordAccessibility) { 'Install Discord, sign in, then run setup.cmd -Only discord -DiscordAccessibility.' } else { '' }) {
    if (-not $DiscordAccessibility) {
        Mark-Skipped 'not selected: normal Discord shortcuts and settings kept'
        return
    }
    $discordDir = Join-Path $env:LOCALAPPDATA 'Discord'
    $update = Join-Path $discordDir 'Update.exe'
    if (-not (Test-Path $update)) {
        if ($DryRun) { Would 'after Discord is installed: create one Discord.lnk on the desktop and the accessibility alias in Startup'; Mark-DryRun 'Discord is not installed yet'; return }
        Mark-Skipped 'Discord is not installed' 'Install Discord (the apps step does it), then run setup.cmd -Only discord -DiscordAccessibility.'; return
    }
    $shell = New-Object -ComObject WScript.Shell
    Set-DiscordShortcuts $shell $Desktop $Startup $discordDir (Join-Path $Root 'tools\shortcut-backups') -Preview:$DryRun
    if ($DryRun) { Mark-DryRun 'would update known Discord shortcuts; custom links kept'; return }
    $notes = @()
    $running = @(Get-CimInstance Win32_Process -Filter "Name='Discord.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -and $_.CommandLine -notmatch '--type=' })
    if ($running | Where-Object { $_.CommandLine -notmatch 'force-renderer-accessibility' }) {
        $notes += 'Discord is running WITHOUT the flag now: quit it (tray icon > Quit Discord) and start "Discord" from the desktop'
    }
    if (Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name Discord -ErrorAction SilentlyContinue) {
        $notes += 'Discord also starts itself without the flag: in Discord > Settings > Windows Settings turn off "Open Discord"'
    }
    Mark-Ok ("shortcuts on the desktop and in Startup" + $(if ($notes) { '; NOTE: ' + ($notes -join '; ') } else { '' }))
}

Invoke-Step 'config' "Her settings -> $ConfigFile" 'Create the folder and a config.json by hand: {"brain_url": "", "model": "star-fast", "dry_run": true}' {
    if (Test-Path $ConfigFile) { Mark-Ok 'kept the existing config.json'; return }
    if ($DryRun) { Would "write $ConfigFile (brain_url '$($A.Brain)', dry_run $($A.ConfigDry))"; Mark-DryRun 'would write the config'; return }
    New-Item -ItemType Directory -Force -Path $Data, $Workspace | Out-Null
    ([ordered]@{ brain_url = $A.Brain; model = 'star-fast'; dry_run = $A.ConfigDry } | ConvertTo-Json) | Set-Content -Path $ConfigFile -Encoding utf8
    Mark-Ok "written (dry_run $($A.ConfigDry); the lead sets brain_url later if it is empty)"
}

Invoke-Step 'task' "Scheduled task '$Task' (at logon of $env:USERDOMAIN\$env:USERNAME, highest privileges)" 'Run setup.cmd -Only task as administrator.' {
    if ($DryRun) {
        Would "register the task: $Venv\Scripts\pythonw.exe -m star.home run (start in $App), at logon, restart every minute on failure"
        Mark-DryRun $(if (Get-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue) { 'task exists, would refresh it' } else { 'would register the task' }); return
    }
    $action = New-ScheduledTaskAction -Execute "$Venv\Scripts\pythonw.exe" -Argument '-m star.home run' -WorkingDirectory $App
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0 `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $Task -Description 'STAR Home: her own loop and host agent (star/home)' -Action $action `
        -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Mark-Ok 'registered (starts at her next logon; the last step starts it now)'
}

Invoke-Step 'controls' 'Owner controls on the desktop (STAR STOP / STAR RESUME)' 'Run setup.cmd -Only controls.' {
    if ($DryRun) { Would "write '$Desktop\STAR STOP.cmd' and '$Desktop\STAR RESUME.cmd'"; Mark-DryRun 'would write the two files'; return }
    "@echo off`r`ncd /d `"$App`"`r`n`"$Venv\Scripts\python.exe`" -m star.home stop`r`npause" |
        Set-Content -Path (Join-Path $Desktop 'STAR STOP.cmd') -Encoding ascii
    "@echo off`r`ncd /d `"$App`"`r`n`"$Venv\Scripts\python.exe`" -m star.home resume`r`npause" |
        Set-Content -Path (Join-Path $Desktop 'STAR RESUME.cmd') -Encoding ascii
    Mark-Ok 'STAR STOP.cmd / STAR RESUME.cmd created; the hotkey Ctrl+Alt+Shift+F12 also stops her'
}

Invoke-Step 'ssh' 'OpenSSH server (for the lead to deploy updates; local network only, key login only)' 'Run setup.cmd -Only ssh as administrator.' {
    $keys = Join-Path $env:ProgramData 'ssh\administrators_authorized_keys'
    if ($DryRun) {
        Would 'install the OpenSSH.Server Windows capability, start sshd, firewall rule for the local subnet only'
        if ($A.SshKey) { Would "write the public key to $keys and turn password login off" } else { Would 'ask for the lead''s public key (skipped when empty)' }
        Mark-DryRun 'would set up sshd'; return
    }
    $cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server*' | Select-Object -First 1
    if ($cap.State -ne 'Installed') { Add-WindowsCapability -Online -Name $cap.Name | Out-Null }
    Set-Service -Name sshd -StartupType Automatic
    Start-Service sshd
    $rule = Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue
    if ($rule) { Set-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -RemoteAddress LocalSubnet -Profile Private, Domain }
    else { New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Direction Inbound `
            -Protocol TCP -LocalPort 22 -Action Allow -RemoteAddress LocalSubnet -Profile Private, Domain | Out-Null }
    if (-not $A.SshKey) { Mark-Ok 'sshd running; no key given (run setup.cmd -Only ssh later to add the lead''s public key)'; return }
    $existing = if (Test-Path $keys) { Get-Content $keys } else { @() }
    if ($existing -notcontains $A.SshKey) { Add-Content -Path $keys -Value $A.SshKey -Encoding ascii }
    icacls $keys /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F' | Out-Null
    $sshd = Join-Path $env:ProgramData 'ssh\sshd_config'
    (Get-Content $sshd) -replace '^#?\s*PasswordAuthentication\s+\w+', 'PasswordAuthentication no' | Set-Content $sshd -Encoding ascii
    Restart-Service sshd
    Mark-Ok 'sshd running, key installed, password login over ssh is off'
}

Invoke-Step 'autologon' "Sign in as $env:USERNAME automatically after a restart (Microsoft Autologon)" 'Run setup.cmd -Only autologon and type her password into the Autologon window.' {
    # Microsoft Sysinternals Autologon: the owner types her password into Autologon's own window; Windows keeps it
    # encrypted as an LSA secret. This script never sees, asks for or stores the password.
    if ($DryRun) { Would 'download Sysinternals AutoLogon.zip, check that Autologon64.exe is signed by Microsoft, open it for you to type her password, stop sleep on AC power'; Mark-DryRun 'would open Autologon'; return }
    if (-not $A.Autologon) { Mark-Skipped 'not selected (it needs her password typed by the owner)' 'Run setup.cmd -Only autologon.'; return }
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
    Write-Host "  In the Autologon window: Username $env:USERNAME, Domain $env:USERDOMAIN, type her password, press Enable."
    Start-Process -FilePath $exe -ArgumentList '/accepteula' -Wait
    # Stay awake so she is reachable; the screen may still turn off.
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    Mark-Ok 'Autologon was opened (also set "Restore on AC power loss" = On in the BIOS so the PC starts after a power cut)'
}

Invoke-Step 'nolock' 'Never ask her for the password (her own PC): no lock, no admin prompts' 'Run setup.cmd -Only nolock as administrator.' {
    # She never types her password: no lock on wake or idle, and admin rights without the consent prompt (UAC stays
    # enabled, so Store apps keep working). Her model never knows the password, so nobody can talk it out of her.
    if ($DryRun) { Would 'powercfg: console lock off; screen saver not secure; ConsentPromptBehaviorAdmin 0 and PromptOnSecureDesktop 0'; Mark-DryRun 'would change lock and UAC prompt settings'; return }
    if (-not $A.NoLock) { Mark-Skipped 'not selected' 'Run setup.cmd -Only nolock.'; return }
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
    Mark-Ok 'no sign-in on wake, no secure screen saver, admin actions without a prompt'
}

Invoke-Step 'check' 'Self-test (dry run: nothing is executed)' "Run: cd /d $App && $VenvPy -m star.home check" {
    if ($DryRun) { Would "python -m star.home check (her loop is started after the summary)"; Mark-DryRun 'would run the self-test'; return }
    if (-not (Test-Path $VenvPy)) { Mark-Skipped 'needs the venv' 'Fix the venv step first.'; return }
    Push-Location $App
    try { $r = Run-Native $VenvPy @('-m', 'star.home', 'check') } finally { Pop-Location }
    if ($r.Code -ne 0) { Mark-Failed "star.home check exit $($r.Code)"; return }
    Mark-Ok 'star.home check passed'
}

Invoke-Step 'optimize' 'PC cleanup and performance audit (read only)' 'Run installer\star-home\optimize-star-pc.ps1 to review optional startup cleanup.' {
    if ($DryRun) { Would 'read startup, optional-app, GPU and power readiness; never apply cleanup'; Mark-DryRun 'would audit the PC'; return }
    $audit = Join-Path $App 'installer\star-home\optimize-star-pc.ps1'
    if (-not (Test-Path -LiteralPath $audit)) { Mark-Skipped 'audit tool not copied yet' 'Run setup.cmd -Only files,optimize'; return }
    $r = Run-Native "$PSHOME\powershell.exe" @('-NoProfile', '-NonInteractive', '-File', $audit, '-Root', $Root)
    if ($r.Code -ne 0) { Mark-Failed 'PC audit could not finish; no cleanup applied'; return }
    Mark-Ok 'read-only audit complete; cleanup was not applied'
}

Invoke-Step 'acceptance' 'Acceptance, quick (no audio, no model loads, no desktop input)' "Read $Data\acceptance\latest.md: every failed check lists its exact fix." {
    if ($DryRun) { Would "python -m star.home acceptance --quick (report in $Data\acceptance)"; Mark-DryRun 'would run the quick acceptance'; return }
    if (-not (Test-Path $VenvPy)) { Mark-Skipped 'needs the venv' 'Fix the venv step first.'; return }
    Push-Location $App
    try { $r = Run-Native $VenvPy @('-m', 'star.home', 'acceptance', '--quick') } finally { Pop-Location }
    if ($r.Code -ne 0) { Mark-Failed "a check failed (exit $($r.Code)); see $Data\acceptance\latest.md" ; return }
    Mark-Ok "no check failed; report $Data\acceptance\latest.md"
}

# ---- summary ------------------------------------------------------------------------------------------------------------
Step-Header 'Summary'
foreach ($r in $script:Results) {
    $color = switch ($r.Status) { 'OK' { 'Green' } 'FAILED' { 'Red' } 'SKIPPED' { 'Yellow' } default { 'DarkYellow' } }
    Write-Host ("  {0,-8} {1,-11} {2}" -f $r.Status, $r.Id, $r.Detail) -ForegroundColor $color
}
$problems = @($script:Results | Where-Object { $_.Status -in 'FAILED', 'SKIPPED' -and $_.Fix })
if ($problems.Count) {
    Write-Host "`nTo fix (finished steps are skipped when you run setup.cmd again):" -ForegroundColor Yellow
    foreach ($r in $problems) { Write-Host "  [$($r.Id)] $($r.Fix)" }
}
if ($script:NeedReboot) { Write-Host "`nRESTART WINDOWS now, then run setup.cmd again (the cable driver needs it)." -ForegroundColor Yellow }
if (-not $DryRun) {
    Write-Host "`nStill by hand (the owner): sign in to Discord, Roblox and Minecraft once with 'remember me'; Sound settings > Recording >" -ForegroundColor Cyan
    Write-Host "  STAR Microphone > Properties > Advanced > 2 channel, 24 bit, 48000 Hz; BIOS: Restore on AC power loss = On." -ForegroundColor Cyan
    Write-Host "PC cleanup preview: powershell -NoProfile -File `"$App\installer\star-home\optimize-star-pc.ps1`" -Root `"$Root`"" -ForegroundColor Cyan
    Write-Host "Streaming scene preview: cd /d `"$App`" then `"$VenvPy`" -m star.stream_setup --help" -ForegroundColor Cyan
    if ((Selected 'task') -and -not @($script:Results | Where-Object { $_.Status -eq 'FAILED' }).Count -and
        (Get-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue)) { Start-ScheduledTask -TaskName $Task }
    try { Stop-Transcript | Out-Null } catch { }
}
$failed = @($script:Results | Where-Object { $_.Status -eq 'FAILED' }).Count

Step-Header 'This PC'
$ips = @(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' } |
    Select-Object -ExpandProperty IPAddress)
# The address on the adapter that has the default gateway is the one the lead can reach on the local network.
$lan = Get-NetIPConfiguration -ErrorAction SilentlyContinue | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } |
    Select-Object -First 1 -ExpandProperty IPv4Address
$mainIp = if ($lan) { $lan.IPAddress } else { $ips | Select-Object -First 1 }
Write-Host "Computer: $env:COMPUTERNAME   User: $env:USERNAME"
Write-Host "Address(es): $($ips -join ', ')   (local network: $mainIp)"
Write-Host "Tell the lead: ssh $env:USERNAME@$mainIp"
if ($DryRun) { Write-Host "Dry run: nothing was changed, downloaded or installed. Run setup.cmd without -DryRun to install." -ForegroundColor DarkYellow }
else {
    $installedTask = Get-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue
    if ($installedTask -and $installedTask.State -eq 'Running') { Write-Host "Her loop is running (task '$Task'). Stop: 'STAR STOP.cmd' on the desktop or Ctrl+Alt+Shift+F12." }
    elseif ($installedTask) { Write-Host "Her task is installed but is not running. Review failed steps and the acceptance report before starting it." }
}
Write-Host "$(if ($DryRun) { 'Dry run' } else { 'Setup' }) finished with $failed failed step(s). Full check of every ability on this PC (plays sound, moves the mouse; --quick = no audio/GPU loads; report in $Data\acceptance):"
Write-Host "  cd /d $App ; $Venv\Scripts\python.exe -m star.home acceptance"
exit $(if ($failed) { 1 } else { 0 })
