# Preview by default. -Apply changes only explicitly selected current-user startup registrations.
# Apps, app data, drivers, services, Windows security and power settings are never removed or changed.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Root = '',
    [switch]$Apply,
    [string[]]$DisableStartupId = @(),
    [string]$RestoreManifest = '',
    [string]$ObsLogPath = '',
    [switch]$FunctionsOnly
)
$ErrorActionPreference = 'Stop'

function Get-StarOptionalStartup {
    return [ordered]@{
        'spotify' = @{ Name = 'Spotify'; App = 'Spotify' }
        'steam' = @{ Name = 'Steam'; App = 'Steam launcher' }
        'epic-games' = @{ Name = 'EpicGamesLauncher'; App = 'Epic Games launcher' }
        'teams-classic' = @{ Name = 'com.squirrel.Teams.Teams'; App = 'Classic Microsoft Teams' }
        'skype' = @{ Name = 'Skype for Desktop'; App = 'Skype desktop' }
    }
}

function Assert-StarNoReparse([string]$Path) {
    $cursor = $Path
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse points are not accepted.' }
        }
        $parent = [IO.Path]::GetDirectoryName($cursor)
        if ($parent -eq $cursor) { break }
        $cursor = $parent
    }
}

function Resolve-StarLocalPath([string]$Path) {
    if (-not $Path -or $Path -notmatch '^[A-Za-z]:\\' -or $Path -match '[\x00-\x1f<>"|?*]' -or
        $Path.Substring(2).Contains(':') -or $Path.Contains('/') -or $Path.Contains('\\') -or
        @($Path.Substring(3).Split('\') | Where-Object { $_ -in '.', '..' -or $_ -match '[ .]$' }).Count) {
        throw 'Use an unambiguous absolute local Windows path.'
    }
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if ($full.Length -le 3) { throw 'A drive root is not an installation folder.' }
    Assert-StarNoReparse $full
    return $full
}

function Resolve-StarOptimizationRoot([string]$Path) {
    $full = Resolve-StarLocalPath $Path
    foreach ($protected in @($env:windir, $env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramData)) {
        if ($protected -and ($full.Equals($protected, [StringComparison]::OrdinalIgnoreCase) -or
            $full.StartsWith($protected.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase))) {
            throw 'Use STAR''s installation folder, outside Windows and shared system folders.'
        }
    }
    if ($env:USERPROFILE -and $full.Equals($env:USERPROFILE, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The user profile itself is not a STAR installation folder.'
    }
    if ((Test-Path -LiteralPath $full) -and -not (Test-Path -LiteralPath $full -PathType Container)) {
        throw 'The installation root must be a directory.'
    }
    return $full
}

function Get-StarStartupValue([string]$Name) {
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Software\Microsoft\Windows\CurrentVersion\Run', $false)
    try {
        if ($null -eq $key -or $key.GetValueNames() -notcontains $Name) { return @{ Present = $false } }
        return @{ Present = $true; Kind = $key.GetValueKind($Name).ToString();
            Value = $key.GetValue($Name, $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames) }
    } finally { if ($key) { $key.Dispose() } }
}

function Remove-StarStartupValue([string]$Name) {
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Software\Microsoft\Windows\CurrentVersion\Run', $true)
    try { if ($key) { $key.DeleteValue($Name, $false) } } finally { if ($key) { $key.Dispose() } }
}

function Set-StarStartupValue([string]$Name, [string]$Value, [string]$Kind) {
    $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Software\Microsoft\Windows\CurrentVersion\Run')
    try { $key.SetValue($Name, $Value, [Microsoft.Win32.RegistryValueKind]::$Kind) } finally { $key.Dispose() }
}

function Get-StarStartupPlan([string[]]$Ids) {
    $catalog = Get-StarOptionalStartup
    if (@($Ids | Select-Object -Unique).Count -ne $Ids.Count) { throw 'Choose each startup ID only once.' }
    foreach ($id in $Ids) { if ($catalog.Keys -cnotcontains $id) { throw 'Unknown startup ID; use the exact IDs in the audit.' } }
    $out = @()
    foreach ($id in $Ids) {
        $item = $catalog[$id]
        $state = Get-StarStartupValue $item.Name
        $supported = $state.Present -and $state.Kind -in 'String', 'ExpandString' -and
            $state.Value -is [string] -and $state.Value.Length -gt 0 -and $state.Value.Length -le 8192
        $out += [pscustomobject]@{ Id = $id; App = $item.App; Registered = [bool]$state.Present;
            Action = $(if (-not $state.Present) { 'not-registered' } elseif ($supported) { 'disable-next-sign-in' } else { 'unsupported-value' }) }
    }
    return $out
}

function Get-StarCurrentSid { return [Security.Principal.WindowsIdentity]::GetCurrent().User.Value }

function Protect-StarOptimizationData([string]$Text) {
    Add-Type -AssemblyName System.Security
    $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
    $entropy = [Text.Encoding]::UTF8.GetBytes('STAR startup optimization v1')
    return [Convert]::ToBase64String([Security.Cryptography.ProtectedData]::Protect(
        $bytes, $entropy, [Security.Cryptography.DataProtectionScope]::CurrentUser))
}

function Unprotect-StarOptimizationData([string]$Text) {
    Add-Type -AssemblyName System.Security
    $entropy = [Text.Encoding]::UTF8.GetBytes('STAR startup optimization v1')
    return [Text.Encoding]::UTF8.GetString([Security.Cryptography.ProtectedData]::Unprotect(
        [Convert]::FromBase64String($Text), $entropy, [Security.Cryptography.DataProtectionScope]::CurrentUser))
}

function Save-StarOptimizationManifest([string]$RootPath, [object[]]$Entries) {
    $rootPath = Resolve-StarOptimizationRoot $RootPath
    $folder = Join-Path $rootPath 'home\optimization'
    Assert-StarNoReparse $folder
    [void][IO.Directory]::CreateDirectory($folder)
    Assert-StarNoReparse $folder
    $path = Join-Path $folder ('startup-' + [Guid]::NewGuid().ToString('N') + '.json')
    $payload = @{ Version = 1; Root = $rootPath; Sid = Get-StarCurrentSid;
        CreatedUtc = [DateTime]::UtcNow.ToString('o'); Entries = @($Entries) } | ConvertTo-Json -Depth 6 -Compress
    $encoded = @{ Format = 'STAR startup backup v1'; Protected = Protect-StarOptimizationData $payload } |
        ConvertTo-Json -Compress
    $stream = [IO.File]::Open($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($encoded)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    } finally { $stream.Dispose() }
    return $path
}

function Read-StarOptimizationManifest([string]$RootPath, [string]$Path) {
    $rootPath = Resolve-StarOptimizationRoot $RootPath
    $full = Resolve-StarLocalPath $Path
    $folder = Join-Path $rootPath 'home\optimization'
    if (-not [IO.Path]::GetDirectoryName($full).Equals($folder, [StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetFileName($full) -notmatch '^startup-[a-f0-9]{32}\.json$' -or
        -not (Test-Path -LiteralPath $full -PathType Leaf) -or (Get-Item -LiteralPath $full).Length -gt 131072) {
        throw 'Choose a startup backup directly inside this STAR root''s home\optimization folder.'
    }
    try {
        $envelope = [IO.File]::ReadAllText($full) | ConvertFrom-Json
        if ($envelope.Format -ne 'STAR startup backup v1' -or $envelope.Protected -isnot [string]) { throw 'invalid' }
        $data = (Unprotect-StarOptimizationData $envelope.Protected) | ConvertFrom-Json
        if ($data.Version -ne 1 -or $data.Sid -ne (Get-StarCurrentSid) -or $data.Root -isnot [string] -or
            -not $data.Root.Equals($rootPath, [StringComparison]::OrdinalIgnoreCase) -or
            $null -eq $data.Entries -or @($data.Entries).Count -gt 5) { throw 'invalid' }
        $catalog = Get-StarOptionalStartup
        $seen = @{}
        foreach ($entry in @($data.Entries)) {
            if ($entry.Id -isnot [string] -or $catalog.Keys -cnotcontains $entry.Id -or $seen.ContainsKey($entry.Id) -or
                $entry.Name -cne $catalog[$entry.Id].Name -or $entry.Kind -notin 'String', 'ExpandString' -or
                $entry.Value -isnot [string] -or -not $entry.Value.Length -or $entry.Value.Length -gt 8192) { throw 'invalid' }
            $seen[$entry.Id] = $true
        }
        return $data
    } catch { throw 'The backup is invalid, altered, or belongs to a different Windows account/root.' }
}

function Invoke-StarStartupCleanup([string]$RootPath, [string[]]$Ids, [bool]$DoApply = $false) {
    $rootPath = Resolve-StarOptimizationRoot $RootPath
    $plan = @(Get-StarStartupPlan $Ids)
    if (-not $DoApply) { return @{ Mode = 'preview'; Changes = $plan; Manifest = $null } }
    if (-not $Ids.Count) { throw 'Applying startup cleanup requires explicit startup IDs.' }
    $catalog = Get-StarOptionalStartup
    $entries = @()
    foreach ($item in $plan) {
        if ($item.Action -eq 'disable-next-sign-in') {
            $state = Get-StarStartupValue $catalog[$item.Id].Name
            if ($state.Kind -notin 'String', 'ExpandString' -or $state.Value -isnot [string] -or
                -not $state.Value.Length -or $state.Value.Length -gt 8192) { throw 'A startup value changed; preview again.' }
            $entries += @{ Id = $item.Id; Name = $catalog[$item.Id].Name; Kind = $state.Kind; Value = $state.Value }
        }
    }
    $manifest = if ($entries.Count) { Save-StarOptimizationManifest $rootPath $entries } else { $null }
    $results = @()
    foreach ($entry in $entries) {
        $current = Get-StarStartupValue $entry.Name
        $status = 'conflict-preserved'
        if ($current.Present -and $current.Kind -ceq $entry.Kind -and $current.Value -ceq $entry.Value) {
            try { Remove-StarStartupValue $entry.Name; $status = 'disabled-next-sign-in' } catch { $status = 'failed' }
        }
        $results += @{ Id = $entry.Id; Status = $status }
    }
    return @{ Mode = 'apply'; Changes = @($results); Manifest = $manifest;
        Restore = 'Run this script with -Root, -RestoreManifest and -Apply as the same Windows account.' }
}

function Restore-StarStartupCleanup([string]$RootPath, [string]$Path, [bool]$DoApply = $false) {
    $data = Read-StarOptimizationManifest $RootPath $Path
    $results = @()
    foreach ($entry in @($data.Entries)) {
        $current = Get-StarStartupValue $entry.Name
        $status = if (-not $current.Present) { 'would-restore' } elseif (
            $current.Kind -ceq $entry.Kind -and $current.Value -ceq $entry.Value) { 'already-original' } else { 'conflict-preserved' }
        if ($DoApply -and $status -eq 'would-restore') {
            # Recheck immediately before writing. A new installer/user value wins.
            if ((Get-StarStartupValue $entry.Name).Present) { $status = 'conflict-preserved' }
            else {
                try { Set-StarStartupValue $entry.Name $entry.Value $entry.Kind; $status = 'restored' } catch { $status = 'failed' }
            }
        }
        $results += @{ Id = $entry.Id; Status = $status }
    }
    return @{ Mode = $(if ($DoApply) { 'restore' } else { 'restore-preview' }); Changes = @($results) }
}

function Invoke-StarReadOnlyProbe([string]$File, [string]$Arguments) {
    if (-not (Test-Path -LiteralPath $File -PathType Leaf)) { return $null }
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $File; $info.Arguments = $Arguments
    $info.UseShellExecute = $false; $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true; $info.RedirectStandardError = $true
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $info
    try {
        [void]$process.Start()
        if (-not $process.WaitForExit(5000)) { $process.Kill(); return $null }
        if ($process.ExitCode -ne 0) { return $null }
        $text = $process.StandardOutput.ReadToEnd()
        if ($text.Length -gt 65536) { return $null }
        return $text
    } catch { return $null } finally { $process.Dispose() }
}

function Convert-StarNumeric([string]$Text) {
    if ([string]::IsNullOrWhiteSpace($Text)) { return $null }
    $number = 0.0
    if ([double]::TryParse($Text.Trim(), [Globalization.NumberStyles]::Float,
        [Globalization.CultureInfo]::InvariantCulture, [ref]$number) -and
        -not [double]::IsNaN($number) -and -not [double]::IsInfinity($number)) { return $number }
    return $null
}

function Convert-StarGpuCsv([string]$Text) {
    $out = @()
    foreach ($row in @($Text | ConvertFrom-Csv -Header Name, Driver, TotalMB, UsedMB, UtilizationPercent, TemperatureC, PowerW)) {
        if (-not $row.Name -or -not $row.Driver) { continue }
        $out += @{ Name = $row.Name.Trim(); Driver = $row.Driver.Trim(); TotalMB = Convert-StarNumeric $row.TotalMB;
            UsedMB = Convert-StarNumeric $row.UsedMB; UtilizationPercent = Convert-StarNumeric $row.UtilizationPercent;
            TemperatureC = Convert-StarNumeric $row.TemperatureC; PowerW = Convert-StarNumeric $row.PowerW }
    }
    return $out
}

function Get-StarObsCounters([string]$Text) {
    $out = @{ RenderingLagPercent = $null; EncodingLagPercent = $null; NetworkDropPercent = $null }
    $patterns = @{ RenderingLagPercent = 'Number of lagged frames due to rendering lag/stalls:';
        EncodingLagPercent = 'number of skipped frames due to encoding lag:';
        NetworkDropPercent = 'Number of dropped frames due to insufficient bandwidth/connection stalls:' }
    foreach ($key in $patterns.Keys) {
        $matches = [regex]::Matches($Text, [regex]::Escape($patterns[$key]) + '[^\r\n]*?\(([0-9]+(?:\.[0-9]+)?)%\)', 'IgnoreCase')
        if ($matches.Count) { $out[$key] = Convert-StarNumeric $matches[$matches.Count - 1].Groups[1].Value }
    }
    return $out
}

function Get-StarOptimizationAudit([string]$RootPath, [string]$LogPath = '') {
    $rootPath = Resolve-StarOptimizationRoot $RootPath
    $issues = @()
    $system = @{ Status = 'unavailable' }
    try {
        $os = Get-CimInstance Win32_OperatingSystem
        $system = @{ Status = 'observed'; Windows = $os.Caption; Build = $os.BuildNumber;
            TotalMemoryMB = [math]::Round($os.TotalVisibleMemorySize / 1024); FreeMemoryMB = [math]::Round($os.FreePhysicalMemory / 1024) }
    } catch { $issues += 'Windows memory snapshot unavailable.' }
    $power = Invoke-StarReadOnlyProbe (Join-Path $env:SystemRoot 'System32\powercfg.exe') '/getactivescheme'
    $powerId = if ($power -match '[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}') { $Matches[0] } else { $null }
    $gpu = @()
    foreach ($exe in @((Join-Path $env:SystemRoot 'System32\nvidia-smi.exe'),
        (Join-Path $env:ProgramFiles 'NVIDIA Corporation\NVSMI\nvidia-smi.exe'))) {
        $csv = Invoke-StarReadOnlyProbe $exe '--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu,temperature.gpu,power.draw --format=csv,noheader,nounits'
        if ($csv) { $gpu = @(Convert-StarGpuCsv $csv); break }
    }
    if (-not $gpu.Count) { $issues += 'NVIDIA snapshot unavailable; no GPU or speed claim made.' }
    $obs = @{ Installed = $false; Version = $null; Counters = $null }
    $obsExe = Join-Path $env:ProgramFiles 'obs-studio\bin\64bit\obs64.exe'
    if (Test-Path -LiteralPath $obsExe -PathType Leaf) { $obs.Installed = $true; $obs.Version = (Get-Item -LiteralPath $obsExe).VersionInfo.FileVersion }
    if ($LogPath) {
        $log = Resolve-StarLocalPath $LogPath
        if ([IO.Path]::GetExtension($log) -cne '.log' -or -not (Test-Path -LiteralPath $log -PathType Leaf) -or
            (Get-Item -LiteralPath $log).Length -gt 8388608) { throw 'Choose one local OBS .log file of at most 8 MiB.' }
        $obs.Counters = Get-StarObsCounters ([IO.File]::ReadAllText($log))
    }
    $packages = @()
    foreach ($name in @('Microsoft.BingNews', 'Microsoft.BingWeather', 'Microsoft.MicrosoftSolitaireCollection',
        'Microsoft.WindowsFeedbackHub', 'Clipchamp.Clipchamp')) {
        try { $installed = [bool](Get-AppxPackage -Name $name -ErrorAction Stop); $packages += @{ Id = $name; Installed = $installed } }
        catch { $packages += @{ Id = $name; Installed = $null } }
    }
    return @{ Mode = 'audit'; Scope = 'current Windows account'; System = $system; ActivePowerPlanGuid = $powerId;
        GpuSnapshot = @($gpu); Obs = $obs; OptionalStartup = @(Get-StarStartupPlan @((Get-StarOptionalStartup).Keys));
        OptionalApps = @($packages); Issues = @($issues);
        Recommendations = @('Measure the same game, avatar and voice workload before/after one change; inspect OBS Stats rendering, encoding and network loss separately.',
            'Use NVENC supported by the destination; AV1 capability does not guarantee platform support or spare GPU memory.',
            'If rendering lags, cap game FPS and simplify scenes before retesting; local AI and avatar rendering share GPU resources.',
            'Review Windows Startup apps. Chosen cleanup only unregisters optional apps at next sign-in; it does not stop apps or uninstall them.',
            'Compare Balanced and Best performance under the actual workload, watching temperature and power; this tool changes neither.',
            'Review optional app removal in Windows Settings only after backing up that app''s data; this tool does not uninstall apps.');
        PerformanceGainMeasured = $false; RestoreGuidance = 'Startup cleanup writes an encrypted backup under <root>\home\optimization before changing any selected value.' }
}

if ($FunctionsOnly) { return }
$DisableStartupId = @($DisableStartupId | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() })
if (-not $Root) { $Root = $env:STAR_ROOT }
if (-not $Root) { throw 'Pass -Root with STAR''s installation folder, for example D:\STAR.' }
$Root = Resolve-StarOptimizationRoot $Root
if ($RestoreManifest -and $DisableStartupId.Count) { throw 'Choose cleanup IDs or a restore manifest, not both.' }
if ($Apply -and -not $RestoreManifest -and -not $DisableStartupId.Count) { throw '-Apply requires exact -DisableStartupId selections or -RestoreManifest.' }
$doApply = [bool]$Apply -and -not [bool]$WhatIfPreference
if ($doApply -and -not $PSCmdlet.ShouldProcess('Selected current-user optional startup values', 'Disable or restore with saved backup')) { $doApply = $false }
if ($RestoreManifest) { Restore-StarStartupCleanup $Root $RestoreManifest $doApply | ConvertTo-Json -Depth 8 }
elseif ($DisableStartupId.Count) { Invoke-StarStartupCleanup $Root $DisableStartupId $doApply | ConvertTo-Json -Depth 8 }
else { Get-StarOptimizationAudit $Root $ObsLogPath | ConvertTo-Json -Depth 8 }
